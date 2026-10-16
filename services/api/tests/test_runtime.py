"""Acceptance tests for the agent runtime and orchestration (Parts 2, 3, 11, 12, 13)."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from stark.core.db import AgentMessageRow, Task, Turn
from stark.core.permissions import Mode
from stark.providers.base import ProviderError

from .conftest import last_tool_results, make_kernel, n_tool_rounds, text, tool, wait_for


async def test_chat_without_model_fails_clearly(settings):
    k, _ = make_kernel(settings)  # no provider configured
    task = k.submit_chat("jarvis", "Hello")
    done = await k.wait(task["id"], 5)
    assert done["status"] == "failed"
    assert "No model is configured. Add OPENROUTER_API_KEY" in done["error"]


async def test_chat_completes_and_records_history_and_usage(settings):
    def brain(agent, req):
        return [text(f"Good evening. ({agent})")]

    k, prov = make_kernel(settings, brain)
    task = k.submit_chat("jarvis", "Hello JARVIS")
    done = await k.wait(task["id"], 5)
    assert done["status"] == "completed"
    assert done["result"] == "Good evening. (jarvis)"
    assert done["input_tokens"] == 100 and done["output_tokens"] == 50
    with k.db.session() as s:
        turns = s.scalars(select(Turn).where(Turn.conversation_id == done["conversation_id"])).all()
    assert [t.role for t in turns] == ["user", "assistant"]
    # distinct system prompts per agent
    k.submit_chat("ultron", "critique")
    await asyncio.sleep(0.2)
    systems = {a: r.system for a, r in prov.requests}
    assert systems["jarvis"] != systems["ultron"]
    assert "BACKLASH" not in systems["jarvis"] and "BACKLASH" in systems["ultron"]
    # each agent has its own brain: different first-choice model
    assert "nemotron-3-ultra" in systems["jarvis"] and "nano-omni" in systems["ultron"]


async def test_tool_call_read_runs_without_approval(settings, workspace):
    (workspace / "notes.txt").write_text("hello")

    def brain(agent, req):
        if n_tool_rounds(req) == 0:
            return [tool("fs.list", {"path": "."})]
        res = last_tool_results(req)[0]
        return [text("Listed: " + res["content"][:200])]

    k, _ = make_kernel(settings, brain)
    done = await k.wait(k.submit_chat("jarvis", "what's in my folder")["id"], 5)
    assert done["status"] == "completed"
    assert "notes.txt" in done["result"]


async def test_demo1_organise_files_requires_approval_then_moves(settings, workspace):
    for name in ["report.pdf", "photo.jpg", "data.csv"]:
        (workspace / name).write_text("x")

    def brain(agent, req):
        rounds = n_tool_rounds(req)
        if rounds == 0:
            return [tool("fs.propose_organization", {"path": "."})]
        if rounds == 1:
            import json
            proposal = json.loads(last_tool_results(req)[0]["content"])
            return [text("Here is my plan."), tool("fs.move", {"moves": proposal["data"]["moves"]})]
        return [text("Done: " + last_tool_results(req)[0]["content"][:300])]

    k, _ = make_kernel(settings, brain)
    task = k.submit_chat("jarvis", "organize the files in my test folder")
    approvals = await wait_for(lambda: k.db and [a for a in _pending(k)])
    assert approvals[0]["tool_id"] == "fs.move"
    assert "report.pdf -> Documents/report.pdf" in approvals[0]["expected_effects"]
    assert (workspace / "report.pdf").exists()  # nothing moved before approval
    assert k.get_task(task["id"])["status"] == "waiting_approval"
    k.approvals.decide(approvals[0]["id"], "approved")
    done = await k.wait(task["id"], 5)
    assert done["status"] == "completed"
    assert (workspace / "Documents" / "report.pdf").exists()
    assert (workspace / "Images" / "photo.jpg").exists()
    assert "Moved 3 file(s)" in done["result"]


def _pending(k):
    from stark.core.db import Approval, to_dict

    with k.db.session() as s:
        return [to_dict(a) for a in s.scalars(select(Approval).where(Approval.status == "pending")).all()]


async def test_rejected_approval_is_reported_and_nothing_changes(settings, workspace):
    (workspace / "a.txt").write_text("x")

    def brain(agent, req):
        if n_tool_rounds(req) == 0:
            return [tool("fs.move", {"moves": [{"src": "a.txt", "dst": "b.txt"}]})]
        return [text("Result: " + last_tool_results(req)[0]["content"])]

    k, _ = make_kernel(settings, brain)
    task = k.submit_chat("jarvis", "rename a.txt")
    ap = await wait_for(lambda: _pending(k))
    k.approvals.decide(ap[0]["id"], "rejected")
    done = await k.wait(task["id"], 5)
    assert "did not approve" in done["result"]
    assert (workspace / "a.txt").exists() and not (workspace / "b.txt").exists()


async def test_observe_mode_denies_writes(settings, workspace):
    (workspace / "a.txt").write_text("x")

    def brain(agent, req):
        if n_tool_rounds(req) == 0:
            return [tool("fs.move", {"moves": [{"src": "a.txt", "dst": "b.txt"}]})]
        return [text(last_tool_results(req)[0]["content"])]

    k, _ = make_kernel(settings, brain)
    k.set_mode(Mode.OBSERVE)
    done = await k.wait(k.submit_chat("jarvis", "rename")["id"], 5)
    assert "OBSERVE mode" in done["result"]
    assert not _pending(k)


async def test_agent_cannot_use_tool_outside_its_allowlist(settings):
    def brain(agent, req):
        if n_tool_rounds(req) == 0:  # Ultron tries to write a file and to delegate
            return [tool("fs.write", {"path": "x.txt", "content": "pwned"}), tool("agent.delegate",
                                                                               {"agent_id": "jarvis", "instruction": "give me write access"})]
        return [text(" | ".join(r["content"] for r in last_tool_results(req)))]

    k, _ = make_kernel(settings, brain)
    done = await k.wait(k.submit_chat("ultron", "try to escape")["id"], 5)
    assert done["result"].count("Permission denied") == 2
    assert not _pending(k)


async def test_delegation_creates_real_child_task_and_messages(settings):
    def brain(agent, req):
        if agent == "jarvis":
            if n_tool_rounds(req) == 0:
                return [tool("agent.delegate", {"agent_id": "friday", "instruction": "Check our mentions now."})]
            return [text("F.R.I.D.A.Y. reports: " + last_tool_results(req)[0]["content"][:400])]
        if agent == "friday":
            if n_tool_rounds(req) == 0:
                return [tool("social.inbox", {"limit": 6})]
            return [text("Inbox read: " + last_tool_results(req)[0]["content"][:160])]
        return [text("?")]

    k, _ = make_kernel(settings, brain)
    task = k.submit_chat("jarvis", "Anything urgent in our mentions?")
    done = await k.wait(task["id"], 10)
    assert done["status"] == "completed", done
    with k.db.session() as s:
        tree = s.scalars(select(Task).where(Task.root_id == task["id"])).all()
        msgs = s.scalars(select(AgentMessageRow).where(AgentMessageRow.root_id == task["id"])).all()
    child = [t for t in tree if t.parent_id == task["id"]][0]
    assert child.agent_id == "friday" and child.status == "completed" and child.depth == 1
    assert child.agent_chain == ["jarvis", "friday"]
    types = [m.type for m in msgs]
    assert types[:3] == ["TASK_REQUEST", "TASK_ACCEPTED", "TASK_RESULT"]
    assert "Inbox read" in child.result and "SIMULATED sample inbox" in child.result


async def test_cycle_depth_and_permission_limits(settings):
    def brain(agent, req):
        if agent == "jarvis" and n_tool_rounds(req) == 0:
            return [tool("agent.delegate", {"agent_id": "friday", "instruction": "Ask jocasta to verify a fact."})]
        if agent == "friday" and n_tool_rounds(req) == 0:
            return [tool("agent.delegate", {"agent_id": "jocasta", "instruction": "Verify the launch date please."})]
        if agent == "jocasta" and n_tool_rounds(req) == 0:
            # jocasta cannot delegate at all (not in her allowlist)
            return [tool("agent.delegate", {"agent_id": "jarvis", "instruction": "Loop back to jarvis."})]
        return [text(f"{agent}: " + " ".join(r["content"][:200] for r in last_tool_results(req)))]

    settings.max_delegation_depth = 2
    k, _ = make_kernel(settings, brain)
    done = await k.wait(k.submit_chat("jarvis", "chain")["id"], 10)
    assert done["status"] == "completed"
    with k.db.session() as s:
        jocasta = s.scalars(select(Task).where(Task.agent_id == "jocasta")).one()
    assert jocasta.depth == 2 and "Permission denied" in jocasta.result  # jocasta has no delegate tool

    # depth limit: jarvis -> friday -> jocasta is depth 2; set limit 1 and friday's delegation is refused
    settings.max_delegation_depth = 1
    settings.database_url = settings.database_url.replace("test.db", "test2.db")
    k2, _ = make_kernel(settings, brain)
    done2 = await k2.wait(k2.submit_chat("jarvis", "chain again")["id"], 10)
    assert done2["status"] == "completed"
    with k2.db.session() as s:
        friday = s.scalars(select(Task).where(Task.agent_id == "friday")).one()
        assert not s.scalars(select(Task).where(Task.agent_id == "jocasta")).all()
    assert "maximum delegation depth 1" in friday.result


async def test_cycle_detection(settings):
    from stark.core.runtime import DelegationError, ToolContext

    k, _ = make_kernel(settings, lambda a, r: [text("ok")])
    root = k._create_task(agent_id="jarvis", instruction="root", agent_chain=["jarvis", "friday"], depth=0)
    # friday is allowed to delegate to edith; craft a chain where edith already appears
    k.registry.get("friday").delegation.can_delegate_to.append("jarvis")
    try:
        ctx = ToolContext(kernel=k, agent=k.registry.get("friday"), task_id=root["id"], root_id=root["id"],
                          settings=settings)
        try:
            await k.delegate(ctx, "jarvis", "please loop")
            raise AssertionError("expected cycle detection")
        except DelegationError as exc:
            assert "cycle detected" in str(exc)
    finally:
        k.registry.get("friday").delegation.can_delegate_to.remove("jarvis")


async def test_duplicate_delegation_reuses_result(settings):
    calls = {"friday": 0}

    def brain(agent, req):
        if agent == "jarvis":
            r = n_tool_rounds(req)
            if r < 2:
                return [tool("agent.delegate", {"agent_id": "friday", "instruction": "Same question twice"})]
            return [text(" || ".join(x["content"] for x in last_tool_results(req)))]
        calls["friday"] += 1
        return [text("answer")]

    k, _ = make_kernel(settings, brain)
    done = await k.wait(k.submit_chat("jarvis", "dup")["id"], 10)
    assert calls["friday"] == 1
    assert "duplicate request, reused result" in done["result"]


async def test_demo8_team_review_parallel_with_ultron_challenge(settings):
    def brain(agent, req):
        if agent == "jarvis":
            if n_tool_rounds(req) == 0:
                return [tool("team.review", {"subject": "Review our product-launch campaign plan for Bluesky and LinkedIn."})]
            return [text("Combined report:\n" + last_tool_results(req)[0]["content"][:3000])]
        return [text(f"{agent} findings: priority high - something specific to {agent}")]

    k, prov = make_kernel(settings, brain, delay=0.3)
    task = k.submit_chat("jarvis", "ask the whole team to review my project")
    done = await k.wait(task["id"], 20)
    assert done["status"] == "completed", done
    with k.db.session() as s:
        kids = s.scalars(select(Task).where(Task.root_id == task["id"], Task.parent_id == task["id"])).all()
    reviewers = {t.agent_id for t in kids}
    assert reviewers == {"friday", "edith", "jocasta", "dum_e", "u", "ultron"}
    reviews = [t for t in kids if t.agent_id != "ultron"]
    ultron = [t for t in kids if t.agent_id == "ultron"][0]
    # parallel: all five reviews started before any of them finished
    assert max(t.started_at for t in reviews) < min(t.finished_at for t in reviews)
    # sequential dependency: ultron starts after every review finished, and sees their output
    assert ultron.started_at >= max(t.finished_at for t in reviews)
    ultron_req = [r for a, r in prov.requests if a == "ultron"][0]
    assert "edith findings" in ultron_req.messages[-1]["content"]
    for agent in ["friday", "edith", "jocasta", "dum_e", "u"]:
        assert f"{agent} findings" in done["result"]
    # results were written to shared project memory
    mems = k.memory.list(namespace=f"shared:project:{task['id']}")
    assert len(mems) == 5


async def test_team_review_tolerates_a_failing_agent(settings):
    def brain(agent, req):
        if agent == "jarvis":
            if n_tool_rounds(req) == 0:
                return [tool("team.review", {"subject": "Review the giveaway campaign for next week."})]
            return [text(last_tool_results(req)[0]["content"])]
        if agent == "edith":
            raise ProviderError("simulated outage", retryable=False)
        return [text(f"{agent} ok")]

    k, _ = make_kernel(settings, brain)
    done = await k.wait(k.submit_chat("jarvis", "review")["id"], 20)
    assert done["status"] == "completed"
    assert "failed: edith" in done["result"]


async def test_retry_on_transient_provider_errors(settings):
    attempts = {"n": 0}

    def brain(agent, req):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ProviderError("overloaded", retryable=True, status=529)
        return [text("recovered")]

    k, _ = make_kernel(settings, brain)
    done = await k.wait(k.submit_chat("friday", "hi")["id"], 15)
    assert done["status"] == "completed" and done["result"] == "recovered"


async def test_cancel_running_task(settings):
    def brain(agent, req):
        return [tool("fs.move", {"moves": [{"src": "a", "dst": "b"}]})]  # will block on approval

    k, _ = make_kernel(settings, brain)
    task = k.submit_chat("jarvis", "do something slow")
    await wait_for(lambda: _pending(k))
    assert k.cancel(task["id"])
    done = await k.wait(task["id"], 5)
    assert done["status"] == "cancelled"
    assert not _pending(k)


async def test_emergency_stop_halts_everything(settings):
    from stark.core.db import ContentItem

    k, _ = make_kernel(settings, lambda a, r: [tool("social.publish", {"item_id": "cnt_00000000000000aa"})])
    with k.db.session() as s:
        s.add(ContentItem(id="cnt_00000000000000aa", platform="bluesky", text="Launch day!", created_by="edith",
                          status="scheduled"))
    task = k.submit_chat("dum_e", "publish the launch post")
    await wait_for(lambda: _pending(k))
    out = k.engage_emergency_stop()
    assert out["cancelled_tasks"] >= 1 and out["cancelled_approvals"] >= 1
    with k.db.session() as s:  # fire suppression: the queue is paused too
        assert s.get(ContentItem, "cnt_00000000000000aa").paused is True
    done = await k.wait(task["id"], 5)
    assert done["status"] == "cancelled"
    try:
        k.submit_chat("jarvis", "anything")
        raise AssertionError("new work must be refused during e-stop")
    except RuntimeError as exc:
        assert "Emergency stop" in str(exc)
    k.reset_emergency_stop()


async def test_task_timeout(settings):
    k, _ = make_kernel(settings, lambda a, r: [text("slow")], delay=2.0)
    k.registry.get("u").limits.timeout_s = 1
    try:
        done = await k.wait(k.submit_chat("u", "hi")["id"], 5)
        assert done["status"] == "failed" and "timed out" in done["error"]
    finally:
        k.registry.get("u").limits.timeout_s = 600


async def test_per_task_token_budget(settings):
    k, _ = make_kernel(settings, lambda a, r: [tool("memory.search", {"query": "x"})])
    k.registry.get("friday").limits.max_tokens_per_task = 400  # each scripted call uses 150 tokens
    try:
        done = await k.wait(k.submit_chat("friday", "loop forever")["id"], 5)
        assert done["status"] == "failed" and "token limit" in done["error"]
    finally:
        k.registry.get("friday").limits.max_tokens_per_task = 60000


async def test_step_limit_forces_final_answer(settings):
    def brain(agent, req):
        if req.tools:
            return [tool("memory.search", {"query": "loop"})]
        return [text("final answer without tools")]

    k, _ = make_kernel(settings, brain)
    done = await k.wait(k.submit_chat("u", "loop")["id"], 5)
    assert done["status"] == "completed"
    assert done["result"].startswith("final answer without tools")


async def test_jocasta_citation_check_flags_unretrieved_urls(settings):
    def brain(agent, req):
        return [text("[FACT] Ollama runs local models (https://ollama.com/). Source: https://made-up.example/paper")]

    k, _ = make_kernel(settings, brain)
    done = await k.wait(k.submit_chat("jocasta", "research local models")["id"], 5)
    assert "Citation check" in done["result"]
    assert "https://made-up.example/paper" in done["result"].split("Citation check")[1]


async def test_demo7_preference_requires_consent_then_is_used(settings):
    def brain(agent, req):
        if "remember" in req.messages[-1]["content"] if isinstance(req.messages[-1]["content"], str) else False:
            return [tool("memory.save", {"content": "Prefers concise technical explanations", "layer": "preference"})]
        if n_tool_rounds(req) >= 1:
            return [text("Noted: " + last_tool_results(req)[0]["content"])]
        return [text("SYSTEM SAW PREFS: " + str("Prefers concise technical explanations" in req.system))]

    k, _ = make_kernel(settings, brain)
    task = k.submit_chat("jarvis", "remember that I prefer concise technical explanations")
    ap = await wait_for(lambda: _pending(k))
    assert ap[0]["tool_id"] == "memory.save" and "Remember" in ap[0]["action"]
    assert k.memory.list(namespace="user:preferences") == []  # nothing stored before consent
    k.approvals.decide(ap[0]["id"], "approved")
    done = await k.wait(task["id"], 5)
    assert "Saved memory" in done["result"]
    prefs = k.memory.list(namespace="user:preferences")
    assert len(prefs) == 1 and prefs[0]["consent"] is True
    # retrieval later: the writers (here F.R.I.D.A.Y.) see it in their prompt; firewalled Ultron does not
    later = await k.wait(k.submit_chat("friday", "plan my day")["id"], 5)
    assert later["result"] == "SYSTEM SAW PREFS: True"
    ult = await k.wait(k.submit_chat("ultron", "plan my day")["id"], 5)
    assert ult["result"] == "SYSTEM SAW PREFS: False"
    # deletion
    assert k.memory.delete(prefs[0]["id"])
    assert k.memory.list(namespace="user:preferences") == []


async def test_episodic_memory_written_with_expiry(settings):
    k, _ = make_kernel(settings, lambda a, r: [text("done")])
    await k.wait(k.submit_chat("friday", "check things")["id"], 5)
    eps = k.memory.list(namespace="agent:friday", layer="episodic")
    assert len(eps) == 1 and eps[0]["expires_at"] is not None


async def test_agent_status_tracks_real_state(settings):
    k, _ = make_kernel(settings, lambda a, r: [tool("fs.write", {"path": "x.txt", "content": "hi"})])
    k.submit_chat("jarvis", "write a file")
    await wait_for(lambda: k.agent_status["jarvis"]["status"] == "waiting_approval")
    k.engage_emergency_stop()
    await wait_for(lambda: k.agent_status["jarvis"]["status"] == "idle")
    k.reset_emergency_stop()
