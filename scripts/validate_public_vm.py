#!/usr/bin/env python3
"""Security upgrade/lifecycle checks ONLY inside the marked disposable Ubuntu VM.

Run as guest root. Never use a personal computer as this VM: fresh phase purges
all managed synthetic state. No paid API is called. Desktop proof is separate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import urllib.error

sys.path.insert(0,str(Path(__file__).resolve().parent))
import validate_deb_vm as vm

WORK=Path('/root/vatilume-public-validation')


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot():
    files=[vm.STATE/n for n in ('ai-api-key','ai-budget.json','ai-limits.json','collector-overrides.json')]
    files+=[Path('/etc/device-observability/collector.toml')]
    return {'files':{str(p):digest(p) for p in files if p.exists()},
            'samples':vm.sample_prefix(),'tariffs':vm.api_client()('/api/settings')['tariffs'],
            'token':digest(vm.STATE/'interface-token'),
            'grants':{str(p):digest(p) for p in Path('/var/lib/vatilume-access').glob('*.url')}}


def preserved(baseline):
    for name,value in baseline['files'].items():assert digest(Path(name))==value,'Changed '+name
    assert vm.sample_prefix(baseline['samples']['maximum_id'])==baseline['samples']
    assert vm.api_client()('/api/settings')['tariffs']==baseline['tariffs']
    vm.wait_for(lambda:vm.sample_prefix()['maximum_id']>baseline['samples']['maximum_id'])
    assert vm.ready()['write_failures']==0


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=['upgrade','preserve','reboot','fresh']);p.add_argument('--package',default='/home/tester/vatilume_0.8.0-1_amd64.deb');a=p.parse_args()
    assert __import__('os').geteuid()==0
    assert Path('/etc/vatilume-disposable-test-vm').read_text().strip()=='vatilume-deb-test'
    assert vm.run(['systemd-detect-virt','--vm']).strip()=='qemu'
    assert 'VERSION_ID="24.04"' in Path('/etc/os-release').read_text()
    WORK.mkdir(exist_ok=True,mode=0o700)
    if a.phase=='upgrade':
        assert vm.run(['dpkg-query','-W','-f=${Version}','vatilume']).strip()=='0.7.0-2'
        assert vm.run(['dpkg-query','-W','-f=${Status}','vatilume']).strip()=='install ok installed'
        baseline=snapshot();old_api=vm.api_client()
        (WORK/'upgrade-before.json').write_text(json.dumps(baseline))
        vm.run(['apt-get','install','-y','--no-install-recommends',a.package])
        preserved(baseline)
        assert digest(vm.STATE/'interface-token')!=baseline['token'],'Legacy exposed token not rotated'
        assert (vm.STATE/'interface-auth-version').read_text().strip()=='2'
        try:old_api('/api/status');raise AssertionError('Old session still valid')
        except urllib.error.HTTPError as e:assert e.code==401
        token=(vm.STATE/'interface-token').read_text().strip()
        for name in baseline['grants']:
            assert '#access='+token in Path(name).read_text()
            assert digest(Path(name))!=baseline['grants'][name]
        api=vm.api_client();assert api('/api/settings')['version']=='0.8.0'
        assert api('/api/ai/settings')['authorized_total_usd']==5
        assert api('/api/ai/settings')['usage']['total_usd']==.0123
        for document in ('license','privacy','security','third-party'):
            text = __import__('urllib.request',fromlist=['urlopen']).urlopen(vm.ORIGIN+'/legal/'+document).read().decode()
            assert ('GNU GENERAL PUBLIC LICENSE' if document=='license' else 'APFS') in text
        baseline=snapshot();baseline['boot_id']=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        (WORK/'baseline.json').write_text(json.dumps(baseline))
        report={'phase':'upgrade','data_preserved':True,'token_rotated':True,'old_session_rejected':True,'desktop_grants_refreshed':True,'paid_calls':0}
    elif a.phase in ('preserve','reboot'):
        baseline=json.loads((WORK/'baseline.json').read_text())
        if a.phase=='preserve':
            vm.run(['apt-get','remove','-y','vatilume'])
            for name,value in baseline['files'].items():assert digest(Path(name))==value
            assert not Path('/usr/bin/vatilume').exists()
            vm.run(['apt-get','install','-y','--no-install-recommends',a.package])
        else:assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=baseline['boot_id']
        preserved(baseline)
        assert digest(vm.STATE/'interface-token')==baseline['token'],'Unexpected repeated rotation'
        for name,value in baseline['grants'].items():assert digest(Path(name))==value
        report={'phase':a.phase,'data_preserved':True,'no_repeated_rotation':True,'paid_calls':0}
    else:
        vm.run(['apt-get','purge','-y','vatilume'])
        assert not vm.STATE.exists()
        vm.run(['apt-get','install','-y','--no-install-recommends',a.package])
        api=vm.api_client();status=api('/api/ai/settings')
        assert status['authorized_total_usd']==0 and status['usage']['total_usd']==0
        assert not status['limits']['enabled'] and not status['key_configured']
        before=vm.sample_prefix();vm.wait_for(lambda:vm.sample_prefix()['maximum_id']>before['maximum_id'])
        report={'phase':'fresh','purge_removed_managed_state':True,'budget_starts_zero':True,'ai_disabled':True,'collection_continues':True,'paid_calls':0}
    report['result']='passed';(WORK/(a.phase+'.json')).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
