# Security Policy

## Reporting a security issue

Please report suspected vulnerabilities privately. Use GitHub's **Report a vulnerability** option in this repository's Security tab if it is available. Otherwise, contact the maintainer privately through the repository owner's GitHub profile. Include the affected version, steps to reproduce, and potential impact. Do not post exploit details or credentials in a public issue.

## Protect your credentials

- Never commit an API key, including `JEV_API_KEY`, to this repository or paste one into an issue, log, or screenshot.
- Never commit a `.env` file. Keep your local `.env` private; `.env.example` is the public template and contains no key.
- If a key is exposed, revoke or rotate it with its provider and remove it from any shared configuration.
- HTTP requires distinct `PERMITMCP_EXECUTION_TOKEN` and `PERMITMCP_APPROVAL_TOKEN` values. Keep both private and never provide the approval token to an Agent. Missing or identical values fail closed. These shared secrets separate two roles; they do not establish individual identity or prove human review.
- Keep HTTP bound to loopback unless you provide TLS and an appropriate access gateway. Docker Compose publishes only to `127.0.0.1`, while the Dockerfile listens on `0.0.0.0` inside the container for port forwarding. Use `docker run -p 127.0.0.1:8000:8000`, not an unrestricted host port mapping. For direct Uvicorn use `--host 127.0.0.1`.

## MCP configuration

- Run the STDIO MCP server only from a trusted local checkout and Python environment. Review the configured `command`, `args`, and working directory before connecting a desktop client.
- HTTP Bearer tokens do not authenticate the stdio MCP transport. The MCP client and local process must be trusted independently.
- Store MCP configuration files containing secrets privately. Prefer a local environment variable or private `.env` file for `JEV_API_KEY` rather than putting the key in a configuration file you may share.
- Grant the MCP connector access only to the tools and files it needs, and do not expose the local server to untrusted users.

## Controlled Agent scope

- The controlled execution example is for a trusted local sandbox. File tools resolve paths against the configured sandbox root and deny absolute paths, traversal, and paths resolving outside that root.
- The tool set has no arbitrary shell. `run_safe_command` accepts only the documented fixed read-only command aliases and invokes them with `shell=False`.
- Review actions remain pending until the caller explicitly approves the matching `action_id`. Approval state and one-use permits are held in memory and are lost when the process exits.
- Deterministic policy runs before JEV and takes precedence over a JEV Choice. The `allow` / `review` / `deny` values are application-layer choices built on the Choice response; they are not a separate TypeSafe Gate primitive.
- JEV is not the only safety boundary. The executor requires a one-use permit bound to the action ID and proposal digest, and it rechecks the sandbox policy before execution.
- This same-process example is not an operating-system security sandbox and must not be used for privileged production actions or with an untrusted caller. Do not describe it as a “safe Agent.”
