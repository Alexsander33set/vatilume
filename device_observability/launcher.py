"""Open the owner's private UI in the desktop browser without printing its URL."""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from . import __version__
from .browser_access import open_private

APP_NAME = 'Vatilume'


def read_access(path: Path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('O arquivo de acesso precisa pertencer ao seu usuário e ser privado (0600). Execute o lançador sem sudo.')
    if info.st_size > 4096:
        raise ValueError('Arquivo de acesso local inválido.')
    url = path.read_text().strip()
    parsed = urllib.parse.urlparse(url)
    values = urllib.parse.parse_qs(parsed.fragment)
    if (parsed.scheme != 'http' or parsed.netloc != '127.0.0.1:8765' or parsed.path != '/'
            or parsed.params or parsed.query or set(values) != {'access'}
            or len(values['access']) != 1 or not values['access'][0]):
        raise ValueError('Endereço de acesso local inválido. Reinstale a interface.')
    return url


def main(argv=None, *, access_path=None):
    parser = argparse.ArgumentParser(prog='vatilume', description='Vatilume · Energia e sinais do seu PC. Abre a interface local no navegador.')
    parser.add_argument('--browser', help='Navegador registrado, por exemplo firefox; padrão: navegador do desktop.')
    parser.add_argument('--check', action='store_true', help='Verificar arquivo privado e disponibilidade da interface, sem abrir o navegador.')
    parser.add_argument('--version', action='version', version=f'{APP_NAME} {__version__}')
    args = parser.parse_args(argv)
    path = access_path or Path(__file__).resolve().parent.parent / 'var/interface-access.url'
    try:
        url = read_access(path)
        if args.check:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open('http://127.0.0.1:8765/', timeout=5) as response:
                if response.status != 200:
                    raise ValueError('A interface local não respondeu corretamente.')
            print(json.dumps({'application': APP_NAME, 'launcher': 'ready', 'interface_reachable': True,
                              'address': 'http://127.0.0.1:8765'}, ensure_ascii=False))
            return 0
        try:
            opened = open_private(url, args.browser)
        except (webbrowser.Error, OSError, ValueError):
            raise ValueError('Não foi possível abrir o navegador. Verifique a sessão gráfica ou o nome passado em --browser.') from None
        if not opened:
            raise ValueError('Não foi possível abrir o navegador. Execute vatilume na sessão gráfica deste PC ou escolha --browser firefox, se instalado.')
        return 0
    except FileNotFoundError:
        print('O acesso à interface ainda não foi instalado. Consulte docs/INTERFACE.md.', file=sys.stderr)
    except (OSError, ValueError, webbrowser.Error) as error:
        # Never print browser/provider exceptions, which might contain the private URL.
        message = str(error) if type(error) is ValueError else 'Não foi possível abrir ou verificar a interface local. Consulte docs/INTERFACE.md.'
        print(message, file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
