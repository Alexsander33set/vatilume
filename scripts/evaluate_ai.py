#!/usr/bin/env python3
"""Reproducible local/API evaluation, isolated from the production services."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import secrets
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from device_observability.ai_evaluation import CASES, SYSTEM, TOOLS, PROMPT_VERSION, TOOLS_VERSION, EvaluationTools, grade

DIRECTORY = ROOT / 'var/ai'
PRICES = {'gpt-5.4-nano-2026-03-17': (.20, 1.25), 'gpt-5.4-mini-2026-03-17': (.75, 4.50),
          'gpt-6-astra': (12.50, 50.0), 'gpt-6-luna': (.125, .50)}  # GPT-6 input includes conservative cache-write uplift.
CAP_USD = 2.0  # User revised the test allowance to USD 2; preserve their other USD 5.
OUTPUT_TOKENS = 384


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


class Budget:
    """Reserve before sending; uncertain failures retain their full reservation.

    Conservative byte-based input bound includes schema/message overhead. This
    is an application guard, not a provider billing limit or FX guarantee.
    """
    def _update(self, operation):
        with (DIRECTORY / 'budget.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = DIRECTORY / 'budget.json'
            ledger = json.loads(path.read_text()) if path.exists() else {'cap_usd': CAP_USD, 'requests': []}
            if ledger['cap_usd'] != CAP_USD: raise ValueError('Unexpected budget cap')
            result = operation(ledger)
            write_json(path, ledger)
            return result

    def reserve(self, model, payload):
        if (DIRECTORY / 'budget-managed.json').exists():
            raise ValueError('Budget migrated to installed interface; standalone paid evaluations are disabled.')
        input_price, output_price = PRICES[model]
        upper_tokens = len(payload) + 4096
        reservation = (upper_tokens * input_price + OUTPUT_TOKENS * output_price) / 1e6
        identity = str(uuid.uuid4())

        def update(ledger):
            if (DIRECTORY / 'budget-managed.json').exists():
                raise ValueError('Budget migrated to installed interface; standalone paid evaluations are disabled.')
            used = sum(r.get('actual_usd', r['reserved_usd']) for r in ledger['requests'])
            if used + reservation > CAP_USD: raise ValueError('Authorized USD budget would be exceeded')
            if model == 'gpt-6-astra' and sum(r.get('actual_usd', r['reserved_usd']) for r in ledger['requests'] if r['model'] == model) + reservation > .35:
                raise ValueError('GPT-6 Astra pilot allowance USD 0.35 would be exceeded')
            ledger['requests'].append({'id': identity, 'model': model, 'reserved_usd': reservation,
                                       'state': 'reserved', 'utc_ms': time.time_ns() // 1_000_000})
        self._update(update)
        return identity

    def finish(self, identity, usage):
        def update(ledger):
            row = next(r for r in ledger['requests'] if r['id'] == identity)
            input_price, output_price = PRICES[row['model']]
            row.update(state='completed', usage=usage,
                       actual_usd=(usage['input_tokens'] * input_price + usage['output_tokens'] * output_price) / 1e6)
        self._update(update)


class Provider:
    def __init__(self, model, remote=False, force_final=False):
        self.model, self.remote = model, remote
        self.force_final = force_final
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.key = None
        if remote:
            path = DIRECTORY / 'openai-api-key'
            info = path.stat()
            if info.st_uid != os.getuid() or info.st_mode & 0o077: raise ValueError('API key file must be private and owned by current user')
            self.key = path.read_text().strip()
            if not self.key: raise ValueError('API key missing')

    def complete(self, messages, timeout, final_turn=False):
        headers = {'Content-Type': 'application/json'}
        if self.remote:
            inputs = []
            for message in messages:
                if message['role'] == 'tool':
                    inputs.append({'type': 'function_call_output', 'call_id': message['tool_call_id'], 'output': message['content']})
                elif message['role'] == 'assistant' and message.get('tool_calls'):
                    for call in message['tool_calls']:
                        inputs.append({'type': 'function_call', 'call_id': call['id'], **call['function']})
                else: inputs.append({'role': message['role'], 'content': message.get('content') or ''})
            body = {'model': self.model, 'input': inputs,
                    'tools': [{'type': 'function', **t['function'], 'strict': False} for t in TOOLS],
                    'parallel_tool_calls': False, 'max_output_tokens': OUTPUT_TOKENS,
                    'reasoning': {'effort': 'low' if self.model == 'gpt-6-astra' else 'none'}, 'store': False}
            endpoint = 'https://api.openai.com/v1/responses'
            headers['Authorization'] = 'Bearer ' + self.key
            if self.force_final and final_turn: body['tool_choice'] = 'none'
        else:
            body = {'model': self.model, 'messages': messages, 'tools': TOOLS, 'tool_choice': 'auto',
                    'parallel_tool_calls': False, 'max_tokens': OUTPUT_TOKENS, 'temperature': 0,
                    'chat_template_kwargs': {'enable_thinking': False}, 'cache_prompt': True}
            endpoint = 'http://127.0.0.1:8768/v1/chat/completions'
            headers['Authorization'] = 'Bearer ' + (DIRECTORY / 'runtime-key').read_text().strip()
            if self.force_final and final_turn: body['tool_choice'] = 'none'
        payload = json.dumps(body, ensure_ascii=False).encode()
        reservation = Budget().reserve(self.model, payload) if self.remote else None
        started = time.monotonic()
        request = urllib.request.Request(endpoint, data=payload, headers=headers)
        # No automatic paid retries: uncertain requests remain reserved.
        try:
            with self.opener.open(request, timeout=timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            suffix = '; reservation retained' if self.remote else ''
            raise RuntimeError(f'Provider HTTP {exc.code}; request not retried' + suffix) from None
        elapsed = time.monotonic() - started
        if self.remote:
            usage = result['usage']
            usage = {'input_tokens': usage['input_tokens'], 'output_tokens': usage['output_tokens']}
            Budget().finish(reservation, usage)
            message = {'role': 'assistant', 'content': '', 'tool_calls': []}
            for output in result.get('output', []):
                if output['type'] == 'function_call':
                    message['tool_calls'].append({'id': output['call_id'], 'type': 'function',
                                                 'function': {'name': output['name'], 'arguments': output['arguments']}})
                elif output['type'] == 'message':
                    message['content'] += ''.join(p.get('text', '') for p in output['content'] if p['type'] == 'output_text')
            finish = result.get('status')
        else:
            choice = result['choices'][0]
            message = {k: v for k, v in choice['message'].items() if k in ('role', 'content', 'tool_calls')}
            source = result.get('usage', {})
            usage = {'input_tokens': source.get('prompt_tokens', 0), 'output_tokens': source.get('completion_tokens', 0)}
            finish = choice['finish_reason']
        return message, {'elapsed_seconds': elapsed, 'usage': usage, 'finish_reason': finish}


def run_case(provider, tools, case, repetition):
    identity, question, _ = case
    messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': question}]
    started = time.monotonic()
    trace, calls, text = [], [], ''
    error = None
    try:
        for turn in range(8):
            remaining = 180 - (time.monotonic() - started)
            if remaining <= 0: raise TimeoutError('Analysis exceeded 180 seconds')
            message, metadata = provider.complete(messages, min(90, remaining), final_turn=turn == 7)
            calls.append(metadata)
            messages.append(message)
            pending = message.get('tool_calls') or []
            if not pending:
                text = message.get('content') or ''
                break
            for call in pending:
                if len(trace) >= 8: raise ValueError('Tool budget exceeded')
                function = call['function']
                step = {'name': function['name']}
                try:
                    arguments = json.loads(function['arguments'])
                    step['arguments'] = arguments
                    output = tools.call(identity, function['name'], arguments)
                    step['result'] = output
                except (ValueError, KeyError, TypeError) as exc:
                    output = {'error': str(exc)}
                    step['error'] = str(exc)
                trace.append(step)
                messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(output, ensure_ascii=False)})
        else: error = 'model_round_limit'
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
    result = {'case': identity, 'repetition': repetition, 'model': provider.model, 'prompt_version': PROMPT_VERSION,
              'tools_version': TOOLS_VERSION,
              'dataset_sha256': tools.dataset_hash, 'elapsed_seconds': time.monotonic() - started,
              'calls': calls, 'tools': trace, 'answer': text, 'error': error,
              'grade': grade(identity, text, trace)}
    if error: result['grade']['passed'] = False
    return result


class LocalServer:
    def __init__(self, model, output, backend='cpu'):
        self.model, self.output, self.backend = model, output, backend
        self.stop_monitor = threading.Event()
        self.samples = []

    def __enter__(self):
        self.lock = (DIRECTORY / 'runtime.lock').open('a')
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with socket.socket() as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(('127.0.0.1', 8768))
        except OSError:
            self.lock.close()
            raise RuntimeError('Evaluation port is occupied; no process was interrupted') from None
        self.key_path = DIRECTORY / 'runtime-key'
        fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w') as stream: stream.write(secrets.token_urlsafe(32))
        self.log = (self.output / 'server.log').open('w')
        runtime = DIRECTORY / ('runtime-vulkan' if self.backend == 'vulkan' else 'runtime') / 'llama-b11968/llama-server'
        model_path = DIRECTORY / f'assets/{self.model}.gguf'
        self.started_utc_ms = time.time_ns() // 1_000_000
        started = time.monotonic()
        acceleration = ['-ngl', 'auto', '--device', 'Vulkan0', '--fit-target', '1024'] if self.backend == 'vulkan' else ['-ngl', '0']
        self.initial_vram = self.read_vram()
        self.process = subprocess.Popen(['nice', '-n', '10', str(runtime), '-m', str(model_path),
            '--host', '127.0.0.1', '--port', '8768', '-t', '4', '-tb', '4', '-c', '4096' if self.backend == 'vulkan' else '8192', '-np', '1',
            *acceleration, '--cache-ram', '0', '--poll', '0', '--threads-http', '2',
            '--jinja', '--chat-template-kwargs', '{"enable_thinking":false}',
            '--api-key-file', str(self.key_path), '--no-webui'], stdout=self.log, stderr=self.log)
        try:
            for _ in range(300):
                if self.process.poll() is not None: raise RuntimeError('Local server exited; inspect server.log')
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8768/health', timeout=1) as response:
                        if response.status == 200: break
                except (OSError, urllib.error.URLError): pass
                time.sleep(.2)
            else: raise TimeoutError('Model did not load within 60 seconds')
            self.load_seconds = time.monotonic() - started
            self.thread = threading.Thread(target=self.monitor, daemon=True)
            self.thread.start()
            return self
        except BaseException:
            self.process.terminate()
            self.process.wait(timeout=20)
            self.log.close()
            self.key_path.unlink(missing_ok=True)
            self.lock.close()
            raise

    def monitor(self):
        while not self.stop_monitor.is_set():
            try:
                status = (Path('/proc') / str(self.process.pid) / 'status').read_text()
                values = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
                stat = (Path('/proc') / str(self.process.pid) / 'stat').read_text().rsplit(')', 1)[1].split()
                self.samples.append({'elapsed': time.monotonic(), 'rss_kib': int(values.get('VmRSS', '0 kB').split()[0]),
                                     'device_vram_bytes': self.read_vram(),
                                     'cpu_seconds': (int(stat[11]) + int(stat[12])) / os.sysconf('SC_CLK_TCK')})
            except (OSError, ValueError): pass
            self.stop_monitor.wait(.5)

    @staticmethod
    def read_vram():
        try: return int(Path('/sys/class/drm/card1/device/mem_info_vram_used').read_text())
        except OSError: return None

    def __exit__(self, *_):
        self.stop_monitor.set()
        self.thread.join(timeout=2)
        self.process.terminate()
        try: self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.log.close()
        self.key_path.unlink(missing_ok=True)
        self.lock.close()
        log = (self.output / 'server.log').read_text()
        offload_lines = [line for line in log.splitlines() if 'offload' in line.lower() and 'layer' in line.lower()]
        write_json(self.output / 'resources.json', {'model': self.model, 'backend': self.backend, 'threads': 4,
            'nice': 10, 'gpu_layers_requested': 'auto' if self.backend == 'vulkan' else 0,
            'gpu_offload_log': offload_lines, 'started_utc_ms': self.started_utc_ms,
            'ended_utc_ms': time.time_ns() // 1_000_000, 'load_seconds': self.load_seconds,
            'load_note': 'new process; filesystem page cache not cleared',
            'peak_rss_mib': max((r['rss_kib'] for r in self.samples), default=0) / 1024,
            'cpu_seconds': self.samples[-1]['cpu_seconds'] if self.samples else None,
            'device_vram_before_bytes': self.initial_vram,
            'device_vram_peak_bytes': max((r['device_vram_bytes'] for r in self.samples if r['device_vram_bytes'] is not None), default=None),
            'device_vram_after_bytes': self.read_vram(),
            'model_process_stopped': self.process.poll() is not None,
            'energy_incremental_kwh': None, 'energy_note': 'No controlled idle-vs-inference experiment; see experiment-events.jsonl for game context.'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True, choices=['Qwen3-4B-Q4_K_M', 'Qwen3-8B-Q4_K_M', 'Qwen3.5-4B-Q4_K_M', 'gemma-3-4b-it-Q4_K_M', *PRICES])
    parser.add_argument('--repetitions', type=int, choices=range(1, 4), default=3)
    parser.add_argument('--backend', choices=['cpu', 'vulkan'], default='cpu')
    parser.add_argument('--force-final', action='store_true', help='Disable tool calls on last round; recorded as an adapter change.')
    parser.add_argument('--cases', default='all', help='comma-separated case IDs, or all')
    args = parser.parse_args()
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    tools = EvaluationTools(DIRECTORY / 'dataset-real.json')
    selected = CASES if args.cases == 'all' else [c for c in CASES if c[0] in args.cases.split(',')]
    if not selected or (args.cases != 'all' and set(args.cases.split(',')) - {c[0] for c in CASES}):
        raise SystemExit('Invalid case selection')
    remote = args.model in PRICES
    provider = Provider(args.model, remote, args.force_final)
    output = DIRECTORY / 'runs' / (time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + args.model + '-' + ('api' if remote else args.backend))
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'model': args.model, 'provider': 'openai' if remote else 'llama.cpp-b11968',
                'backend': 'api' if remote else args.backend,
                'force_final_on_last_round': args.force_final,
                'dataset_sha256': tools.dataset_hash, 'prompt_version': PROMPT_VERSION, 'repetitions': args.repetitions,
                'tools_version': TOOLS_VERSION,
                'evaluation_source_sha256': hashlib.sha256((ROOT / 'device_observability/ai_evaluation.py').read_bytes()).hexdigest(),
                'cases': [c[0] for c in selected], 'output_token_limit': OUTPUT_TOKENS,
                'critical_human_review_pending': True, 'price_usd_per_million': PRICES.get(args.model),
                'prefix_cache': 'enabled; conversations remain independent' if not remote else 'provider default',
                'authorized_total_cap_usd': CAP_USD if remote else None}
    write_json(output / 'manifest.json', manifest)
    results = []

    def interrupted(*_): raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)

    def evaluate():
        for repetition in range(1, args.repetitions + 1):
            for case in selected:
                result = run_case(provider, tools, case, repetition)
                results.append(result)
                write_json(output / f'{case[0]}-{repetition}.json', result)
                print(json.dumps({'model': args.model, 'case': case[0], 'repetition': repetition,
                    'seconds': round(result['elapsed_seconds'], 2), 'mechanical_pass': result['grade']['passed'],
                    'failures': result['grade']['failures'], 'error': result['error']}), flush=True)
                if result['error']:
                    raise RuntimeError('Run stopped after provider/runtime failure; completed results preserved')

    try:
        if remote: evaluate()
        else:
            with LocalServer(args.model, output, args.backend): evaluate()
    finally:
        times = sorted(r['elapsed_seconds'] for r in results)
        write_json(output / 'summary.json', {'model': args.model, 'completed': len(results),
            'planned': len(selected) * args.repetitions, 'mechanical_passes': sum(r['grade']['passed'] for r in results),
            'median_seconds': statistics.median(times) if times else None,
            'p95_seconds': times[max(0, math_ceil(.95 * len(times)) - 1)] if times else None,
            'human_review_pending': True, 'results_directory': str(output.relative_to(ROOT))})


def math_ceil(value):
    return int(value) + (value > int(value))


if __name__ == '__main__':
    main()
