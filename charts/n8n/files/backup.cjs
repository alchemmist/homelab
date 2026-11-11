'use strict';
// SQLite online backup, never a raw copy of a live database/WAL.
const fs = require('fs');
const path = require('path');
const cp = require('child_process');
const sqlite = require('/usr/local/lib/node_modules/n8n/node_modules/sqlite3');
const crypto = require('crypto');
const root = '/tmp/n8n-backup';
const data = path.join(root, 'data');
const source = '/data';
const fail = () => { console.error('n8n backup failed; inspect job privately'); process.exitCode = 1; };

async function main() {
  fs.mkdirSync(data, { recursive: true, mode: 0o700 });
  // Copy non-database state first. Execution logs are diagnostic, not recovery state.
  fs.cpSync(source, data, { recursive: true, filter: p => {
    const n = path.basename(p);
    return !n.startsWith('database.sqlite') && !n.startsWith('n8nEventLog') && n !== 'crash.journal';
  }});
  const db = await new Promise((resolve, reject) => {
    const d = new sqlite.Database('/data/database.sqlite', sqlite.OPEN_READONLY, e => e ? reject(e) : resolve(d));
  });
  await new Promise((resolve, reject) => {
    const b = db.backup(path.join(data, 'database.sqlite'));
    b.step(-1, e => b.finish(e2 => e || e2 ? reject(e || e2) : resolve()));
  });
  await new Promise((resolve, reject) => db.close(e => e ? reject(e) : resolve()));
  const check = new sqlite.Database(path.join(data, 'database.sqlite'), sqlite.OPEN_READONLY);
  await new Promise((resolve, reject) => check.get('PRAGMA integrity_check', (e, row) => {
    if (e || Object.values(row)[0] !== 'ok') reject(e || new Error('integrity')); else resolve();
  }));
  await new Promise((resolve, reject) => check.close(e => e ? reject(e) : resolve()));
  // This key must accompany encrypted credentials for disaster recovery.
  fs.copyFileSync('/recovery/encryption-key', path.join(root, 'encryption-key'));
  fs.chmodSync(path.join(root, 'encryption-key'), 0o600);
  fs.writeFileSync(path.join(root, 'manifest.json'), JSON.stringify({
    createdAt: new Date().toISOString(), sourceNode: 'socrat-5',
    database: 'SQLite online backup; integrity_check=ok',
    databaseSha256: crypto.createHash('sha256').update(fs.readFileSync(path.join(data, 'database.sqlite'))).digest('hex'),
    note: 'Non-database files copied online; not a transactionally atomic snapshot of external services.'
  }, null, 2));
  fs.copyFileSync('/ssh/id_ed25519', '/tmp/id_ed25519');
  fs.chmodSync('/tmp/id_ed25519', 0o600);
  const tar = cp.spawn('tar', ['-C', root, '-czf', '-', '.'], {stdio: ['ignore', 'pipe', 'inherit']});
  const ssh = cp.spawn('ssh', ['-T', '-p', '2222', '-i', '/tmp/id_ed25519',
    '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
    '-o', 'UserKnownHostsFile=/ssh/known_hosts', '-o', 'ConnectTimeout=30',
    '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
    'alchemmist@10.250.0.5', 'receive-n8n-backup'], {stdio: ['pipe', 'inherit', 'inherit']});
  tar.stdout.pipe(ssh.stdin);
  const ended = p => new Promise((resolve, reject) => {
    p.on('error', reject); p.on('close', code => code === 0 ? resolve() : reject(new Error('child failed')));
  });
  await Promise.all([ended(tar), ended(ssh)]);
  console.log('n8n SQLite snapshot integrity verified; archive transferred to socrat-3');
}
main().catch(fail);
