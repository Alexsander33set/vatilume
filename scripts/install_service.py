#!/usr/bin/env python3
"""Install immutable, root-owned code and enable one dedicated system service.

    sudo python3 scripts/install_service.py

No pip/network access, no changes to sensor controls, no data deletion. Existing
configuration is preserved. Re-running installs a versioned release and restarts
only device-observability.service. --check performs read-only preflight checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import venv
from contextlib import closing
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
PREFIX = Path("/opt/device-observability")
CONFIG = Path("/etc/device-observability/collector.toml")
UNIT = Path("/etc/systemd/system/device-observability.service")
ACCOUNT = "device-observability"
MARKER = "# Managed by device-observability/scripts/install_service.py"


def call(arguments, **kwargs):
    return subprocess.run(arguments, check=True, text=True, **kwargs)


def release_files(include_interface=False):
    files = list((PROJECT / "device_observability").glob("*.py"))
    files.extend((PROJECT / "docs").glob("*.md"))
    files += [PROJECT / "README.md", PROJECT / "pyproject.toml"]
    if include_interface:
        files.extend(p for p in (PROJECT / "backend/static").rglob("*") if p.is_file())
        files.extend((PROJECT / "scripts/wheels").glob("*.whl"))
        files.append(PROJECT / "backend/requirements.lock")
    return sorted(files)


def digest(files):
    result = hashlib.sha256()
    for path in files:
        result.update(str(path.relative_to(PROJECT)).encode() + b"\0" + path.read_bytes() + b"\0")
    return result.hexdigest()[:16]


def install_file(source, destination, mode=0o644):
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    temporary = destination.with_name(destination.name + ".new")
    if temporary.exists() or temporary.is_symlink():
        raise RuntimeError(f"refusing to overwrite staging file {temporary}")
    with temporary.open("xb") as output:
        output.write(source.read_bytes())
        output.flush()
        os.fsync(output.fileno())
    temporary.chmod(mode)
    os.replace(temporary, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="preflight only, no installation")
    parser.add_argument("--validate-recovery", action="store_true", help="after installation, validate SIGKILL recovery for this service only")
    parser.add_argument("--with-interface", action="store_true", help="install the built local UI and its optional offline runtime")
    parser.add_argument('--with-processes', action='store_true', help='enable bounded CPU/RSS process collection, preserving other settings')
    args = parser.parse_args()
    for command in ("systemctl", "systemd-analyze", "useradd", "runuser"):
        if not shutil.which(command):
            raise RuntimeError(f"required command missing: {command}")
    call(["/usr/bin/python3", "-c", "import sys,sqlite3,tomllib; assert sys.version_info >= (3,11)"])
    call(["systemd-analyze", "verify", str(PROJECT / "systemd/device-observability.service")],
         env={**os.environ, "SYSTEMD_LOG_LEVEL": "warning"})
    if UNIT.exists() and not UNIT.read_text().startswith(MARKER):
        raise RuntimeError(f"existing unmanaged unit must be reviewed: {UNIT}")
    if args.with_interface:
        if not (PROJECT / "backend/static/index.html").is_file() or not list((PROJECT / "scripts/wheels").glob("uvicorn-*.whl")):
            raise RuntimeError("build the interface and prepare its locked offline wheels before installing")
        with tempfile.TemporaryDirectory(prefix="device-observability-units-") as staging:
            paths = []
            for name in ("device-observability-web.socket", "device-observability-web.service"):
                target = Path(staging) / name
                # The installed venv doesn't exist until installation; validate the
                # unit syntax with the already-verified system interpreter instead.
                target.write_text((PROJECT / "systemd" / name).read_text().replace(
                    "/opt/device-observability/current/.venv/bin/python", "/usr/bin/python3"))
                paths.append(str(target))
            call(["systemd-analyze", "verify", *paths])
    files = release_files(args.with_interface)
    identity = digest(files)
    release = PREFIX / "releases" / identity
    if args.check:
        print(json.dumps({"preflight": "ok", "release": str(release), "unit": str(UNIT),
                          "configuration": str(CONFIG), "existing_configuration_preserved": True,
                          'enable_processes':args.with_processes}, indent=2))
        return
    if os.geteuid() != 0:
        raise PermissionError("run this installer with sudo from your terminal")
    try:
        account = pwd.getpwnam(ACCOUNT)
    except KeyError:
        call(["useradd", "--system", "--user-group", "--home-dir", "/var/lib/device-observability",
              "--no-create-home", "--shell", "/usr/sbin/nologin", ACCOUNT])
        account = pwd.getpwnam(ACCOUNT)
    if account.pw_uid == 0:
        raise RuntimeError("service account must not be root")
    if release.exists():
        for path in files:
            target = release / path.relative_to(PROJECT)
            if target.is_symlink() or target.read_bytes() != path.read_bytes():
                raise RuntimeError("existing release differs; refusing overwrite")
    else:
        release.mkdir(parents=True, mode=0o755)
        for path in files:
            install_file(path, release / path.relative_to(PROJECT))
    if args.with_interface:
        owner = pwd.getpwnam(os.environ["SUDO_USER"]) if os.environ.get("SUDO_USER") else pwd.getpwuid(PROJECT.stat().st_uid)
        uv = shutil.which("uv") or str(Path(owner.pw_dir) / ".local/bin/uv")
        if not Path(uv).is_file():
            raise RuntimeError("uv is required only to prepare the isolated optional interface environment")
        venv.EnvBuilder(with_pip=False, symlinks=True).create(release / ".venv")
        call([uv, "pip", "sync", "--python", str(release / ".venv/bin/python"), "--no-index",
              "--find-links", str(release / "scripts/wheels"), "--require-hashes", str(release / "backend/requirements.lock"),
              "--cache-dir", str(PREFIX / "build-cache")])
        call([str(release / ".venv/bin/python"), "-c", "from device_observability.web import create_app"], cwd=release)
    CONFIG.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    if not CONFIG.exists():
        install_file(PROJECT / "config/service.toml", CONFIG, 0o640)
        os.chown(CONFIG, 0, account.pw_gid)
    # Validate the preserved configuration before switching an installed version.
    call(["/usr/bin/python3", "-c",
          "from pathlib import Path; from device_observability.config import load_config; load_config(Path('/etc/device-observability/collector.toml'))"], cwd=release)
    if args.with_interface:
        database = Path("/var/lib/device-observability/telemetry.sqlite3")
        if database.exists():
            target = PREFIX / "backups" / f"telemetry-before-interface-{time.time_ns()}.sqlite3"
            target.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as reader, closing(sqlite3.connect(target)) as writer:
                reader.backup(writer)
                if writer.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("pre-update backup integrity failed")
            target.chmod(0o600)
    if UNIT.exists():
        destination = PREFIX / "backups" / f"unit-{time.time_ns()}.service"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(UNIT, destination)
    install_file(PROJECT / "systemd/device-observability.service", UNIT)
    if args.with_interface:
        for name in ("device-observability-web.socket", "device-observability-web.service"):
            destination = UNIT.parent / name
            if destination.exists() and not destination.read_text().startswith("# Managed by device-observability"):
                raise RuntimeError(f"unmanaged existing unit: {destination}")
            install_file(PROJECT / "systemd" / name, destination)
        sys.path.insert(0, str(PROJECT))
        from device_observability.ai_install import migrate_ai_state
        migrated = migrate_ai_state(PROJECT / 'var/ai', Path('/var/lib/device-observability'),
            account.pw_uid, account.pw_gid, owner.pw_uid, owner.pw_gid)
        print(json.dumps({'ai_migration': migrated}))
    current = PREFIX / "current"
    if current.exists() and not current.is_symlink():
        raise RuntimeError("current must be a release symlink")
    previous = os.readlink(current) if current.is_symlink() else None
    temporary = PREFIX / "current.new"
    temporary.symlink_to(release)
    os.replace(temporary, current)
    if args.with_processes:
        sys.path.insert(0, str(PROJECT))
        from device_observability.config import EDITABLE, load_config
        from device_observability.controls import durable_json
        selected = load_config(CONFIG)
        values = {key:selected.document()[key] for key in EDITABLE}
        if 'processes' not in values['enabled_collectors']:
            values['enabled_collectors'].append('processes')
        selected.data_dir.mkdir(parents=True, exist_ok=True, mode=0o750)
        os.chown(selected.data_dir, account.pw_uid, account.pw_gid)
        overrides = selected.data_dir / 'collector-overrides.json'
        durable_json(overrides, values)
        overrides.chmod(0o600)
        os.chown(overrides, account.pw_uid, account.pw_gid)
        print(json.dumps({'process_collection':'enabled','interval_seconds':selected.process_interval_seconds,
                          'top_n_per_ranking':selected.process_top_n,'other_settings_preserved':True}))
    (PREFIX / "installation.json").write_text(json.dumps({
        "release": str(release), "previous_release": previous, "installed_utc_ns": time.time_ns(),
    }, indent=2) + "\n")
    call(["systemctl", "daemon-reload"])
    call(["systemctl", "enable", "device-observability.service"])
    call(["systemctl", "restart", "device-observability.service"])
    deadline = time.monotonic() + 30
    while True:
        result = subprocess.run(["runuser", "-u", ACCOUNT, "--", "/usr/bin/python3", "-m", "device_observability",
                                 "--config", str(CONFIG), "status"], cwd=release, capture_output=True, text=True)
        if result.returncode == 0:
            health = json.loads(result.stdout)
            if health["state"] == "running" and health["health"]["last_committed_sequence"] >= 1:
                print(json.dumps({"installation": "ok", "release": str(release), "status": health}, indent=2))
                break
        if time.monotonic() >= deadline:
            print(result.stdout + result.stderr, file=sys.stderr)
            raise RuntimeError("service did not report healthy collection; inspect journalctl -u device-observability")
        time.sleep(0.5)
    call(["systemctl", "is-enabled", "device-observability.service"])
    if args.with_interface:
        import urllib.request
        directory = Path("/var/lib/device-observability")
        token_path = directory / "interface-token"
        if not token_path.exists():
            fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(secrets.token_urlsafe(32))
            os.chown(token_path, account.pw_uid, account.pw_gid)
        token = token_path.read_text().strip()
        access = PROJECT / "var/interface-access.url"
        access.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(access, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write("http://127.0.0.1:8765/#access=" + token + "\n")
        access.chmod(0o600)
        os.chown(access, owner.pw_uid, owner.pw_gid)
        call(["systemctl", "enable", "--now", "device-observability-web.socket"])
        # Restart only if an earlier UI process is active; otherwise socket activation starts it below.
        if subprocess.run(["systemctl", "is-active", "--quiet", "device-observability-web.service"]).returncode == 0:
            call(["systemctl", "restart", "device-observability-web.service"])
        request = urllib.request.Request("http://127.0.0.1:8765/api/session", method="POST", headers={
            "Origin": "http://127.0.0.1:8765", "Authorization": "Bearer " + token})
        deadline = time.monotonic() + 30
        while True:
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    if response.status == 200:
                        break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("interface did not respond; inspect its systemd journal")
                time.sleep(.5)
        call(["runuser", "-u", owner.pw_name, "--", "/usr/bin/python3",
              str(PROJECT / "scripts/install_launcher.py"), "--home", owner.pw_dir])
        print(json.dumps({"interface": "ready", "application": "Vatilume", "address": "http://127.0.0.1:8765",
                          "command": "vatilume", "launcher": str(Path(owner.pw_dir) / ".local/bin/vatilume"),
                          "open": str(PROJECT / "open-ui.sh"), "access_key_in_private_file": True}, indent=2))
    if args.validate_recovery:
        call(["/usr/bin/python3", str(PROJECT / "scripts/validate_service.py"), "--restart-test"])


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        sys.exit(1)
