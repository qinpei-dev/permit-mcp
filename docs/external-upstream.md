# Configured external stdio MCP server (v0.5.0)

This path controls selected tools from one trusted local stdio server. It is a bounded integration, not a universal proxy. The owner installs and configures the upstream process; remote MCP calls cannot set a command, arguments, environment, or rules.

## Install and run

Use Python 3.11 or later:

```bash
python -m pip install permit-mcp==0.5.0
python -m pip install mcp-server-time==2026.8.18
```

Copy `examples/time-server.json.example` to a private local file. Replace `command` with the absolute path to the Python executable where `mcp-server-time` is installed. The file selects discovered `get_current_time` as `allow` and `convert_time` as `review`. `env` maps upstream variable names to existing *local* environment variable names, never credential values; missing values fail startup. This example needs none.

Set `PERMITMCP_UPSTREAM_CONFIG` to the absolute config path and `PERMITMCP_UPSTREAM_APPROVAL_TOKEN` to a long private value, then start `permit-mcp`. A minimal MCP host entry is:

```json
{"mcpServers":{"permit-mcp":{"command":"permit-mcp","args":[],"env":{"PERMITMCP_UPSTREAM_CONFIG":"ABSOLUTE_PRIVATE_CONFIG_PATH","PERMITMCP_UPSTREAM_APPROVAL_TOKEN":"PRIVATE_APPROVAL_SECRET"}}}}
```

Prefer injecting the approval secret into the local server process without exposing it to an agent or shared host configuration. An untrusted agent must only have access to `upstream_tools` and `upstream_call`, not `upstream_approve` or the approval secret. MCP stdio itself assumes a trusted host and does not authenticate individual clients. The approval secret separates roles but does not prove a human reviewed the action.

The client calls `upstream_tools`, then `upstream_call` with `tool="get_current_time"` and `arguments={"timezone":"UTC"}`. For `convert_time`, call `upstream_call` with `{"source_timezone":"UTC","time":"12:00","target_timezone":"Asia/Shanghai"}`. The first response is `review` plus an `action_id`; an authorized reviewer calls `upstream_approve` with that exact ID and the separate secret. Unknown tools, invalid arguments, and `deny` rules never call upstream. The result contains the actual MCP `CallToolResult` serialized as JSON. An upstream `isError` or process failure becomes a generic control error; raw stderr and credentials are not returned.

For a local interactive run outside an MCP host:

```bash
permit-mcp-upstream --config PRIVATE_CONFIG_PATH --tool get_current_time --arguments '{"timezone":"UTC"}'
```

The deterministic policy runs before any upstream execution. Permits bind the entire proposal digest, expire by default after one minute, and are consumed once. The executor rechecks policy and discovery. No upstream arguments are sent to an optional decision provider by this integration; configured calls currently use no external provider. `JEV_API_KEY` is optional for the older decision tools and uses your own TypeSafe account and quota.

## Verification and limits

Run `python -m pytest -q tests/test_configured_upstream.py` after installing the pinned independent server. The test launches its real process, initializes MCP, discovers tools, calls both selected tools, and exercises denial, review, approval, replay, argument tampering, and upstream errors. Without the optional server dependency the independent-process cases skip; a skip is not integration evidence.

This integration supports one local stdio server per PermitMCP process. It does not sandbox upstream code or inspect its side effects. Do not connect an untrusted executable, grant it unnecessary OS permissions, or assume the input schema captures every semantic risk. Review rules are owner-selected; choosing `allow` for a dangerous tool is dangerous. Approval and permit state are in memory, lost on restart, and not suitable for shared multi-user deployments. The older `agent_run` workflow remains a separate path. Remote HTTP transport and automatic arbitrary server configuration are unsupported.
