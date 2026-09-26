"""Reusable control chain behavior independent of the local agent planner."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.composition import create_controlled_agent
from src.control.chain import ControlChain
from src.control.controller import DecisionController
from src.control.models import (
    ActionProposal, ControlDecision, DecisionOutcome, PolicyResult, PolicyStatus, ToolResult,
)
from src.control.permits import ExecutionPermitAuthority, PermitError
from src.core.decision import DecisionEngine
from src.core.models import DecisionRequest
from src.jev.mock import MockJEVClient


class GenericPolicy:
    def check(self, proposal):
        status = {
            "remote.delete": PolicyStatus.DENY,
            "remote.review": PolicyStatus.REVIEW,
        }.get(proposal.tool, PolicyStatus.PASS)
        return PolicyResult(status=status, reason=status.value)


class GenericExecutor:
    def __init__(self, permits):
        self.permits = permits
        self.calls = []

    def execute(self, proposal, permit):
        self.permits.consume(proposal, permit)
        self.calls.append((proposal.tool, proposal.arguments))
        return ToolResult(output="executed")


class ProviderSpy:
    def __init__(self):
        self.calls = 0

    async def decide(self, task, options):
        self.calls += 1
        raise AssertionError("provider should not be called")


def action(tool="remote.search", arguments=None):
    return ActionProposal(tool=tool, arguments=arguments or {"query": "hello"}, description="generic call")


def test_generic_tool_and_provider_disabled_pass_execute():
    permits = ExecutionPermitAuthority()
    executor = GenericExecutor(permits)
    chain = ControlChain(DecisionController(None, GenericPolicy()), permits, executor)
    proposed = action()
    result = asyncio.run(chain.run(proposed))
    assert result.status == "success"
    assert result.decision.source == "policy"
    assert result.permit.approval_source == "policy"
    assert executor.calls == [("remote.search", {"query": "hello"})]
    with pytest.raises(PermitError, match="invalid or does not match"):
        permits.consume(proposed, result.permit)


def test_generic_policy_requires_explicit_provider_argument_view():
    provider = ProviderSpy()
    controller = DecisionController(provider, GenericPolicy())
    with pytest.raises(ValueError, match="explicit argument view"):
        asyncio.run(controller.decide(action(arguments={"query": "hello", "secret": "private-value"})))
    assert provider.calls == 0


def test_generic_argument_projection_keeps_full_permit_digest():
    class RecordingProvider:
        task = None

        async def decide(self, task, options):
            self.task = task
            return SimpleNamespace(decision="allow", confidence=0.9, reason="approved")

    class ProjectingPolicy(GenericPolicy):
        @staticmethod
        def decision_arguments(proposal):
            return {"query": proposal.arguments["query"]}

    provider = RecordingProvider()
    permits = ExecutionPermitAuthority()
    executor = GenericExecutor(permits)
    chain = ControlChain(DecisionController(provider, ProjectingPolicy()), permits, executor)
    original = action(arguments={"query": "hello", "secret": "private-value"}).model_copy(
        update={"description": "caller description private-value"}
    )
    result = asyncio.run(chain.run(original))
    context = json.loads(provider.task.split(". ", 1)[1])
    assert context["arguments"] == {"query": "hello"}
    assert "private-value" not in provider.task
    assert result.status == "success"
    assert result.permit.proposal_digest == original.digest()
    assert result.decision.proposal_digest == original.digest()
    redacted = original.model_copy(update={"arguments": {"query": "hello"}})
    assert result.permit.proposal_digest != redacted.digest()


@pytest.mark.parametrize("tool,outcome", [
    ("remote.delete", DecisionOutcome.DENY),
    ("remote.review", DecisionOutcome.REVIEW),
])
def test_deny_and_review_short_circuit_provider_and_execution(tool, outcome):
    provider = ProviderSpy()
    permits = ExecutionPermitAuthority()
    executor = GenericExecutor(permits)
    chain = ControlChain(DecisionController(provider, GenericPolicy()), permits, executor)
    result = asyncio.run(chain.run(action(tool)))
    assert result.decision.outcome == outcome
    assert result.permit is None
    assert provider.calls == 0
    assert executor.calls == []


def test_argument_digest_binding_rejects_changed_call():
    permits = ExecutionPermitAuthority()
    original = action(arguments={"query": "first"})
    decision = ControlDecision(
        action_id=original.action_id, proposal_digest=original.digest(),
        outcome=DecisionOutcome.ALLOW, reason="pass", source="policy",
    )
    permit = permits.issue(original, decision, "policy")
    changed = original.model_copy(update={"arguments": {"query": "second"}})
    assert changed.digest() != original.digest()
    with pytest.raises(PermitError, match="invalid or does not match"):
        permits.consume(changed, permit)
    permits.consume(original, permit)
    with pytest.raises(PermitError, match="invalid or does not match"):
        permits.consume(original, permit)


def test_permit_ttl_expires_and_cannot_be_extended(monkeypatch):
    import src.control.permits as permits_module

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    class Clock:
        @staticmethod
        def now(tz):
            return now

    monkeypatch.setattr(permits_module, "datetime", Clock)
    permits = ExecutionPermitAuthority(ttl=timedelta(seconds=5))
    proposed = action()
    decision = ControlDecision(
        action_id=proposed.action_id, proposal_digest=proposed.digest(),
        outcome=DecisionOutcome.ALLOW, reason="pass", source="policy",
    )
    permit = permits.issue(proposed, decision, "policy")
    extended = permit.model_copy(update={"expires_at": permit.expires_at + timedelta(hours=1)})
    with pytest.raises(PermitError, match="invalid or does not match"):
        permits.consume(proposed, extended)
    now += timedelta(seconds=5)
    with pytest.raises(PermitError, match="expired"):
        permits.consume(proposed, permit)
    with pytest.raises(PermitError, match="invalid or does not match"):
        permits.consume(proposed, permit)


def test_legacy_mock_is_disabled_for_control_by_shared_composition(tmp_path):
    runner = create_controlled_agent(DecisionEngine(MockJEVClient()), tmp_path)
    assert runner.controller.engine is None


def test_legacy_mock_cannot_fall_back_to_allow_for_control_options():
    result = asyncio.run(MockJEVClient().decide(DecisionRequest(
        task="any proposed action", options=["allow", "review", "deny"]
    )))
    assert result.decision == "review"
