"""Fail closed on missing setup outputs, missing jobs, failures and unexpected skips."""
import argparse
import json
import os
from ci_filter import AREAS


def expected_jobs(outputs, private=False):
    flags = {}
    for key in (*AREAS, 'heavy', 'full'):
        if outputs.get(key) not in ('true', 'false'):
            raise ValueError(f'Missing or invalid setup output: {key}')
        flags[key] = outputs[key] == 'true'
    full = flags['full']
    versions = ['3.10', '3.11', '3.12', '3.13'] if full else ['3.10', '3.13']
    if json.loads(outputs['python-versions']) != versions:
        raise ValueError('Unexpected Python matrix')
    contract_tests = json.loads(outputs['contract-tests'])
    if not isinstance(contract_tests, list) or (flags['contracts'] and not contract_tests):
        raise ValueError('Missing contract test selection')
    areas = AREAS if private else ('python', 'ts', 'contracts')
    if flags['heavy'] != any(flags[area] for area in areas):
        raise ValueError('Inconsistent heavy output')
    if full and not all(flags[area] for area in areas):
        raise ValueError('Incomplete full selection')
    expected = {
        'ci-light': not flags['heavy'],
        'test': flags['python'] or full,
        'ts-tests': flags['ts'] or full,
        'contracts': flags['contracts'] and not flags['python'] and not full,
    }
    if private:
        expected.update({
            'worker-tests': flags['worker'] or full,
            'browser-e2e': flags['browser'] or full,
            'site-security': flags['site'] or full,
            'plugin-package': flags['plugin'] or full,
            'dependency-security': flags['npm-audit'] or flags['pip-audit'] or full,
            'build': flags['build'] or full,
        })
    return expected


def verify(needs, private=False):
    if needs.get('setup', {}).get('result') != 'success':
        raise ValueError('Setup did not succeed')
    expected = expected_jobs(needs['setup']['outputs'], private)
    if set(needs) != {'setup', *expected}:
        raise ValueError('Missing or unaccounted validation jobs')
    for job, selected in expected.items():
        result = needs[job]['result']
        if result != ('success' if selected else 'skipped'):
            raise ValueError(f'{job}: expected {"success" if selected else "skipped"}, got {result}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--private', action='store_true')
    args = parser.parse_args()
    verify(json.loads(os.environ['CI_NEEDS']), args.private)
    print('All selected validation jobs succeeded.')
