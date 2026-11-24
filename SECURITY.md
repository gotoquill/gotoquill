# Security Policy

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Report privately through either channel:

- GitHub private vulnerability reporting:
  [Report a vulnerability](https://github.com/gotoquill/gotoquill/security/advisories/new)
  (repository → **Security** → **Report a vulnerability**).
- Email: [hello@gotoquill.com](mailto:hello@gotoquill.com). A subject line such as "Security report" helps.

Do not use the general feedback form for vulnerability details.

Reports in English or Hebrew are welcome.

## What to include

- What you found and where (local package, hosted Cloud service, relay or website).
- Steps to reproduce.
- The impact you expect.
- The version you tested, if relevant.

Please do **not** include real signed documents, personal data, credentials or links that contain a `#` key.
The part of a sealed link after `#` holds the decryption key. Use `examples/sample_contract.pdf` or a document
you made for testing.

## What to expect

Gotoquill is a volunteer-maintained open-source project with a hosted Cloud service. Handling of reports is
**best-effort**:

- there is no service level agreement (SLA);
- there is no guaranteed response or fix time;
- there is no bug bounty, and reports are not paid.

The maintainer aims to acknowledge reports within a reasonable time. Once a fix is released, an advisory may
be published, and you are credited unless you ask not to be.

The software is provided "as is", without warranty of any kind. See [LICENSE](LICENSE) (sections 7 and 8)
and [DISCLAIMER.md](DISCLAIMER.md).

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
