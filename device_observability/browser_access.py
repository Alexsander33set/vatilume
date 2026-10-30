"""Open a private redirect file, never a credential-bearing process argument.

The HTTP handler is used explicitly: the user's HTML editor association must not
receive the credential file. These imports and files exist only at UI launch.
"""
from __future__ import annotations

import html
import os
import secrets
import stat
from pathlib import Path


def private_directory(path, *, create=False):
    if create:
        try: path.mkdir(mode=0o700)
        except FileExistsError: pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('O diretório de abertura precisa pertencer ao seu usuário e ser privado (0700).')
    return path


def redirect_directory(browser_hint='', *, runtime=None, home=None):
    # Snap browser confinement may reject arbitrary /run/user paths. Its own
    # private common directory is readable by that browser and the desktop owner.
    home = Path(home) if home else Path.home()
    hint = browser_hint.casefold()
    for browser in ('firefox', 'chromium'):
        if browser in hint and Path('/snap/bin/' + browser).exists():
            directory = home / 'snap' / browser / 'common'
            if not directory.is_dir():
                raise ValueError('Abra seu navegador uma vez para preparar seu perfil e tente novamente.')
            for parent in (home / 'snap', directory.parent, directory):
                info = parent.lstat()
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
                    raise ValueError('O perfil do navegador precisa pertencer ao seu usuário e impedir escrita por outros.')
            return private_directory(directory / 'vatilume', create=True)
    base = Path(runtime) if runtime else Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
    return private_directory(private_directory(base) / 'vatilume', create=True)


def redirect_file(url, directory):
    private_directory(directory)
    escaped = html.escape(url, quote=True)
    document = ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
                '<meta name="referrer" content="no-referrer">'
                f'<meta http-equiv="refresh" content="0;url={escaped}">'
                '<title>Abrindo Vatilume</title></head><body>'
                f'<a href="{escaped}">Abrir Vatilume neste PC</a></body></html>')
    temporary = directory / ('.open-' + secrets.token_hex(16))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(document); stream.flush(); os.fsync(stream.fileno())
        destination = directory / 'open.html'
        os.replace(temporary, destination)
        return destination.as_uri()
    finally:
        temporary.unlink(missing_ok=True)


def default_browser():
    try:
        from gi.repository import Gio
        app = Gio.AppInfo.get_default_for_uri_scheme('http')
    except (ImportError, ValueError):
        raise ValueError('O lançador precisa de python3-gi para abrir o navegador padrão com segurança.') from None
    if app is None:
        raise ValueError('Configure um navegador padrão para endereços HTTP e tente novamente.')
    return app


def open_private(url, browser=None):
    if browser:
        import webbrowser
        controller = webbrowser.get(browser)
        file_uri = redirect_file(url, redirect_directory(browser))
        return controller.open(file_uri, new=2)
    app = default_browser()
    hint = ' '.join((app.get_id() or '', app.get_executable() or ''))
    file_uri = redirect_file(url, redirect_directory(hint))
    try:
        return app.launch_uris([file_uri], None)
    except Exception:
        # A browser/desktop exception must not disclose file contents or tokens.
        raise ValueError('O desktop não conseguiu abrir o navegador padrão. Verifique sua sessão gráfica.') from None
