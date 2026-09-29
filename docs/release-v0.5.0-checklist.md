# v0.5.0 release candidate checklist

- [x] v0.4.1 baseline and local suite audited.
- [x] Independent `mcp-server-time==2026.8.18` process tested for initialization, discovery, allow, review, approval, denial, replay, invalid input, and upstream error.
- [x] Existing suite and wheel build run locally.
- [x] Clean isolated installation and outside-checkout call confirmed with `mcp-server-time==2026.8.18`.
- [x] Official Registry `/v0.1/validate` returned `{"valid":true,"issues":[]}` for `server.json` without publishing.
- [ ] Owner reviews security limits, package name, and registry namespace.
- [ ] Owner explicitly authorizes PyPI publication, then confirms published package metadata includes README ownership marker.
- [ ] Owner explicitly authorizes Registry publication after PyPI artifact exists.
- [ ] Release tag and GitHub release created only after publication verification and owner authorization.

Registry metadata is a draft until the exact PyPI version exists. The official Registry verifies the `mcp-name` marker in the published README and requires namespace authentication. Do not publish `server.json` as a substitute for the package.
