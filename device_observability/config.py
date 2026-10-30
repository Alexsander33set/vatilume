from __future__ import annotations

import hashlib
import json
import math
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

COLLECTORS = {"system", "powercap", "gpu", "thermal", "processes", "network"}
EDITABLE = {"interval_seconds", "thermal_interval_seconds", "enabled_collectors", "process_interval_seconds", "process_top_n", "max_storage_bytes", "retention_days"}


@dataclass(frozen=True)
class Config:
    data_dir: Path
    interval_seconds: float = 10
    thermal_interval_seconds: float = 30
    process_interval_seconds: float = 30
    process_top_n: int = 5
    sensor_timeout_seconds: float = 2
    rediscover_seconds: float = 300
    max_pending_cycles: int = 3
    minimum_free_bytes: int = 256 * 1024 * 1024
    max_storage_bytes: int = 2 * 1024**3
    retention_days: int = 0
    enabled_collectors: tuple[str, ...] = ("system", "powercap", "gpu", "thermal")

    def validate(self) -> Config:
        for name, minimum, maximum in (
            ("interval_seconds", 0.1, 86400),
            ("thermal_interval_seconds", 0.1, 86400),
            ("process_interval_seconds", 5, 3600),
            ("sensor_timeout_seconds", 0.01, 30),
            ("rediscover_seconds", 0.1, 86400),
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a number")
            if not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError(f"{name} must be between {minimum} and {maximum}")
        for name, minimum, maximum in (
            ("max_pending_cycles", 1, 100),
            ("process_top_n", 1, 10),
            ("minimum_free_bytes", 0, 1024**4),
            ("max_storage_bytes", 64 * 1024**2, 1024**4),
            ("retention_days", 0, 3650),
        ):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")
        if not self.enabled_collectors or len(set(self.enabled_collectors)) != len(self.enabled_collectors):
            raise ValueError("enabled_collectors must be nonempty and unique")
        if set(self.enabled_collectors) - COLLECTORS:
            raise ValueError("unknown collector")
        return self

    def document(self) -> dict:
        result = asdict(self)
        result["data_dir"] = str(self.data_dir)
        result["enabled_collectors"] = list(self.enabled_collectors)
        return result

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.document(), sort_keys=True).encode()).hexdigest()


def load_config(path: Path, *, overrides: bool = True) -> Config:
    path = path.resolve()
    values = tomllib.loads(path.read_text())
    unknown = set(values) - set(Config.__dataclass_fields__)
    if unknown:
        raise ValueError(f"unknown configuration keys: {sorted(unknown)}")
    directory = values.pop("data_dir", "../var/collector")
    if not isinstance(directory, str) or not directory:
        raise ValueError("data_dir must be a nonempty path")
    if "enabled_collectors" in values:
        names = values["enabled_collectors"]
        if not isinstance(names, list) or any(not isinstance(x, str) for x in names):
            raise ValueError("enabled_collectors must be an array of strings")
        values["enabled_collectors"] = tuple(names)
    config = Config(data_dir=(path.parent / directory).resolve(), **values).validate()
    override_path = config.data_dir / "collector-overrides.json"
    if overrides and override_path.exists():
        patch = json.loads(override_path.read_text())
        if not isinstance(patch, dict) or set(patch) - EDITABLE:
            raise ValueError("invalid collector overrides")
        document = config.document()
        document.update(patch)
        document["data_dir"] = config.data_dir
        names = document["enabled_collectors"]
        if not isinstance(names, list) or any(not isinstance(x, str) for x in names):
            raise ValueError("invalid collector list")
        document["enabled_collectors"] = tuple(names)
        config = Config(**document).validate()
    return config

