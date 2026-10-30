#!/usr/bin/env python3
"""Graphical Snap browser validation ONLY in the disposable Ubuntu test VM.

Run as tester in the marked guest. No personal profiles, passwords or keys.
Default-browser settings are changed ONLY in this synthetic desktop. Never
prints redirect contents or the Vatilume token. Inspect capture.png separately.
"""
import argparse
import json
import os
from pathlib import Path
import pwd
import subprocess
import time


def call(args):return subprocess.check_output(args,text=True,stderr=subprocess.PIPE).strip()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('browser',choices=['firefox','chromium']);p.add_argument('step',choices=['prime','terms','menu','select','capture']);a=p.parse_args()
    assert Path('/etc/vatilume-disposable-test-vm').read_text().strip()=='vatilume-deb-test'
    assert call(['systemd-detect-virt','--vm'])=='qemu'
    user=pwd.getpwnam('tester');assert os.getuid()==user.pw_uid
    pid=call(['pgrep','-u',str(user.pw_uid),'-x','xfce4-session']).splitlines()[0]
    env=dict(item.split(b'=',1) for item in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0') if b'=' in item)
    for key in (b'DISPLAY',b'XAUTHORITY',b'DBUS_SESSION_BUS_ADDRESS',b'XDG_RUNTIME_DIR',b'XDG_CURRENT_DESKTOP',b'XDG_DATA_DIRS'):
        if key in env:os.environ[key.decode()]=env[key].decode()
    os.environ.setdefault('DISPLAY',':0');os.environ.setdefault('XAUTHORITY',user.pw_dir+'/.Xauthority')
    os.environ['LIBGL_ALWAYS_SOFTWARE']='true'
    out=Path(user.pw_dir)/'vatilume-validation';out.mkdir(exist_ok=True)
    desktop=a.browser+'_'+a.browser+'.desktop'
    if a.step=='prime':
        with (out/(a.browser+'-launch.log')).open('a') as log:
            subprocess.Popen(['/snap/bin/'+a.browser,'about:blank'],stdout=log,stderr=log,start_new_session=True)
    elif a.step=='terms':
        assert a.browser=='chromium'
        window=call(['xdotool','search','--onlyvisible','--name','^Chromium Additional Terms of Service$']).splitlines()[-1]
        call(['xdotool','windowactivate','--sync',window]);call(['xdotool','key','Return'])
    elif a.step=='menu':
        for args in (['xdg-settings','set','default-web-browser',desktop],['xdg-mime','default',desktop,'x-scheme-handler/http'],['xdg-mime','default',desktop,'x-scheme-handler/https']):call(args)
        from gi.repository import Gio
        app=Gio.AppInfo.get_default_for_uri_scheme('http');assert app.get_id()==desktop
        window=call(['xdotool','search','--onlyvisible','--class','xfce4-appfinder']).splitlines()[-1]
        call(['xdotool','windowactivate','--sync',window]);call(['xdotool','key','ctrl+a']);call(['xdotool','type','--clearmodifiers','Vatilume'])
    elif a.step=='select':
        window=call(['xdotool','search','--onlyvisible','--class','xfce4-appfinder']).splitlines()[-1]
        call(['xdotool','windowactivate','--sync',window])
        call(['xdotool','key','Return'])
    time.sleep(2)
    screenshot=out/(a.browser+'-'+a.step+'.png');call(['import','-window','root',str(screenshot)])
    redirect=Path(user.pw_dir)/'snap'/a.browser/'common/vatilume/open.html'
    result={'browser':a.browser,'step':a.step,'screenshot':str(screenshot),'default_browser':call(['xdg-settings','get','default-web-browser']),'private_redirect_present':redirect.exists()}
    if redirect.exists():
        result.update(redirect_file_mode=oct(redirect.stat().st_mode&0o777),redirect_dir_mode=oct(redirect.parent.stat().st_mode&0o777))
    print(json.dumps(result))

if __name__=='__main__':main()
