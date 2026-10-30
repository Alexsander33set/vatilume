import copy
import json
import tempfile
import unittest
from pathlib import Path

from device_observability.applications import capture_ancestors, group_entries, identify, MAX_ANCESTORS
from device_observability.process_analysis import coincidences, ProcessHistory
from device_observability.ai_evidence import EvidenceSession, snapshot
from device_observability.ai_cost import CostLedger, DEFAULT_LIMITS
from test_processes import BASE, process_history
import test_processes
from test_ai_service import frozen_fixture


def entry(pid, name, ppid=0, start=5, cpu=10):
    value = copy.deepcopy(process_history(name)['snapshots'][0]['context']['entries'][0])
    value.update(pid=pid, ppid=ppid, start_ticks=start, cpu_percent=cpu,
                 cpu_ticks=int((cpu or 0)*120), ancestors=[])
    return value


class ApplicationTests(unittest.TestCase):
    def test_recognizable_names_and_unknown_instances_are_separate(self):
        groups = group_entries([entry(1,'aces'), entry(2,'ChatGPT'), entry(3,'python3'),entry(4,'python3')])
        self.assertEqual({g['name'] for g in groups}, {'War Thunder','ChatGPT / Codex','python3'})
        self.assertEqual(len(groups),4)
        self.assertFalse(identify(entry(3,'QtWebEngineProc'))['recognized'])

    def test_helper_parent_links_identify_app_and_keep_original_members(self):
        root, child = entry(100,'zen'),entry(101,'Isolated Web Co',100,start=6,cpu=5)
        child['ancestors'] = capture_ancestors(child,{100:root,101:child})
        groups = group_entries([root,child])
        self.assertEqual(len(groups),1)
        self.assertEqual(groups[0]['name'],'Zen Browser')
        self.assertEqual(groups[0]['cpu_percent'],15)
        self.assertEqual(groups[0]['observed_processes'],2)
        self.assertEqual(groups[0]['rss_bytes'],root['rss_bytes']+child['rss_bytes'])
        self.assertEqual(groups[0]['methods'],['name_rule','parent_rule'])
        self.assertTrue(groups[0]['members_only'])
        self.assertEqual(groups[0]['entries'][1]['ancestors'][0]['name'],'zen')

    def test_browser_forkserver_preserves_the_link_to_the_actual_browser(self):
        root=entry(100,'zen')
        broker=entry(101,'forkserver',100,start=6)
        child=entry(102,'Isolated Web Co',101,start=7)
        child['ancestors']=capture_ancestors(child,{100:root,101:broker})
        self.assertEqual([row['name'] for row in child['ancestors']],['forkserver','zen'])
        self.assertEqual(identify(child)['name'],'Zen Browser')
        broker['ppid']=99
        child['ancestors']=capture_ancestors(child,{100:root,101:broker})
        self.assertFalse(identify(child)['recognized'])

    def test_same_helper_for_two_apps_is_never_merged_by_helper_name(self):
        roots = [entry(100,'insync'),entry(200,'zapzap')]
        children = [entry(101,'QtWebEngineProc',100,start=6),entry(201,'QtWebEngineProc',200,start=6)]
        for child in children:
            child['ancestors'] = capture_ancestors(child,{r['pid']:r for r in roots})
        self.assertEqual({g['name'] for g in group_entries(children)}, {'Insync','ZapZap'})

    def test_reused_parent_cycle_missing_link_and_desktop_shell_do_not_invent_app(self):
        child = entry(101,'Isolated Web Co',100,start=6)
        for parent in [entry(100,'zen',start=7),entry(200,'zen'),entry(100,'gnome-shell'),entry(101,'zen')]:
            child['ancestors']=[parent]
            self.assertFalse(identify(child)['recognized'],parent)
        child['ancestors']=[]
        child['application']={'name':'Fake trusted app','id':'app:fake','recognized':True}
        self.assertEqual(identify(child)['name'],'Isolated Web Co')

    def test_wrapper_chain_is_bounded_and_generic_process_does_not_adopt_parent(self):
        child=entry(100,'QtWebEngineProc',99,start=100)
        rows={pid:entry(pid,'bwrap',pid-1,start=pid) for pid in range(1,100)}
        child['ancestors']=capture_ancestors(child,rows)
        self.assertEqual(len(child['ancestors']),MAX_ANCESTORS)
        self.assertFalse(identify(child)['recognized'])
        generic=entry(101,'python3',100,start=6)
        self.assertEqual(capture_ancestors(generic,{100:entry(100,'zen')}),[])

    def test_unknown_cpu_stays_unknown_and_duplicates_do_not_inflate_totals(self):
        first=entry(100,'ChatGPT',cpu=None)
        second=entry(101,'ChatGPT',cpu=1)
        group=group_entries([first,first,second])[0]
        self.assertEqual(group['observed_processes'],2)
        self.assertEqual(group['cpu_known_processes'],1)
        self.assertEqual(group['cpu_percent'],1)
        self.assertIsNone(group_entries([first])[0]['cpu_percent'])

    def test_real_collector_uses_only_stat_and_saves_needed_parent_links(self):
        fixture=test_processes.ProcessCollectorTests();fixture.setUp()
        try:
            fixture.put(100,100,name='zen',start=5)
            fixture.put(101,100,name='Isolated Web Co',start=6)
            file=fixture.root/'101'/'stat'
            raw=file.read_text();tail=raw[raw.rindex(')')+1:].split();tail[1]='100'
            file.write_text(raw[:raw.rindex(')')+1]+' '+' '.join(tail))
            fixture.collector.read()
            child=next(e for e in fixture.collector.context['entries'] if e['pid']==101)
            self.assertEqual(identify(child)['name'],'Zen Browser')
            self.assertEqual({p.name for p in file.parent.iterdir()},{'stat'})
        finally:fixture.tearDown()

    def test_old_history_has_friendly_direct_names_but_no_invented_parentage(self):
        history=process_history('aces')
        context=history['snapshots'][0]['context']
        view=ProcessHistory(BASE,BASE+60_000,2)
        view.add({'id':4,'session_id':'s','utc_ns':(BASE+30_000)*1_000_000},{'quality':'ok','context':context})
        self.assertEqual(view.document()['snapshots'][0]['context']['applications'][0]['name'],'War Thunder')
        context['entries'][0]['name']='Isolated Web Co'
        result=coincidences([{'time_ms':BASE+15_000,'cpu_w':100}],history,{'start_ms':BASE,'end_ms':BASE+60_000},'cpu_w')
        self.assertFalse(result['peaks'][0]['matches'][0]['recognized'])

    def test_group_evidence_rechecks_cpu_and_keeps_names_parentage_out_of_model(self):
        base=frozen_fixture();start=base['window']['start_ms']+30*60_000
        history=process_history('zen',start=start,end=start+60_000)
        root=history['snapshots'][0]['context']['entries'][0]
        root.update(ppid=0)
        child={**root,'pid':100,'ppid':root['pid'],'start_ticks':6,'name':'Isolated Web Co'}
        child['ancestors']=capture_ancestors(child,{root['pid']:root})
        invalid={**root,'pid':101,'cpu_percent':99}
        history['snapshots'][0]['context']['entries']=[root,child,invalid]
        base['processes']=history
        session=EvidenceSession(snapshot(base,base['tariffs']), 'Quais aplicativos coincidem com os picos de GPU?')
        primary=session.facts['process_peak_gpu_w_0']
        self.assertIn('Zen Browser',primary['text'])
        self.assertEqual(primary['values']['peak']['matches'][0]['cpu_percent'],20)
        sent=json.dumps(session.initial())+json.dumps(session.compact(primary['evidence_ids'][0]))
        for private in ('Zen Browser','Isolated Web Co','ancestors','ppid','start_ticks','process:'):
            self.assertNotIn(private,sent)
        self.assertIn('"observed_processes": 2',sent)
        self.assertIn('"members_only": true',sent)


class AuthorizedBudgetTests(unittest.TestCase):
    def test_new_five_dollar_cap_enforces_total_and_uncertain_spend(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ledger=CostLedger(root/'ai-budget.json',root/'ai-limits.json')
            ledger.configure({**DEFAULT_LIMITS,'per_analysis_usd':.05,'daily_usd':5,'monthly_usd':5},cap_usd=5)
            self.assertEqual(ledger.status()['authorized_total_usd'],5)
            seed={'cap_usd':5.0,'requests':[{'id':'uncertain','utc_ms':1,'state':'reserved','reserved_usd':4.9999}]}
            ledger.path.write_text(json.dumps(seed))
            with self.assertRaises(ValueError):ledger.reserve(b'next-call',512,'test')
            self.assertAlmostEqual(ledger.status()['usage']['pending_usd'],4.9999)
            with self.assertRaises(ValueError):ledger.configure({**DEFAULT_LIMITS,'monthly_usd':6})
