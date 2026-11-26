"""Existing behavioural tests, unique PG schema per temporary SQLite path; disposable DB only."""
import hashlib, os,sys,unittest
from pathlib import Path
from unittest.mock import patch
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
root=Path(__file__).resolve().parents[1];sys.path[:0]=[str(root/'backend'),str(root/'tests/backend')];from core import Store
url=os.environ['SPI_TEST_PG']; schemas=set(); orig=Store.__init__
def init(self,path,*args,**kw):
    schema='test_'+hashlib.sha256(str(path).encode()).hexdigest()[:24]
    if schema not in schemas:
        with psycopg.connect(url) as db:db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        schemas.add(schema)
    with patch.dict(os.environ,SPI_POSTGRES_URL=make_conninfo(url,options='-c search_path='+schema)):orig(self,path,*args,**kw)
try:
    with patch.object(Store,'__init__',init):
        suite=unittest.defaultTestLoader.discover(str(root/'tests/backend'));ok=unittest.TextTestRunner().run(suite).wasSuccessful()
finally:
    with psycopg.connect(url,autocommit=True) as db:
        for schema in schemas:db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
sys.exit(not ok)
