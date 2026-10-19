import json
import pathlib
import sqlite3
import sys

database = pathlib.Path(sys.argv[1]).resolve()
connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
try:
    integrity = connection.execute("PRAGMA quick_check").fetchall()
    if integrity != [("ok",)]:
        raise RuntimeError(str(integrity))
    tables = sorted(row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    counts = {table: connection.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0] for table in tables}
    print(json.dumps(counts, sort_keys=True))
finally:
    connection.close()
