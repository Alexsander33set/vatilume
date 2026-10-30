"""Bounded, read-only interpretation of raw telemetry. No AI or wall-power model."""
from __future__ import annotations

import bisect
import json
import math
import time
from contextlib import closing
from pathlib import Path

from .storage import readonly
from .process_analysis import ProcessHistory

MAX_CPU_WATTS = 2000  # A rejection guard for implausible/ambiguous counter deltas, never an estimate.


def integrate_cost(start_ms, end_ms, start_w, end_w, tariffs):
    """Integrate linear power, splitting exactly at tariff boundaries."""
    energy = priced = cost = 0.0
    boundaries = [start_ms, *[t["effective_ms"] for t in tariffs if start_ms < t["effective_ms"] < end_ms], end_ms]
    for left, right in zip(boundaries, boundaries[1:]):
        duration = end_ms - start_ms
        p0 = start_w + (end_w - start_w) * (left - start_ms) / duration
        p1 = start_w + (end_w - start_w) * (right - start_ms) / duration
        part = (p0 + p1) / 2 * (right - left) / 3_600_000_000
        energy += part
        applicable = next((t for t in reversed(tariffs) if t["effective_ms"] <= left), None)
        if applicable:
            priced += part
            cost += part * float(applicable["price"])
    return energy, priced, cost


def overview(database: Path, start_ms: int, end_ms: int, tariffs: list[dict], points: int = 240) -> dict:
    if not 1_000 <= end_ms - start_ms <= 31 * 86400 * 1000 or not 24 <= points <= 600:
        raise ValueError("Selecione um período entre um segundo e 31 dias.")
    deadline = time.monotonic() + 25
    width = (end_ms - start_ms) / points
    buckets = [{} for _ in range(points)]
    previous = {}
    latest_sources = {}
    live = {}
    process_history = ProcessHistory(start_ms, end_ms, points)
    flags = {"rejected_intervals": 0, "reading_errors": 0, "adapter_errors": 0}
    totals = {key: {"id": key, "energy_kwh": 0.0, "covered_seconds": 0.0,
                    "priced_energy_kwh": 0.0, "cost_brl": 0.0, "priced_seconds": 0.0,
                    "peak_w": None, "power_area_ws": 0.0} for key in ("cpu", "gpu")}

    def add(name, value, instant):
        if value is None or not math.isfinite(value):
            return
        live[name] = {"value": value, "time_ms": int(instant)}
        if start_ms <= instant <= end_ms:
            index = min(points - 1, int((instant - start_ms) / width))
            pair = buckets[index].setdefault(name, [0, 0])
            pair[0] += value
            pair[1] += 1

    with closing(readonly(database)) as con:
        con.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        # One read snapshot keeps catalogue/configuration and rows coherent while the agent writes.
        con.execute("BEGIN")
        sources = {row["id"]: json.loads(row["metadata_json"]) for row in con.execute("SELECT * FROM sources")}
        configurations = {row["hash"]: json.loads(row["document"]) for row in con.execute("SELECT * FROM configurations")}
        cpu_sources = sorted(s["id"] for s in sources.values() if s["metric"] == "cpu.energy_reported" and not s.get("parent_domain"))
        gpu_sources = sorted(s["id"] for s in sources.values() if s["metric"] == "gpu.power_reported")
        selected = {"cpu": cpu_sources[0] if cpu_sources else None, "gpu": gpu_sources[0] if gpu_sources else None}
        inventory = con.execute("SELECT inventory_json FROM sessions ORDER BY rowid DESC LIMIT 1").fetchone()
        inventory = json.loads(inventory[0]) if inventory else {}
        first_record = con.execute("SELECT MIN(utc_ns) FROM samples").fetchone()[0]
        last_record = con.execute("SELECT MAX(utc_ns) FROM samples").fetchone()[0]
        older = con.execute("""SELECT * FROM samples WHERE utc_ns<? ORDER BY utc_ns DESC LIMIT 1""", (start_ms * 1_000_000,)).fetchone()
        highwater = con.execute('SELECT id,utc_ns,session_id FROM samples ORDER BY id DESC LIMIT 1').fetchone()
        provenance = {'highwater': dict(highwater) if highwater else None,
                      'previous_sample_id': older['id'] if older else None,
                      'selected_sources': {name: sources[identity] for name, identity in selected.items() if identity}}
        if provenance['highwater']:
            provenance['highwater']['utc_ns'] = str(provenance['highwater']['utc_ns'])  # Preserve nanoseconds in browser JSON.
        cursor = con.execute("""SELECT * FROM samples WHERE utc_ns>=? AND utc_ns<=? ORDER BY id LIMIT 400001""",
                             (start_ms * 1_000_000, end_ms * 1_000_000))
        sample_count = 0
        last_system = None

        def consume(row, counted=True):
            nonlocal last_system, sample_count
            if counted:
                sample_count += 1
                if sample_count > 400000 or time.monotonic() > deadline:
                    raise ValueError("Esse período contém muitos dados. Selecione uma janela menor.")
            config = configurations[row["config_hash"]]
            allowed_gap = config["interval_seconds"] * 2.5 + config.get("sensor_timeout_seconds", 2)
            payload = json.loads(row["collectors_json"])
            if counted and 'processes' in payload:
                process_history.add(row, payload['processes'])
            system = {}
            for collector, result in payload.items():
                if result["quality"] != "ok":
                    flags["adapter_errors"] += int(counted)
                    for s in sources.values():
                        if s["collector"] == collector:
                            previous.pop(s["id"], None)
                    continue
                instant = result.get("observed_utc_ns", row["utc_ns"]) / 1_000_000
                mono = result.get("observed_monotonic_ns", row["monotonic_ns"])
                for reading in result["readings"]:
                    identity = reading["source_id"]
                    descriptor = sources.get(identity)
                    if not descriptor:
                        continue
                    raw = reading["value"]
                    valid = reading["quality"] == "ok" and isinstance(raw, (float, int)) and math.isfinite(raw)
                    value = raw * descriptor.get("scale", 1) if valid else None
                    latest_sources[identity] = {"id": identity, "collector": collector, "metric": descriptor["metric"],
                        "label": descriptor.get("label") or descriptor["metric"], "scope": descriptor["scope"],
                        "unit": descriptor.get("output_unit") or descriptor["unit"], "raw_unit": descriptor["unit"],
                        "value": value, "raw_value": raw if valid else None, "quality": reading["quality"],
                        "error": reading.get("error"), "time_ms": int(instant)}
                    if not valid:
                        flags["reading_errors"] += int(counted)
                        previous.pop(identity, None)
                        continue
                    metric = descriptor["metric"]
                    if collector == "system":
                        system[metric] = raw
                    if metric == "gpu.utilization": add("gpu_percent", value, instant)
                    if metric == "gpu.vram_used": add("vram_used_bytes", value, instant)
                    if metric == "gpu.vram_total": add("vram_total_bytes", value, instant)
                    if metric == "temperature":
                        if "k10temp:" in descriptor.get("label", "") or "coretemp:" in descriptor.get("label", ""):
                            add("cpu_temp", value, instant)
                        if "amdgpu:" in descriptor.get("label", "") and descriptor.get("path", "").endswith("temp1_input"):
                            add("gpu_temp", value, instant)
                    component = next((name for name, sid in selected.items() if identity == sid), None)
                    if not component:
                        continue
                    old = previous.get(identity)
                    current = (instant, mono, row["boottime_ns"], raw, row["session_id"])
                    previous[identity] = current
                    if component == "gpu":
                        add("gpu_w", value, instant)
                    if not old:
                        continue
                    old_ms, old_mono, old_boot, old_raw, old_session = old
                    dt = (mono - old_mono) / 1e9
                    continuous = (old_session == row["session_id"] and 0 < dt <= allowed_gap
                        and abs((instant - old_ms) / 1000 - dt) < 2
                        and abs((row["boottime_ns"] - old_boot) / 1e9 - dt) < 1)
                    if not continuous:
                        flags["rejected_intervals"] += int(counted)
                        continue
                    if component == "cpu":
                        maximum = descriptor.get("max_range")
                        delta = raw - old_raw
                        if delta < 0 and maximum:
                            delta += maximum
                        if (delta < 0 or delta / 1e6 / dt > MAX_CPU_WATTS
                                or (maximum and dt * MAX_CPU_WATTS >= maximum / 1e6)):
                            flags["rejected_intervals"] += int(counted)
                            continue
                        p0 = p1 = delta / 1e6 / dt
                        add("cpu_w", p1, instant)
                    else:
                        p0, p1 = old_raw * descriptor.get("scale", 1), value
                        if min(p0, p1) < 0:
                            continue
                    left, right = max(start_ms, old_ms), min(end_ms, instant)
                    if left >= right:
                        continue
                    # Clip at the requested window without charging its unobserved edges.
                    a = p0 + (p1 - p0) * (left - old_ms) / (instant - old_ms)
                    b = p0 + (p1 - p0) * (right - old_ms) / (instant - old_ms)
                    # UTC locates the interval; monotonic time determines its physical duration.
                    ratio = dt * 1000 / (instant - old_ms)
                    energy, priced, cost = integrate_cost(left, right, a * ratio, b * ratio, tariffs)
                    total = totals[component]
                    total["energy_kwh"] += energy
                    total["priced_energy_kwh"] += priced
                    total["cost_brl"] += cost
                    total["covered_seconds"] += (right - left) / 1000 * ratio
                    total["power_area_ws"] += energy * 3_600_000
                    total["peak_w"] = max(total["peak_w"] or 0, a, b)
                    if any(t["effective_ms"] <= left for t in tariffs): total["priced_seconds"] += (right - left) / 1000 * ratio
                    elif tariffs and tariffs[0]["effective_ms"] < right: total["priced_seconds"] += (right - tariffs[0]["effective_ms"]) / 1000 * ratio
            if system:
                stamp = row["utc_ns"] / 1_000_000
                for key in ("memory.total", "memory.available"):
                    if key in system: add(key.replace(".", "_") + "_bytes", system[key], stamp)
                if "memory.total" in system and "memory.available" in system:
                    add("memory_used_bytes", system["memory.total"] - system["memory.available"], stamp)
                if last_system and last_system[1] == row["session_id"]:
                    old = last_system[0]
                    if all(k in old and k in system for k in ("cpu.total", "cpu.idle_including_iowait")):
                        total = system["cpu.total"] - old["cpu.total"]
                        idle = system["cpu.idle_including_iowait"] - old["cpu.idle_including_iowait"]
                        if total > 0 and 0 <= idle <= total: add("cpu_percent", (1 - idle / total) * 100, stamp)
                last_system = system, row["session_id"]

        if older: consume(older, False)
        for row in cursor: consume(row)
        events = [dict(r) for r in con.execute("SELECT id,utc_ns,type,details_json FROM events WHERE utc_ns>=? AND utc_ns<=? ORDER BY id DESC LIMIT 150", (start_ms * 1_000_000, end_ms * 1_000_000))]
    components = []
    for name, total in totals.items():
        total["source_id"] = selected[name]
        total["label"] = "CPU" if name == "cpu" else "GPU"
        total["average_w"] = total.pop("power_area_ws") / total["covered_seconds"] if total["covered_seconds"] else None
        if not total["covered_seconds"]:
            total["energy_kwh"] = total["cost_brl"] = None
        elif not total["priced_seconds"]:
            total["cost_brl"] = None
        total["coverage_percent"] = min(100, total["covered_seconds"] / ((end_ms - start_ms) / 1000) * 100)
        components.append(total)
    series = [{"time_ms": int(start_ms + (index + .5) * width), **{k: v[0] / v[1] for k, v in bucket.items()}}
              for index, bucket in enumerate(buckets)]
    for event in events:
        event["time_ms"] = event.pop("utc_ns") // 1_000_000
        event["details"] = json.loads(event.pop("details_json"))
    return {"window": {"start_ms": start_ms, "end_ms": end_ms}, "inventory": inventory,
            "sample_count": sample_count, "first_record_ms": first_record // 1_000_000 if first_record else None,
            "last_record_ms": last_record // 1_000_000 if last_record else None,
            "components": components, "latest": live, "series": series,
            "sensors": list(latest_sources.values()), "events": events, "quality": flags,
            "scope": "reported_components_only", "aggregation": "mean_per_bucket", "provenance": provenance,
            'processes':process_history.document()}
