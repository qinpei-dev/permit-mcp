"""Real independent mcp-server-time process plus local trust-boundary checks."""

import asyncio
import json
import sys

import pytest

from src.control.models import ActionProposal
from src.control.permits import PermitError
from src.upstream.configured import ConfiguredUpstream


def config():
    return {
        "command": sys.executable,
        "args": ["-m", "mcp_server_time"],
        "env": {},
        "tools": {"get_current_time": "allow", "convert_time": "review"},
    }


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("mcp_server_time") is None,
    reason="install mcp-server-time==2026.8.18 for independent server test",
)
def test_real_third_party_control_flow():
    async def run():
        upstream = ConfiguredUpstream(config())
        assert set(await upstream.initialize()) == {"get_current_time", "convert_time"}
        allowed = ActionProposal(
            tool="get_current_time", arguments={"timezone": "UTC"}, description="time"
        )
        success = await upstream.chain.run(allowed)
        assert success.status == "success"
        assert "UTC" in success.tool_result.output
        with pytest.raises(PermitError):
            upstream.chain.executor.execute(allowed, success.permit)
        actual_call = upstream.chain.executor._call

        async def forbidden_call(*_args):
            pytest.fail("denied or pending action reached upstream")

        upstream.chain.executor._call = forbidden_call
        denied = ActionProposal(tool="missing", arguments={}, description="missing")
        assert (await upstream.chain.run(denied)).status == "blocked"
        invalid = ActionProposal(
            tool="get_current_time", arguments={}, description="invalid"
        )
        assert (await upstream.chain.run(invalid)).status == "blocked"
        review = ActionProposal(
            tool="convert_time",
            arguments={
                "source_timezone": "UTC",
                "time": "12:00",
                "target_timezone": "Asia/Shanghai",
            },
            description="conversion",
        )
        pending = await upstream.chain.run(review)
        assert pending.status == "review"
        upstream.chain.executor._call = actual_call
        tampered = review.model_copy(
            update={
                "arguments": {
                    "source_timezone": "UTC",
                    "time": "13:00",
                    "target_timezone": "Asia/Shanghai",
                }
            }
        )
        with pytest.raises(ValueError):
            upstream.chain.approve(tampered, pending)
        approved = upstream.chain.approve(review, pending)
        assert approved.status == "success"
        assert "20:00" in approved.tool_result.output
        with pytest.raises(PermitError):
            upstream.chain.executor.execute(review, approved.permit)
        failure = ActionProposal(
            tool="get_current_time",
            arguments={"timezone": "Not/A_Zone"},
            description="failure",
        )
        assert (await upstream.chain.run(failure)).status == "error"

    asyncio.run(run())


def test_invalid_local_configuration_and_missing_credential(monkeypatch):
    bad = config()
    bad["command"] = "python"
    with pytest.raises(ValueError):
        ConfiguredUpstream(bad)
    bad = config()
    bad["env"] = {"TOKEN": "MISSING_TEST_TOKEN"}
    monkeypatch.delenv("MISSING_TEST_TOKEN", raising=False)
    with pytest.raises(ValueError):
        ConfiguredUpstream(bad)


def test_unknown_configured_tool_fails_initialization():
    async def run():
        bad = config()
        bad["tools"] = {"nonexistent": "allow"}
        with pytest.raises(ValueError, match="not discovered"):
            await ConfiguredUpstream(bad).initialize()

    if __import__("importlib").util.find_spec("mcp_server_time"):
        asyncio.run(run())


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("mcp_server_time") is None,
    reason="independent server is optional",
)
def test_explicit_deny_and_upstream_process_failure():
    async def run():
        upstream = ConfiguredUpstream(config())
        await upstream.initialize()
        upstream.rules["get_current_time"] = "deny"
        proposal = ActionProposal(
            tool="get_current_time", arguments={"timezone": "UTC"}, description="time"
        )
        assert (await upstream.chain.run(proposal)).status == "blocked"
        upstream.rules["get_current_time"] = "allow"
        upstream.server.args = ["-m", "module_that_does_not_exist"]
        result = await upstream.chain.run(proposal)
        assert result.status == "error"
        assert result.error == "configured upstream MCP call failed"

    asyncio.run(run())


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("mcp_server_time") is None,
    reason="independent server is optional",
)
def test_mcp_adapter_approval_secret_and_pending_action(monkeypatch, tmp_path):
    from src.jev.mock import MockJEVClient
    from src.mcp.tools import create_mcp_server

    path = tmp_path / "upstream.json"
    path.write_text(json.dumps(config()), encoding="utf-8")
    monkeypatch.setenv("PERMITMCP_UPSTREAM_CONFIG", str(path))
    monkeypatch.setenv("PERMITMCP_UPSTREAM_APPROVAL_TOKEN", "local-review-secret")
    server = create_mcp_server(MockJEVClient())

    async def run():
        names = {tool.name for tool in await server.list_tools()}
        assert {"upstream_tools", "upstream_call", "upstream_approve"} <= names
        result = await server.call_tool(
            "upstream_call",
            {
                "tool": "convert_time",
                "arguments": {
                    "source_timezone": "UTC",
                    "time": "12:00",
                    "target_timezone": "Asia/Shanghai",
                },
            },
        )
        review = json.loads(result[0].text)
        assert review["status"] == "review"
        with pytest.raises(Exception, match="invalid approval token"):
            await server.call_tool(
                "upstream_approve",
                {"action_id": review["action_id"], "approval_token": "wrong"},
            )
        good = await server.call_tool(
            "upstream_approve",
            {"action_id": review["action_id"], "approval_token": "local-review-secret"},
        )
        assert json.loads(good[0].text)["status"] == "success"

    asyncio.run(run())
