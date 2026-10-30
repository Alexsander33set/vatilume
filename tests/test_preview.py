import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('prepare_preview', ROOT / 'scripts/prepare_preview.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class PreviewBoundaryTests(unittest.TestCase):
    def archive(self, directory, entries, manifest=None):
        path = Path(directory) / 'source.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            for name, data in entries:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            if manifest is not None:
                data = json.dumps({'files': manifest}).encode()
                info = tarfile.TarInfo('vatilume/SOURCE-MANIFEST.json')
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        return path

    def test_tampered_source_fails_even_with_a_present_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.archive(directory, [('vatilume/README.md', b'changed')],
                                {'vatilume/README.md': hashlib.sha256(b'original').hexdigest()})
            with self.assertRaisesRegex(ValueError, 'differs from its manifest'):
                preview.source_entries(path)

    def test_duplicate_archive_entries_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.archive(directory, [('vatilume/file', b'first'), ('vatilume/file', b'second')])
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                preview.source_entries(path)

    def test_traversal_and_private_state_cannot_enter_sources(self):
        for name in ('vatilume/../outside', '/vatilume/file', 'vatilume/var/telemetry.sqlite3', 'vatilume/.git/config'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = self.archive(directory, [(name, b'private')])
                with self.assertRaises(ValueError):
                    preview.source_entries(path)

    def test_matching_bytes_without_manifest_are_insufficient(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.archive(directory, [('vatilume/README.md', b'hello')])
            with self.assertRaisesRegex(ValueError, 'manifest missing'):
                preview.source_entries(path)
