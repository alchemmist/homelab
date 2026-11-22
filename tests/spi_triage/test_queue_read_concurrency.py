"""Queue telemetry must not contend for SQLite's one WAL writer."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'charts/spi-triage/files'))
from core import Store


def test_health_reads_during_open_writer(tmp_path):
    store = Store(tmp_path / 'queue.sqlite')
    with store.db() as writer:
        writer.execute('INSERT INTO dispatch VALUES(1,?,?,?)', ('reserved', 42, 1))
        assert store.health()['counts'] == {}
        assert store.dispatch_status()['attempts'] == 0
        with store.read_db() as reader, pytest.raises(sqlite3.OperationalError, match='readonly'):
            reader.execute('DELETE FROM dispatch')
    assert store.dispatch_status()['attempts'] == 1
