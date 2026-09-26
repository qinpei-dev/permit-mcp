# Upstream MCP proof (v0.4 work in progress)

The repository includes one separate stdio MCP server, `src.upstream.sample_server`. Its only tool, `read_sample`, returns one of two fixed strings. `ReadSampleExecutor` launches that server with `sys.executable`, opens a real MCP `ClientSession`, initializes it, and sends `tools/call`. The executor is reached through the reusable `ControlChain`; the test does not call the Python tool function directly.

Run from the repository root, with dependencies installed and no API key:

```bash
python -m examples.upstream_mcp_demo
python -m pytest -q tests/test_upstream_mcp.py
```

The path is `ActionProposal → ReadSamplePolicy → optional DecisionProvider → ExecutionPermit → ReadSampleExecutor → stdio MCP tools/call → ToolResult`. The policy accepts only `read_sample` with a known `sample_id` and explicitly projects that field for an external decision provider. A generic policy with no explicit projection fails before contacting a provider. The caller-supplied description is excluded from the provider request; the complete proposal, including its arguments and description, remains bound to the permit digest.

Policy `DENY` stops before the upstream call. `REVIEW` returns without execution until `ControlChain.approve` receives the matching proposal and reviewed result. The executor rechecks policy and consumes the permit once before the call. Startup, timeout, protocol, tool, and unsupported-result failures return a control error without a successful `ToolResult`; raw upstream error text is not returned to the caller. The MCP client context closes the child process and streams after the call or failure.

This is a fixed local proof, not a general MCP proxy or a compatibility claim for third-party MCP servers. Permit and approval state remain in process memory. The sample service is read-only, and the project does not provide operating-system isolation, distributed permit management, or a production deployment of this upstream path. Existing `agent_run` skill routing is separate and is not covered by this permit gate.
