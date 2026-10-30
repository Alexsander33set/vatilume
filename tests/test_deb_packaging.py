import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from device_observability import deb_access

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('build_deb', ROOT / 'scripts/build_deb.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class AccessBoundaryTests(unittest.TestCase):
    def test_caller_comes_only_from_polkit_identity(self):
        for environment in ({}, {'SUDO_USER': 'someone'}, {'PKEXEC_UID': '0'}, {'PKEXEC_UID': '../1000'}, {'PKEXEC_UID': '١٠٠٠'}):
            with self.subTest(environment=environment), self.assertRaises((ValueError, KeyError)):
                deb_access.caller_uid(environment)
        with patch.object(deb_access.pwd, 'getpwuid') as lookup:
            lookup.return_value.pw_gid = 1000
            lookup.return_value.pw_shell = '/bin/bash'
            self.assertEqual(deb_access.caller_uid({'PKEXEC_UID': '1000'}), (1000, 1000))

    def test_token_rejects_symlinks_permissions_content_and_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            token = Path(directory) / 'token'
            token.write_text('a' * 43)
            token.chmod(0o600)
            self.assertEqual(deb_access.private_token(token, os.getuid()), 'a' * 43)
            with self.assertRaises(ValueError):
                deb_access.private_token(token, os.getuid() + 1)
            token.chmod(0o644)
            with self.assertRaises(ValueError):
                deb_access.private_token(token, os.getuid())
            token.chmod(0o600)
            token.write_text('a' * 500)
            with self.assertRaises(ValueError):
                deb_access.private_token(token, os.getuid())
            link = Path(directory) / 'link'
            link.symlink_to(token)
            with self.assertRaises(OSError):
                deb_access.private_token(link, os.getuid())

    def test_fifo_rejected_without_blocking_root_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory) / 'fifo'
            os.mkfifo(fifo, 0o600)
            with self.assertRaises(ValueError):
                deb_access.private_token(fifo, os.getuid())

    def test_access_directory_must_be_root_owned_and_not_writable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            path.chmod(0o777)
            with self.assertRaises(ValueError):
                deb_access.grant(os.getuid(), os.getgid(), 'a' * 43, path)
            self.assertEqual(list(path.iterdir()), [])


class PackageInputTests(unittest.TestCase):
    def test_no_unlocked_wheel_can_enter_package(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'unexpected-1.0-py3-none-any.whl').write_bytes(b'not a locked wheel')
            with self.assertRaisesRegex(ValueError, 'not hash-locked'):
                builder.locked_wheels(path, 'unexpected==1.0\n')

    def test_missing_dependencies_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'exactly'):
                builder.locked_wheels(Path(directory), 'fastapi==0.162.0\n')

    def test_wheel_cannot_escape_vendor_directory(self):
        import zipfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wheel = root / 'bad.whl'
            with zipfile.ZipFile(wheel, 'w') as archive:
                archive.writestr('../outside', 'bad')
            with self.assertRaisesRegex(ValueError, 'path'):
                builder.unpack_wheel(wheel, root / 'vendor')
            self.assertFalse((root / 'outside').exists())

    def test_desktop_entry_has_no_privileged_or_secret_arguments(self):
        desktop = (ROOT / 'packaging/debian/vatilume.desktop').read_text()
        self.assertIn('Exec=/usr/bin/vatilume\n', desktop)
        self.assertNotIn('pkexec', desktop)
        self.assertNotIn('#access=', desktop)
