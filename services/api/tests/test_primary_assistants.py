import pytest
from stark.core.addressing import parse_address
from stark.core.memory import MemoryAccessError
from stark.core.db import TASK_BRAND
from stark.core.runtime import ToolContext
from .conftest import make_kernel, tool, text, n_tool_rounds


def test_primary_parity_and_specialist_restrictions(settings):
    k, _ = make_kernel(settings)
    vision, wanda = k.registry.get('vision'), k.registry.get('wanda')
    assert vision.tools == wanda.tools
    assert vision.permission_level == wanda.permission_level == 'assist'
    assert vision.voice.preferred_voices != wanda.voice.preferred_voices
    assert vision.color != wanda.color
    assert 'wanda' in vision.delegation.can_delegate_to and 'vision' in wanda.delegation.can_delegate_to
    assert k.registry.get('ultron').permission_level == 'observe'
    assert 'social.publish' not in k.registry.get('jarvis').tools
    assert parse_address('Hey Vision, open my project') == ('vision','open my project')
    assert parse_address('Hey Wanda, help me write') == ('wanda','help me write')


async def test_real_kernel_primary_collaboration_and_history_isolation(settings):
    def brain(agent, request):
        if agent == 'vision' and n_tool_rounds(request) == 0:
            return [tool('agent.delegate', {'agent_id':'wanda','instruction':'Suggest a title'})]
        return [text('A useful title' if agent == 'wanda' else 'Wanda completed the title task.')]
    k, provider = make_kernel(settings, brain)
    task = k.submit_chat('vision','Ask Wanda for a title')
    from .conftest import wait_for
    from sqlalchemy import select
    from stark.core.db import Approval
    def pending():
        with k.db.session() as session:
            return session.scalar(select(Approval).where(Approval.status == 'pending'))
    approval = await wait_for(pending)
    assert approval.tool_id == 'agent.delegate'
    k.approvals.decide(approval.id, 'approved')
    result = await k.wait(task['id'], timeout=5)
    assert result['status'] == 'completed'
    assert {'vision','wanda'} <= {agent for agent, _ in provider.requests}
    later = k.submit_chat('wanda','Fresh personal conversation',conversation_id=task['conversation_id'])
    assert later['conversation_id'] != task['conversation_id']
    await k.wait(later['id'],timeout=5)


def test_personal_memory_requires_consent_and_stays_out_of_brand(settings):
    k, _ = make_kernel(settings)
    vision, wanda = k.registry.get('vision'), k.registry.get('wanda')
    with pytest.raises(MemoryAccessError):
        k.memory.save(actor=vision,namespace='personal:vision',layer='preference',content='Private astronomy preference')
    k.memory.save(actor=vision,namespace='personal:vision',layer='preference',content='Private astronomy preference',consent=True)
    assert k.memory.search(actor=vision,query='astronomy')
    assert not k.memory.search(actor=wanda,query='astronomy')
    assert not k.memory.search(actor=k.registry.get('jarvis'),query='astronomy')
    token = TASK_BRAND.set({'name':'Example Brand'})
    try:
        assert not k.memory.search(actor=vision,query='astronomy')
        with pytest.raises(MemoryAccessError):
            k.memory.save(actor=vision,namespace=vision.private_namespace,layer='agent',content='Private note',consent=True)
    finally:
        TASK_BRAND.reset(token)


def test_primary_preference_tool_needs_approval(settings):
    k, _ = make_kernel(settings)
    agent = k.registry.get('vision')
    ctx = ToolContext(kernel=k, agent=agent, task_id='test',root_id='test',settings=settings)
    save = k.tools.get('memory.save')
    args = save.Input(content='Remember my preference',layer='preference')
    assert save.needs_approval(args,ctx)
    assert save.describe(args,ctx).target == 'personal:vision'


def test_owner_handoff_sends_only_approved_context(settings):
    from fastapi.testclient import TestClient
    from stark.main import create_app
    from .conftest import ScriptedProvider
    provider = ScriptedProvider(lambda *_: [text('Acknowledged.')])
    with TestClient(create_app(settings, {'openrouter':provider})) as c:
        c.headers['authorization'] = 'Bearer '+settings.api_token
        source = c.post('/api/chat',json={'agent_id':'vision','message':'private-source-astronomy'}).json()
        result = c.post('/api/conversations/'+source['conversation_id']+'/handoff',json={'agent_id':'wanda','context':'Approved short summary'})
        assert result.status_code == 200
        handoff = result.json()
        assert handoff['conversation_id'] != source['conversation_id']
        assert handoff['instruction'] == 'Approved short summary'
        k=c.app.state.kernel
        assert k._history(handoff['conversation_id'],handoff['id']) == []


async def test_rejected_primary_delegation_never_calls_recipient(settings):
    from .conftest import wait_for
    from sqlalchemy import select
    from stark.core.db import Approval
    def brain(agent, request):
        if n_tool_rounds(request) == 0:
            return [tool('agent.delegate', {'agent_id':'wanda','instruction':'Do not share without consent'})]
        return [text('The delegation was not approved.')]
    k, provider = make_kernel(settings, brain)
    task = k.submit_chat('vision','Prepare a task')
    def pending():
        with k.db.session() as session:
            return session.scalar(select(Approval).where(Approval.status == 'pending'))
    approval = await wait_for(pending)
    k.approvals.decide(approval.id,'rejected')
    await k.wait(task['id'],timeout=5)
    assert {agent for agent, _ in provider.requests} == {'vision'}
