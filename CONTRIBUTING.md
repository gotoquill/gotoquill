# Contributing to gotoquill

Thanks for helping! gotoquill is created and maintained by [Shay Levi](https://github.com/shay2301).

## Scope (read this before opening a PR)

gotoquill does **one thing**: it lets an AI agent get a human's signature on a PDF. Proposals outside this
scope will be closed, however well they are built:

- **Signing only.** Placing signatures, initials, dates and the audit trail. No form filling, no field
  extraction or auto-completion, no document editing or generation, and no general PDF toolkit.
- **Local and optional Cloud.** Local open-source signing is free under Apache 2.0. Gotoquill Cloud is a separate hosted service whose implementation is not in the public tree. Cloud work happens in the private repository. Keep document handling, encryption, and retention claims accurate for the mode you change.
- **Small and auditable.** Few dependencies, no CDNs, nothing that makes the crypto harder to review.

If you aren't sure, open an issue first and ask. Scope is decided by the maintainer (see [GOVERNANCE.md](GOVERNANCE.md)).

## Ways to help

Use the repository issue templates for bugs, features, or assistant support requests. If you do not have GitHub access, use the [feedback page](https://gotoquill.com/feedback/) or [support](https://gotoquill.com/support/). Repository publication requires separate owner approval. Follow our [Code of Conduct](CODE_OF_CONDUCT.md).


- **Report a bug / ask for a feature:** open an issue with steps to reproduce, OS, Python version, and
  (if relevant) browser/phone. Never attach real signed documents or links that contain a `#` key.
- **Security issues:** don't open a public issue. Report them privately via GitHub Security Advisories
  (see [SECURITY.md](SECURITY.md)).
- **Code / docs:** pull requests are welcome. For larger changes, open an issue first to discuss.

## Development

```bash
uv venv && . .venv/bin/activate && uv pip install -e '.[dev]'
python -m pytest -q
```

- Keep changes focused.
- **Tests are required.** Every bug fix comes with a test that fails without the fix, and every feature
  comes with tests. Tests must not touch the network: use the `fake_relay` fixture and mock `urlopen`.
  The full `pytest -q` run must pass.
- Don't add new runtime dependencies or vendored code without discussing it first; any third-party code must
  be compatible with Apache-2.0 and be listed in `THIRD_PARTY_NOTICES.md` and `NOTICE`.
- `web/` must stay dependency-free and self-contained (no CDNs).

## Pull request process

1. For anything bigger than a small fix, open an issue first and agree on the approach.
2. Fork the repo, branch off `main`, and keep each PR to one topic.
3. Fill in the PR template: what changed, how you tested it, and CHANGELOG.md for user-facing changes.
4. The maintainer runs Local CI manually with `workflow_dispatch`. It runs pytest on Python 3.10-3.13 and does not build packages. Those tests must pass before merge.
5. A code owner (@shay2301, see `.github/CODEOWNERS`) must approve. Repository protection is a maintainer setup step. Do not force push. PRs are squash-merged by the maintainer.
6. Don't add personal data, real documents or links containing a `#` key. Use `examples/` and
   realistic synthetic names such as "Dana Cohen".

The private source tree currently remains authoritative. The maintainer integrates accepted public changes there before re-exporting, preserving contributor credit and PR links. Outside code merges are held until the maintainer decides whether to activate the intended CLA process. Issues and PR review can proceed while signing is inactive.

## Contributor License Agreement (approved, not yet in force)

The [Individual CLA](CLA.md) was approved by Shay Levi on 23 November 2026 (Asia/Jerusalem). It is not legal advice and is not yet in force. Do not post a signing comment or attestation yet. The CLA workflow and `CLA_ENABLED` stay off, including after repository publication, until a separate maintainer opt-in. No signing bot is active.

Once activated, the intended contribution process includes the approved CLA before a first merge. Contributors keep copyright. The agreement grants Shay Levi copyright and patent licenses, including rights to relicense, sublicense, and transfer the granted rights. Its substantive grants remain in the full document. Released Apache versions remain available under Apache 2.0.

The project does not use the DCO. `Signed-off-by:` lines do not replace a CLA.

## License (inbound = outbound)

Local contributions are accepted under the same [Apache License 2.0](LICENSE) as the Local project, including section 5 (inbound = outbound). The separate CLA is approved but not yet in force; this text does not collect agreement to it. Contributions are provided as is, without warranty, as described in the license.

## No support obligation

This is a volunteer project. Reviews, answers, fixes and releases are **best-effort**, with no promised
timeline or support obligation, and neither the maintainer nor contributors owe users any support. See
[DISCLAIMER.md](DISCLAIMER.md).

