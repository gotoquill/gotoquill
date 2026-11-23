# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Email support@gotoquill.com with subject "Security report". If private vulnerability reporting is enabled in the public repository, you may also use its Security tab. Do not use the general feedback form for vulnerability details.

Include what you found, how to reproduce it and the impact you expect. Please don't include real
signed documents, personal data or links that contain a `#` key.

## What to expect

This is a volunteer-maintained open-source project. Handling of reports is **best-effort**:
- there is no service level agreement (SLA);
- there is no guaranteed response or fix time;
- there is no bug bounty.

The maintainer aims to acknowledge reports within a reasonable time. Once a fix is released, the
advisory may be published, and you are credited unless you ask not to be.

The software is provided "as is", without warranty of any kind. See [LICENSE](LICENSE) (sections 7 and 8)
and [DISCLAIMER.md](DISCLAIMER.md). Reporting or fixing an issue does not create any warranty, support
obligation or liability.

## Supported versions

Only the latest released version may get security fixes.

## Scope

Of special interest:
- hosted Cloud Worker and site authentication, tenant isolation, operator exports and account erasure;
- OAuth sessions, token rotation, revocation and replay protection;
- hosted document retention, capability responses and lifecycle cleanup;
- the sealed link (AES-256-GCM, key in the URL fragment);
- the ntfy.sh relay handling;
- reply verification (request id, document hash, HMAC, one-time use, expiry);
- the local `127.0.0.1` page;
- the saved-signature vault;
- webhook and command hooks.

Issues in third-party services, such as ntfy.sh, GitHub Pages or browsers, should be reported to those
projects.
