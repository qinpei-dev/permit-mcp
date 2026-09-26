"""Policy-first ALLOW / REVIEW / DENY decisions with an optional provider."""

import json
from collections.abc import Callable
from typing import Any, Protocol

from .models import ActionProposal, ControlDecision, DecisionOutcome, PolicyResult, PolicyStatus


class DecisionProvider(Protocol):
    async def decide(self, task: str, options: list[str]): ...


class Policy(Protocol):
    def check(self, proposal: ActionProposal) -> PolicyResult: ...


class DecisionController:
    """Apply deterministic policy first, then optionally ask for a structured choice."""

    outcomes = [DecisionOutcome.ALLOW.value, DecisionOutcome.REVIEW.value, DecisionOutcome.DENY.value]

    def __init__(
        self,
        engine: DecisionProvider | None,
        policy: Policy,
        minimum_confidence: float = 0.5,
        argument_view: Callable[[ActionProposal], dict[str, Any]] | None = None,
    ):
        if not 0 <= minimum_confidence <= 1:
            raise ValueError("minimum_confidence must be between 0 and 1")
        self.engine = engine
        self.policy = policy
        self.minimum_confidence = minimum_confidence
        # An external provider may only receive arguments through an explicit
        # view. Never infer that a generic policy permits disclosure.
        self.argument_view = argument_view if argument_view is not None else getattr(
            policy, "decision_arguments", None
        )

    async def decide(self, proposal: ActionProposal) -> tuple[PolicyResult, ControlDecision]:
        proposal_digest = proposal.digest()
        policy_result = self.policy.check(proposal)
        if policy_result.status == PolicyStatus.DENY:
            return policy_result, ControlDecision(
                action_id=proposal.action_id,
                proposal_digest=proposal_digest,
                outcome=DecisionOutcome.DENY,
                reason=policy_result.reason,
                source="policy",
            )
        if policy_result.status == PolicyStatus.REVIEW:
            return policy_result, ControlDecision(
                action_id=proposal.action_id,
                proposal_digest=proposal_digest,
                outcome=DecisionOutcome.REVIEW,
                reason=policy_result.reason,
                source="policy",
            )

        if self.engine is None:
            return policy_result, ControlDecision(
                action_id=proposal.action_id,
                proposal_digest=proposal_digest,
                outcome=DecisionOutcome.ALLOW,
                reason=policy_result.reason,
                source="policy",
            )

        if self.argument_view is None:
            raise ValueError("an explicit argument view is required for an external decision provider")
        provider_arguments = self.argument_view(proposal)
        if not isinstance(provider_arguments, dict):
            raise TypeError("decision argument view must return a dictionary")
        context = {
            "action_id": proposal.action_id,
            "tool": proposal.tool,
            "arguments": provider_arguments,
            "system_risk_context": policy_result.risk_context,
        }
        task = "Decide whether this proposed local tool action may execute. " + json.dumps(
            context, ensure_ascii=False, sort_keys=True
        )
        result = await self.engine.decide(task, self.outcomes)
        if proposal.digest() != proposal_digest:
            raise ValueError("action proposal changed while its JEV decision was pending")
        if result.decision not in self.outcomes:
            raise ValueError("JEV returned an invalid control outcome")
        if result.confidence < self.minimum_confidence and result.decision == "allow":
            decision = ControlDecision(
                action_id=proposal.action_id,
                proposal_digest=proposal_digest,
                outcome=DecisionOutcome.REVIEW,
                confidence=result.confidence,
                reason=(
                    f"JEV confidence {result.confidence:.2f} is below the "
                    f"{self.minimum_confidence:.2f} execution threshold"
                ),
                source="confidence",
            )
        else:
            decision = ControlDecision(
                action_id=proposal.action_id,
                proposal_digest=proposal_digest,
                outcome=DecisionOutcome(result.decision),
                confidence=result.confidence,
                reason=result.reason,
                source="jev",
            )
        if decision.action_id != proposal.action_id:
            raise ValueError("control decision action_id does not match the proposal")
        return policy_result, decision
