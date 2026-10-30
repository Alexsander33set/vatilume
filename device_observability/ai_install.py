"""Private key and cumulative budget migration, called only by the installer."""
import fcntl
import json
import math
import os
import stat
import time
from pathlib import Path

from .ai_cost import MAX_TOTAL_USD, CostLedger, atomic_json


def migrate_ai_state(source: Path, target: Path, service_uid: int, service_gid: int, owner_uid: int, owner_gid: int):
    created = not source.exists()
    source.mkdir(parents=True, exist_ok=True)
    if created: os.chown(source, owner_uid, owner_gid)
    target.mkdir(parents=True, exist_ok=True)
    if source.is_symlink() or target.is_symlink(): raise ValueError('State directories cannot be symlinks')
    os.chown(target, service_uid, service_gid)
    with (source / 'budget.lock').open('a') as source_lock, (target / 'ai-budget.lock').open('a') as target_lock:
        fcntl.flock(source_lock, fcntl.LOCK_EX)
        fcntl.flock(target_lock, fcntl.LOCK_EX)
        os.chown(source / 'budget.lock', owner_uid, owner_gid)
        os.chown(target / 'ai-budget.lock', service_uid, service_gid)
        ledgers = []
        for path in (source / 'budget.json', target / 'ai-budget.json'):
            if path.exists():
                if path.is_symlink() or path.stat().st_size > 32 * 1024 * 1024: raise ValueError('Unsafe budget file')
                ledger = json.loads(path.read_text())
                cap = ledger.get('cap_usd')
                if isinstance(cap, bool) or not isinstance(cap, (float, int)) or not math.isfinite(cap) or not 0 <= cap <= MAX_TOTAL_USD:
                    raise ValueError('Invalid existing budget cap; migration blocked')
                ledgers.append(ledger)
        combined = {}
        for ledger in ledgers:
            for row in ledger['requests']:
                combined[row['id']] = row
        # The installed ledger is authoritative when present; otherwise retain
        # the legacy authorization. A fresh install grants no budget. Migration
        # must never raise a ceiling to a value chosen for the private pilot.
        cap = ledgers[-1]['cap_usd'] if ledgers else 0.0
        amounts = [CostLedger.amount(row) for row in combined.values()]
        if any(not math.isfinite(value) or value < 0 for value in amounts) or sum(amounts) > cap + 1e-12:
            raise ValueError('Merged spending exceeds the existing authorization; review limits explicitly before migration')
        imported = {'cap_usd': cap, 'requests': list(combined.values())}
        atomic_json(target / 'ai-budget.json', imported)
        os.chown(target / 'ai-budget.json', service_uid, service_gid)
        key_source, key_target = source / 'openai-api-key', target / 'ai-api-key'
        if not key_target.exists() and key_source.exists():
            info = key_source.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != owner_uid or info.st_mode & 0o077:
                raise ValueError('Source API key must be private and owned by installing user')
            value = key_source.read_text().strip()
            if not 10 <= len(value) <= 1024 or any(c.isspace() for c in value): raise ValueError('Invalid API key file')
            fd = os.open(key_target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            os.chown(key_target, service_uid, service_gid)
        windows = []
        for path in sorted((source / 'runs').glob('*/resources.json')):
            item = json.loads(path.read_text())
            if 'started_utc_ms' in item and 'ended_utc_ms' in item:
                windows.append({'start_ms': item['started_utc_ms'], 'end_ms': item['ended_utc_ms'],
                                'kind': 'local_ai_evaluation'})
        atomic_json(target / 'ai-experiment-windows.json', windows)
        os.chown(target / 'ai-experiment-windows.json', service_uid, service_gid)
        # Stops the old standalone runner from creating a second spending pool.
        marker = source / 'budget-managed.json'
        atomic_json(marker, {'managed_by': 'installed_interface', 'migrated_ms': time.time_ns() // 1_000_000,
                            'authorized_total_usd': cap})
        os.chown(marker, owner_uid, owner_gid)
        return {'budget_preserved': True, 'requests_imported': len(combined), 'key_configured': key_target.is_file(),
                'authorized_total_usd': cap}
