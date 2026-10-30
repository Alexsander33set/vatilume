import html
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import unquote, urlparse

from device_observability.browser_access import open_private, private_directory, redirect_file


class PrivateBrowserLaunchTests(unittest.TestCase):
    def test_default_http_browser_receives_only_private_file_uri(self):
        with tempfile.TemporaryDirectory() as root:
            url = 'http://127.0.0.1:8765/#access=private-test-capability'
            app = MagicMock(); app.get_id.return_value = 'native.desktop'; app.get_executable.return_value = '/usr/bin/native-browser'
            app.launch_uris.return_value = True
            with patch.dict(os.environ, {'XDG_RUNTIME_DIR': root}), patch('device_observability.browser_access.default_browser', return_value=app):
                self.assertTrue(open_private(url))
            arguments = app.launch_uris.call_args.args
            file_uri = arguments[0][0]
            self.assertNotIn('private-test-capability', str(arguments))
            self.assertTrue(file_uri.startswith('file://'))
            path = Path(unquote(urlparse(file_uri).path))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
            self.assertIn(html.escape(url, quote=True), path.read_text())
            self.assertIn('no-referrer', path.read_text())

    def test_selected_browser_never_receives_authentication_in_arguments(self):
        with tempfile.TemporaryDirectory() as root:
            controller = MagicMock(); controller.open.return_value = True
            with patch('device_observability.browser_access.redirect_directory',return_value=Path(root)), \
                 patch('webbrowser.get', return_value=controller):
                self.assertTrue(open_private('http://127.0.0.1:8765/#access=private-fixture', 'firefox'))
            self.assertNotIn('private-fixture', str(controller.open.call_args))

    def test_public_or_symlink_runtime_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / 'public'; directory.mkdir(mode=0o755)
            with self.assertRaises(ValueError): private_directory(directory)
            link = Path(root) / 'link'; link.symlink_to(Path(root), target_is_directory=True)
            with self.assertRaises(ValueError): private_directory(link)

    def test_repeated_launch_overwrites_file_without_following_old_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root); outside = directory / 'other'; outside.write_text('unchanged')
            (directory / 'open.html').symlink_to(outside)
            redirect_file('http://127.0.0.1:8765/#access=new-private-fixture', directory)
            self.assertEqual(outside.read_text(), 'unchanged')
            self.assertFalse((directory / 'open.html').is_symlink())
            self.assertEqual(list(directory.glob('.open-*')), [])

    def test_redirect_escapes_html_special_characters(self):
        with tempfile.TemporaryDirectory() as root:
            redirect_file('http://127.0.0.1:8765/#access=\"<tag>&', Path(root))
            text = (Path(root) / 'open.html').read_text()
            self.assertNotIn('<tag>', text)
            self.assertIn('&quot;&lt;tag&gt;&amp;', text)
