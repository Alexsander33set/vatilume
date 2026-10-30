from __future__ import annotations

import json
import os
import signal
import tempfile
import threading
from dataclasses import replace
from pathlib import Path

from .agent import process_start_ticks
from .config import EDITABLE, load_config


def durable_json(path: Path, document: dict):
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(document, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


class Controls:
    def __init__(self, config_path: Path):
        self.path = config_path
        self.lock = threading.Lock()

    def health(self) -> dict:
        config = load_config(self.path)
        try:
            return json.loads((config.data_dir / "health.json").read_text())
        except (OSError, ValueError):
            return {}

    def settings(self):
        config = load_config(self.path)
        health = self.health()
        return {"values": {k: config.document()[k] for k in EDITABLE}, "revision": config.fingerprint,
                "applied_revision": health.get("config_hash"),
                "applied": health.get("config_hash") == config.fingerprint,
                "reload_supported": "config_hash" in health}

    def save(self, patch: dict, revision: str):
        with self.lock:
            config = load_config(self.path)
            if revision != config.fingerprint:
                raise ValueError("A configuração mudou em outra sessão. Atualize os dados antes de salvar.")
            if set(patch) - EDITABLE:
                raise ValueError("Campo de configuração não permitido.")
            if "enabled_collectors" in patch:
                names = patch["enabled_collectors"]
                if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
                    raise ValueError("Selecione pelo menos um grupo de sensores.")
                patch["enabled_collectors"] = tuple(names)
            candidate = replace(config, **patch).validate()
            health = self.health()
            if "config_hash" not in health:
                raise ValueError("O coletor precisa ser atualizado antes de aplicar configurações pela interface.")
            pid = health.get("pid")
            running = (type(pid) is int and pid > 1 and health.get("running") is True
                       and health.get("boot_id") == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
                       and health.get("pid_start_ticks") is not None
                       and process_start_ticks(pid) == health["pid_start_ticks"])
            if not running:
                raise ValueError("O coletor não está ativo. Nenhuma configuração foi alterada.")
            target = config.data_dir / "collector-overrides.json"
            previous = json.loads(target.read_text()) if target.exists() else None
            values = {k: candidate.document()[k] for k in EDITABLE}
            durable_json(target, values)
            try:
                os.kill(pid, signal.SIGHUP)
            except OSError:
                if previous is None:
                    target.unlink(missing_ok=True)
                else:
                    durable_json(target, previous)
                raise ValueError("Não foi possível notificar o coletor. A configuração anterior foi preservada.") from None
            return self.settings()
