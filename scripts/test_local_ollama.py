"""Real Windows/macOS local inference acceptance on disposable runners.

Downloads one Apache-2.0 test model with an explicit 1 GiB budget, using the
application's model manager. Does not install a service or alter user settings.
"""
from __future__ import annotations
import argparse
import asyncio
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

from stark.config import REPO_ROOT, Settings
from stark.local_models import LocalModels, Pull
from stark.main import build_kernel
from stark.providers.ollama import OllamaProvider


async def prepare(url, root):
    provider = OllamaProvider(url, 'qwen3:0.6b')
    for _ in range(120):
        if (await provider.health())[0]:
            break
        await asyncio.sleep(0.5)
    else:
        raise RuntimeError('Test Ollama did not start')
    settings = Settings(api_token='synthetic-local-acceptance-token-0123456789',
                        database_url='sqlite:///' + str(root/'test.db'), data_dir=root/'data',
                        agents_dir=REPO_ROOT/'agents', workspace_roots=[root/'workspace'])
    service = LocalModels(build_kernel(settings, {'ollama':provider}))
    job = service.start(Pull(model='qwen3:0.6b', license_reviewed=True, max_bytes=1024**3))
    try:
        await service.tasks[job['id']]
        if service.jobs[job['id']]['status'] != 'done':
            raise RuntimeError('Test model transfer failed: ' + str(service.jobs[job['id']]))
        print('Real model download verified', flush=True)
    finally:
        await service.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ollama', required=True, type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='nexonic-local-acceptance-') as temp:
        root = Path(temp)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'OLLAMA_HOST':f'127.0.0.1:{port}', 'OLLAMA_MODELS':str(root/'models'),
               'OLLAMA_NO_CLOUD':'1', 'OLLAMA_NUM_PARALLEL':'1'}
        with (root/'server.log').open('wb') as log:
            proc = subprocess.Popen([str(args.ollama.resolve()), 'serve'], env=env, stdout=log, stderr=log)
            try:
                asyncio.run(prepare(url, root))
                test_env = {**os.environ, 'STARK_TEST_OLLAMA_URL':url, 'STARK_TEST_OLLAMA_MODEL':'qwen3:0.6b'}
                subprocess.run([sys.executable, '-m', 'pytest',
                    'services/api/tests/test_ollama.py::test_real_installed_local_model_opt_in', '-q'],
                    env=test_env, check=True, timeout=180)
            except Exception:
                print((root/'server.log').read_text(errors='replace')[-4000:])
                raise
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

if __name__ == '__main__':
    main()
