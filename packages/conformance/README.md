# Gotoquill conformance fixtures

Shared synthetic PDF and PNG fixtures for the Python package and the draft Local TypeScript implementation in `packages/ts`. No real documents or personal signatures belong here.

Local implementations should agree on the sealed-link fragment, AES-GCM wire format (`iv || ciphertext || tag`, AAD `gotoquill/sealed/v1|kind|topic`), and `gotoquill-response` JSON, including HMAC proof. Cloud-specific conformance work happens in the private repository.
