#!/usr/bin/env python3
"""Run isolated browser tests and stop both temporary processes on completion.

Only var/validation/ui-data and port 8766 are used. AI is simulated. No paid calls.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    directory = ROOT / 'var/validation/ui-data'
    if not (directory / 'telemetry.sqlite3').exists():
        raise SystemExit('Prepare the disposable telemetry copy in var/validation/ui-data first.')
    for name in ('ai.sqlite3','ai.sqlite3-wal','ai.sqlite3-shm','ai-budget.json','ai-limits.json','ai-api-key'):
        (directory / name).unlink(missing_ok=True)
    (directory / 'ai-api-key').write_text('validation-only-not-a-real-api-key')
    (directory / 'ai-api-key').chmod(0o600)
    # A realistic historic balance, isolated from the actual spending ledger.
    seed = {'cap_usd':5.0,'requests':[{'id':'synthetic-prior-spend','state':'completed','model':'validation',
        'utc_ms':time.time_ns()//1_000_000,'reserved_usd':.54,'actual_usd':.54}]}
    (directory / 'ai-budget.json').write_text(json.dumps(seed))
    subprocess.run([sys.executable,str(ROOT/'tests/build_process_ui_fixture.py')],cwd=ROOT,check=True)
    logs = ROOT / 'var/validation/interface-runtime'
    logs.mkdir(parents=True, exist_ok=True)
    children, streams = [], []
    try:
        for name, command in [('collector',['-m','device_observability','--config',str(ROOT/'var/validation/ui.toml'),'run']),
                              ('backend',[str(ROOT/'tests/serve_interface_validation.py')])]:
            stream = (logs / (name+'.log')).open('w')
            streams.append(stream)
            children.append(subprocess.Popen([sys.executable,*command],cwd=ROOT,stdout=stream,stderr=stream))
        for _ in range(100):
            if any(child.poll() is not None for child in children): raise RuntimeError('Validation process exited; inspect logs.')
            try:
                with urllib.request.urlopen('http://127.0.0.1:8766/',timeout=1) as response:
                    if response.status==200:break
            except OSError: pass
            time.sleep(.1)
        else: raise TimeoutError('Disposable backend did not start')
        result = subprocess.run(['npx','playwright','test',*sys.argv[1:]],cwd=ROOT/'frontend',
            env={**os.environ,'PLAYWRIGHT_BROWSERS_PATH':'/tmp/device-observability-browsers'},timeout=240)
        return result.returncode
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try: child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill();child.wait()
        for stream in streams:stream.close()


if __name__=='__main__':sys.exit(main())
