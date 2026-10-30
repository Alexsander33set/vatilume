#!/usr/bin/env python3
"""Download pinned, public local evaluation assets; no system installation."""
import argparse
import fcntl
import hashlib
import json
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = [
    dict(name='llama-b11968-bin-ubuntu-x64.tar.gz',
         url='https://github.com/ggml-org/llama.cpp/releases/download/b11968/llama-b11968-bin-ubuntu-x64.tar.gz',
         sha256='6f9e44cafe6d185e993741de35e2b24a2333132f980dadb378b09ded78a19f2f'),
    dict(name='Qwen3-4B-Q4_K_M.gguf',
         url='https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/bc640142c66e1fdd12af0bd68f40445458f3869b/Qwen3-4B-Q4_K_M.gguf',
         sha256='7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5'),
    dict(name='Qwen3-8B-Q4_K_M.gguf',
         url='https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/7c41481f57cb95916b40956ab2f0b139b296d974/Qwen3-8B-Q4_K_M.gguf',
         sha256='d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785'),
]
VULKAN = dict(name='llama-b11968-bin-ubuntu-vulkan-x64.tar.gz',
              url='https://github.com/ggml-org/llama.cpp/releases/download/b11968/llama-b11968-bin-ubuntu-vulkan-x64.tar.gz',
              sha256='1995045eec05c222004ea7170cf24ba9e2e57ebe69bf137f72045ecccbe4a02c')
EXTRA_MODELS = {
    'qwen35-4b': dict(name='Qwen3.5-4B-Q4_K_M.gguf',
        url='https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/e87f176479d0855a907a41277aca2f8ee7a09523/Qwen3.5-4B-Q4_K_M.gguf',
        sha256='00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4'),
    'gemma3-4b': dict(name='gemma-3-4b-it-Q4_K_M.gguf',
        url='https://huggingface.co/ggml-org/gemma-3-4b-it-GGUF/resolve/d0976223747697cb51e056d85c532013931fe52e/gemma-3-4b-it-Q4_K_M.gguf',
        sha256='882e8d2db44dc554fb0ea5077cb7e4bc49e7342a1f0da57901c0802ea21a0863'),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=['4b', '8b', 'both', *EXTRA_MODELS], default='both')
    parser.add_argument('--backend', choices=['cpu', 'vulkan'], default='cpu')
    args = parser.parse_args()
    directory = ROOT / 'var/ai/assets'
    directory.mkdir(parents=True, exist_ok=True)
    lock = (directory.parent / 'runtime.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    runtime_asset = VULKAN if args.backend == 'vulkan' else ASSETS[0]
    models = [EXTRA_MODELS[args.model]] if args.model in EXTRA_MODELS else [a for a in ASSETS[1:] if args.model == 'both' or f'Qwen3-{args.model[0]}B-' in a['name']]
    selected = [runtime_asset, *models]
    for asset in selected:
        path = directory / asset['name']
        if not path.exists():
            temporary = path.with_suffix(path.suffix + '.part')
            print('Downloading ' + asset['name'], flush=True)
            subprocess.run(['curl', '--fail', '--location', '--retry', '3', '--silent', '--show-error',
                            '--continue-at', '-', '--output', str(temporary), asset['url']], check=True)
            temporary.rename(path)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != asset['sha256']:
            raise ValueError('Hash mismatch: ' + path.name)
        print('Verified ' + asset['name'], flush=True)
        if asset is runtime_asset:
            runtime = directory.parent / ('runtime-vulkan' if args.backend == 'vulkan' else 'runtime')
            runtime.mkdir(exist_ok=True)
            with tarfile.open(path) as archive:
                archive.extractall(runtime, filter='data')
    (directory.parent / 'assets.json').write_text(json.dumps(selected, indent=2) + '\n')


if __name__ == '__main__':
    main()
