"""Exercise classification boundaries, real Git diffs and aggregate failure paths."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ci_filter import AREAS, changed_paths, main, select
from ci_required import expected_jobs, verify


class ClassificationTests(unittest.TestCase):
    def test_docs_are_light_on_pr_and_main(self):
        for private in (False, True):
            result = select(['docs/guide.md', 'AGENTS.md', '.github/ISSUE_TEMPLATE/bug.yml'], private=private)
            self.assertEqual(result['heavy'], 'false')
            self.assertEqual(json.loads(result['python-versions']), ['3.10', '3.13'])

    def test_unknown_locks_and_ci_select_all_with_two_versions(self):
        for private in (False, True):
            for path in ('new/runtime.bin', '.gitignore', 'uv.lock', 'pyproject.toml',
                         'requirements-dev.txt', 'packages/ts/package-lock.json',
                         '.github/workflows/ci.yml', '.github/scripts/ci_filter.py',
                         '.github/actions/install/action.yml', 'tests/conftest.py',
                         'packages/conformance/fixtures/hello.pdf'):
                with self.subTest(private=private, path=path):
                    result = select([path], private=private)
                    for key in (AREAS if private else ('python', 'ts', 'contracts')):
                        self.assertEqual(result[key], 'true')
                    self.assertEqual(result['full'], 'false')
                    self.assertEqual(len(json.loads(result['python-versions'])), 2)

    def test_python_ts_and_shared_protocol(self):
        for private in (False, True):
            python = select(['gotoquill/notify.py'], private=private)
            self.assertEqual(python['python'], 'true')
            self.assertEqual(python['worker'], 'false')
            self.assertEqual(python['ts'], 'false')
            ts = select(['packages/ts/src/pdf.ts'], private=private)
            self.assertEqual(ts['ts'], 'true')
            self.assertEqual(ts['python'], 'false')
            for path in ('web/index.html', 'schemas/functions.json'):
                shared = select([path], private=private)
                self.assertEqual(shared['python'], 'true')
                self.assertEqual(shared['ts'], 'true')
                self.assertEqual(shared['browser'], str(private).lower())

    def test_worker_production_tests_fixtures_and_package(self):
        unit = select(['cloud/worker-ts/test/crypto.test.ts'], private=True)
        self.assertEqual(unit['worker'], 'true')
        self.assertEqual(unit['python'], 'false')
        self.assertEqual(unit['browser'], 'false')
        for path in ('src/index.ts', 'public/sign.html', 'scripts/browser-e2e.mjs',
                     'e2e/entry.ts', 'wrangler.toml', 'tsconfig.json', 'package.json',
                     'test/fixtures/hebrew-geometry.json'):
            self.assertEqual(select(['cloud/worker-ts/' + path], private=True)['browser'], 'true')
        fixtures = select(['cloud/worker-ts/test/fixtures/hebrew-label-cases.json'], private=True)
        self.assertIn('tests/test_placement_hebrew.py', json.loads(fixtures['contract-tests']))
        package = select(['cloud/worker-ts/package.json'], private=True)
        self.assertEqual(package['plugin'], 'true')
        self.assertEqual(package['npm-audit'], 'true')
        self.assertEqual(package['pip-audit'], 'false')

    def test_contract_and_packaged_markdown_exceptions(self):
        for path in ('cloud/site/privacy/index.html', 'cloud/preview-site/privacy/index.html',
                     'docs/cloud/TERMS.md', 'scripts/sync-legal-pages.py'):
            result = select([path], private=True)
            self.assertEqual(result['contracts'], 'true')
            self.assertEqual(result['python'], 'false')
            for test in ('bilingual_policy_sync', 'cloud_legal_notices', 'public_export'):
                self.assertIn(f'tests/test_{test}.py', json.loads(result['contract-tests']))
        packaged = select(['docs/cloud/submission/plugin-build/README.md'], private=True)
        self.assertEqual(packaged['plugin'], 'true')
        self.assertEqual(packaged['contracts'], 'true')
        notice = select(['NOTICE'])
        self.assertEqual(json.loads(notice['contract-tests']), ['tests/test_legal_notices.py'])
        self.assertEqual(notice['python'], 'false')
        mixed = select(['docs/guide.md', 'packages/ts/src/pdf.ts', 'README.md'])
        self.assertEqual(mixed['ts'], 'true')
        self.assertEqual(mixed['contracts'], 'true')

    def test_full_events_and_reusable_tag_caller(self):
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory, 'event.json')
            event.write_text('{}')
            for name, force in (('schedule', 'false'), ('workflow_dispatch', 'false'), ('push', 'true')):
                output = Path(directory, 'output')
                output.write_text('')
                with patch.dict(os.environ, GITHUB_EVENT_NAME=name, GITHUB_EVENT_PATH=str(event),
                                GITHUB_OUTPUT=str(output), FORCE_FULL=force), patch('sys.argv', ['ci_filter.py']):
                    main()
                values = dict(line.split('=', 1) for line in output.read_text().splitlines())
                self.assertEqual(values['full'], 'true')
                self.assertEqual(len(json.loads(values['python-versions'])), 4)

    def test_real_git_diff_renames_deletions_and_unusual_filenames(self):
        with tempfile.TemporaryDirectory() as directory:
            def git(*args):
                return subprocess.check_output(['git', '-C', directory, *args], stderr=subprocess.DEVNULL).decode().strip()
            git('init')
            git('config', 'user.name', 'CI Test')
            git('config', 'user.email', 'ci@example.invalid')
            Path(directory, 'docs').mkdir()
            Path(directory, 'README.md').write_text('old notice')
            Path(directory, 'docs/deleted.md').write_text('deleted')
            git('add', '.')
            git('commit', '-m', 'base')
            base = git('rev-parse', 'HEAD')
            Path(directory, 'README.md').rename(Path(directory, 'docs/renamed\nnotice.md'))
            Path(directory, 'docs/deleted.md').unlink()
            Path(directory, 'docs/new space.md').write_text('new')
            git('add', '-A')
            git('commit', '-m', 'head')
            head = git('rev-parse', 'HEAD')
            previous = os.getcwd()
            try:
                os.chdir(directory)
                for event, name in (({'before': base}, 'push'),
                                    ({'pull_request': {'base': {'sha': base}}}, 'pull_request')):
                    paths = changed_paths(event, name, head)
                    self.assertEqual(set(paths), {'README.md', 'docs/renamed\nnotice.md', 'docs/deleted.md', 'docs/new space.md'})
                    self.assertEqual(select(paths)['contracts'], 'true')
                    self.assertEqual(select(paths)['full'], 'false')
                with self.assertRaises(ValueError):
                    changed_paths({'before': '0' * 40}, 'push', head)
                with self.assertRaises(subprocess.CalledProcessError):
                    changed_paths({'before': 'a' * 40}, 'push', head)
                with self.assertRaises(ValueError):
                    changed_paths({}, 'unknown', head)
            finally:
                os.chdir(previous)


class AggregateTests(unittest.TestCase):
    @staticmethod
    def needs(paths, private=False, full=False):
        outputs = select(paths, private=private, full=full)
        return {'setup': {'result': 'success', 'outputs': outputs}, **{
            job: {'result': 'success' if chosen else 'skipped'}
            for job, chosen in expected_jobs(outputs, private).items()}}

    def test_valid_docs_area_and_full_results(self):
        for private in (False, True):
            for paths, full in ((['docs/guide.md'], False), (['README.md'], False),
                                (['gotoquill/core.py'], False), ([], True)):
                verify(self.needs(paths, private, full), private)

    def test_failed_cancelled_skipped_or_missing_selected_job_fails(self):
        for private in (False, True):
            good = self.needs([], private, True)
            for job in good:
                for result in ('failure', 'cancelled', 'skipped'):
                    # contracts and ci-light are intentionally skipped on full runs.
                    if good[job]['result'] == 'skipped':
                        continue
                    bad = copy.deepcopy(good)
                    bad[job]['result'] = result
                    with self.subTest(job=job, result=result), self.assertRaises(ValueError):
                        verify(bad, private)
                bad = copy.deepcopy(good)
                del bad[job]
                with self.assertRaises(ValueError):
                    verify(bad, private)

    def test_bad_setup_outputs_and_unselected_failures_fail(self):
        good = self.needs(['docs/guide.md'])
        for key in good['setup']['outputs']:
            bad = copy.deepcopy(good)
            del bad['setup']['outputs'][key]
            with self.subTest(key=key), self.assertRaises((ValueError, KeyError)):
                verify(bad)
        for result in ('failure', 'cancelled', 'success'):
            bad = copy.deepcopy(good)
            bad['test']['result'] = result
            with self.assertRaises(ValueError):
                verify(bad)


if __name__ == '__main__':
    unittest.main()
