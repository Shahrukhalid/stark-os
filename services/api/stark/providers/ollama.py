"""Opt-in loopback Ollama adapter. Never falls back to a cloud provider."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

import httpx

from .base import ModelRequest, ProviderError
from .openai_compat import OpenAICompatProvider


class OllamaProvider(OpenAICompatProvider):
    def __init__(self, base_url: str, model: str = '', *, transport=None):
        url = urlsplit(base_url)
        try:
            local = ipaddress.ip_address(url.hostname or '').is_loopback
        except ValueError:
            local = False
        if url.scheme != 'http' or not local or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
            raise ValueError('Ollama must use a literal loopback HTTP address, e.g. http://127.0.0.1:11434')
        self.root = base_url.rstrip('/')
        self.default_model = model
        super().__init__('ollama', self.root + '/v1', transport=transport, timeout_s=180)

    def _client(self):
        return httpx.AsyncClient(timeout=httpx.Timeout(180, connect=3), transport=self._transport,
                                 trust_env=False, follow_redirects=False)

    async def _json(self, method, path, body=None):
        try:
            async with self._client() as client:
                async with client.stream(method, self.root + path, json=body) as response:
                    if response.status_code != 200:
                        raise ProviderError(f'Ollama HTTP {response.status_code}', status=response.status_code)
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 4 * 1024 * 1024:
                            raise ProviderError('Ollama response exceeds 4 MiB')
            import json
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get('error'):
                raise ProviderError('Ollama returned an error or invalid response')
            return data
        except (httpx.HTTPError, ValueError):
            raise ProviderError('Local Ollama is unavailable or returned invalid JSON') from None

    async def health(self):
        try:
            await self._json('GET', '/api/tags')
            return True, 'Local Ollama reachable'
        except ProviderError:
            return False, 'Local Ollama unavailable'

    async def list_models(self):
        data = await self._json('GET', '/api/tags')
        return [m['name'] for m in data.get('models', []) if isinstance(m, dict) and isinstance(m.get('name'), str)]

    async def inspect_model(self, model):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', model) or 'cloud' in model.lower():
            raise ProviderError('Choose an installed local model')
        data = await self._json('POST', '/api/show', {'model': model})
        if data.get('remote_model') or data.get('remote_host'):
            raise ProviderError('Cloud-backed Ollama models are disabled')
        return data

    async def complete(self, request: ModelRequest):
        from .openai_compat import to_openai_messages, to_openai_tools, from_openai_response
        info = await self.inspect_model(request.model)
        if request.tools and 'tools' not in info.get('capabilities', []):
            raise ProviderError('The selected local model does not advertise tool support')
        body = {'model': request.model, 'messages': to_openai_messages(request.system, request.messages),
                'stream': False, 'max_tokens': request.max_tokens, 'temperature': request.temperature}
        if request.tools:
            body['tools'] = to_openai_tools(request.tools)
        return from_openai_response(await self._json('POST', '/v1/chat/completions', body), self.name, request.model)
