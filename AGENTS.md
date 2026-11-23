# Working on Gotoquill Local

Gotoquill is an Apache 2.0 MCP server for human-confirmed PDF signing. Form filling is out of scope. A human must review and consent in the UI. Use the synthetic examples, never private documents or signing links in issues or commits.

The Python package and vault are in `gotoquill/`, browser assets in `web/`, self-hosted relays in `relay/`, adapters in `packages/` and `integrations/`, and examples in `examples/`. Cloud is a separate hosted service with a private implementation.

Install from this checkout with `python -m pip install -e '.[dev]'`. Run `python -m pytest -q`. Keep tests offline using the fake relay fixture. See [CONTRIBUTING](CONTRIBUTING.md), [LICENSE](LICENSE), [NOTICE](NOTICE), [CLA](CLA.md) and [TRADEMARK](TRADEMARK.md). The CLA, trademark policy and Cloud data-handling texts are approved. CLA signing is inactive; keep `CLA_ENABLED` off until separate owner approval.

Do not publish, deploy, submit, collect signatures, or change remotes without the owner's explicit authorization. Do not print credentials or pairing codes. The exporter preserves destination Git history and does not configure remotes. Preparing this tree is not permission to publish it.
