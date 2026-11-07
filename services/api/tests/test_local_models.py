import asyncio
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from stark.main import create_app, build_kernel
from stark.local_models import LocalModels, Pull, model_name
from stark.providers.ollama import OllamaProvider

@pytest.mark.parametrize('name', ['https://evil.test/model', 'evil.test/model', '../escape', 'foo:cloud', 'user/model/extra'])
def test_download_names_are_not_remote_addresses(name):
    with pytest.raises(ValueError): model_name(name)


def provider(handler):
    return OllamaProvider('http://127.0.0.1:11434', transport=httpx.MockTransport(handler))


def test_authenticated_selection_persists_without_agent_changes(settings):
    p = provider(lambda r: httpx.Response(200, json={'capabilities':['tools']}))
    with TestClient(create_app(settings, {'ollama':p})) as c:
        assert c.get('/api/models/local').status_code == 401
        c.headers['authorization'] = 'Bearer ' + settings.api_token
        assert c.get('/api/models/local').status_code == 200
        assert c.put('/api/models/local/selection', json={'agent':'jarvis','provider':'ollama','model':'test:latest'}).status_code == 200
        assert c.app.state.kernel.registry.get('jarvis').model.provider == 'ollama'
    k = build_kernel(settings, {'ollama':p})
    assert k.registry.get('jarvis').model.model == 'test:latest'
    assert k.registry.get('ultron').permission_level == 'observe'


async def test_download_verified_and_limit_enforced(settings):
    def handler(r):
        if r.url.path == '/api/show':
            return httpx.Response(200, json={'capabilities':['tools']})
        return httpx.Response(200, content=b'{"digest":"x","total":10,"completed":10}\n{"status":"success"}\n')
    p = provider(handler)
    service = LocalModels(build_kernel(settings, {'ollama':p}))
    job = service.start(Pull(model='test', license_reviewed=True, max_bytes=20))
    await service.tasks[job['id']]
    assert service.jobs[job['id']]['status'] == 'done'
    job = service.start(Pull(model='test', license_reviewed=True, max_bytes=5))
    await service.tasks[job['id']]
    assert service.jobs[job['id']]['status'] == 'failed'
    await service.close()


async def test_no_license_approval_and_incomplete_stream(settings):
    from fastapi import HTTPException
    p = provider(lambda r: httpx.Response(200, content=b'{"status":"pulling"}\n'))
    service = LocalModels(build_kernel(settings, {'ollama':p}))
    with pytest.raises(HTTPException): service.start(Pull(model='test'))
    job = service.start(Pull(model='test', license_reviewed=True))
    await service.tasks[job['id']]
    assert service.jobs[job['id']]['status'] == 'failed'

async def test_download_cancellation_and_shutdown(settings):
    entered = asyncio.Event()
    async def handler(r):
        entered.set()
        await asyncio.Event().wait()
    service = LocalModels(build_kernel(settings, {'ollama':provider(handler)}))
    job = service.start(Pull(model='test', license_reviewed=True))
    await entered.wait()
    await service.close()
    assert service.jobs[job['id']]['status'] == 'cancelled'

async def test_missing_local_provider_is_not_cloud_fallback(settings):
    from fastapi import HTTPException
    service = LocalModels(build_kernel(settings, {}))
    with pytest.raises(HTTPException) as exc:
        service.start(Pull(model='test', license_reviewed=True))
    assert exc.value.status_code == 409
