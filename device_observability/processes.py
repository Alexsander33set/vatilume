"""Bounded /proc/PID/stat sampling. Never reads argv, environment, files or paths."""
from __future__ import annotations

import heapq
import os
import time
from pathlib import Path
from .applications import capture_ancestors, CATALOG_VERSION

MAX_PIDS = 4096
MAX_SCAN_NS = 50_000_000


def clocks():
    return time.monotonic_ns(), time.time_ns(), time.clock_gettime_ns(time.CLOCK_BOOTTIME)


def parse_stat(text, pid, page_size):
    left, right = text.index('('), text.rindex(')')
    if int(text[:left].strip()) != pid:
        raise ValueError('PID mismatch')
    fields = text[right+1:].split()
    ticks, start, pages = int(fields[11]) + int(fields[12]), int(fields[19]), int(fields[21])
    if min(ticks, start, pages) < 0:
        raise ValueError('Negative process counter')
    label = ''.join(c if c.isprintable() else ' ' for c in text[left+1:right])[:64].strip() or 'processo'
    ppid = int(fields[1])
    if ppid < 0:
        raise ValueError('Negative parent PID')
    return {'pid': pid, 'ppid': ppid, 'start_ticks': start, 'name': label, 'cpu_ticks': ticks, 'rss_bytes': pages * page_size}


class ProcessCollector:
    def __init__(self, sys_root=Path('/sys'), proc_root=Path('/proc'), *, clock=clocks):
        self.proc, self.clock = proc_root, clock
        self.sources = []
        self.context = {}
        self.previous = {}
        self.last_pid = 0
        self.interval = 30
        self.top_n = 5
        self.hz = os.sysconf('SC_CLK_TCK')
        self.page_size = os.sysconf('SC_PAGE_SIZE')
        self.cpu_count = os.cpu_count() or 1
        self.generation = None

    def configure(self, options):
        interval, top_n = options['interval_seconds'], options['top_n']
        if interval != self.interval or options.get('generation') != self.generation:
            self.previous.clear()
        self.interval, self.top_n = interval, top_n
        self.generation = options.get('generation')

    def discover(self):
        return []

    def read(self):
        started = time.monotonic_ns()
        counters = {'scanned': 0, 'readable': 0, 'permission_denied': 0, 'vanished': 0, 'parse_errors': 0}
        rows, truncated, visible = [], False, 0
        # Stream directory entries; cap both enumeration and reads. Resume after the
        # last scanned PID within the bounded candidate set when a time limit is hit.
        with os.scandir(self.proc) as entries:
            candidates = []
            for entry in entries:
                if time.monotonic_ns() - started >= MAX_SCAN_NS:
                    truncated = True
                    break
                if entry.name.isascii() and entry.name.isdigit():
                    visible += 1
                    if visible > MAX_PIDS:
                        truncated = True
                        break
                    candidates.append(int(entry.name))
        candidates.sort(key=lambda pid: (pid <= self.last_pid, pid))
        for pid in candidates:
            if time.monotonic_ns() - started >= MAX_SCAN_NS:
                truncated = True
                break
            counters['scanned'] += 1
            self.last_pid = pid
            try:
                with (self.proc / str(pid) / 'stat').open() as stream:
                    text = stream.read(4097)
                if len(text) > 4096:
                    raise ValueError('Oversize stat')
                row = parse_stat(text, pid, self.page_size)
                mono, utc, boot = self.clock()
                old = self.previous.get(pid)
                row.update(cpu_percent=None, previous_cpu_ticks=None, interval_start_ms=None,
                           interval_end_ms=utc // 1_000_000, elapsed_ns=None)
                if old and old['start_ticks'] == row['start_ticks'] and old['name'] == row['name']:
                    elapsed = mono - old['mono']
                    delta = row['cpu_ticks'] - old['cpu_ticks']
                    continuous = (0 < elapsed <= (self.interval * 2.5 + 2) * 1e9
                        and abs((boot - old['boot']) - elapsed) < 1e9
                        and abs((utc - old['utc']) - elapsed) < 2e9)
                    percent = delta / self.hz / (elapsed / 1e9) / self.cpu_count * 100 if continuous else None
                    if percent is not None and delta >= 0 and 0 <= percent <= 100.01:
                        row.update(cpu_percent=min(100.0, percent), previous_cpu_ticks=old['cpu_ticks'],
                                   interval_start_ms=old['utc'] // 1_000_000, elapsed_ns=elapsed)
                self.previous[pid] = {**{k: row[k] for k in ('start_ticks','cpu_ticks','name')}, 'mono':mono,'utc':utc,'boot':boot}
                rows.append(row)
                counters['readable'] += 1
            except PermissionError:
                counters['permission_denied'] += 1
                self.previous.pop(pid, None)
            except (FileNotFoundError, ProcessLookupError):
                counters['vanished'] += 1
                self.previous.pop(pid, None)
            except (OSError, ValueError, IndexError):
                counters['parse_errors'] += 1
                self.previous.pop(pid, None)
        # Remove dead/unseen entries after a full pass; otherwise keep bounded baselines.
        if not truncated:
            present = {r['pid'] for r in rows}
            self.previous = {pid: value for pid, value in self.previous.items() if pid in present}
        while len(self.previous) > MAX_PIDS:
            self.previous.pop(next(iter(self.previous)))
        cpu = heapq.nlargest(self.top_n, (r for r in rows if r['cpu_percent'] is not None), key=lambda r:(r['cpu_percent'],-r['pid']))
        memory = heapq.nlargest(self.top_n, rows, key=lambda r:(r['rss_bytes'],-r['pid']))
        chosen = {r['pid']: r for r in cpu + memory}
        by_pid = {row['pid']: row for row in rows}
        for row in chosen.values():
            row['ancestors'] = capture_ancestors(row, by_pid)
        self.context = {**counters, 'truncated':truncated, 'top_n':self.top_n, 'interval_seconds':self.interval,
            'application_catalog_version':CATALOG_VERSION,
            'clock_ticks_per_second':self.hz, 'machine_cpu_count':self.cpu_count,
            'cpu_intervals':sum(r['cpu_percent'] is not None for r in rows),
            'scan_ms':(time.monotonic_ns()-started)/1e6, 'entries':list(chosen.values()),
            'cpu_basis':'percent_of_machine_capacity', 'memory_basis':'rss_shared_pages_may_repeat'}
        return [], []
