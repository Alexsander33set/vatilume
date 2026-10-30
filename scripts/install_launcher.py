#!/usr/bin/env python3
"""Install this user's terminal launcher without modifying shell startup files."""
from __future__ import annotations

import argparse
import os
import shlex
import stat
import tempfile
from pathlib import Path

MARKER = '# Managed by device-observability/scripts/install_launcher.py'
COMMAND = 'vatilume'


def install(home: Path, project: Path):
    directory = home / '.local/bin'
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / COMMAND
    if destination.is_symlink():
        raise ValueError(f'{destination} já é um link existente; não foi substituído.')
    if destination.exists():
        info = destination.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or MARKER not in destination.read_text():
            raise ValueError(f'{destination} já existe e não pertence a este instalador; não foi substituído.')
    script = project.resolve() / 'scripts/open_interface.py'
    if not script.is_file():
        raise ValueError('Lançador da interface não encontrado neste projeto.')
    content = f'#!/bin/sh\n{MARKER}\nexec /usr/bin/python3 {shlex.quote(str(script))} "$@"\n'
    fd, name = tempfile.mkstemp(prefix='.' + COMMAND + '-', dir=directory)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o755)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home(), help='Home directory of the launcher owner')
    args = parser.parse_args()
    if os.getuid() == 0:
        parser.error('Execute como o proprietário do desktop, sem sudo.')
    try:
        path = install(args.home, Path(__file__).resolve().parent.parent)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')
    print(f'Comando instalado: {path}')


if __name__ == '__main__':
    main()
