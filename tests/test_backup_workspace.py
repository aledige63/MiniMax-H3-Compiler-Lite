import hashlib
import os
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from app.workspace_lock import workspace_lock
from scripts.backup_workspace import create, restore, verify


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / 'project'
        self.data = self.project / 'data'
        (self.data / 'media').mkdir(parents=True)
        self.media = self.data / 'media/original.bin'
        self.media.write_bytes(b'original media bytes')
        (self.data / 'access.json').write_text('{"fixture":"private settings"}')
        (self.project / 'models').mkdir()
        (self.project / 'models/weights.bin').write_bytes(b'local model fixture')
        self.db = sqlite3.connect(self.data / 'workspace.sqlite3')
        self.db.executescript('PRAGMA journal_mode=WAL; CREATE TABLE entries(id INTEGER PRIMARY KEY,value TEXT);'
                             'CREATE TABLE media(id TEXT PRIMARY KEY,relative_path TEXT,sha256 TEXT);')
        self.db.execute('INSERT INTO entries VALUES (?,?)', (1, 'saved in the WAL'))
        self.db.execute('INSERT INTO media VALUES (?,?,?)', ('media-id', 'media/original.bin', hashlib.sha256(self.media.read_bytes()).hexdigest()))
        self.db.commit()
        self.backup = self.root / 'backup'

    def tearDown(self):
        self.db.close()
        self.temporary.cleanup()

    def test_full_roundtrip_includes_wal_content_media_settings_and_local_weights(self):
        self.assertGreater((self.data / 'workspace.sqlite3-wal').stat().st_size, 0)
        report = create(self.project, self.backup)
        self.assertTrue(report['verified'])
        self.assertEqual(report['media_files_checked'], 1)
        self.assertFalse((self.backup / 'data/workspace.sqlite3-wal').exists())
        self.assertFalse((self.backup / 'data/service.lock').exists())
        if os.name != 'nt':
            self.assertEqual(self.backup.stat().st_mode & 0o777, 0o700)
            self.assertEqual((self.backup / 'data/access.json').stat().st_mode & 0o777, 0o600)
        destination = self.root / 'recovered'
        self.assertTrue(restore(self.backup, destination)['restored'])
        with closing(sqlite3.connect(destination / 'data/workspace.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT value FROM entries').fetchone()[0], 'saved in the WAL')
        self.assertEqual((destination / 'data/media/original.bin').read_bytes(), self.media.read_bytes())
        self.assertEqual((destination / 'data/access.json').read_bytes(), (self.data / 'access.json').read_bytes())
        self.assertEqual((destination / 'models/weights.bin').read_bytes(), b'local model fixture')

    def test_running_server_or_active_jobs_prevent_copying(self):
        with workspace_lock(self.data):
            with self.assertRaisesRegex(ValueError, 'Ferma prima il servizio'):
                create(self.project, self.backup)
        self.assertFalse(self.backup.exists())
        self.db.executescript("CREATE TABLE jobs(data TEXT); INSERT INTO jobs VALUES ('{\"status\":\"running\"}');")
        with self.assertRaisesRegex(ValueError, 'Lavori attivi'):
            create(self.project, self.backup)
        self.assertFalse(self.backup.exists())

    def test_corruption_or_missing_files_block_restore_before_destination_is_created(self):
        create(self.project, self.backup)
        path = self.backup / 'data/media/original.bin'
        path.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'Integrità'):
            restore(self.backup, self.root / 'recovered')
        self.assertFalse((self.root / 'recovered').exists())
        path.unlink()
        with self.assertRaisesRegex(ValueError, 'elenco dei file'):
            verify(self.backup)

    def test_existing_destinations_and_nested_sources_are_never_overwritten(self):
        with self.assertRaises(ValueError):create(self.project, self.data / 'nested')
        create(self.project, self.backup)
        existing = self.root / 'existing'
        existing.mkdir(); (existing / 'keep.txt').write_text('keep')
        with self.assertRaises(ValueError):restore(self.backup, existing)
        self.assertEqual((existing / 'keep.txt').read_text(), 'keep')
        with self.assertRaises(ValueError):create(self.project, self.backup)

    def test_symlink_source_is_rejected(self):
        try:
            (self.data / 'external-link').symlink_to(self.media)
        except OSError as error:
            if getattr(error, 'winerror', None) == 1314:
                self.skipTest('Windows account cannot create symbolic links')
            raise
        with self.assertRaisesRegex(ValueError, 'Link simbolico'):
            create(self.project, self.backup)

    def test_registered_missing_media_cannot_be_declared_a_verified_backup(self):
        self.media.unlink()
        with self.assertRaisesRegex(ValueError, 'Media mancante'):
            create(self.project, self.backup)

    def test_external_archive_roundtrip_does_not_take_the_checkouts_data_or_models(self):
        external = self.root / 'personal archive'
        external.mkdir()
        with closing(sqlite3.connect(external / 'workspace.sqlite3')) as db:
            db.execute('CREATE TABLE entries(value TEXT)')
            db.execute('INSERT INTO entries VALUES (?)', ('caffè esterno',))
            db.commit()
        (external / 'settings.json').write_text('{"private":"external"}', encoding='utf-8')
        report = create(self.project, self.backup, data_dir=external)
        self.assertTrue(report['verified'])
        self.assertFalse((self.backup / 'models').exists())
        self.assertFalse((self.backup / 'data/media').exists())
        restored = self.root / 'restored'
        restore(self.backup, restored)
        with closing(sqlite3.connect(restored / 'data/workspace.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT value FROM entries').fetchone()[0], 'caffè esterno')
        with workspace_lock(external):
            with self.assertRaisesRegex(ValueError, 'Ferma prima il servizio'):
                create(self.project, self.root / 'other-backup', data_dir=external)
        with self.assertRaises(ValueError):
            create(self.project, external / 'nested', data_dir=external)
        self.assertEqual(self.media.read_bytes(), b'original media bytes')


if __name__ == '__main__':unittest.main()
