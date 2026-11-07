import json
import httpx
import pytest
from stark.providers.ollama import OllamaProvider
from stark.providers.base import ModelRequest, ProviderError

@pytest.mark.parametrize('url', ['https://ollama.com', 'http://localhost:11434', 'http://10.0.0.1', 'http://127.0.0.1@evil.test', 'http://127.0.0.1/api'])
def test_refuses_nonliteral_or_remote_endpoints(url):
    with pytest.raises(ValueError):
        OllamaProvider(url)

async def test_local_chat_and_tool_response():
    calls = []
    def handle(req):
        calls.append(str(req.url))
        assert req.url.host == '127.0.0.1'
        if req.url.path == '/api/show':
            return httpx.Response(200, json={'capabilities': ['tools']})
        body = json.loads(req.content)
        assert body['model'] == 'local:latest'
        return httpx.Response(200, json={'choices': [{'message': {'content': 'Offline answer'}, 'finish_reason': 'stop'}]})
    p = OllamaProvider('http://127.0.0.1:11434', transport=httpx.MockTransport(handle))
    result = await p.complete(ModelRequest('local:latest', 'System', [{'role': 'user', 'content': 'Hello'}]))
    assert result.text == 'Offline answer' and len(calls) == 2

async def test_remote_model_and_redirect_refused():
    for status, data in [(200, {'remote_host': 'ollama.com'}), (302, {})]:
        p = OllamaProvider('http://127.0.0.1:11434', transport=httpx.MockTransport(lambda r: httpx.Response(status, json=data, headers={'location': 'https://ollama.com'})))
        with pytest.raises(ProviderError):
            await p.inspect_model('model:latest')

async def test_tool_incompatible_model_refused():
    p = OllamaProvider('http://127.0.0.1:11434', transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    with pytest.raises(ProviderError, match='tool support'):
        await p.complete(ModelRequest('local', 'System', [], tools=[{'name':'test'}]))

async def test_real_installed_local_model_opt_in():
    """No downloads. Run explicitly against a disposable, cloud-disabled Ollama server."""
    import os
    url = os.environ.get('STARK_TEST_OLLAMA_URL')
    model = os.environ.get('STARK_TEST_OLLAMA_MODEL')
    if not url or not model:
        pytest.skip('requires an explicitly configured local Ollama acceptance server and installed model')
    p = OllamaProvider(url, model)
    assert (await p.health())[0]
    result = await p.complete(ModelRequest(model, 'Answer briefly. /no_think',
        [{'role':'user','content':'What is two plus two? Reply with the number only. /no_think'}], max_tokens=128, temperature=0))
    assert '4' in result.text and result.provider == 'ollama'
    tools = [{'name':'local_test_answer','description':'Return the requested numeric answer',
              'input_schema':{'type':'object','properties':{'answer':{'type':'integer'}},'required':['answer']}}]
    result = await p.complete(ModelRequest(model, 'Use local_test_answer to answer. /no_think',
        [{'role':'user','content':'Use the tool with answer 4. /no_think'}], tools=tools, max_tokens=256, temperature=0))
    assert any(c['name']=='local_test_answer' and c['input'].get('answer')==4 for c in result.tool_calls)
