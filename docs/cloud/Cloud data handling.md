# Cloud data handling

Last updated: 23 November 2026 (Asia/Jerusalem). Not legal advice.

This page is also available [in Hebrew](Cloud%20data%20handling.he.md). If the versions differ, the version more favorable to you applies.

This page explains in plain language how Gotoquill Cloud handles data. It does not replace the [Privacy Policy](https://gotoquill.com/privacy/) or the [Terms](https://gotoquill.com/terms/). Gotoquill Local runs on your own machine under Apache 2.0. Gotoquill Cloud is a separate hosted service operated by Shay Levi in Israel.

## What Cloud stores and where

Cloud processes and stores data on Cloudflare, using Workers, KV and Durable Objects. This is not a promise of storage only in Israel. When Cloud generates a Muse offline artifact, PDF bytes are sent to Cloudflare Browser Rendering.

- Pending original PDFs, encrypted signing payloads and the keys needed to process signing replies and stamp PDFs on the server.
- Request records: account ownership, document name and hash, signature placements, signer name when supplied, consent text, timestamps, status, messages, proof data, and decline reasons when supplied. Completed requests can contain the signed PDF and signature evidence.
- Account and authentication data: provider-derived account identifiers, name and email when supplied, creation and last-seen times, connected clients, accepted Terms version and time, browser sessions, OAuth client metadata, credential digests, refresh-token families, consent grants and revocation records. Sign-in also uses short-lived authorization and email/provider state.

## Encryption and access

**Cloud is not end-to-end encrypted and is not zero-knowledge.** It stores pending documents and signing keys and stamps PDFs server-side. Encryption in a signing link does not prevent the operator from accessing stored documents and keys while they exist.

The operator can access stored data to operate the service and handle support or deletion requests. Cloudflare processes it as the infrastructure provider. The signed-in account and its authorized assistant connections can access their requests. Anyone holding a bearer signing link or offline signing file can open the document and act as the signer while the request is pending; possession does not verify identity. Preview and download links also grant access to the artifact they identify while valid. Share these only with intended recipients.

Chat hosts receive the tool inputs, outputs, PDFs, previews or signing artifacts passed to them. Copies retained in chats, downloads or offline files follow those recipients' handling and retention. Deleting Cloud's copy does not delete those copies.

## Retention periods

These are the periods Cloud uses. The operator can configure the pending default and maximum. The code enforces a one-hour pending minimum and a maximum of 30 days for finished requests.

| Data | Retention |
| --- | --- |
| Pending request, original PDF and request mailbox | Default 7 days; minimum 1 hour; configured maximum defaults to 14 days. |
| Finished request record and any signed PDF | 30 days after completion, decline or cancellation by default. The operator can set a shorter period. |
| Account records and user index | No automatic expiry. Contact privacy@gotoquill.com for deletion. |
| Browser session | 7-day idle clock, renewed only when you return to the Cloud connect or consent screen, with an absolute cap of 90 days from sign-in. General activity, signing-page use and assistant use do not renew this clock. |
| Registered OAuth clients | 90 days, extended when registration is successfully refreshed. |
| Remembered consent grants | 90 days after approval, not extended when a remembered grant is reused. |
| OAuth access credentials | 1 hour. |
| OAuth refresh family | 90 days of inactivity, renewed on rotation, capped at 180 days from creation. Legacy families without a creation timestamp retain their existing expiry as the cap. |
| Authorization codes | 5 minutes. |
| Sign-in and consent transactions, provider/email state | Up to 10 minutes, bounded by the transaction expiry. |

When a request becomes final, the saved record removes signing keys and upload credentials. Cloud then attempts to delete the original PDF, offline artifact and request/reply mailboxes. If storage cleanup fails, a later authorized write can retry; the original storage expiry is the fallback. The final record and any signed PDF remain for their separate retention period. Downloading does not delete data or extend that period.

Durable Objects check expiry on reads and use alarms for deletion. KV deletion is eventually consistent. These deadlines do not guarantee the time of physical erasure from provider backups or logs. Account revocation markers can persist to prevent revoked access from returning. Provider logs, support mail and copies exported for operations require separate handling; document expiry does not erase them. See the [Privacy Policy retention table](https://gotoquill.com/privacy/) for structured security events, analytics, feedback, and Cloudflare observability and other provider logs. Cloudflare Workers logs for Cloud are kept for 7 days. Those and other provider logs can outlast application document retention periods.

## Cancellation and deletion

Ask your connected assistant to cancel a pending request to stop signing and initiate the cleanup above. Cancellation retains a final request record for the finished-request period; it is not an immediate full wipe. Removing Gotoquill from a chat host stops use through that host, but does not by itself revoke credentials Gotoquill already issued or erase stored data. To revoke access or delete your account, email privacy@gotoquill.com. This page does not promise a self-service account wipe.

For account or other deletion requests, email [privacy@gotoquill.com](mailto:privacy@gotoquill.com). The operator has a separate account-erasure process. Do not send signing links, passwords or document contents in the initial email. Keep your own copies of signed PDFs before their expiry, and ask chat hosts or other recipients separately about deleting copies they hold.

A limited copy preserved for an access request is kept separately until we have answered and provided a reasonable opportunity to access it. This preservation does not extend signing links or credentials.

## Governing law and language

The Cloud Terms specify the laws of the State of Israel and the competent courts in Tel Aviv-Yafo, subject to consumer rights that mandatory law does not allow to be waived. This page does not amend those Terms. If the versions differ, the version more favorable to you applies.

Change note (2026-11-23): clarified host disconnection versus revocation and erasure, preservation for access requests, and the more favorable language rule.
