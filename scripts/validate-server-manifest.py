"""Validate prepared metadata against the official registry schema. Never publish."""
import json
from pathlib import Path
from urllib.request import urlopen

from jsonschema import Draft7Validator, FormatChecker

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "server.json").read_text())
with urlopen(manifest["$schema"], timeout=30) as response:
    schema = json.load(response)
Draft7Validator.check_schema(schema)
Draft7Validator(schema, format_checker=FormatChecker()).validate(manifest)
assert manifest["packages"][0]["transport"]["type"] == "stdio"
assert manifest["remotes"] == [{"type": "streamable-http", "url": "https://mcp.gotoquill.com/mcp"}]
assert manifest["name"] == "io.github.gotoquill/gotoquill"
assert manifest["repository"]["url"] == "https://github.com/gotoquill/gotoquill"
print("Registry schema valid; validation does not publish.")
