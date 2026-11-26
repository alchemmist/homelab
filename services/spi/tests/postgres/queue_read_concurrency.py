"""Run against a fresh disposable PostgreSQL instance via SPI_TEST_PG_SOCKET."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from core import Store


class PostgresQueueReads(unittest.TestCase):
    def test_postgres_reader_does_not_wait_for_writer(self):
        from unittest.mock import patch
        import psycopg
        url = 'host=' + os.environ['SPI_TEST_PG_SOCKET'] + ' dbname=spi_queue_test'
        with patch.dict(os.environ, SPI_POSTGRES_URL=url):
            store = Store(':memory:')
            with store.db() as writer:
                writer.execute('INSERT INTO dispatch VALUES(1,?,?,?)', ('reserved', 42, 1))
                self.assertEqual(store.health()['counts'], {})
                self.assertEqual(store.dispatch_status()['attempts'], 0)
                with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction), store.read_db() as reader:
                    reader.execute('DELETE FROM dispatch')
            self.assertEqual(store.dispatch_status()['attempts'], 1)


if __name__ == "__main__":
    unittest.main()
