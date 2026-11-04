"""Durable original-card decoration outbox; no GitHub/model dependencies.

Transport: request(method, path, json=None) -> (HTTP status, decoded dict).
It owns credentials/timeouts and MUST NOT log headers or response bodies.
The current legacy bot cannot safely deliver: guarded_protocol defaults False.
Enable only against reviewed episode/revision + per-copy acknowledgement API.
"""
import json
import re
import time
import uuid
from urllib.parse import urlencode

_URL = re.compile(r'https://github\.com/alchemmist/homelab/issues/([1-9][0-9]*)(?:#issuecomment-([1-9][0-9]*))?\Z')


def primary_url(publication):
    url = publication.get('html_url', '')
    match = _URL.fullmatch(url) if isinstance(url, str) else None
    if not match or int(match[1]) != publication.get('issue_number'):
        raise ValueError('INVALID_PRIMARY_URL')
    if publication.get('kind') == 'issue':
        valid = match[2] is None
    else:
        valid = (publication.get('kind') == 'comment' and match[2] is not None
                 and int(match[2]) == publication.get('id'))
    if not valid or publication.get('role') != 'primary':
        raise ValueError('INVALID_PRIMARY_RECEIPT')
    return url


class Links:
    def __init__(self, store, request, clock=time.time, jitter=lambda: 0.5,
                 guarded_protocol=False):
        self.store, self.request, self.clock = store, request, clock
        self.jitter, self.guarded = jitter, guarded_protocol
        with store.db() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS spi_card_receipts (
              episode TEXT PRIMARY KEY, receipt TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS spi_links (
              episode TEXT PRIMARY KEY, event_key TEXT NOT NULL, revision INTEGER NOT NULL,
              url TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
              available REAL NOT NULL DEFAULT 0, lease REAL NOT NULL DEFAULT 0,
              owner TEXT, attempts INTEGER NOT NULL DEFAULT 0, error TEXT,
              acknowledgement TEXT NOT NULL DEFAULT '{}');
            ''')

    def record_card_receipt(self, episode, receipt, connection=None):
        # Store only identity, never original alert text/credentials.
        safe = {k: receipt[k] for k in ('key', 'episode', 'generation', 'copies') if k in receipt}
        safe['copies'] = [{k: x[k] for k in ('chat_id', 'message_id') if k in x}
                          for x in safe.get('copies', [])]
        if safe.get('episode', episode) != episode:
            raise ValueError('EPISODE_MISMATCH')
        def save(c):
            previous = c.execute('SELECT receipt FROM spi_card_receipts WHERE episode=?', (episode,)).fetchone()
            encoded = json.dumps(safe, sort_keys=True)
            if previous and previous[0] != encoded:
                raise ValueError('RECEIPT_CONFLICT')
            c.execute('INSERT OR IGNORE INTO spi_card_receipts VALUES (?,?)', (episode, encoded))
            c.execute("UPDATE spi_links SET available=0 WHERE episode=? AND state!='applied'", (episode,))
        if connection is not None:
            save(connection)
        else:
            with self.store.db() as c: save(c)

    def record_primary_publication(self, event_key, episode, revision, publication, connection=None):
        url = primary_url(publication)
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError('INVALID_REVISION')
        def save(c):
            row = c.execute('SELECT * FROM spi_links WHERE episode=?', (episode,)).fetchone()
            if row and revision <= row['revision']:
                if revision == row['revision'] and (url != row['url'] or event_key != row['event_key']):
                    raise ValueError('REVISION_CONFLICT')
                return
            c.execute('''INSERT INTO spi_links(episode,event_key,revision,url) VALUES(?,?,?,?)
              ON CONFLICT(episode) DO UPDATE SET event_key=excluded.event_key,
              revision=excluded.revision,url=excluded.url,state='pending',available=0,
              lease=0,owner=NULL,attempts=0,error=NULL,acknowledgement='{}' ''',
                      (episode, event_key, revision, url))
        if connection is not None:
            save(connection)
        else:
            with self.store.db() as c: save(c)

    def snapshot(self, episode):
        with self.store.db() as c:
            row = c.execute('SELECT * FROM spi_links WHERE episode=?', (episode,)).fetchone()
            return dict(row) if row else None

    def once(self):
        """One bounded attempt. Run on a dedicated thread, never the dispatch loop.

        Extended bot contract: conditional POST atomically validates episode,
        generation, copies and monotonic revision. GET must advertise
        link_protocol=1 and expose per-copy applied_url/applied_revision;
        DB desired spi_url alone is deliberately never considered success.
        """
        now, owner = self.clock(), uuid.uuid4().hex
        with self.store.db() as c:
            row = c.execute("SELECT * FROM spi_links WHERE state!='applied' AND available<=? AND lease<=? ORDER BY available,episode LIMIT 1", (now, now)).fetchone()
            if row is None: return False
            row = dict(row)
            c.execute("UPDATE spi_links SET lease=?,owner=?,attempts=attempts+1 WHERE episode=?", (now+120, owner, row['episode']))
            receipt = c.execute('SELECT receipt FROM spi_card_receipts WHERE episode=?', (row['episode'],)).fetchone()
        error, ack, applied = 'WAIT_RECEIPT', {}, False
        try:
            receipt = json.loads(receipt[0]) if receipt else {}
            if receipt.get('key'):
                if not self.guarded:
                    error = 'BOT_GUARD_REQUIRED'
                elif not all(k in receipt for k in ('episode', 'generation', 'copies')) or not receipt['copies']:
                    error = 'WAIT_IMMUTABLE_RECEIPT'
                else:
                    path = '/v1/cards/item?' + urlencode({'key': receipt['key']})
                    status, item = self.request('GET', path)
                    if status != 200:
                        error = 'CARD_NOT_READY' if status in (404,409) else 'BOT_HTTP_ERROR'
                    elif item.get('link_protocol') != 1:
                        error = 'BOT_GUARD_REQUIRED'
                    elif any(item.get(k) != receipt[k] for k in ('episode','generation')):
                        error = 'EPISODE_MISMATCH'
                    else:
                        payload = dict(receipt, url=row['url'], label='SPI', revision=row['revision'])
                        status, _ = self.request('POST', '/v1/cards/links', json=payload)
                        error = 'BOT_HTTP_ERROR'
                        if status == 200:
                            status, item = self.request('GET', path)
                            expected = {(x['chat_id'],x['message_id']) for x in receipt['copies']}
                            copies = item.get('copies', []) if status == 200 else []
                            actual = {(x.get('chat_id'),x.get('message_id')) for x in copies}
                            applied = (status == 200 and item.get('link_protocol') == 1
                                       and all(item.get(k) == receipt[k] for k in ('episode','generation'))
                                       and expected <= actual and bool(copies)
                                       and all(x.get('applied_url') == row['url'] and
                                               x.get('applied_revision') == row['revision'] and
                                               x.get('delivery_state') == 'applied' for x in copies))
                            ack = {'expected': len(expected), 'observed': len(actual), 'verified': applied}
                            error = None if applied else 'COPIES_PENDING'
        except Exception:
            # Ambiguous acceptance is retryable, never a fabricated receipt.
            error = 'DELIVERY_UNKNOWN'
        delay = min(3600, 2 ** min(row['attempts']+1, 11)) * (0.75 + 0.5*self.jitter())
        with self.store.db() as c:
            c.execute('''UPDATE spi_links SET state=?,error=?,acknowledgement=?,
              available=?,lease=0,owner=NULL WHERE episode=? AND revision=? AND owner=?''',
                      ('applied' if applied else 'pending', error, json.dumps(ack),
                       self.clock()+delay, row['episode'], row['revision'], owner))
        return True
