import json
import os
import signal
import tempfile
import time
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
    from device_observability.web import create_app
except ImportError:
    TestClient = None

from device_observability.agent import process_start_ticks
from device_observability.config import load_config
from device_observability.controls import Controls
from test_analysis import synthetic, BASE


@unittest.skipUnless(TestClient, "optional web dependencies not installed")
class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        synthetic(self.root)
        self.path = self.root / "collector.toml"
        self.path.write_text('data_dir="."\n')
        config = load_config(self.path)
        self.health = {"pid": os.getpid(), "pid_start_ticks": process_start_ticks(os.getpid()), "boot_id": Path('/proc/sys/kernel/random/boot_id').read_text().strip(), "running": True, "config_hash": config.fingerprint}
        (self.root / 'health.json').write_text(json.dumps(self.health))
        self.client = TestClient(create_app(self.path, token="test-local-secret"), base_url="http://127.0.0.1:8765")
        self.origin = {"Origin": "http://127.0.0.1:8765"}

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def login(self):
        response = self.client.post('/api/session', headers={**self.origin, 'Authorization': 'Bearer test-local-secret'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('HttpOnly', response.headers['set-cookie'])

    def test_only_fixed_public_legal_documents_are_served_without_session(self):
        for document, text in [('license', 'GNU GENERAL PUBLIC LICENSE'), ('privacy', 'APFS'),
                               ('security', 'contato@apfs.com.br'), ('third-party', 'Dependências')]:
            response = self.client.get('/legal/' + document)
            self.assertEqual(response.status_code, 200)
            self.assertIn(text, response.text)
            self.assertEqual(response.headers['cache-control'], 'no-store')
        for document in ('collector.toml', 'interface-token', '%2e%2e%2fPRIVACY.md'):
            self.assertEqual(self.client.get('/legal/' + document).status_code, 404)

    def test_private_api_and_foreign_origins_are_rejected(self):
        self.assertEqual(self.client.get('/api/settings').status_code, 401)
        self.assertEqual(self.client.post('/api/session', headers={'Origin':'http://evil.invalid','Authorization':'Bearer test-local-secret'}).status_code, 403)
        self.login()
        response = self.client.post('/api/settings/tariffs', headers={'Origin':'http://evil.invalid'}, json={'price':'1','effective_date':'2026-10-28'})
        self.assertEqual(response.status_code, 403)

    def test_request_body_limit_precedes_json_validation(self):
        self.login()
        response = self.client.put('/api/ai/key', headers={**self.origin,'Content-Type':'application/json'}, content=b'X' * 17000)
        self.assertEqual(response.status_code, 413)
        self.assertNotIn('XXX', response.text)

    def test_chunked_request_cannot_bypass_body_limit(self):
        self.login()
        response = self.client.put('/api/ai/key', headers={**self.origin,'Content-Type':'application/json'},
                                   content=iter([b'X' * 4096] * 5))
        self.assertEqual(response.status_code, 413)

    def test_validation_errors_never_echo_submitted_api_key(self):
        self.login()
        secret = 'PRIVATE-FIXTURE-' * 100
        response = self.client.put('/api/ai/key', headers=self.origin, json={'key': secret})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('PRIVATE-FIXTURE', response.text)
        self.assertNotIn('input', response.text)

    def test_api_key_removal_pauses_calls_without_resetting_budget(self):
        self.login()
        limits = {'enabled':True,'per_analysis_usd':.05,'daily_usd':1.,'monthly_usd':2.,'authorized_total_usd':4.}
        self.assertEqual(self.client.put('/api/ai/settings',headers=self.origin,json=limits).status_code,200)
        self.assertEqual(self.client.put('/api/ai/key',headers=self.origin,json={'key':'synthetic-not-a-provider-key'}).status_code,200)
        self.assertEqual(self.client.delete('/api/ai/key',headers={'Origin':'http://evil.invalid'}).status_code,403)
        self.assertTrue((self.root/'ai-api-key').exists())
        self.assertEqual(self.client.delete('/api/ai/key',headers=self.origin).json(),{'key_configured':False})
        self.assertFalse((self.root/'ai-api-key').exists())
        status = self.client.get('/api/ai/settings').json()
        self.assertFalse(status['limits']['enabled'])
        self.assertEqual(status['authorized_total_usd'],4.)

    def test_budget_booleans_are_not_accepted_as_money(self):
        self.login()
        body={'enabled':True,'per_analysis_usd':.05,'daily_usd':1.,'monthly_usd':2.,'authorized_total_usd':True}
        self.assertEqual(self.client.put('/api/ai/settings',headers=self.origin,json=body).status_code,422)

    def test_tariff_persists_and_cost_is_calculated_from_real_raw_schema(self):
        self.login()
        response = self.client.post('/api/settings/tariffs', headers=self.origin, json={'price':'1,25','effective_date':'2026-10-28','description':'Synthetic test tariff'})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.get('/api/overview', params={'start_ms':BASE,'end_ms':BASE+20_000,'points':24})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertAlmostEqual(response.json()['components'][0]['cost_brl'], 2000/3_600_000*1.25)
        self.assertEqual(self.client.get('/api/settings').json()['tariffs'][0]['price'],'1.25')
        self.assertEqual(self.client.get('/api/export.csv', params={'start_ms':BASE,'end_ms':BASE+20_000}).status_code, 200)

    def test_config_only_allows_safe_keys_and_preserves_raw_data_directory(self):
        self.login()
        settings = self.client.get('/api/settings').json()['collector']
        body = {'revision':settings['revision'],'interval_seconds':12,'thermal_interval_seconds':36,'enabled_collectors':['system','powercap','gpu']}
        with patch('device_observability.controls.os.kill') as kill:
            response = self.client.put('/api/settings/collector',headers=self.origin,json=body)
            self.assertEqual(response.status_code,200,response.text)
            kill.assert_called_once_with(os.getpid(),signal.SIGHUP)
        self.assertEqual(load_config(self.path).interval_seconds,12)
        self.assertFalse(response.json()['applied'])
        invalid = {**body,'data_dir':'/tmp/other-history'}
        self.assertEqual(self.client.put('/api/settings/collector',headers=self.origin,json=invalid).status_code,422)

    def test_failed_signal_rolls_back_previous_config(self):
        controls = Controls(self.path)
        with patch('device_observability.controls.os.kill',side_effect=PermissionError):
            with self.assertRaises(ValueError):
                controls.save({'interval_seconds':20},load_config(self.path).fingerprint)
        self.assertEqual(load_config(self.path).interval_seconds,10)
        self.assertFalse((self.root/'collector-overrides.json').exists())

    def test_stale_configuration_revision_and_bad_tariff_are_rejected(self):
        self.login()
        bad = self.client.post('/api/settings/tariffs',headers=self.origin,json={'price':'nan','effective_date':'2026-10-28'})
        self.assertEqual(bad.status_code,422)
        self.assertEqual(self.client.get('/api/settings').json()['tariffs'],[])
        with self.assertRaises(ValueError): Controls(self.path).save({'interval_seconds':20},'0'*64)

    def test_ai_api_preserves_auth_private_credentials_limits_and_saved_evidence(self):
        from test_ai_service import FakeTransport
        transport = FakeTransport(final={'answer_id':'energy_cpu', 'fact_ids':['energy_cpu','scope'], 'recommendation_ids':[], 'answer_status':'evidence_found'})
        self.client.close()
        self.client = TestClient(create_app(self.path, token='test-local-secret', ai_transport=transport), base_url='http://127.0.0.1:8765')
        self.assertEqual(self.client.get('/api/ai/settings').status_code, 401)
        self.login()
        credential = 'test-only-api-credential-no-network'
        saved = self.client.put('/api/ai/key', headers=self.origin, json={'key':credential})
        self.assertEqual(saved.status_code, 200)
        self.assertNotIn(credential, self.client.get('/api/ai/settings').text)
        self.assertEqual(self.client.get('/api/ai/settings').json()['authorized_total_usd'],0)
        approved = self.client.put('/api/ai/settings',headers=self.origin,json={
            'enabled':True,'per_analysis_usd':.05,'daily_usd':1,'monthly_usd':2,'authorized_total_usd':5})
        self.assertEqual(approved.status_code,200,approved.text)
        quote = self.client.post('/api/ai/quotes',headers=self.origin,json={'start_ms':BASE,'end_ms':BASE+20000,'question':'Qual é a energia observada?'}).json()
        started = self.client.post('/api/ai/analyses/'+quote['id'],headers=self.origin)
        self.assertEqual(started.status_code, 200, started.text)
        for _ in range(100):
            result = self.client.get('/api/ai/analyses/'+quote['id']).json()
            if result['state']!='running': break
            time.sleep(.01)
        self.assertEqual(result['state'], 'complete', result)
        evidence_id = result['report']['claims'][0]['evidence_ids'][0]
        proof = self.client.get('/api/ai/analyses/'+quote['id']+'/evidence/'+evidence_id)
        self.assertEqual(proof.status_code, 200)
        self.assertEqual(proof.json()['snapshot_sha256'],quote['snapshot_sha256'])
        raw = self.client.get('/api/ai/analyses/'+quote['id']+'/evidence/'+evidence_id+'/raw.csv')
        self.assertEqual(raw.status_code,200,raw.text)
        self.assertIn('raw_value,raw_unit,scale,counter_max_range',raw.text)
        self.assertIn('cpu',raw.text)
        self.assertEqual(self.client.post('/api/ai/analyses/'+quote['id'],headers=self.origin).status_code,200)
        self.assertEqual(len(transport.calls),1)
        for hours in (0, -1, 25):
            invalid = self.client.post('/api/ai/quotes', headers=self.origin,
                json={'start_ms':BASE,'end_ms':BASE+20000,'question':'Qual seria o custo mensal?', 'hours_per_day':hours})
            self.assertEqual(invalid.status_code, 422)
        preview = self.client.post('/api/ai/quotes', headers=self.origin,
            json={'start_ms':BASE,'end_ms':BASE+20000,'question':'Qual seria o custo mensal com 8h/dia?', 'hours_per_day':24})
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()['projection']['hours_per_day'], 8)
        self.assertEqual(preview.json()['calculation_preview']['values']['status'], 'needs_tariff')
        self.assertEqual(len(transport.calls), 1)
        limits = {'enabled':True,'per_analysis_usd':.05,'daily_usd':1,'monthly_usd':6}
        self.assertEqual(self.client.put('/api/ai/settings',headers=self.origin,json=limits).status_code,422)

    def test_process_evidence_is_authenticated_overlap_checked_and_exported_from_saved_analysis(self):
        from test_processes import process_history
        from test_ai_service import FakeTransport
        final={'answer_id':'process_peak_cpu_w_0','fact_ids':['scope'], 'recommendation_ids':[], 'answer_status':'evidence_found'}
        transport=FakeTransport(final)
        with sqlite3.connect(self.root/'telemetry.sqlite3') as con:
            row=con.execute('SELECT collectors_json FROM samples WHERE id=3').fetchone()
            payload=json.loads(row[0])
            context=process_history('=test-process',start=BASE+10000,end=BASE+20000)['snapshots'][0]['context']
            root={**context['entries'][0],'pid':100,'ppid':0,'name':'zen'}
            helper={**root,'pid':101,'ppid':100,'start_ticks':6,'name':'Isolated Web Co',
                    'ancestors':[{'pid':100,'ppid':0,'start_ticks':5,'name':'zen'}]}
            context['entries'].extend([root,helper])
            payload['processes']={'quality':'ok','readings':[],'context':context,'observed_utc_ns':(BASE+20000)*1_000_000}
            con.execute('UPDATE samples SET collectors_json=? WHERE id=3',(json.dumps(payload),))
        self.client.close()
        self.client=TestClient(create_app(self.path,token='test-local-secret',ai_transport=transport),base_url='http://127.0.0.1:8765')
        self.assertEqual(self.client.get('/api/processes/coincidences').status_code,401)
        self.login()
        self.client.put('/api/ai/key',headers=self.origin,json={'key':'test-only-private-key-not-network'})
        self.client.put('/api/ai/settings',headers=self.origin,json={
            'enabled':True,'per_analysis_usd':.05,'daily_usd':1,'monthly_usd':2,'authorized_total_usd':5})
        params={'start_ms':BASE,'end_ms':BASE+20000,'metric':'cpu_w'}
        result=self.client.get('/api/processes/coincidences',params=params)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['peaks'][0]['matches'][0]['name'],'Zen Browser')
        self.assertEqual(result.json()['peaks'][0]['matches'][0]['cpu_percent'],20)
        self.assertIn('=test-process',[m['name'] for m in result.json()['peaks'][0]['matches']])
        self.assertFalse(result.json()['causality_proven'])
        quote=self.client.post('/api/ai/quotes',headers=self.origin,json={**{k:v for k,v in params.items() if k!='metric'},'question':'Quais processos coincidiram com os picos?'}).json()
        self.client.post('/api/ai/analyses/'+quote['id'],headers=self.origin)
        for _ in range(100):
            record=self.client.get('/api/ai/analyses/'+quote['id']).json()
            if record['state']!='running':break
            time.sleep(.01)
        self.assertEqual(record['state'],'complete',record)
        report=record['report']
        proof=next(e for e in report['evidence'].values() if e['tool']=='inspect_process_activity')
        response=self.client.get('/api/ai/analyses/'+quote['id']+'/evidence/'+proof['id']+'/processes.csv')
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('previous_cpu_ticks,clock_ticks_per_second,machine_cpu_count',response.text)
        self.assertIn("'=test-process",response.text)
        self.assertIn('application_members_only,ancestors_json',response.text)
        self.assertIn('Zen Browser',response.text)
        self.assertIn('parent_rule',response.text)
        self.assertIn('Isolated Web Co',response.text)
        self.assertNotIn('Zen Browser',json.dumps(transport.calls))
        self.assertNotIn('Isolated Web Co',json.dumps(transport.calls))
        self.assertNotIn('=test-process',json.dumps(transport.calls))
        self.assertNotIn('test-only-private-key',response.text)

    def test_diagnostics_and_model_configuration_are_private_and_redacted(self):
        self.assertEqual(self.client.get('/api/diagnostics').status_code,401)
        self.login()
        result=self.client.get('/api/diagnostics')
        self.assertEqual(result.status_code,200)
        self.assertEqual(len(result.json()['checks']),4)
        self.assertNotIn('pid',result.text)
        self.assertEqual(result.json()['storage']['limit_bytes'],2*1024**3)
        self.assertEqual(self.client.put('/api/ai/model',headers=self.origin,json={'model':'arbitrary'}).status_code,422)
        result=self.client.put('/api/ai/model',headers=self.origin,json={'model':'gpt-6-luna'})
        self.assertEqual(result.json()['model'],'gpt-6-luna')
        self.assertEqual(self.client.post('/api/ai/key/check',headers=self.origin).status_code,422)

    def test_provider_key_check_never_returns_key_or_claims_billing_verified(self):
        self.login()
        self.client.put('/api/ai/key',headers=self.origin,json={'key':'synthetic-not-a-provider-key'})
        with patch('device_observability.ai_service.urllib.request.OpenerDirector.open') as remote:
            result=self.client.post('/api/ai/key/check',headers=self.origin)
        self.assertEqual(result.status_code,200)
        self.assertFalse(result.json()['billing_verified'])
        self.assertNotIn('synthetic-not-a-provider-key',result.text)
        import urllib.error
        with patch('device_observability.ai_service.urllib.request.OpenerDirector.open',side_effect=urllib.error.HTTPError('url',401,'private provider content',{},None)):
            result=self.client.post('/api/ai/key/check',headers=self.origin)
        self.assertEqual(result.status_code,422)
        self.assertNotIn('private provider content',result.text)
        self.assertIn('chave',result.text.lower())

    def test_quote_uses_observed_daily_time_and_explicit_question_overrides_it(self):
        self.login()
        self.client.put('/api/ai/key',headers=self.origin,json={'key':'synthetic-not-a-provider-key'})
        self.client.put('/api/ai/settings',headers=self.origin,json={'enabled':True,'per_analysis_usd':.05,'daily_usd':1.,'monthly_usd':2.,'authorized_total_usd':5.})
        question={'start_ms':BASE,'end_ms':BASE+20000,'question':'Qual seria meu custo mensal de energia?'}
        result=self.client.post('/api/ai/quotes',headers=self.origin,json=question)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['projection']['hours_origin'],'collector_observed')
        self.assertAlmostEqual(result.json()['projection']['hours_per_day'],20/3600)
        self.assertTrue(any('Base de tempo observado' in text for text in result.json()['calculation_preview']['assumptions']))
        question['question']='Qual seria o custo mensal se ficar ligado 18 horas diárias?'
        result=self.client.post('/api/ai/quotes',headers=self.origin,json=question)
        self.assertEqual(result.json()['projection']['hours_per_day'],18)

    def test_explicit_duration_skips_observed_history_scan(self):
        self.login()
        self.client.put('/api/ai/key',headers=self.origin,json={'key':'synthetic-not-a-provider-key'})
        self.client.put('/api/ai/settings',headers=self.origin,json={'enabled':True,'per_analysis_usd':.05,'daily_usd':1.,'monthly_usd':2.,'authorized_total_usd':5.})
        with patch('device_observability.web.observed_usage',side_effect=AssertionError('Should not scan for an explicit scenario')):
            result=self.client.post('/api/ai/quotes',headers=self.origin,json={'start_ms':BASE,'end_ms':BASE+20000,'question':'Qual seria meu custo mensal por 18 horas diárias?'})
        self.assertEqual(result.status_code,200,result.text)

    def test_storage_warning_is_available_on_regular_status_refresh(self):
        self.login()
        result=self.client.get('/api/status')
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['storage']['limit_bytes'],2*1024**3)
        self.assertIn('blocked',result.json()['storage'])
