import contextlib
import io
import subprocess
import tempfile
import unittest
import webbrowser
from pathlib import Path
from unittest.mock import MagicMock, patch

from device_observability.launcher import main, read_access
from scripts.install_launcher import install


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.access = self.root / 'access.url'
        self.url = 'http://127.0.0.1:8765/#access=test-only-not-a-real-credential'
        self.access.write_text(self.url)
        self.access.chmod(0o600)

    def tearDown(self):
        self.temporary.cleanup()

    def test_browser_receives_private_open_request_without_printing_credentials(self):
        for arguments in ([], ['--browser','firefox']):
            with patch('device_observability.launcher.open_private',return_value=True) as target, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(arguments, access_path=self.access), 0)
                target.assert_called_once_with(self.url, 'firefox' if arguments else None)
                self.assertNotIn('test-only', output.getvalue())

    def test_browser_failures_do_not_log_private_url_and_exit_with_failure(self):
        for error in (webbrowser.Error(self.url), ValueError(self.url), OSError(self.url)):
            with patch('device_observability.launcher.open_private',side_effect=error), contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(main([], access_path=self.access), 1)
                self.assertNotIn('test-only', output.getvalue())
        with patch('device_observability.launcher.open_private',return_value=False), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([], access_path=self.access), 1)

    def test_access_requires_private_permissions_and_a_loopback_address(self):
        self.access.chmod(0o644)
        with self.assertRaises(ValueError): read_access(self.access)
        self.access.chmod(0o600)
        for url in ('https://example.com/#access=key', 'http://localhost:8765/#access=key',
                    'http://127.0.0.1:8765/?query=key#access=key', 'http://127.0.0.1:8765/#access='):
            self.access.write_text(url)
            with self.assertRaises(ValueError): read_access(self.access)

    def test_check_is_readonly_and_does_not_launch_a_browser_or_send_the_key(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.status = 200
        with patch('device_observability.launcher.urllib.request.build_opener',return_value=opener), \
             patch('device_observability.launcher.open_private') as browser, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--check'],access_path=self.access), 0)
            opener.open.assert_called_once_with('http://127.0.0.1:8765/',timeout=5)
            browser.assert_not_called()
            self.assertNotIn('test-only', output.getvalue())

    def test_install_is_idempotent_for_managed_command_and_quotes_paths_and_arguments(self):
        project = self.root / "project with spaces ' and $ characters"
        script = project / 'scripts/open_interface.py'
        script.parent.mkdir(parents=True)
        script.write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\n')
        installed = install(self.root, project)
        self.assertEqual(installed.stat().st_mode & 0o777, 0o755)
        original = installed.read_text()
        self.assertEqual(install(self.root,project).read_text(), original)
        result = subprocess.run([str(installed),'--browser','value with spaces'],capture_output=True,text=True,check=True)
        self.assertEqual(result.stdout.strip(), '["--browser", "value with spaces"]')

    def test_install_never_replaces_unmanaged_files_or_links(self):
        project = self.root / 'project'
        (project / 'scripts').mkdir(parents=True)
        (project / 'scripts/open_interface.py').write_text('pass')
        destination = self.root / '.local/bin/vatilume'
        destination.parent.mkdir(parents=True)
        destination.write_text('existing user command')
        with self.assertRaises(ValueError): install(self.root,project)
        self.assertEqual(destination.read_text(),'existing user command')
        destination.unlink()
        destination.symlink_to(self.root/'missing')
        with self.assertRaises(ValueError): install(self.root,project)
        self.assertTrue(destination.is_symlink())


if __name__ == '__main__': unittest.main()
