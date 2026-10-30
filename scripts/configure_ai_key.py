#!/usr/bin/env python3
"""Store the evaluation-only API key locally without echo or shell history."""
import getpass
import os
from pathlib import Path

directory = Path(__file__).resolve().parent.parent / 'var/ai'
directory.mkdir(parents=True, exist_ok=True)
key = getpass.getpass('Chave da API OpenAI (entrada oculta): ').strip()
if not key or any(c.isspace() for c in key):
    raise SystemExit('Chave vazia ou com espaços; nada foi salvo.')
path = directory / 'openai-api-key'
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
os.fchmod(fd, 0o600)
with os.fdopen(fd, 'w') as stream:
    stream.write(key)
    stream.flush()
    os.fsync(stream.fileno())
print('Chave salva somente neste PC, em arquivo privado ignorado pelo projeto. Nenhuma chamada foi feita.')
