"""Offline only. Large-sort reproduction is opt-in with a host RO fixture."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import unittest

spec = importlib.util.spec_from_file_location('retry', Path(__file__).resolve().parents[1] / 'scripts/n8n/spi_operator_retry.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class HashTests(unittest.TestCase):
    def connection(self):
        c = sqlite3.connect(':memory:', isolation_level=None)
        c.row_factory = sqlite3.Row
        self.addCleanup(c.close)
        return c

    def test_orders_and_identifiers(self):
        for ddl in ('CREATE TABLE "a""b"("rowid" TEXT, "oid" TEXT, k TEXT, v BLOB)',
                    'CREATE TABLE "a""b"(k TEXT, v BLOB, PRIMARY KEY(k DESC)) WITHOUT ROWID'):
            with self.subTest(ddl=ddl):
                c = self.connection()
                c.execute(ddl)
                n = len(c.execute('SELECT * FROM "a""b"').description)
                for key in ('z', 'a', 'm'):
                    c.execute('INSERT INTO "a""b" VALUES(' + ','.join('?' for _ in range(n)) + ')', ([key] * (n-1) + [b'payload']))
                c.execute('BEGIN IMMEDIATE')
                before = m.table_hashes(c)
                self.assertEqual(before, m.table_hashes(c))
                c.execute('UPDATE "a""b" SET v=?', (b'changed',))
                self.assertNotEqual(before, m.table_hashes(c))
                c.rollback()
                self.assertEqual(before, m.table_hashes(c))

    def test_shadowed_aliases_refused(self):
        c = self.connection()
        c.execute('CREATE TABLE t(rowid, _rowid_, oid, value)')
        with self.assertRaisesRegex(ValueError, 'shadowed'):
            m.table_hashes(c)

    def test_virtual_refused(self):
        c = self.connection()
        c.execute('CREATE VIRTUAL TABLE t USING fts5(value)')
        with self.assertRaisesRegex(ValueError, 'unsupported table kind'):
            m.table_hashes(c)

    def test_physical_order_is_not_external_canonical(self):
        hashes = []
        for values in (('a', 'b'), ('b', 'a')):
            c = self.connection()
            c.execute('CREATE TABLE t(value)')
            c.executemany('INSERT INTO t VALUES(?)', [(v,) for v in values])
            hashes.append(m.table_hashes(c))
        self.assertNotEqual(*hashes)

    @unittest.skipUnless(os.environ.get('SPI_SORT_FIXTURE'), 'requires host fixture and tiny container tmpfs')
    def test_disk_full_sort_reproduction(self):
        c = sqlite3.connect('file:' + os.environ['SPI_SORT_FIXTURE'] + '?mode=ro', uri=True, isolation_level=None)
        self.addCleanup(c.close)
        c.row_factory = sqlite3.Row
        self.assertEqual(c.execute('PRAGMA temp_store').fetchone()[0], 0)
        c.execute('BEGIN IMMEDIATE')
        with self.assertRaisesRegex(sqlite3.OperationalError, 'database or disk is full'):
            for _ in c.execute('SELECT * FROM payload ORDER BY 1,2'):
                pass
        self.assertTrue(m.table_hashes(c)['payload'])
        self.assertEqual(len(m.table_hashes(c)['payload']), 64)
        c.rollback()


if __name__ == '__main__':
    unittest.main()
