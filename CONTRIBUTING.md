# Contributing to gotoquill

Thanks for helping! gotoquill is created and maintained by [Shay Levi](https://github.com/shay2301).

## How this repository works

This repository is an export of the Local open-source package from a private source repository. The two trees are not identical. This public tree does not contain the hosted Cloud implementation, the website, billing or deploy setup.

You can open issues and pull requests here. The maintainer reviews each one and decides whether to accept it. Nothing lands without that decision. Accepted changes are copied into the private source with credit and come back here in the next export. The details are in [Pull request process](#pull-request-process).

## Scope (read this before opening a PR)

gotoquill does **one thing**: it lets an AI agent get a human's signature on a PDF. Proposals outside this
scope will be closed, however well they are built:

- **Signing only.** Placing signatures, initials, dates and the audit trail. No form filling, no field
  extraction or auto-completion, no document editing or generation, and no general PDF toolkit.
- **Local and optional Cloud.** Local open-source signing is free under Apache 2.0. Gotoquill Cloud is a separate hosted service whose implementation is not in the public tree. Cloud work happens in the private repository. Keep document handling, encryption, and retention claims accurate for the mode you change.
- **Small and auditable.** Few dependencies, no CDNs, nothing that makes the crypto harder to review.

If you aren't sure, open an issue or a [Discussion](https://github.com/gotoquill/gotoquill/discussions) first and ask. Scope is decided by the maintainer (see [GOVERNANCE.md](GOVERNANCE.md)).

## Ways to help

Follow our [Code of Conduct](CODE_OF_CONDUCT.md).

- **Something is broken:** open a [Bug report](https://github.com/gotoquill/gotoquill/issues/new/choose).
- **Something works, but badly:** if it is confusing, slow, fragile or awkward, use **Something works badly or could be better**.
- **A new capability:** use **Feature idea**. Keep it inside the scope above.
- **Another assistant or MCP host:** use **Assistant support request**.
- **Questions and looser ideas:** use [GitHub Discussions](https://github.com/gotoquill/gotoquill/discussions) (Q&A and Ideas).
- **No GitHub account:** use the [feedback page](https://gotoquill.com/feedback/) or [support](https://gotoquill.com/support/).
- **Security problems:** do not open a public issue. Follow [SECURITY.md](SECURITY.md). Report privately through [a GitHub security advisory](https://github.com/gotoquill/gotoquill/security/advisories/new) or by email to [hello@gotoquill.com](mailto:hello@gotoquill.com).
- **Code and docs:** pull requests are welcome. For larger changes, open an issue first so the approach can be agreed.

### What makes a useful issue

- Use the matching issue template and fill in every required field.
- Give numbered steps that someone else can follow to see the problem.
- Include your gotoquill version (`uv pip show gotoquill` or `pip show gotoquill`), operating system, Python version, and the assistant or MCP host. Add the browser or phone if the signing page is involved.
- Reproduce with a synthetic PDF, such as `examples/sample_contract.pdf`, and made-up names such as Dana Cohen.
- Say what you expected to happen and what actually happened.
- Paste error text as text, not screenshots, and keep it to the relevant lines.
- One problem or idea per issue.
- Do not include real or signed documents, signatures, personal data, credentials, tokens, pairing codes, or signing links that contain a `#` key. Remove them from logs before pasting.

### How issues get fixed

When the maintainer picks up an issue, the fix is made in the private source and exported to this repository. The issue is then closed with a link to the export commit on `main`. Not every issue will be picked up, and there is no timeline (see [No support obligation](#no-support-obligation)).

## Development

gotoquill supports Python 3.10, 3.11, 3.12 and 3.13. Development uses [uv](https://docs.astral.sh/uv/).

The render tests call `pdftoppm`, which comes from poppler. Install it first:

- **Debian / Ubuntu:** `sudo apt-get install -y poppler-utils`
- **macOS (Homebrew):** `brew install poppler`
- **Windows:** one common option is conda-forge: `conda install -c conda-forge poppler`. `pdftoppm` must be on your `PATH`.

Check with `pdftoppm -v`.

Then set up and run the tests:

```bash
uv venv && . .venv/bin/activate && uv pip install -e '.[dev]'
# Run explicit affected tests while iterating; use the scope rule below.
```

On Windows, activate with `.venv\Scripts\activate` instead.

- Keep changes focused.
- **Tests are required.** Every bug fix comes with a test that fails without the fix, and every feature
  comes with tests. Tests must not touch the network: use the `fake_relay` fixture and mock `urlopen`.
  Follow the test scope rule below.
- Don't add new runtime dependencies or vendored code without discussing it first. Any third-party code must
  be compatible with Apache-2.0 and be listed in `THIRD_PARTY_NOTICES.md` and `NOTICE`.
- `web/` must stay dependency-free and self-contained (no CDNs).

CI selects affected areas on pull requests and pushes to `main`, with Python 3.10 and 3.13 for Python changes. Weekly, manual, and release-tag verification runs validate all areas on Python 3.10 through 3.13. Release publication waits for full verification. For a first-time contributor, GitHub may ask the maintainer to approve the workflow run before it starts.

### Test scope

1. Small isolated edits: run explicit affected tests on one interpreter/runtime while iterating. Ordinary prose-only docs need no application suite; packaged copy and policy contracts still do.
2. Shared PDF stamping, MCP tools, auth, encryption, dependencies, common fixtures, or uncertain impact: run the full affected area before opening the PR.
3. Risky or cross-area changes: run full repository validation before merge to main. Use `workflow_dispatch` if PR filters would skip needed jobs. Full release validation must pass before publication.
4. Wait only for required CI in repositories actually changed. Do not rerun `test:workerd` after `npm test`. Record what was run.

## Pull request process

1. For anything bigger than a small fix, open an issue first and agree on the approach.
2. Fork the repo, branch off `main`, and keep each PR to one topic.
3. Fill in the PR template: what changed, how you tested it, and a CHANGELOG.md entry under Unreleased for user-facing changes.
4. CI must pass.
5. The maintainer reviews (code owner: @shay2301, see `.github/CODEOWNERS`). During review, push follow-up commits rather than force-pushing, so review comments stay attached.
6. Don't add personal data, real documents or links containing a `#` key. Use `examples/` and
   realistic synthetic names such as "Dana Cohen".

### What happens when a PR is accepted

This repository is regenerated from the private source on each export. A PR merged with the GitHub Merge button would be overwritten by the next export, so accepted PRs are not merged that way. Instead:

1. The maintainer ports your change into the private source and credits you with a `Co-authored-by` trailer. The name and email come from your commits, so commit with an address you are happy to show publicly, such as your GitHub noreply address.
2. The maintainer exports the updated tree, and the change appears as a new commit on `main` here. That commit carries the same credit.
3. Your PR is closed with a comment linking to that export commit.

**A PR closed with a link to an export commit was accepted, not rejected.** GitHub shows it as "Closed" rather than "Merged". That is expected.

The ported change may be adjusted slightly to fit the source tree, for example small edits to tests or wording. If a PR is not accepted, the maintainer may close it with a short reason.

## Contributor License Agreement (approved, not yet in force)

The [Individual CLA](CLA.md) was approved by Shay Levi on 23 November 2026 (Asia/Jerusalem). It is not legal advice and is not yet in force. Do not post a signing comment or attestation yet. The repository is public, but the CLA workflow and `CLA_ENABLED` stay off until a separate maintainer opt-in. No signing bot is active.

Once activated, the intended contribution process includes the approved CLA before a first merge. Contributors keep copyright. The agreement grants Shay Levi copyright and patent licenses, including rights to relicense, sublicense, and transfer the granted rights. Its substantive grants remain in the full document. Released Apache versions remain available under Apache 2.0.

The project does not use the DCO. `Signed-off-by:` lines do not replace a CLA.

## License (inbound = outbound)

Local contributions are accepted under the same [Apache License 2.0](LICENSE) as the Local project, including section 5 (inbound = outbound). The separate CLA is approved but not yet in force; this text does not collect agreement to it. Contributions are provided as is, without warranty, as described in the license.

## No support obligation

This is a volunteer project. Reviews, answers, fixes and releases are **best-effort**, with no promised
timeline or support obligation, and neither the maintainer nor contributors owe users any support. See
[DISCLAIMER.md](DISCLAIMER.md).
