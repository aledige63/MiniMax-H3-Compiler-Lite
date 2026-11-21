import asyncio
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

from scripts import launcher
from scripts.build_packages import build, verify_archive
from scripts.guided_server import GuidedServer
import uvicorn


class PackagingTests(unittest.TestCase):
    def test_browser_opens_only_after_successful_server_startup(self):
        for started in (False, True):
            server = GuidedServer(uvicorn.Config('unused'))
            server.started, server.open_browser = started, True
            server.local_url = 'http://127.0.0.1:18767/'
            with patch.object(uvicorn.Server, 'startup', new=AsyncMock()), \
                    patch('scripts.guided_server.threading.Thread') as thread:
                asyncio.run(server.startup())
                self.assertEqual(thread.call_count, int(started))
                if started:
                    thread.return_value.start.assert_called_once()

    def test_both_zips_are_reproducible_and_include_only_verified_runtime_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            first = build(output)
            self.assertEqual(first, build(output))
            for package in first['packages']:
                path = output / package['file']
                manifest = verify_archive(path)
                self.assertEqual(manifest['compiler_source_commit'], first['compiler_source_commit'])
                self.assertEqual(manifest['license'], 'MIT')
                self.assertEqual(manifest['copyright'], 'Copyright (c) 2026 aledige')
                self.assertTrue(manifest['runtime_matches_reference'])
                self.assertEqual(set(manifest['documentation']), {'it', 'en'})
                self.assertNotIn('data', {name.split('/')[0] for name in manifest['files']})
                with zipfile.ZipFile(path) as archive:
                    prefix = archive.namelist()[0].split('/')[0] + '/'
                    self.assertIn(b'Copyright (c) 2026 aledige', archive.read(prefix + 'LICENSE'))
                    notices = archive.read(prefix + 'THIRD-PARTY-NOTICES.md').decode('utf-8')
                    self.assertIn('Italiano', notices)
                    self.assertIn('English', notices)
                    for language, documents in manifest['documentation'].items():
                        for name in documents:
                            self.assertIn(name, manifest['files'])
                            self.assertTrue(archive.read(prefix + name), (language, name))
                    for name in manifest['files']:
                        self.assertNotIn(b'/Users/', archive.read(prefix + name), name)
                    self.assertIn(b'DEFAULT_TEXT_MODEL = ""', archive.read(prefix + 'app/interpreter.py'))
                    self.assertIn(b'Scegli un modello testo', archive.read(prefix + 'app/static/index.html'))
                    wrapper = 'Avvia.command' if package['platform'] == 'macos-arm64' else 'Avvia.cmd'
                    item = next(item for item in archive.infolist() if item.filename.endswith('/' + wrapper))
                    if wrapper.endswith('.command'):
                        self.assertEqual((item.external_attr >> 16) & 0o777, 0o755)
                    else:
                        self.assertNotIn(b'\n', archive.read(item).replace(b'\r\n', b''))
                with zipfile.ZipFile(path, 'a') as archive:
                    archive.writestr('unexpected-private-file.txt', 'not allowed')
                with self.assertRaisesRegex(ValueError, 'differisce dal manifesto'):
                    verify_archive(path)

    def test_source_runtime_change_is_rejected_before_distribution(self):
        from scripts import build_packages
        original = build_packages.prepared_bytes

        def changed(name):
            content = original(name)
            return content + b'\n# unexpected change\n' if name == 'app/api.py' else content

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(build_packages, 'prepared_bytes', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'runtime differisce'):
                build(Path(directory))

    def test_personal_data_path_is_stable_on_both_platforms_and_linux_is_rejected(self):
        home = Path('/synthetic-home')
        self.assertEqual(launcher.default_data_dir('Darwin', home, {}),
                         home / 'Library/Application Support/MiniMax H3 Compiler Lite/data')
        self.assertEqual(launcher.default_data_dir('Windows', home, {'LOCALAPPDATA': '/synthetic-local'}),
                         Path('/synthetic-local/MiniMax H3 Compiler Lite/data'))
        with self.assertRaises(ValueError):
            launcher.default_data_dir('Linux', home, {})
        with self.assertRaises(ValueError):
            launcher.default_data_dir('Windows', home, {})

    def test_wrong_python_architecture_and_foreign_zip_are_rejected_before_installing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(launcher.sys, 'version_info', (3, 13, 0)):
                with self.assertRaisesRegex(ValueError, 'Python 3.12'):
                    launcher.check_runtime(root)
            with patch.object(launcher.platform, 'system', return_value='Darwin'), \
                    patch.object(launcher.platform, 'machine', return_value='x86_64'):
                with self.assertRaisesRegex(ValueError, 'Rosetta'):
                    launcher.check_runtime(root)
            (root / 'release-manifest.json').write_text(json.dumps({'platform': 'windows-x64'}))
            with patch.object(launcher.platform, 'system', return_value='Darwin'), \
                    patch.object(launcher.platform, 'machine', return_value='arm64'):
                with self.assertRaisesRegex(ValueError, 'altra piattaforma'):
                    launcher.check_runtime(root)
