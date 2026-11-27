"""Conservative CI selection. No dependencies, network, or GitHub API required."""
import argparse
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess

AREAS = ('python', 'ts', 'contracts', 'worker', 'site', 'plugin', 'browser',
         'build', 'npm-audit', 'pip-audit')
CONTRACTS = {
    'notices': 'tests/test_legal_notices.py',
    'policy': 'tests/test_bilingual_policy_sync.py',
    'cloud': 'tests/test_cloud_legal_notices.py',
    'export': 'tests/test_public_export.py',
    'placement': 'tests/test_placement_hebrew.py',
}


def select(paths, *, private=False, full=False):
    selected = set()
    contracts = set()
    available = set(AREAS if private else ('python', 'ts', 'contracts'))

    def all_areas():
        selected.update(available)
        contracts.update(CONTRACTS if private else ('notices',))

    if full:
        all_areas()
    for path in paths:
        name = path.rsplit('/', 1)[-1]
        # Shared infrastructure and locks precede all documentation allowances.
        if (path.startswith(('.github/workflows/', '.github/actions/', '.github/scripts/',
                             'scripts/public-export/', 'scripts/export-public-tree.',
                             'packages/conformance/', 'tests/fixtures/'))
                or name in ('uv.lock', 'package-lock.json', 'pyproject.toml', 'conftest.py')
                or fnmatch.fnmatchcase(name, 'requirements*.txt')
                or path in ('tests/pdfmake.py', 'package.json')):
            all_areas()
        elif private and path == 'docs/assets/social-preview.png':
            selected.add('worker')
        elif private and path.startswith('cloud/worker-ts/'):
            selected.update(('worker', 'contracts'))
            contracts.update(('policy', 'cloud', 'export'))
            relative = path.removeprefix('cloud/worker-ts/')
            if (relative.startswith(('src/', 'public/', 'scripts/', 'e2e/', 'test/fixtures/'))
                    or relative == 'package.json'
                    or relative.startswith(('wrangler', 'tsconfig', 'playwright'))):
                selected.add('browser')
            if relative == 'package.json':
                selected.update(('plugin', 'npm-audit'))
            if relative.startswith('test/fixtures/'):
                contracts.add('placement')
        elif private and (path.startswith(('cloud/site/', 'cloud/preview-site/', 'cloud/cf-site/'))
                          or path in ('scripts/test/connection-chooser.test.mjs',
                                      'scripts/sync-legal-pages.py', 'scripts/build-draft-data-handling.py')):
            # Worker asset and audit regressions import the site implementation.
            selected.update(('site', 'worker', 'contracts'))
            contracts.update(('policy', 'cloud', 'export'))
        elif private and (path.startswith('docs/cloud/') or path in (
                'scripts/build-chatgpt-plugin-zip.mjs', 'scripts/test/build-chatgpt-plugin-zip.test.mjs')):
            selected.add('contracts')
            contracts.update(('policy', 'cloud', 'export'))
            if path.startswith('docs/cloud/submission/') or path.startswith('scripts/'):
                selected.add('plugin')
            if path.startswith('docs/cloud/submission/'):
                selected.add('worker')
        elif path.startswith(('web/', 'schemas/')):
            selected.update(('python', 'ts'))
            if private:
                selected.update(('worker', 'browser'))
        elif path.startswith(('gotoquill/', 'tests/')) or path in (
                '.python-version', 'pytest.ini', 'setup.cfg', 'tox.ini'):
            selected.add('python')
            if private and (path.startswith('gotoquill/static/') or path in ('gotoquill/pdf.py', 'gotoquill/pdfdoc.py',
                                    'gotoquill/placement.py', 'gotoquill/labels.py',
                                    'gotoquill/core.py', 'gotoquill/tools.py', 'gotoquill/sealed.py')):
                selected.update(('worker', 'browser'))
        elif path.startswith('packages/ts/'):
            selected.add('ts')
        elif (path in ('README.md', 'DISCLAIMER.md', 'THIRD_PARTY_NOTICES.md', 'CLA.md', 'TRADEMARK.md')
              or ('/' not in path and name.startswith(('LICENSE', 'NOTICE')))):
            selected.add('contracts')
            contracts.add('notices')
            if private:
                selected.add('build')
                contracts.add('export')
                if path == 'README.md':
                    selected.add('site')
        elif path.startswith(('packages/', 'integrations/', 'skills/')):
            # Packaged Markdown is not ordinary prose.
            all_areas()
        elif (path.startswith(('docs/', '.github/ISSUE_TEMPLATE/')) or path.endswith('.md')
              or path in ('.github/FUNDING.yml', '.github/CODEOWNERS')):
            pass
        else:
            # Unknown paths select every area, but keep the event's Python matrix.
            all_areas()
    if private and 'python' in selected:
        selected.add('build')
    output = {area: str(area in selected).lower() for area in AREAS}
    output.update({
        'heavy': str(bool(selected)).lower(),
        'full': str(full).lower(),
        'python-versions': json.dumps(['3.10', '3.11', '3.12', '3.13'] if full else ['3.10', '3.13']),
        'contract-tests': json.dumps([CONTRACTS[key] for key in sorted(contracts)]),
    })
    return output


def changed_paths(event, event_name, head):
    if event_name == 'pull_request':
        base = event['pull_request']['base']['sha']
    elif event_name == 'push':
        base = event['before']
    else:
        raise ValueError('Unsupported event without full verification')
    for sha in (base, head):
        if not re.fullmatch(r'[0-9a-fA-F]{40,64}', sha) or set(sha) == {'0'}:
            raise ValueError('Missing diff history; refusing a light pass')
    # --no-renames represents renames as delete + add, preserving BOTH names.
    # NUL separation handles whitespace, newlines and non-UTF-8 filenames.
    result = subprocess.run(['git', 'diff', '--no-ext-diff', '--no-renames', '--name-only',
                             '-z', base, head, '--'], check=True, capture_output=True)
    return [os.fsdecode(p) for p in result.stdout.split(b'\0') if p]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--private', action='store_true')
    args = parser.parse_args()
    event_name = os.environ['GITHUB_EVENT_NAME']
    # Reusable workflows retain their caller's event name (tag push).
    full = event_name in ('schedule', 'workflow_dispatch') or os.environ.get('FORCE_FULL') == 'true'
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    paths = [] if full else changed_paths(event, event_name, os.environ['GITHUB_SHA'])
    output = select(paths, private=args.private, full=full)
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        for key, value in output.items():
            print(f'{key}={value}', file=stream)
    print(json.dumps(output, sort_keys=True))


if __name__ == '__main__':
    main()
