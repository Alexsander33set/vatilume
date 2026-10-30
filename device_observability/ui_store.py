from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import date, datetime, time as datetime_time, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/Sao_Paulo")


class UIStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as con:
            con.executescript("""CREATE TABLE IF NOT EXISTS tariffs(
                id TEXT PRIMARY KEY, effective_ms INTEGER UNIQUE NOT NULL, price TEXT NOT NULL,
                description TEXT NOT NULL, created_ms INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS audit(
                id INTEGER PRIMARY KEY, utc_ms INTEGER NOT NULL, kind TEXT NOT NULL, details TEXT NOT NULL);""")

    def connect(self):
        con = sqlite3.connect(self.path, timeout=3, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")
        return con

    def tariffs(self):
        with closing(self.connect()) as con:
            return [dict(row) for row in con.execute("SELECT * FROM tariffs ORDER BY effective_ms")]

    def save_tariff(self, price: str, effective_date: str, description: str) -> dict:
        normalized = price.strip().replace(",", ".")
        if not re.fullmatch(r"\d{1,4}(?:\.\d{1,6})?", normalized) or not 0 < Decimal(normalized) <= 1000:
            raise ValueError("Informe um valor de kWh positivo, com até seis casas decimais.")
        day = date.fromisoformat(effective_date)
        if day.year < 2000 or day.year > 2100:
            raise ValueError("A data de vigência deve estar entre 2000 e 2100.")
        effective_ms = int(datetime.combine(day, datetime_time.min, ZONE).timestamp() * 1000)
        item = {"id": str(uuid.uuid4()), "effective_ms": effective_ms,
                "price": str(Decimal(normalized)), "description": description.strip()[:180], "created_ms": time.time_ns() // 1_000_000}
        with closing(self.connect()) as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                previous = con.execute("SELECT * FROM tariffs WHERE effective_ms=?", (effective_ms,)).fetchone()
                if previous:
                    item["id"] = previous["id"]
                    con.execute("UPDATE tariffs SET price=?,description=?,created_ms=? WHERE id=?",
                                (item["price"], item["description"], item["created_ms"], item["id"]))
                else:
                    con.execute("INSERT INTO tariffs VALUES (:id,:effective_ms,:price,:description,:created_ms)", item)
                con.execute("INSERT INTO audit(utc_ms,kind,details) VALUES (?,?,?)",
                            (item["created_ms"], "tariff_saved", json.dumps({"before": dict(previous) if previous else None, "after": item})))
                con.commit()
            except BaseException:
                con.rollback()
                raise
        return item

    def audit(self, kind: str, details: dict):
        with closing(self.connect()) as con:
            con.execute("INSERT INTO audit(utc_ms,kind,details) VALUES (?,?,?)",
                        (time.time_ns() // 1_000_000, kind, json.dumps(details)))
