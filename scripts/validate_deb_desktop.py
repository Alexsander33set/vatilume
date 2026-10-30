#!/usr/bin/env python3
"""Interactive desktop check helper ONLY for the disposable XFCE test VM.

Run prepare as root INSIDE the marked guest, then the other steps as tester:
menu (inspect screenshot), select (inspect first-use polkit dialog), authorize,
capture. Screenshots live in ~/vatilume-validation/. No personal passwords or
API keys are used; prepare creates a temporary password only in this guest.
"""
import argparse
import json
import os
import pwd
import secrets
import subprocess
import time
from pathlib import Path


def call(arguments, **kwargs):
    return subprocess.run(arguments, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('step', choices=['prepare', 'menu', 'select', 'authorize', 'capture', 'reopen'])
    args = parser.parse_args()
    assert Path('/etc/vatilume-disposable-test-vm').read_text().strip() == 'vatilume-deb-test'
    assert call(['systemd-detect-virt', '--vm']) == 'qemu'
    account = pwd.getpwnam('tester')
    home = Path(account.pw_dir)
    password_path = home / 'vatilume-validation/guest-test-password'
    if args.step == 'prepare':
        assert os.geteuid() == 0
        password = secrets.token_urlsafe(24)
        call(['chpasswd'], input='tester:' + password + '\n')
        fd = os.open(password_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(password)
            os.fchown(stream.fileno(), account.pw_uid, account.pw_gid)
        autostart = home / '.config/autostart'
        autostart.mkdir(parents=True, exist_ok=True)
        for name, executable in (
            ('vatilume-test-menu', 'xfce4-appfinder --disable-server'),
            ('vatilume-test-agent', '/usr/lib/policykit-1-gnome/polkit-gnome-authentication-agent-1'),
        ):
            path = autostart / (name + '.desktop')
            path.write_text(f'[Desktop Entry]\nType=Application\nName={name}\nExec={executable}\nTerminal=false\n')
            os.chown(path, account.pw_uid, account.pw_gid)
        for path in (home / '.config', autostart):
            os.chown(path, account.pw_uid, account.pw_gid)
        path = home / '.xsessionrc'
        path.write_text('export WEBKIT_DISABLE_DMABUF_RENDERER=1\nexport LIBGL_ALWAYS_SOFTWARE=true\nexport NO_AT_BRIDGE=1\nexport GSK_RENDERER=cairo\nexport GDK_BACKEND=x11\nexport GTK_A11Y=none\n')
        os.chown(path, account.pw_uid, account.pw_gid)
        print(json.dumps({'guest_test_password': 'prepared privately'}))
        return
    assert os.getuid() == account.pw_uid, 'Run graphical steps as tester, without sudo'
    session = call(['pgrep', '-u', str(account.pw_uid), '-x', 'xfce4-session']).splitlines()[0]
    environment = dict(part.split(b'=', 1) for part in Path(f'/proc/{session}/environ').read_bytes().split(b'\0') if b'=' in part)
    for key in (b'DISPLAY', b'XAUTHORITY', b'DBUS_SESSION_BUS_ADDRESS', b'XDG_RUNTIME_DIR', b'XDG_CURRENT_DESKTOP'):
        if key in environment:
            os.environ[key.decode()] = environment[key].decode()
    os.environ.setdefault('DISPLAY', ':0')
    os.environ.setdefault('XAUTHORITY', str(home / '.Xauthority'))
    os.environ['WEBKIT_DISABLE_DMABUF_RENDERER'] = '1'
    os.environ['LIBGL_ALWAYS_SOFTWARE'] = 'true'
    log = (home / 'vatilume-validation/desktop-apps.txt').open('a')
    if args.step == 'menu':
        call(['xdg-settings', 'set', 'default-web-browser', 'org.gnome.Epiphany.desktop'])
        call(['xdg-mime', 'default', 'org.gnome.Epiphany.desktop', 'x-scheme-handler/http'])
        call(['xdg-mime', 'default', 'org.gnome.Epiphany.desktop', 'x-scheme-handler/https'])
        # The finder must originate in the real graphical login session. Starting
        # it over SSH with DISPLAY set would correctly fail the active-seat policy.
        call(['pgrep', '-u', str(account.pw_uid), '-x', 'xfce4-appfinder'])
        window = call(['xdotool', 'search', '--onlyvisible', '--class', 'xfce4-appfinder']).splitlines()[-1]
        call(['xdotool', 'windowactivate', '--sync', window])
        call(['xdotool', 'key', 'ctrl+a'])
        call(['xdotool', 'type', '--clearmodifiers', 'Vatilume'])
    elif args.step == 'select':
        call(['xdotool', 'key', 'Return'])
    elif args.step == 'authorize':
        # Only the disposable guest password is typed; never read host credentials.
        deadline = time.monotonic() + 30
        while True:
            result = subprocess.run(['xdotool', 'search', '--onlyvisible', '--name', '^Authenticate$'], text=True, stdout=subprocess.PIPE)
            if result.returncode == 0 and result.stdout.strip():
                call(['xdotool', 'windowactivate', '--sync', result.stdout.splitlines()[-1]])
                break
            if time.monotonic() >= deadline:
                raise TimeoutError('No polkit authentication dialog; no password typed')
            time.sleep(1)
        call(['xdotool', 'type', '--clearmodifiers', '--file', str(password_path)])
        call(['xdotool', 'key', 'Return'])
    elif args.step == 'reopen':
        subprocess.Popen(['/usr/bin/vatilume'], stdout=log, stderr=log, start_new_session=True)
    time.sleep(2)
    screenshot = home / 'vatilume-validation' / (args.step + '.png')
    call(['import', '-window', 'root', str(screenshot)])
    print(json.dumps({'desktop_step': args.step, 'screenshot': str(screenshot),
                      'default_browser': call(['xdg-settings', 'get', 'default-web-browser'])}))


if __name__ == '__main__':
    main()
