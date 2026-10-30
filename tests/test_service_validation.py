import tempfile
import unittest
from pathlib import Path

from device_observability.config import Config
from device_observability.storage import Store
from scripts.validate_service import current_session_has_sample, snapshot
from test_storage import frame


class ServiceValidationTests(unittest.TestCase):
    def test_new_session_alone_does_not_prove_new_committed_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "telemetry.sqlite3"
            config = Config(Path(directory))
            store = Store(path)
            try:
                old = store.start("old-boot", config, {})
                store.append(old, frame(), config, [])
                previous = snapshot(path)
                new = store.start("new-boot-simulated", config, {})
                self.assertFalse(current_session_has_sample(snapshot(path)))
                store.append(new, frame(), config, [])
                after = snapshot(path, previous["through_id"])
                self.assertTrue(current_session_has_sample(after))
                self.assertEqual(previous["prefix_sha256"], after["prefix_sha256"])
            finally:
                store.close()

    def test_no_session_or_no_data_cannot_pass(self):
        self.assertFalse(current_session_has_sample({"session": None, "latest_sample_session_id": None}))
        self.assertFalse(current_session_has_sample({"session": {"id": "new"}, "latest_sample_session_id": None}))


if __name__ == "__main__":
    unittest.main()
