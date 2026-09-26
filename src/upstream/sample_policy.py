"""Exact policy and provider view for the single read_sample upstream tool."""

from ..control.models import ActionProposal, PolicyResult, PolicyStatus


TOOL_NAME = "read_sample"
SAMPLE_IDS = frozenset({"greeting", "farewell"})


class ReadSamplePolicy:
    def check(self, proposal: ActionProposal) -> PolicyResult:
        if proposal.tool != TOOL_NAME:
            return PolicyResult(status=PolicyStatus.DENY, reason="tool is not the permitted upstream tool")
        sample_id = proposal.arguments.get("sample_id")
        if set(proposal.arguments) != {"sample_id"} or not isinstance(sample_id, str) or sample_id not in SAMPLE_IDS:
            return PolicyResult(status=PolicyStatus.DENY, reason="invalid read_sample arguments")
        return PolicyResult(
            status=PolicyStatus.PASS,
            reason="fixed read-only sample is allowed",
            risk_context={"tool": TOOL_NAME, "read_only": True},
        )

    @staticmethod
    def decision_arguments(proposal: ActionProposal) -> dict[str, str]:
        # The policy admits only this non-sensitive field. Keep the projection
        # explicit even though there are no secret arguments for this tool.
        return {"sample_id": proposal.arguments["sample_id"]}
