#!/usr/bin/env python3
"""Check Git-index contents, never dump secret values or inspect private history.

This lightweight guard is complementary to a dedicated secret scanner. It reads
only tracked/staged blobs. Local capability/API-key files, if readable, are used
only for exact-match detection and their contents are never printed.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlparse

ROOT=Path(__file__).resolve().parent.parent
BLOCKED_PARTS={'.git','.aws','.codex','.agents','node_modules','.venv','__pycache__'}
BLOCKED_NAMES={'interface-access.url','interface-token','openai-api-key','ai-api-key','ai-budget.json','budget.json','health.json','.env'}
PATTERNS=[
    ('OpenAI credential',re.compile(rb'(?<![A-Za-z0-9_])sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}')),
    ('GitHub credential',re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,})')),
    ('private key',re.compile(rb'-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----')),
    ('credential in URL',re.compile(rb'https?://[^\s/:]+:[^\s/@]+@')),
]


def findings(path,content,known_secrets=()):
    pure=PurePosixPath(path)
    if (set(pure.parts)&BLOCKED_PARTS or pure.parts[0]=='var'
        or pure.name in BLOCKED_NAMES or pure.name.startswith('.env.') and pure.name!='.env.example'
        or re.search(r'\.(?:sqlite3?|db)(?:-.*)?$',pure.name)
        or pure.suffix in {'.gguf','.safetensors','.pem','.key','.log','.zip'}
        or path.startswith(('docs/validation/','docs/commercial/','backend/static/','scripts/wheels/','frontend/test-results/','frontend/playwright-report/'))):
        return ['private or generated path']
    reasons=[]
    if len(content)>1024*1024:reasons.append('unexpected file above 1 MiB')
    reasons.extend(label for label,pattern in PATTERNS if pattern.search(content))
    if any(secret and secret in content for secret in known_secrets):reasons.append('local credential/capability value')
    return reasons


def local_secrets():
    values=[]
    path=ROOT/'var/ai/openai-api-key'
    if path.is_file():
        try:values.append(path.read_bytes().strip())
        except PermissionError:pass
    path=ROOT/'var/interface-access.url'
    if path.is_file():
        try:
            url=urlparse(path.read_text().strip())
            values.extend(value.encode() for value in parse_qs(url.fragment).get('access',[]))
        except (PermissionError,ValueError):pass
    return [value for value in values if len(value)>=10]


def main():
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    secrets=local_secrets();failures=[];count=size=0
    for path in filter(None,paths):
        content=subprocess.check_output(['git','show',':'+path],cwd=ROOT)
        count+=1;size+=len(content)
        reasons=findings(path,content,secrets)
        if reasons:failures.append({'path':path,'reasons':reasons})
    if not count:raise ValueError('No indexed source files to check')
    print(json.dumps({'repository_check':'failed' if failures else 'passed','files':count,'bytes':size,
        'findings':failures,'scope':'Git index; lightweight patterns and readable local credential values, not a full security audit'},indent=2))
    return bool(failures)


if __name__=='__main__':sys.exit(main())
