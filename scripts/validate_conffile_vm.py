#!/usr/bin/env python3
"""Exercise real APT conffile preservation only inside the marked disposable VM."""
from pathlib import Path
import subprocess,sys,tempfile,json
assert Path('/etc/vatilume-disposable-test-vm').read_text().strip()=='vatilume-deb-test'
assert subprocess.check_output(['systemd-detect-virt','--vm'],text=True).strip() in ('qemu','kvm')
sys.path.insert(0,str(Path(__file__).resolve().parent))
import upgrade_deb as upgrade
config=Path('/etc/vatilume-conffile-probe.conf')
assert not config.exists()
with tempfile.TemporaryDirectory(prefix='vatilume-conffile-probe-',dir='/root') as directory:
    root=Path(directory)
    for version,value in ((1,'original'),(2,'maintainer-new-default')):
        stage=root/('stage'+str(version));(stage/'DEBIAN').mkdir(parents=True);(stage/'etc').mkdir()
        (stage/'DEBIAN/control').write_text(f'Package: vatilume-conffile-probe\nVersion: {version}\nArchitecture: all\nMaintainer: APFS <contato@apfs.com.br>\nDescription: disposable conffile preservation regression\n')
        (stage/'DEBIAN/conffiles').write_text('/etc/vatilume-conffile-probe.conf\n')
        (stage/'etc/vatilume-conffile-probe.conf').write_text(value+'\n')
        subprocess.run(['dpkg-deb','--root-owner-group','--build',str(stage),str(root/(str(version)+'.deb'))],check=True,stdout=subprocess.DEVNULL)
    with (root/'apt.log').open('w') as log:
        try:
            upgrade.run(['apt-get','install','-y',str(root/'1.deb')],log)
            config.write_text('user-custom-setting=preserve-this\n')
            upgrade.run(['apt-get','install','-y',str(root/'2.deb')],log)
            assert config.read_text()=='user-custom-setting=preserve-this\n'
        finally:
            upgrade.run(['apt-get','purge','-y','vatilume-conffile-probe'],log)
assert not config.exists()
print(json.dumps({'conffile_regression':'passed','real_apt_and_dpkg':True,'modified_configuration_preserved':True,'interactive_input':'disabled','paid_calls':0}))
