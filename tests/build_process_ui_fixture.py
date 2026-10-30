"""Synthetic UI-only process evidence; never stored in the real telemetry database."""
import copy
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from test_ai_service import frozen_fixture
from test_processes import process_history
from device_observability.ai_evidence import EvidenceSession,snapshot
from device_observability.process_analysis import coincidences,PROCESS_METRICS
from device_observability.applications import capture_ancestors,group_entries

base=frozen_fixture()
start=base['window']['start_ms']+30*60_000
history=process_history('zen',start=start,end=start+60_000)
context=history['snapshots'][0]['context']
root=context['entries'][0];root['ppid']=0
child=copy.deepcopy(root);child.update(pid=100,ppid=root['pid'],start_ticks=6,name='Isolated Web Co')
child['ancestors']=capture_ancestors(child,{root['pid']:root})
war=copy.deepcopy(root);war.update(pid=101,ppid=0,name='aces')
unknown=copy.deepcopy(root);unknown.update(pid=102,ppid=0,name='QtWebEngineProc',cpu_percent=None,previous_cpu_ticks=None,elapsed_ns=None,interval_start_ms=None)
context['entries']=[root,child,war,unknown]
context['applications']=group_entries(context['entries'])
history.update(scans=2,failed_scans=0,partial_scans=0,warmup_scans=1,retained_snapshots=1,bucket_seconds=60,sampling_method='Synthetic UI fixture')
base['processes']=history
frozen=snapshot(base,base['tariffs'],base['experiments'],base['projection'])
evidence=EvidenceSession(frozen,'Quais aplicativos coincidem com os picos da GPU?')
report=evidence.validate({'answer_id':'process_peak_gpu_w_0','fact_ids':['scope'],'recommendation_ids':[],'answer_status':'evidence_found'})
report.update(model='simulated-ui-only',validator_version='applications-1',elapsed_seconds=.1)
record={'id':'synthetic-process-ui','created_ms':start,'state':'complete','question':'Quais aplicativos coincidem com os picos da GPU?','report':report,'error':None,'estimated_cost_usd':0}
result={'window':base['window'],'series':base['series'],'processes':history,'record':record,'coincidences':{metric:coincidences(base['series'],history,base['window'],metric) for metric in PROCESS_METRICS}}
(ROOT/'var/validation/process-ui-fixture.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
