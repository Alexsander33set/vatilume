import copy
import hashlib
from datetime import datetime
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from device_observability.ai_cost import CostLedger, DEFAULT_LIMITS
from device_observability.ai_evidence import EvidenceSession
from device_observability.ai_models import MODELS
from device_observability.ai_service import AIService
from device_observability.analysis import overview
from device_observability.config import Config
from device_observability.observed_usage import observed_usage
from device_observability.projection import projection_scenario, monthly_projection
from device_observability.sensors import GPUCollector, NetworkCollector, SystemCollector
from device_observability.storage import Store
from device_observability.storage_policy import storage_status, ensure_capacity, maintain
from device_observability.ai_raw_export import validate_history
from test_analysis import synthetic,BASE
from test_ai_service import frozen_fixture,FakeTransport


def rehash(frozen):
    frozen['sha256']=hashlib.sha256(json.dumps({k:v for k,v in frozen.items() if k not in ('sha256','approval_max_usd')},sort_keys=True,allow_nan=False).encode()).hexdigest()


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()

    def test_observed_time_counts_valid_intervals_including_idle_not_window_length(self):
        database=synthetic(self.root)
        result=observed_usage(database,BASE+20_000)
        self.assertAlmostEqual(result['hours_per_day'],20/3600)
        self.assertTrue(result['partial_base'])
        self.assertEqual(result['days_observed'],1)
    def test_observed_time_excludes_restart_and_long_gap(self):
        database=synthetic(self.root, timestamps=(0,10,100),split=True)
        self.assertIsNone(observed_usage(database,BASE+100_000)['hours_per_day'])
    def test_suspension_is_not_uptime(self):
        database=synthetic(self.root)
        with sqlite3.connect(database) as con:
            con.execute('UPDATE samples SET boottime_ns=boottime_ns+100000000000 WHERE sequence=3')
        self.assertAlmostEqual(observed_usage(database,BASE+20_000)['hours_per_day'],10/3600)
    def test_midnight_splits_time_and_explicit_question_overrides_observed(self):
        import test_analysis
        # 02:59:50 UTC is 23:59:50 in the configured zone.
        midnight=int(datetime.fromisoformat('2026-10-29T02:59:50+00:00').timestamp()*1000)
        with patch.object(test_analysis,'BASE',midnight):
            database=synthetic(self.root)
        value=observed_usage(database,midnight+20000)
        self.assertEqual(len(value['daily']),2)
        self.assertAlmostEqual(sum(d['observed_hours'] for d in value['daily']),20/3600)
        scenario=projection_scenario('PC fique ligado por 18 horas diárias',None,value)
        self.assertEqual(scenario['hours_per_day'],18)
        self.assertEqual(scenario['hours_origin'],'question')
    def test_observed_and_manual_scenario_are_distinct(self):
        profile={'hours_per_day':8,'partial_base':False}
        self.assertEqual(projection_scenario('custo mensal',None,profile)['hours_origin'],'collector_observed')
        self.assertEqual(projection_scenario('custo mensal',6,profile)['hours_per_day'],6)
        with self.assertRaisesRegex(ValueError,'intervalos suficientes'):projection_scenario('custo mensal',None,{})
    def test_unknown_gpu_domain_prevents_combined_cost(self):
        frozen=frozen_fixture();frozen['components'][1]['energy_domain']='unknown'
        result=monthly_projection(frozen)
        self.assertEqual(result['status'],'domain_unconfirmed')
        self.assertIsNone(result['projected_cost_brl'])
        self.assertGreater(result['components'][1]['projected_cost_brl'],0)
        rehash(frozen)
        evidence=EvidenceSession(frozen,'Qual seria meu custo mensal de energia?')
        report=evidence.validate({'answer_id':'monthly_projection','fact_ids':['monthly_projection'],'recommendation_ids':[],'answer_status':'evidence_found'})
        self.assertIn('domínio',report['answer']['text'])
    def test_ambiguous_gpus_never_pick_alphabetically(self):
        database=synthetic(self.root)
        with sqlite3.connect(database) as con:
            meta=json.loads(con.execute("SELECT metadata_json FROM sources WHERE id='gpu'").fetchone()[0]);meta.update(id='gpu2',scope='another-gpu')
            con.execute('INSERT INTO sources VALUES (?,?,?)',('gpu2',json.dumps(meta),BASE*1000000))
            for identity,payload in con.execute('SELECT id,collectors_json FROM samples').fetchall():
                groups=json.loads(payload);groups['gpu']['readings'].append({'source_id':'gpu2','value':20000000,'quality':'ok'})
                con.execute('UPDATE samples SET collectors_json=? WHERE id=?',(json.dumps(groups),identity))
        result=overview(database,BASE,BASE+20000,[],24)
        self.assertTrue(result['energy_policy']['ambiguous_gpu']);self.assertIsNone(result['components'][1]['energy_kwh'])
    def test_inactive_catalogue_does_not_make_gpu_ambiguous(self):
        database=synthetic(self.root)
        with sqlite3.connect(database) as con:
            meta=json.loads(con.execute("SELECT metadata_json FROM sources WHERE id='gpu'").fetchone()[0]);meta.update(id='old',scope='old-gpu')
            con.execute('INSERT INTO sources VALUES (?,?,?)',('old',json.dumps(meta),0))
        self.assertFalse(overview(database,BASE,BASE+20000,[],24)['energy_policy']['ambiguous_gpu'])
    def test_amd_apu_not_discrete_and_replacement_changes_identity(self):
        device=self.root/'devices/pci/gpu';device.mkdir(parents=True)
        (device/'vendor').write_text('0x1002');(device/'device').write_text('0x1636')
        power=device/'hwmon/hwmon1/power1_average';power.parent.mkdir(parents=True);power.write_text('20000000')
        card=self.root/'class/drm/card0';card.mkdir(parents=True);(card/'device').symlink_to(device)
        sensor=GPUCollector(self.root).discover()[0]
        self.assertEqual(sensor.metric,'soc.power_reported');self.assertEqual(sensor.energy_domain,'soc_cpu_gpu')
        (device/'device').write_text('0x73ef');other=GPUCollector(self.root).discover()[0]
        self.assertEqual(other.energy_domain,'discrete_gpu');self.assertNotEqual(sensor.id,other.id)
        (device/'device').write_text('0xffff');self.assertEqual(GPUCollector(self.root).discover()[0].energy_domain,'unknown')
    def test_network_is_optional_and_only_reads_interface_byte_counters(self):
        self.assertNotIn('network',Config(self.root).enabled_collectors)
        path=self.root/'net/dev';path.parent.mkdir();path.write_text('header\nheader\n lo: 1 0 0 0 0 0 0 0 2 0 0 0 0 0 0 0\n eth0: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0\n')
        readings,sources=NetworkCollector(proc_root=self.root).read()
        self.assertEqual([r['value'] for r in readings],[100,200])
        self.assertEqual([s.metric for s in sources],['network.received','network.sent'])
    def test_retention_is_off_by_default_and_never_deletes_secrets_or_budget(self):
        database=synthetic(self.root)
        original=database.read_bytes();config=Config(self.root)
        store=Store(database)
        self.assertEqual(maintain(store.con,config)['deleted'],0)
        (self.root/'ai-api-key').write_text('fixture-only')
        (self.root/'ai-budget.json').write_text('{"cap_usd":5,"requests":[]}')
        result=maintain(store.con,replace(config,retention_days=1))
        # Synthetic data is past the simulated cutoff.
        self.assertEqual(result['deleted'],1)
        self.assertEqual([r[0] for r in store.con.execute('SELECT id FROM samples ORDER BY id')],[2,3])
        self.assertEqual((self.root/'ai-api-key').read_text(),'fixture-only')
        self.assertEqual(json.loads((self.root/'ai-budget.json').read_text())['cap_usd'],5)
        store.close()
    def test_quota_blocks_before_writing_and_does_not_delete(self):
        (self.root/'history.bin').write_bytes(b'x'*100)
        before=(self.root/'history.bin').read_bytes()
        with self.assertRaisesRegex(OSError,'cota'):ensure_capacity(self.root,100,additional_bytes=1)
        self.assertEqual((self.root/'history.bin').read_bytes(),before)
        self.assertTrue(storage_status(self.root,100)['warning'])
    def test_symlink_targets_not_counted_or_modified(self):
        (self.root/'outside').mkdir();target=self.root/'outside/key';target.write_bytes(b'x'*100)
        (self.root/'link').symlink_to(target)
        self.assertEqual(storage_status(self.root,100)['physical_bytes'],0)
        self.assertEqual(target.stat().st_size,100)
    def test_expired_raw_csv_is_explained_without_losing_report(self):
        database=synthetic(self.root)
        with sqlite3.connect(database) as con:con.execute("INSERT INTO metadata VALUES ('raw_pruned_max_utc_ns',?)",(str(BASE*1000000),))
        with self.assertRaisesRegex(ValueError,'expiraram'):
            validate_history(database,{'highwater':{'id':3}},BASE)
    def test_selected_model_frozen_and_mixed_costs_preserve_cap(self):
        service=AIService(self.root,transport=FakeTransport())
        service.save_key('fixture-only-not-real');service.ledger.configure(DEFAULT_LIMITS,cap_usd=5)
        service.save_model('gpt-6-luna')
        frozen=frozen_fixture();frozen['model']='gpt-6-luna'
        service.save_model('gpt-6.1-terra')
        rehash(frozen)
        service.analyze('luna',frozen,'Compare a GPU')
        self.assertTrue(all(c['model']=='gpt-6-luna' for c in service.transport.calls))
        self.assertAlmostEqual(service.ledger.run_cost('luna'),2*(100*.125+50*.5)/1e6)
        self.assertEqual(service.ledger.status()['authorized_total_usd'],5)
        with self.assertRaises(ValueError):service.save_model('unregistered-model')
    def test_paid_runner_uses_authoritative_budget_and_honors_additional_cap(self):
        spec=importlib.util.spec_from_file_location('comparison',Path(__file__).resolve().parents[1]/'scripts/compare_models.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        installed=self.root/'installed';output=self.root/'result';installed.mkdir();output.mkdir()
        service=AIService(installed);service.save_key('synthetic-key-only');service.ledger.configure(DEFAULT_LIMITS,cap_usd=5)
        original=AIService.__init__
        def init(service,*args,**kwargs):
            kwargs['transport']=FakeTransport(final={'answer_id':'scope','fact_ids':['scope'],'recommendation_ids':[],'answer_status':'insufficient'})
            original(service,*args,**kwargs)
        with patch.object(AIService,'__init__',init):result=module.run(output,installed,.01,1)
        self.assertLessEqual(result['total_after_usd']-result['total_before_usd'],.010000001)
        self.assertTrue(result['runs']);self.assertEqual(service.ledger.status()['usage']['total_usd'],result['total_after_usd'])
        self.assertFalse((output/'ai-budget.json').exists());self.assertFalse((output/'ai-api-key').exists())

    def test_export_requires_original_preceding_reading_even_after_window_cutoff(self):
        database=synthetic(self.root)
        result=overview(database,BASE+15000,BASE+20000,[],24)
        provenance=result['provenance']
        with sqlite3.connect(database) as con:con.execute('DELETE FROM samples WHERE id=?',(provenance['previous_sample_id'],))
        with self.assertRaisesRegex(ValueError,'leitura de origem'):
            validate_history(database,provenance,BASE+15000)

    def test_key_cannot_change_during_an_active_analysis(self):
        import fcntl
        service=AIService(self.root);service.save_key('first-synthetic-key')
        with (self.root/'ai-active.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError,'Aguarde'):service.save_key('second-synthetic-key')
        self.assertEqual((self.root/'ai-api-key').read_text(),'first-synthetic-key')

    def test_unknown_gpu_has_an_explicit_scope_warning(self):
        database=synthetic(self.root)
        with sqlite3.connect(database) as con:
            descriptor=json.loads(con.execute("SELECT metadata_json FROM sources WHERE id='gpu'").fetchone()[0]);descriptor.pop('energy_domain')
            con.execute("UPDATE sources SET metadata_json=? WHERE id='gpu'",(json.dumps(descriptor),))
        view=overview(database,BASE,BASE+20000,[],24)
        self.assertTrue(view['energy_policy']['unconfirmed_gpu'])

    def test_legacy_gpu_chart_survives_identity_upgrade_without_joining_energy(self):
        database=synthetic(self.root)
        with sqlite3.connect(database) as con:
            descriptor=json.loads(con.execute("SELECT metadata_json FROM sources WHERE id='gpu'").fetchone()[0]);descriptor.update(id='gpu-v2',scope='discrete-gpu:0x1002:0x73ef')
            con.execute('INSERT INTO sources VALUES (?,?,?)',('gpu-v2',json.dumps(descriptor),(BASE+10000)*1000000))
            for identity,payload in con.execute('SELECT id,collectors_json FROM samples WHERE id>=2').fetchall():
                groups=json.loads(payload);groups['gpu']['readings'][0]['source_id']='gpu-v2'
                con.execute('UPDATE samples SET collectors_json=? WHERE id=?',(json.dumps(groups),identity))
        result=overview(database,BASE,BASE+20000,[],24)
        self.assertEqual([p['gpu_w'] for p in result['series'] if 'gpu_w' in p],[10,30,50])
        self.assertEqual(result['components'][1]['covered_seconds'],10)
        self.assertAlmostEqual(result['components'][1]['energy_kwh'],400/3600000)

    def test_raw_export_rechecks_retention_inside_its_snapshot_before_any_csv_row(self):
        from device_observability.ai_raw_export import raw_csv
        from device_observability.ai_evidence import snapshot
        database=synthetic(self.root)
        frozen=snapshot(overview(database,BASE,BASE+20000,[],24),[])
        validate_history(database,frozen['provenance'],BASE)
        stream=raw_csv(database,frozen)
        # Maintenance can run after the HTTP preflight and before iteration.
        with sqlite3.connect(database) as con:con.execute("INSERT INTO metadata VALUES ('raw_pruned_max_utc_ns',?)",(str(BASE*1000000),))
        with self.assertRaisesRegex(ValueError,'expiraram'):next(stream)

    def test_benchmark_missing_tariff_has_no_phantom_cost_facts(self):
        from device_observability.benchmark_cases import cases
        for name,question,frozen in cases():
            evidence=EvidenceSession(frozen,question)
            if not frozen['tariffs']:
                self.assertTrue(all(c['cost_brl'] is None and c['priced_seconds']==0 for c in frozen['components']))
                self.assertTrue(all(evidence.facts['cost_'+c['id']]['values']['cost_brl'] is None for c in frozen['components']))

    def test_benchmark_resume_cannot_reset_the_original_additional_ceiling(self):
        spec=importlib.util.spec_from_file_location('comparison_resume',Path(__file__).resolve().parents[1]/'scripts/compare_models.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        installed=self.root/'installed';output=self.root/'result';installed.mkdir();output.mkdir()
        service=AIService(installed);service.save_key('synthetic-key-only');service.ledger.configure(DEFAULT_LIMITS,cap_usd=5)
        ledger=json.loads((installed/'ai-budget.json').read_text());ledger['requests'].append({'id':'prior-comparison','state':'completed','utc_ms':0,'actual_usd':.4,'reserved_usd':.4})
        (installed/'ai-budget.json').write_text(json.dumps(ledger))
        result=module.run(output,installed,.30,1,anchor=.1)
        self.assertEqual(result['runs'],[])
        self.assertEqual(result['comparison_anchor_total_usd'],.1)
        self.assertEqual(result['total_before_usd'],result['total_after_usd'])

    def test_explicit_half_comparison_rejects_generic_scope_as_primary(self):
        evidence=EvidenceSession(frozen_fixture(),'Compare a potência da CPU entre as metades do período.')
        self.assertEqual(evidence.output_schema()['properties']['answer_id']['enum'],['comparison_cpu_w'])
        with self.assertRaisesRegex(ValueError,'comparação solicitada'):
            evidence.validate({'answer_id':'scope','fact_ids':['scope'],'recommendation_ids':[],'answer_status':'evidence_found'})
        report=evidence.validate({'answer_id':'comparison_cpu_w','fact_ids':['comparison_cpu_w'],'recommendation_ids':[],'answer_status':'evidence_found'})
        self.assertEqual(report['answer']['values']['before_mean'],50)
        # A request about named dates is not silently interpreted as halves.
        other=EvidenceSession(frozen_fixture(),'Compare a potência da CPU entre ontem e hoje.')
        self.assertIsNone(other.comparison_metric)

    def test_explicit_usage_comparison_without_data_returns_its_actual_limitation(self):
        evidence=EvidenceSession(frozen_fixture(),'Compare o uso da CPU entre as duas metades do período.')
        report=evidence.validate({'answer_id':'comparison_cpu_percent','fact_ids':['comparison_cpu_percent'],'recommendation_ids':[],'answer_status':'evidence_found'})
        self.assertEqual(report['answer_status'],'insufficient')
        self.assertIn('três intervalos',report['answer']['text'])
