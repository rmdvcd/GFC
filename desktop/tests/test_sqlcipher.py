import tempfile
import unittest
from pathlib import Path
from fichacosto.repositorio import RepositorioFichas


class SqlCipherTest(unittest.TestCase):
    def test_licensing_state_and_quota_are_persisted_in_sqlcipher(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "licensing.db"
            repo = RepositorioFichas(path, "test-local-key")
            repo.license_set_state("last_seen_ts", "2026-10-28T12:00:00Z")
            self.assertEqual(repo.license_get_state("last_seen_ts"), "2026-10-28T12:00:00Z")
            self.assertTrue(repo.license_consume_quota("id-1", "fichas", 1))
            self.assertFalse(repo.license_consume_quota("id-1", "fichas", 1))
            repo.cerrar()
            reopened = RepositorioFichas(path, "test-local-key")
            self.assertEqual(reopened.license_get_usage("id-1", "fichas"), 1)
            reopened.cerrar()

    def test_database_is_encrypted_and_key_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fichas.db"
            repo = RepositorioFichas(path, "test-local-key")
            version = repo.db.execute("PRAGMA cipher_version").fetchone()[0]
            self.assertTrue(version)
            repo.db.close()
            self.assertNotEqual(path.read_bytes()[:16], b"SQLite format 3\x00")
            with self.assertRaises(Exception):
                RepositorioFichas(path, "wrong-key")
            reopened = RepositorioFichas(path, "test-local-key")
            reopened.cerrar()

if __name__ == "__main__": unittest.main()
