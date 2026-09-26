# Changelog

## Unreleased

## [0.4.0] - 2026-09-27

### Added
- Extracted a reusable `ControlChain` for policy, optional decision provider, approval, one-time `ExecutionPermit`, and executor flow.
- Added an explicit safe argument projection for external control decisions; caller-supplied descriptions are excluded from provider requests, while the complete proposal digest remains bound to each permit.
- Added a separate repository-owned stdio MCP service with a fixed `read_sample` tool, called through a real permit-gated `tools/call`.

### Tests and limits
- 98 passed, 1 skipped locally on Windows; the skipped test requires Windows symbolic-link privileges. Python 3.11, 3.12, and 3.13 CI passed on the accepted implementation commit.
- Covered upstream startup, timeout, protocol and tool errors, approval, denial, replay, expiry, and argument binding.
- Validation covers only the fixed repository-owned stdio MCP service. There is no general MCP proxy or operating-system sandbox. The real JEV API was not revalidated for this release.

## [0.3.0] - 2026-09-25

### Added
- Controlled Agent execution loop with `ActionProposal`, deterministic policy, and a JEV-backed `DecisionController`.
- Application-layer `allow` / `review` / `deny` control, one-time `ExecutionPermit`, sandboxed local tools, and explicit approval for review actions.
- FastMCP tools `controlled_agent_run` and `approve_action`, matching HTTP endpoints, and structured `AgentTrace` output.
- Local README-to-summary demonstration and controlled-agent documentation.

### Fixed
- Bind MCP approvals to both run and action IDs and redact file contents from public traces.
- Stop tracking the generated `output/summary.md`; fresh CI checkouts create it during the controlled-agent smoke.

### Tests and CI
- Expanded offline control-flow and adapter tests; added controlled-agent smoke to the Python 3.11, 3.12, and 3.13 CI matrix.
- Validated compatibility of the controlled decision path with a real TypeSafe JEV Choice response.

## [0.2.1] - 2026-09-25

### Fixed
- Centralized and hardened JEV decision validation.
- Reject invalid, blank, duplicate, and unavailable decision options.
- Fixed registered `research_skill` routing.
- Improved TypeSafe response validation and error handling.

### Tests
- Expanded test coverage from 15 to 39 tests.
- Added offline TypeSafe response parsing tests.
- Added invalid-choice and validation boundary tests.

### CI
- Added GitHub Actions CI for Python 3.11, 3.12, and 3.13.
- Added pytest and mock benchmark smoke checks.

### Documentation
- Aligned README / README_CN with actual JEV capabilities and current project behavior.
- Clarified Choice as the currently integrated native primitive.
- Clarified that ranking / action gating remain application-layer abstractions.

## v0.1.0

- Positioned the project as an MCP Server exposing a JEV-powered MCP Decision Layer for MCP-compatible AI Agents, with client compatibility notes and decision routing examples.
- Integrated the TypeSafe JEV API for decisions, with a local mock when no API key is configured.
- Added an MCP server that exposes decision, skill execution, and skill discovery tools.
- Added a skill registry, router, and executor with local demonstration workflows.
- Tested with Doubao Desktop MCP Connector.
