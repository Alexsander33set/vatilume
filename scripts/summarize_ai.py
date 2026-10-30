#!/usr/bin/env python3
"""Summarize completed, matching pilot-3 runs without making model/API calls."""
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from device_observability.ai_evaluation import CASES, TOOLS_VERSION, grade

PRICES = {'gpt-5.4-nano-2026-03-17': (.20, 1.25), 'gpt-5.4-mini-2026-03-17': (.75, 4.50)}
MODELS = ['Qwen3-4B-Q4_K_M', 'Qwen3-8B-Q4_K_M', *PRICES]


def main():
    groups = {model: {} for model in MODELS}
    resources = {model: [] for model in MODELS}
    sources = {model: set() for model in MODELS}
    hashes = set()
    for path in sorted((ROOT / 'var/ai/runs').glob('*/manifest.json')):
        manifest = json.loads(path.read_text())
        model = manifest['model']
        if model not in groups or manifest.get('tools_version') != TOOLS_VERSION or manifest['repetitions'] != 3:
            continue
        if model not in PRICES and manifest.get('backend') != 'vulkan':
            continue
        for result_path in sorted(path.parent.glob('*-[123].json')):
            result = json.loads(result_path.read_text())
            if result['error']: raise ValueError('Incomplete primary run: ' + str(result_path))
            result['recomputed_grade'] = grade(result['case'], result['answer'], result['tools'])
            groups[model][result['case'], result['repetition']] = result
            hashes.add(result['dataset_sha256'])
        sources[model].add(str(path.parent.relative_to(ROOT)))
        resource_path = path.parent / 'resources.json'
        if resource_path.exists(): resources[model].append(json.loads(resource_path.read_text()))
    expected = {(case[0], repetition) for case in CASES for repetition in range(1, 4)}
    for model, group in groups.items():
        if set(group) != expected: raise ValueError(f'{model}: missing {sorted(expected - set(group))}')
    if len(hashes) != 1: raise ValueError('Datasets do not match')
    summary = {'method': {'cases': 14, 'repetitions': 3, 'tools_version': TOOLS_VERSION,
                         'dataset_sha256': hashes.pop(), 'grader_source_sha256': hashlib.sha256((ROOT / 'device_observability/ai_evaluation.py').read_bytes()).hexdigest(),
                         'quality_note': 'Mechanical schema, numeric and investigation checks; human review required. Not an independent quality grade.',
                         'cost_note': 'USD full-rate estimate from returned token usage; cached-input discounts ignored; not a billing statement.'},
               'models': []}
    for model, group in groups.items():
        results = list(group.values())
        times = sorted(result['elapsed_seconds'] for result in results)
        failures = Counter(f for r in results for f in r['recomputed_grade']['failures'])
        usage = {k: sum(c['usage'][k] for r in results for c in r['calls']) for k in ('input_tokens', 'output_tokens')}
        cost = (usage['input_tokens'] * PRICES[model][0] + usage['output_tokens'] * PRICES[model][1]) / 1e6 if model in PRICES else None
        model_resources = resources[model]
        summary['models'].append({'model': model, 'backend': 'api' if model in PRICES else 'vulkan',
            'analyses': len(results), 'mechanical_passes': sum(r['recomputed_grade']['passed'] for r in results),
            'failures': dict(failures), 'median_seconds': statistics.median(times), 'p95_seconds': times[math.ceil(.95 * len(times)) - 1],
            'token_usage': usage, 'primary_estimated_usd': cost, 'primary_estimated_usd_per_analysis': cost / len(results) if cost else None,
            'resources': model_resources, 'primary_runs': sorted(sources[model]),
            'case_passes': {case[0]: sum(group[case[0], rep]['recomputed_grade']['passed'] for rep in range(1, 4)) for case in CASES}})
    ledger = json.loads((ROOT / 'var/ai/budget.json').read_text())
    summary['spend_all_stages'] = {'cap_usd': ledger['cap_usd'], 'requests': len(ledger['requests']),
        'estimated_usd_full_rate': sum(row.get('actual_usd', 0) for row in ledger['requests']),
        'pending_reservations_usd': sum(row['reserved_usd'] for row in ledger['requests'] if row['state'] != 'completed')}
    summary['experiment_events'] = [json.loads(line) for line in (ROOT / 'var/ai/experiment-events.jsonl').read_text().splitlines()]
    destination = ROOT / 'docs/validation/ai-comparison-2026-10-28.json'
    destination.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'report': str(destination.relative_to(ROOT)), 'models': [
        {k: m[k] for k in ('model', 'analyses', 'mechanical_passes', 'failures', 'median_seconds', 'p95_seconds', 'primary_estimated_usd')}
        for m in summary['models']], 'all_spend': summary['spend_all_stages']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
