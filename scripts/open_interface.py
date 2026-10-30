#!/usr/bin/env python3
"""Compatibility entry point for open-ui.sh and the user's vatilume command."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from device_observability.launcher import main

if __name__ == '__main__':
    sys.exit(main(access_path=ROOT / 'var/interface-access.url'))
