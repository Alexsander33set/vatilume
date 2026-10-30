"""Desktop entry point for the Debian package; collector stays independent."""
import os
import subprocess
import sys

from .deb_access import ACCESS
from .launcher import main as open_interface


def main():
    path = ACCESS / f'{os.getuid()}.url'
    flags = {'--help', '-h', '--version', '--check'}
    if not path.exists() and not flags.intersection(sys.argv[1:]):
        try:
            result = subprocess.run(['/usr/bin/pkexec', '/usr/lib/vatilume/grant-access'], check=False)
        except OSError:
            result = None
        if result is None or result.returncode:
            print('A abertura requer autorização de acesso ao histórico deste PC. Tente novamente pelo menu.', file=sys.stderr)
            return 1
    return open_interface(access_path=path)
