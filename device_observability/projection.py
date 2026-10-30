"""Conditional component-energy projections, calculated locally, never by an LLM."""
from __future__ import annotations

import math
import re
import unicodedata
from decimal import Decimal, InvalidOperation


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if not unicodedata.combining(c))


def asks_monthly_projection(question):
    text = normalized(question)
    monthly = re.search(r'\b(mensal|mensais|mes|meses|monthly|month)\b', text)
    energy = re.search(r'custo|gast|cust|pag|energia|consum|kwh|cost|energy', text)
    historical = re.search(r'\b(mes passado|ultimo mes|neste mes|este mes|mes atual)\b', text)
    explicit = re.search(r'proje|estim|previ|seria|custaria|gastaria', text)
    return bool(monthly and energy and (not historical or explicit))


def explicit_comparison_metric(question):
    text=normalized(question).strip()
    # Only this unambiguous, supported intent is bound automatically. Requests
    # about named dates, multiple components or other comparisons remain open.
    match=re.match(r'^(?:por favor,?\s+)?compar(?:e|ar)\s+(?:[ao]\s+)?(potencia(?:\s+reportada)?|uso|utilizacao)\s+(?:d[ao]\s+)?(cpu|gpu)\b',text)
    if not match or not re.search(r'\bentre\s+(?:as\s+)?(?:duas\s+)?metades\b',text) or len(set(re.findall(r'\b(?:cpu|gpu)\b',text)))!=1:
        return None
    return match[2]+('_w' if match[1].startswith('potencia') else '_percent')


def projection_scenario(question, hours_per_day=24, observed_usage=None):
    # An explicit daily duration in the question takes precedence over the UI default.
    matches = re.findall(r'(?<![\w.,])([+-]?[\d]+(?:[.,]\d+)?)\s*(?:horas?|h)\s*(?:por\s+dia|ao\s+dia|/\s*dia|diari[ao]s?)', normalized(question))
    durations = {float(value.replace(',', '.')) for value in matches}
    if len(durations) > 1:
        raise ValueError('Escolha uma duração diária por análise para a projeção mensal.')
    hours = next(iter(durations)) if durations else hours_per_day
    automatic = hours is None
    if automatic:
        hours = (observed_usage or {}).get('hours_per_day')
        if hours is None:
            raise ValueError('Ainda não há intervalos suficientes para calcular o tempo observado. Aguarde a coleta ou informe horas por dia.')
    if type(hours) not in (int, float) or not math.isfinite(hours) or not 0 < hours <= 24:
        raise ValueError('Informe mais de zero e no máximo 24 horas de uso por dia.')
    return {'hours_per_day': hours, 'days': 30, 'hours_origin': 'question' if durations else 'collector_observed' if automatic else 'interface_scenario',
            **({'observed_usage': observed_usage} if automatic else {})}


def monthly_projection(frozen):
    """Use each component's actual covered duration; gaps are never treated as off-time."""
    scenario = frozen.get('projection', projection_scenario(''))
    hours = Decimal(str(scenario['hours_per_day']))
    days = scenario['days']
    rows = []
    for component in frozen['components']:
        energy, covered = component['energy_kwh'], component['covered_seconds']
        if (type(energy) not in (int, float) or type(covered) not in (int, float)
                or not math.isfinite(energy) or not math.isfinite(covered) or energy < 0 or covered <= 0):
            continue
        hourly_kwh = Decimal(str(energy)) * 3600 / Decimal(str(covered))
        rows.append({**component, 'observed_hours': covered / 3600, 'hourly_kwh': float(hourly_kwh),
                     'projected_kwh': float(hourly_kwh * hours * days)})
    # Use the tariff effective at the END of the base window, not an average of old tariffs.
    applicable = [t for t in frozen['tariffs'] if t['effective_ms'] <= frozen['window']['end_ms']]
    tariff = max(applicable, key=lambda t: t['effective_ms']) if applicable else None
    price = None
    if tariff:
        try:
            candidate = Decimal(str(tariff['price']))
            if candidate.is_finite() and candidate >= 0: price = candidate
        except InvalidOperation:
            pass
    independent = len(rows) <= 1 or all(row.get('energy_domain') in ('cpu_package', 'discrete_gpu') for row in rows)
    energy = sum((Decimal(str(row['projected_kwh'])) for row in rows), Decimal(0)) if rows and independent else None
    for row in rows:
        row['projected_cost_brl'] = float(Decimal(str(row['projected_kwh'])) * price) if price is not None else None
    return {**scenario, 'components': rows, 'missing_components': [name for name in ('cpu', 'gpu') if name not in {c['id'] for c in rows}],
            'tariff': tariff if price is not None else None, 'tariff_brl_per_kwh': float(price) if price is not None else None,
            'projected_kwh': float(energy) if energy is not None else None,
            'projected_cost_brl': float(energy * price) if energy is not None and price is not None else None,
            'window_hours': (frozen['window']['end_ms'] - frozen['window']['start_ms']) / 3_600_000,
            'whole_pc_measured': False, 'independent_components': independent, 'status': 'no_data' if not rows else 'domain_unconfirmed' if not independent else 'needs_tariff' if price is None else 'projected'}
