"""Disposable browser-test backend. AI transport is simulated, never paid."""
import json
import sys
import subprocess
import signal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import uvicorn
from device_observability.web import create_app


def simulated_transport(body, timeout):
    request = json.loads(body)
    if not any(item.get('type') == 'function_call_output' for item in request['input']):
        output = [{'type':'function_call','call_id':'validation-quality','name':'inspect_quality','arguments':'{}'}]
    else:
        choices=request['text']['format']['schema']['properties']['answer_id']['enum']
        primary = choices[0] if choices == ['monthly_projection'] or all(value.startswith('process_') for value in choices) else 'observed_cost'
        answer = {'answer_id':primary, 'fact_ids':['energy_cpu','cost_cpu','scope'],'recommendation_ids':[],'answer_status':'evidence_found'}
        output = [{'type':'message','content':[{'type':'output_text','text':json.dumps(answer)}]}]
    return {'status':'completed','output':output,'usage':{'input_tokens':100,'output_tokens':50}}


if __name__ == '__main__':
    process=subprocess.Popen([sys.executable,'-m','device_observability','--config',str(ROOT/'var/validation/ui.toml'),'run'],cwd=ROOT)
    try:
        app = create_app(ROOT / 'var/validation/ui.toml', port=8766, ai_transport=simulated_transport)
        uvicorn.run(app, host='127.0.0.1', port=8766, access_log=False)
    finally:
        process.send_signal(signal.SIGTERM)
        process.wait(timeout=15)
