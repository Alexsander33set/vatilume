"""Durable cumulative spending guard shared by the installed UI and evaluations.

Reservations survive uncertain HTTP outcomes. Values are conservative estimates
from full-price token usage, not a statement from the billing provider.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .ai_models import DEFAULT_MODEL, model_info

MODEL = DEFAULT_MODEL
MAX_TOTAL_USD = 1000.0
PRICE = (.75, 4.50)
DEFAULT_LIMITS = {'enabled': True, 'per_analysis_usd': .05, 'daily_usd': 1.0, 'monthly_usd': 2.0}
ZONE = ZoneInfo('America/Sao_Paulo')


def atomic_json(path: Path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


class CostLedger:
    def __init__(self, path: Path, limits_path: Path):
        self.path, self.limits_path = path, limits_path
        path.parent.mkdir(parents=True, exist_ok=True)

    def update(self, operation, *, limits_to_commit=None):
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ledger = json.loads(self.path.read_text()) if self.path.exists() else {'cap_usd': 0.0, 'requests': []}
            cap = ledger.get('cap_usd')
            if isinstance(cap, bool) or not isinstance(cap, (int, float)) or not math.isfinite(cap) or not 0 <= cap <= MAX_TOTAL_USD:
                raise ValueError('O limite acumulado do histórico é inválido; operação bloqueada.')
            limits = {**DEFAULT_LIMITS, 'enabled': cap > 0,
                      **(json.loads(self.limits_path.read_text()) if self.limits_path.exists() else {})}
            before = json.dumps(ledger, sort_keys=True)
            result = operation(ledger, limits)
            # Cross-file changes fail closed: an interrupted configuration leaves
            # calls paused until the owner saves again, never a partially raised
            # spending ceiling with calls already enabled.
            if limits_to_commit is not None:
                atomic_json(self.limits_path, {**limits_to_commit, 'enabled': False})
            if not self.path.exists() or before != json.dumps(ledger, sort_keys=True): atomic_json(self.path, ledger)
            if limits_to_commit is not None:
                atomic_json(self.limits_path, limits_to_commit)
            return result

    @staticmethod
    def amount(row):
        return float(row.get('actual_usd', row['reserved_usd']))

    def totals(self, ledger):
        now = datetime.now(ZONE)
        today, month = now.strftime('%Y-%m-%d'), now.strftime('%Y-%m')
        total = daily = monthly = pending = 0.0
        for row in ledger['requests']:
            amount = self.amount(row)
            if not math.isfinite(amount) or amount < 0: raise ValueError('Registro de gasto inválido.')
            stamp = datetime.fromtimestamp(row['utc_ms'] / 1000, ZONE).strftime('%Y-%m-%d')
            uncertain = row.get('state') != 'completed'
            total += amount
            if uncertain: pending += amount
            if stamp == today or uncertain: daily += amount
            if stamp[:7] == month or uncertain: monthly += amount
        return {'total_usd': total, 'daily_usd': daily, 'monthly_usd': monthly, 'pending_usd': pending}

    def status(self):
        def read(ledger, limits):
            totals = self.totals(ledger)
            return {'limits': limits, 'authorized_total_usd': ledger['cap_usd'], 'model': MODEL,
                    'prices_per_million_usd': {'input': PRICE[0], 'output': PRICE[1]},
                    'usage': totals, 'remaining_usd': max(0, min(ledger['cap_usd'] - totals['total_usd'],
                    limits['daily_usd'] - totals['daily_usd'], limits['monthly_usd'] - totals['monthly_usd'])),
                    'basis': 'full_rate_token_estimate_including_uncertain_reservations',
                    'timezone': 'America/Sao_Paulo'}
        return self.update(read)

    def configure(self, values, *, cap_usd=None):
        if set(values) != set(DEFAULT_LIMITS) or not isinstance(values['enabled'], bool):
            raise ValueError('Configuração de gasto inválida.')
        for key in ('per_analysis_usd', 'daily_usd', 'monthly_usd'):
            value = values[key]
            maximum = 5.0 if key == 'per_analysis_usd' else MAX_TOTAL_USD
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not .001 <= value <= maximum:
                raise ValueError('Use limites positivos; por análise até US$ 5 e por dia/mês até US$ 1.000.')
        if not values['per_analysis_usd'] <= values['daily_usd'] <= values['monthly_usd']:
            raise ValueError('Use limite por análise ≤ diário ≤ mensal.')
        def save(ledger, limits):
            cap = ledger['cap_usd'] if cap_usd is None else cap_usd
            if isinstance(cap, bool) or not isinstance(cap, (float, int)) or not math.isfinite(cap) or not 0 <= cap <= MAX_TOTAL_USD:
                raise ValueError('O limite acumulado precisa ficar entre US$ 0 e US$ 1.000.')
            if cap + 1e-12 < self.totals(ledger)['total_usd']:
                raise ValueError('O limite acumulado não pode ficar abaixo do gasto e das reservas já registrados.')
            if values['enabled'] and (cap == 0 or any(values[key] > cap for key in ('per_analysis_usd','daily_usd','monthly_usd'))):
                raise ValueError('O limite excede o teto acumulado deste histórico.')
            ledger['cap_usd'] = cap
        self.update(save, limits_to_commit=values)
        return self.status()

    def reserve(self, payload: bytes, max_output_tokens: int, analysis_id: str, *, maximum=None, model=MODEL):
        if self.path.name == 'budget.json' and (self.path.parent / 'budget-managed.json').exists():
            raise ValueError('O gasto foi migrado para a interface instalada. Use esse acesso para novas análises.')
        price = model_info(model)
        bound = ((len(payload) + 4096) * price['reserve_input'] + max_output_tokens * price['output']) / 1e6
        identity = str(uuid.uuid4())
        def append(ledger, limits):
            if not limits['enabled']: raise ValueError('As chamadas de IA estão pausadas.')
            totals = self.totals(ledger)
            per_run = sum(self.amount(r) for r in ledger['requests'] if r.get('analysis_id') == analysis_id)
            checks = [(totals['total_usd'], ledger['cap_usd']), (totals['daily_usd'], limits['daily_usd']),
                      (totals['monthly_usd'], limits['monthly_usd']),
                      (per_run, min(limits['per_analysis_usd'], maximum) if maximum is not None else limits['per_analysis_usd'])]
            if any(used + bound > maximum + 1e-12 for used, maximum in checks):
                raise ValueError('A próxima chamada excederia um limite de gasto. Consulte os gastos e limites.')
            ledger['requests'].append({'id': identity, 'analysis_id': analysis_id, 'model': model,
                'utc_ms': time.time_ns() // 1_000_000, 'state': 'reserved', 'reserved_usd': bound})
        self.update(append)
        return identity

    def finish(self, identity, usage):
        if set(usage) != {'input_tokens', 'output_tokens'} or any(type(v) is not int or v < 0 for v in usage.values()):
            raise ValueError('Uso retornado pelo provedor é inválido; a reserva será mantida.')
        def complete(ledger, limits):
            row = next(r for r in ledger['requests'] if r['id'] == identity)
            price = model_info(row.get('model', MODEL))
            actual = (usage['input_tokens'] * price['reserve_input'] + usage['output_tokens'] * price['output']) / 1e6
            row.update(state='completed', usage=usage, actual_usd=actual)
        self.update(complete)

    def run_cost(self, identity):
        return self.update(lambda ledger, limits: sum(self.amount(r) for r in ledger['requests'] if r.get('analysis_id') == identity))
