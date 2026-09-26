# Controlled Agent

The local execution loop uses a reusable, single-call `ControlChain`. The bundled planner is deterministic and demonstrates one task, while callers may supply another `AgentPlanner` implementation.

## Architecture

```text
MCP Client / HTTP caller
  -> Deterministic Agent Planner
  -> ActionProposal
  -> ControlChain: DeterministicPolicy
  -> optional DecisionController provider
  -> ALLOW / REVIEW / DENY
  -> one-use ExecutionPermit
  -> SandboxToolExecutor -> Observation
  -> Agent Planner
```

JEV does not execute tools and does not replace the Agent. The `allow`, `review`, and `deny` outcomes are this application's interpretation of a TypeSafe Choice result, not a separate TypeSafe Gate primitive. The deterministic policy runs first and may deny or require review without calling a provider. With no provider, policy `PASS` permits execution. The legacy skill-routing mock is disabled for control in the shared adapter composition.

Before contacting an external provider, the policy or controller must supply an explicit safe argument projection. With no projection, the decision fails closed. The sandbox policy omits `write_file` content and sends its length instead. Caller-supplied descriptions are not sent to the provider. The permit digest still covers the unredacted complete proposal. The separate fixed upstream MCP proof is documented in [Upstream MCP proof](upstream-mcp.md).

The v0.2.1 `jev_decide`, `agent_run`, and `list_skills` tools remain available for compatibility. The new controlled path is exposed through `controlled_agent_run` and `approve_action`; both MCP and HTTP adapters call the same `ControlledAgentRunner` service.

## Action lifecycle

1. The planner returns an `ActionProposal` with an action ID, generic tool name, arguments, description, and optional caller-supplied risk context.
2. The generic proposal model retains canonical JSON digest binding. The sandbox policy validates its four supported tool names and argument shapes, then derives risk from the filesystem state; it does not trust the proposal's `risk_context`.
3. Absolute paths, traversal, resolved paths outside the configured root, and commands outside the exact allowlist are denied before JEV.
4. Writing an existing file returns `approval_required`. Other policy-passing actions are sent to the configured decision provider, if present, as a Choice among `allow`, `review`, and `deny`. Proposed write content is not included in that Choice request.
5. Only an `allow` or an explicit approval of a reviewed action can receive a permit. Denied or invalid decisions cannot reach the executor.
6. The executor rechecks policy, checks and consumes the permit once, invokes the fixed tool registry, and returns a typed result. The result becomes an observation for the planner.
7. Successful results, policy denials, and tool errors are passed back as observations. The planner may finish or propose another action; review pauses for approval. The runner also enforces `max_steps` (default 5, maximum 20).

## Permit model

`ExecutionPermit` binds the proposal's `action_id`, tool, decision, approval source, SHA-256 digest of the complete proposal, and explicit expiry. The default permit TTL is one minute. `ExecutionPermitAuthority` keeps issued permit IDs in process memory and removes them on consumption or expiry. Reusing a permit, changing the action, using a permit for another action, extending its expiry, or omitting the permit is rejected. Approval is also bound to one pending action ID and is removed before the runner resumes work.

## Review flow

When an action needs review, the run returns `status: "approval_required"`, its `run_id`, `pending_action`, `pending_decision`, and a trace. No tool has run for that action. Approve through MCP with `approve_action(run_id, action_id)` or HTTP with `POST /api/v1/controlled-agent/{run_id}/approve` and `{"action_id":"..."}`. The service then issues a caller-sourced permit, executes the action once, feeds the result to the planner, and continues the same run. A wrong, stale, or replayed run/action pair is rejected. Pending runs are in memory only and do not survive a process restart.

Public MCP and HTTP traces redact `read_file` results and proposed `write_file` content. The planner still receives the full read observation inside the process. Reviewers can inspect the target path and proposal digest; they should approve only tasks they initiated and trust. A custom planner's description or final answer remains caller-controlled text.

## Sandbox tools

The controlled registry contains four operations:

- `list_files`: list names under the sandbox.
- `read_file`: read a UTF-8 file under the sandbox.
- `write_file`: write a UTF-8 file under the sandbox; replacing an existing file requires review.
- `run_safe_command`: choose only `python-version`, `git-status`, or `git-diff-stat`. Each maps to a fixed argument vector and runs with `shell=False`, a fixed working directory, and a timeout.

The configured root is the MCP/API process working directory by default. Start it from a trusted, dedicated directory or inject a different `sandbox_root` when creating the service. The example uses the repository root because it reads `README.md` and writes `output/summary.md`.

## Examples

Run the no-key example from the repository root:

```bash
python -m examples.controlled_agent_demo
```

It reads the actual README, creates a deterministic short summary, creates `output/summary.md`, and prints a machine-readable trace. The generated `output/` directory is ignored by Git. It runs control without a provider and stays offline by default. Add `--real-jev` to use TypeSafe JEV with the configured `JEV_API_KEY`. On later runs, an existing destination waits for review; pass `--approve-existing` only to explicitly approve that overwrite.

The HTTP endpoints are:

- `POST /api/v1/controlled-agent/run` with `{"task":"...", "max_steps":5}`
- `POST /api/v1/controlled-agent/{run_id}/approve` with `{"action_id":"..."}`

## Limitations

- The bundled deterministic planner only demonstrates the README summary task; it is not a general reasoning model. The caller supplies any production planner implementation.
- This is a same-process path policy, not an operating-system sandbox. It rejects traversal and symlink-resolved escapes, but does not isolate the Python process from other local code, OS permissions, or filesystem races.
- The MCP server's default sandbox is its working directory. Use a trusted local checkout and do not expose the server to untrusted callers.
- The command list is intentionally fixed and read-only. There is no arbitrary shell, network, package installation, or privileged action tool.
- Review state and permit state are in memory; restart loses pending approvals.
- JEV decisions can vary. Low-confidence `allow` choices become review; deterministic policy denials always take precedence.
- The existing legacy `agent_run` still runs its registered simulated skill after routing. Only the new controlled tools use the permit-gated filesystem executor.
