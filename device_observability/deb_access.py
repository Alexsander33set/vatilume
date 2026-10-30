"""Narrow root helper for a packaged installation, invoked through polkit.

No user paths or tokens are accepted as arguments. Only the authenticated caller
receives access to this PC's shared telemetry; this is not a multi-tenant server.
"""
from __future__ import annotations

import os
import pwd
import secrets
import stat
from pathlib import Path

ACCESS = Path('/var/lib/vatilume-access')
TOKEN = Path('/var/lib/device-observability/interface-token')
ACCOUNT = 'device-observability'


def caller_uid(environment):
    value = environment.get('PKEXEC_UID', '')
    if not value.isascii() or not value.isdecimal():
        raise ValueError('Abra o Vatilume pelo menu ou pelo comando vatilume, sem sudo.')
    uid = int(value)
    account = pwd.getpwuid(uid)
    if uid < 1000 or uid >= 65534 or account.pw_shell in ('/usr/sbin/nologin', '/bin/false'):
        raise ValueError('O acesso requer um usuário pessoal da sessão gráfica.')
    return uid, account.pw_gid


def private_token(path, expected_uid):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != expected_uid or info.st_mode & 0o077:
            raise ValueError('Arquivo de acesso do serviço inválido.')
        value = stream.read(257).strip()
    if not 32 <= len(value) <= 256 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in value):
        raise ValueError('Token de acesso inválido.')
    return value


def grant(uid, gid, token, directory=ACCESS):
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError('Diretório de acesso inválido.')
    temporary = directory / ('.grant-' + secrets.token_hex(16))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write('http://127.0.0.1:8765/#access=' + token + '\n')
            stream.flush()
            os.fchown(stream.fileno(), uid, gid)
            os.fsync(stream.fileno())
        os.replace(temporary, directory / f'{uid}.url')
        parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    import sys
    try:
        if os.geteuid() != 0 or len(sys.argv) != 1:
            raise ValueError('Este auxiliar aceita apenas a autorização do lançador.')
        uid, gid = caller_uid(os.environ)
        account = pwd.getpwnam(ACCOUNT)
        parent = TOKEN.parent.lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != account.pw_uid:
            raise ValueError('Diretório do serviço inválido.')
        grant(uid, gid, private_token(TOKEN, account.pw_uid))
        return 0
    except (OSError, KeyError, ValueError):
        # Do not include root file contents, tokens or uncontrolled error messages.
        print('Não foi possível autorizar o acesso local ao Vatilume. Verifique a instalação.', file=sys.stderr)
        return 1
