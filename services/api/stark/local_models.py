"""Owner-only local model management, sharing the existing kernel and audit trail."""
from __future__ import annotations

import asyncio
import json
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .providers.base import ProviderError
from .providers.ollama import OllamaProvider


def model_name(value: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)?(?::[A-Za-z0-9._-]+)?', value) or 'cloud' in value.lower():
        raise ValueError('Use a local Ollama model name, without a registry hostname or cloud tag')
    return value


class Selection(BaseModel):
    agent: str
    provider: str
    model: str = Field(min_length=1, max_length=200)
    allow_cloud_fallback: bool = False
    cloud_fallback_model: str | None = Field(default=None, max_length=200)


class Pull(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    license_reviewed: bool = False
    max_bytes: int = Field(default=4 * 1024**3, ge=1, le=16 * 1024**3)


class LocalModels:
    def __init__(self, kernel):
        self.k = kernel
        self.jobs = {}
        self.tasks = {}

    def provider(self):
        p = self.k.router.providers.get('ollama')
        if not isinstance(p, OllamaProvider):
            raise HTTPException(409, 'Configure STARK_OLLAMA_URL and restart to enable local models')
        return p

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def start(self, body: Pull):
        p = self.provider()
        try:
            model_name(body.model)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        if not body.license_reviewed:
            raise HTTPException(400, 'Review the model license before requesting a download')
        if any(not t.done() for t in self.tasks.values()):
            raise HTTPException(409, 'One model download is already active')
        # Keep bounded history without evicting running work.
        while len(self.jobs) >= 20:
            old = next(iter(self.jobs))
            self.jobs.pop(old)
            self.tasks.pop(old, None)
        ident = uuid.uuid4().hex
        self.jobs[ident] = dict(id=ident, model=body.model, status='queued', completed=0, total=0)
        self.tasks[ident] = asyncio.create_task(self._pull(p, ident, body))
        self.k.obs.audit('user', 'models.local.download', 'requested', detail={'model': body.model})
        return dict(self.jobs[ident])

    async def _pull(self, provider, ident, body):
        job = self.jobs[ident]
        job['status'] = 'downloading'
        totals = {}
        completed = {}
        try:
            async with asyncio.timeout(1800):
                async with provider._client() as client:
                    async with client.stream('POST', provider.root + '/api/pull', json={'model': body.model, 'stream': True}) as response:
                        if response.status_code != 200:
                            raise ProviderError('Local model download request failed')
                        pending = bytearray()
                        count = 0
                        async for chunk in response.aiter_bytes():
                            pending.extend(chunk)
                            if len(pending) > 65536:
                                raise ProviderError('Invalid model progress response')
                            while b'\n' in pending:
                                line, _, rest = pending.partition(b'\n')
                                pending = bytearray(rest)
                                if not line.strip():
                                    continue
                                count += 1
                                if count > 100000:
                                    raise ProviderError('Too many model progress events')
                                event = json.loads(line)
                                if not isinstance(event, dict) or event.get('error'):
                                    raise ProviderError('Ollama rejected the model download')
                                digest = event.get('digest')
                                if digest:
                                    if not isinstance(digest, str) or len(digest) > 200 or len(totals) > 100:
                                        raise ProviderError('Invalid model layer information')
                                    total = event.get('total', 0)
                                    done = event.get('completed', 0)
                                    if not isinstance(total, int) or not isinstance(done, int) or not 0 <= done <= total:
                                        raise ProviderError('Invalid model size information')
                                    totals[digest] = total
                                    completed[digest] = done
                                    if sum(totals.values()) > body.max_bytes:
                                        raise ProviderError('Model exceeds the approved download limit')
                                    job.update(total=sum(totals.values()), completed=sum(completed.values()))
                                if event.get('status') == 'success':
                                    job['status'] = 'verifying'
                        if pending.strip() or job['status'] != 'verifying':
                            raise ProviderError('Model download ended before verified success')
                await provider.inspect_model(body.model)
                job['status'] = 'done'
        except asyncio.CancelledError:
            job['status'] = 'cancelled'
        except Exception:
            job.update(status='failed', error='Download failed, exceeded its limit, or could not be verified. Check local Ollama.')
        finally:
            self.k.obs.audit('user', 'models.local.download', job['status'], detail={'model': body.model})
            self.k.bus.publish('model.local.download', dict(job))

    def router(self, auth):
        r = APIRouter(prefix='/api/models/local', dependencies=[Depends(auth)])

        @r.get('')
        async def status():
            p = self.k.router.providers.get('ollama')
            available = isinstance(p, OllamaProvider)
            models, error = [], None
            if available:
                try:
                    models = await p.list_models()
                except ProviderError:
                    error = 'Local Ollama is unavailable'
            return {'enabled': available, 'models': models, 'error': error,
                    'jobs': list(self.jobs.values()), 'agents': [
                        {'id': a.id, 'name': a.name, 'provider': a.model.provider or self.k.router.settings.default_provider,
                         'model': a.model.model or '', 'allow_cloud_fallback':a.model.allow_cloud_fallback,
                         'cloud_fallback_model':a.model.cloud_fallback_model} for a in self.k.registry.all()]}

        @r.put('/selection')
        async def select(body: Selection):
            if body.agent not in self.k.registry:
                raise HTTPException(404, 'Unknown agent')
            if body.provider not in self.k.router.providers:
                raise HTTPException(400, 'Unknown provider')
            if body.provider == 'ollama':
                try:
                    await self.provider().inspect_model(body.model)
                except ProviderError as exc:
                    raise HTTPException(400, str(exc)) from None
            elif body.provider != 'openrouter':
                raise HTTPException(400, 'Unsupported provider selection')
            if body.allow_cloud_fallback and (body.provider != 'ollama' or not body.cloud_fallback_model or not (
                    body.cloud_fallback_model.endswith(':free') or body.cloud_fallback_model == 'openrouter/free')):
                raise HTTPException(400, 'Cloud fallback requires explicit selection of a free OpenRouter model')
            agent = self.k.registry.get(body.agent)
            overrides = self.k.db.get_setting('agent_model_overrides', {})
            overrides[body.agent] = {'provider': body.provider, 'model': body.model,
                                     'allow_cloud_fallback':body.allow_cloud_fallback,
                                     'cloud_fallback_model':body.cloud_fallback_model if body.allow_cloud_fallback else None}
            self.k.db.set_setting('agent_model_overrides', overrides)
            agent.model.provider, agent.model.model = body.provider, body.model
            agent.model.allow_cloud_fallback = body.allow_cloud_fallback
            agent.model.cloud_fallback_model = body.cloud_fallback_model if body.allow_cloud_fallback else None
            self.k.obs.audit('user', 'models.selection', 'saved', detail={'agent': body.agent, 'provider': body.provider})
            return {'ok': True}

        @r.post('/downloads')
        async def download(body: Pull):
            return self.start(body)

        @r.post('/downloads/{ident}/cancel')
        async def cancel(ident: str):
            task = self.tasks.get(ident)
            if task is None:
                raise HTTPException(404, 'Unknown download')
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                self.jobs[ident]['status'] = 'cancelled'
            return dict(self.jobs[ident])

        return r
