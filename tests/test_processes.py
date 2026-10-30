import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from device_observability.processes import ProcessCollector, parse_stat
from device_observability.config import Config
from device_observability.storage import Store, readonly
from device_observability.sensors import SensorPool
from device_observability.process_analysis import ProcessHistory, coincidences

BASE = 1_793_188_800_000


def stat_line(pid, ticks, start=1, pages=100, name='example'):
    fields = ['0'] * 30
    fields[0], fields[11], fields[12], fields[19], fields[21] = 'R', str(ticks), '0', str(start), str(pages)
    return f'{pid} ({name}) ' + ' '.join(fields)


def process_history(name='example', *, start=BASE, end=BASE+30_000, cpu=10, session='session'):
    row = {'pid':99, 'start_ticks':5, 'name':name, 'cpu_ticks':int(cpu/100*4*100*(end-start)/1000), 'previous_cpu_ticks':0,
        'cpu_percent':cpu, 'rss_bytes':4_096_000, 'interval_start_ms':start, 'interval_end_ms':end,
        'elapsed_ns':(end-start)*1_000_000}
    context = {'entries':[row], 'clock_ticks_per_second':100, 'machine_cpu_count':4, 'top_n':5,
        'interval_seconds':30, 'scanned':5, 'readable':5, 'permission_denied':0, 'parse_errors':0,
        'vanished':0, 'truncated':False, 'cpu_intervals':5, 'scan_ms':1}
    return {'available':True,'snapshots':[{'sample_id':4,'session_id':session,'time_ms':end,'quality':'ok','context':context}]}


class ProcessCollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = [10_000_000_000, BASE*1_000_000, 10_000_000_000]
        self.collector = ProcessCollector(proc_root=self.root,clock=lambda:tuple(self.now))
        self.collector.hz, self.collector.cpu_count = 100, 4

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, pid, ticks, **kw):
        file = self.root/str(pid)/'stat'
        file.parent.mkdir(exist_ok=True)
        file.write_text(stat_line(pid,ticks,**kw))

    def advance(self, seconds=30):
        self.now = [value+int(seconds*1e9) for value in self.now]

    def test_warmup_cpu_units_and_rss_are_distinct_and_no_sensitive_files_are_read(self):
        self.put(10,100,pages=250)
        self.collector.read()
        self.assertIsNone(self.collector.context['entries'][0]['cpu_percent'])
        self.advance();self.put(10,1300,pages=300)
        with patch('pathlib.Path.readlink',side_effect=AssertionError('No exe/cwd reads')):
            self.collector.read()
        row=self.collector.context['entries'][0]
        self.assertAlmostEqual(row['cpu_percent'],10)
        self.assertEqual(row['elapsed_ns'],30_000_000_000)
        self.assertEqual(row['previous_cpu_ticks'],100)
        self.assertEqual(row['rss_bytes'],300*self.collector.page_size)
        self.assertEqual({p.name for p in (self.root/'10').iterdir()},{'stat'})

    def test_pid_reuse_name_change_counter_reset_and_large_gaps_do_not_get_cpu_attribution(self):
        for change in ({'start':50},{'name':'another'},{'ticks':1},{'gap':120}):
            self.collector.previous.clear();self.put(10,100)
            self.collector.read();self.advance(change.get('gap',30))
            self.put(10,change.get('ticks',500),**{k:v for k,v in change.items() if k not in ('ticks','gap')})
            self.collector.read()
            self.assertIsNone(self.collector.context['entries'][0]['cpu_percent'],change)

    def test_suspension_wall_clock_jump_and_configuration_change_require_new_baseline(self):
        for clock_index in (1,2):
            self.collector.previous.clear();self.put(10,100);self.collector.read()
            self.advance();self.now[clock_index]+=10_000_000_000;self.put(10,200);self.collector.read()
            self.assertIsNone(self.collector.context['entries'][0]['cpu_percent'])
        self.collector.configure({'interval_seconds':30,'top_n':5,'generation':'new-config'})
        self.assertFalse(self.collector.previous)

    def test_parentheses_and_controls_in_names_do_not_break_stat_fields(self):
        row=parse_stat(stat_line(15,42,name='name ) (\n<&>'),15,4096)
        self.assertEqual(row['cpu_ticks'],42)
        self.assertEqual(row['name'],'name ) ( <&>')
        with self.assertRaises(ValueError):parse_stat(stat_line(15,42),99,4096)

    def test_output_and_baselines_are_bounded_and_dead_processes_are_removed(self):
        for pid in range(10,30):self.put(pid,100,pages=pid)
        self.collector.top_n=3;self.collector.read();self.advance()
        for pid in range(10,30):self.put(pid,100+pid*10,pages=40-pid)
        self.collector.read()
        self.assertLessEqual(len(self.collector.context['entries']),6)
        self.assertEqual(self.collector.context['cpu_intervals'],20)
        (self.root/'10'/'stat').unlink();(self.root/'10').rmdir()
        self.collector.read();self.assertNotIn(10,self.collector.previous)
        with patch('device_observability.processes.MAX_PIDS',2):self.collector.read()
        self.assertTrue(self.collector.context['truncated'])
        self.assertLessEqual(self.collector.context['scanned'],2)
        self.assertLessEqual(len(self.collector.previous),2)
        with patch('device_observability.processes.MAX_SCAN_NS',0):self.collector.read()
        self.assertTrue(self.collector.context['truncated'])
        self.assertEqual(self.collector.context['scanned'],0)

    def test_permission_failure_is_explicit_and_not_a_zero_cpu_reading(self):
        self.put(10,100)
        with patch('pathlib.Path.open',side_effect=PermissionError):self.collector.read()
        self.assertEqual(self.collector.context['permission_denied'],1)
        self.assertEqual(self.collector.context['entries'],[])

    def test_context_uses_existing_atomic_persistence_without_growing_sensor_catalogue(self):
        self.put(10,100);self.collector.read()
        config=Config(self.root)
        store=Store(self.root/'telemetry.sqlite3')
        try:
            session=store.start('boot',config,{})
            frame={'sequence':1,'utc_ns':BASE*1_000_000,'monotonic_ns':1,'boottime_ns':1,'collection_ms':1,
                'collectors':{'processes':{'quality':'ok','readings':[],'sources':[],'context':self.collector.context}}}
            store.append(session,frame,config,[])
            store.finish(session,'test',{})
        finally:store.close()
        con=readonly(self.root/'telemetry.sqlite3')
        try:
            saved=json.loads(con.execute('SELECT collectors_json FROM samples').fetchone()[0])
            self.assertEqual(saved['processes']['context']['entries'][0]['name'],'example')
            self.assertEqual(con.execute('SELECT COUNT(*) FROM sources').fetchone()[0],0)
            self.assertEqual(con.execute('PRAGMA integrity_check').fetchone()[0],'ok')
        finally:con.close()


class ProcessEvidenceTests(unittest.TestCase):
    def test_invalid_saved_cpu_calculation_is_not_accepted_as_evidence(self):
        history=process_history()
        history['snapshots'][0]['context']['entries'][0]['cpu_percent']=99
        result=coincidences([{'time_ms':BASE+15_000,'cpu_w':100}],history,{'start_ms':BASE,'end_ms':BASE+30_000},'cpu_w')
        self.assertEqual(result['peaks'][0]['matches'],[])

    def test_only_actual_overlapping_cpu_intervals_are_evidence_of_activity(self):
        series=[{'time_ms':BASE+15_000,'gpu_w':100},{'time_ms':BASE+45_000,'gpu_w':200}]
        window={'start_ms':BASE,'end_ms':BASE+60_000}
        result=coincidences(series,process_history(),window,'gpu_w')
        self.assertEqual(result['peaks'][0]['value'],200)
        self.assertEqual(result['peaks'][0]['matches'],[])
        result=coincidences(series,process_history(start=BASE+30_000,end=BASE+60_000),window,'gpu_w')
        self.assertEqual(result['peaks'][0]['matches'][0]['name'],'example')
        self.assertFalse(result['causality_proven'])
        self.assertFalse(result['per_process_gpu_available'])

    def test_history_retention_is_bounded_and_missing_past_remains_missing(self):
        history=ProcessHistory(BASE,BASE+120_000,24)
        context=process_history()['snapshots'][0]['context']
        for index in range(1000):
            row={'id':index+1,'session_id':'s','utc_ns':(BASE+index*100)*1_000_000}
            history.add(row,{'quality':'ok','context':context})
        self.assertEqual(history.scans,1000)
        self.assertLessEqual(len(history.document()['snapshots']),24)
        empty=ProcessHistory(BASE,BASE+120_000,24).document()
        self.assertFalse(empty['available'])
        with self.assertRaises(ValueError):coincidences([],empty,{'start_ms':BASE,'end_ms':BASE+1},'cpu_temp')


if __name__=='__main__':unittest.main()
