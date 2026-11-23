# Governance

gotoquill is a single-maintainer project.

- **Maintainer:** [Shay Levi](https://github.com/shay2301) (@shay2301), the creator and owner of the project.
- **Model: BDFL ("benevolent dictator for life").** The maintainer has the final say on the project's scope,
  design, roadmap, releases, and which pull requests are merged or closed. Discussion is welcome and
  decisions are explained where practical, but they are not made by vote.
- **Scope** is defined in [CONTRIBUTING.md](CONTRIBUTING.md#scope-read-this-before-opening-a-pr): signing
  only, with no form filling. Local open-source signing is Apache 2.0. Gotoquill Cloud is a separate hosted service whose implementation is not in the public tree; Cloud work happens in the private repository. Changes to the scope are made only by the maintainer.
- **Merges:** every change to `main` goes through a pull request approved by a code owner
  (`.github/CODEOWNERS`) with passing CI. Only the maintainer merges.
- **Contributions** use inbound = outbound Apache 2.0. The [CLA](CLA.md) was approved by Shay Levi on 23 November 2026 (Asia/Jerusalem), but is not yet in force. Its signing process is inactive, and `CLA_ENABLED` stays off until that opt-in. Activation requires public launch and a separate maintainer opt-in. Do not post a signing comment or attestation yet. The agreement includes relicensing rights, while released Apache versions stay Apache.
- **Releases** (PyPI, MCP Registry, ClawHub) are published only by the maintainer.
- **Security** reports go privately to the maintainer (see [SECURITY.md](SECURITY.md)).
- **Changes to this document** are made only by the maintainer. If the project ever adds maintainers or
  moves to a foundation, this file will be updated to say so.
