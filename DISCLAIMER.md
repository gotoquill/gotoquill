# Disclaimer

gotoquill is free, open-source software, licensed under the [Apache License 2.0](LICENSE).
Read this before you use it, or build on it, for anything that matters.

1. **Provided "as is", with no warranty.** The software comes with no warranty or condition of any kind,
   express or implied. This includes merchantability, fitness for a particular purpose, title,
   non-infringement, accuracy and availability. Sections 7 and 8 of the [LICENSE](LICENSE) apply in full.

2. **Not legal advice.** Nothing in this project is legal advice, including the code, the documentation,
   the signing page, the consent wording and the audit record. If the legal effect of a signature matters to
   you, ask a qualified lawyer in your jurisdiction.

3. **Not a certified or qualified e-signature or trust service.** gotoquill produces a simple electronic
   signature: an image placed on a PDF, plus an audit record with hashes and timestamps.
   - It is **not** an advanced or qualified electronic signature (AdES/QES) under eIDAS.
   - It is not a qualified trust service and not a certificate-based digital signature.
   - There is **no guarantee** that it meets the U.S. ESIGN Act, UETA or any other law, regulation,
     industry rule or contractual requirement.
   - Some documents (for example, certain wills, notarised deeds, real-estate or court filings) may need a
     form of signature that this software does not provide.

4. **You are solely responsible for your use of it.** Users, operators and integrators (including anyone
   who connects it to an AI agent) are solely responsible for:
   - whether a signature is legally valid and enforceable where they are;
   - getting and recording proper consent, including consent to sign electronically;
   - verifying the identity of signers and authorising the people who get a link;
   - keeping, retaining and backing up documents and records;
   - data protection and privacy obligations (for example GDPR or CCPA);
   - the security of their machines, links, keys, files and agent setup.

5. **No liability.** To the maximum extent allowed by law, the author(s) and contributors are not liable
   for any damages or losses of any kind. This includes:
   - lost, corrupted, altered, leaked or wrongly signed documents;
   - signatures found invalid or unenforceable;
   - misuse by anyone, including an AI agent acting on instructions;
   - security incidents;
   - downtime;
   - indirect, incidental, special or consequential damages, however caused.

6. **Third-party services are outside the author's control.** The default sealed-link flow uses the public
   [ntfy.sh](https://ntfy.sh) relay. Only encrypted data passes through it; the key stays in the link. You can
   use the open-source **gotoquill relay** instead. There is **no shared public instance**: each user deploys
   it on **their own Cloudflare account** (see [`relay/README.md`](relay/README.md)). The flow may also use a
   static page host, such as GitHub Pages, and the signer's browser and messaging apps. These services are run
   by third parties under their own terms. They may change, fail, log metadata (such as IP addresses, sizes and
   times) or become unavailable. You can self-host ntfy, the gotoquill relay, and the signing page.

7. **No support obligation.** Support, fixes and answers are best-effort and voluntary, with no service
   level or response time.

8. **AI agents act on your instructions.** If you connect gotoquill to an AI agent, the agent decides which
   documents, signers and signature positions to send, based on your instructions and its own behaviour. You are
   responsible for reviewing every document, placement and signed output before you send it or rely on it.
   Automatic suggestions, such as where a signature or date goes, can be wrong.

9. **The software and the hosted service are different.** This disclaimer and the [LICENSE](LICENSE) cover the
   open-source software you run yourself. When run locally, it does not send your documents or usage data to
   the author. **Gotoquill Cloud**, the hosted service at gotoquill.com, is a separate service governed by its
   [Terms of Service](https://gotoquill.com/terms/) and [Privacy Policy](https://gotoquill.com/privacy/).

10. **No duty to update, and not for high-risk use.** The author has no obligation to fix, maintain, update or
    keep providing the software. Do not use it where a failure, a wrong signature or a lost document could cause
    death, personal injury, or severe financial or legal harm, unless you add your own independent checks.

If you do not accept these terms, do not use the software.
