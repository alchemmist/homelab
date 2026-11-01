from datetime import datetime, timezone
import json
import os
import subprocess


MAX_RECORDS = 100000
MAX_BYTES = 16 * 1024 * 1024


def collect():
    process = subprocess.Popen(['journalctl', '--system', '--since=-10min', '--output=json',
                                '--no-pager', '--quiet'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    records = serialized_bytes = message_bytes = invalid_records = 0
    truncated = False
    try:
        while line := process.stdout.readline(MAX_BYTES - serialized_bytes + 1):
            serialized_bytes += len(line)
            if serialized_bytes > MAX_BYTES:
                truncated = True
                process.terminate()
                break
            try:
                event = json.loads(line)
                if not isinstance(event, dict):
                    raise ValueError('Journal record is not an object')
                message = event.get('MESSAGE', '')
                if isinstance(message, str):
                    message_bytes += len(message.encode())
                else:
                    message_bytes += len(json.dumps(message).encode())
            except (ValueError, TypeError):
                invalid_records += 1
            records += 1
            if records >= MAX_RECORDS:
                truncated = True
                process.terminate()
                break
    finally:
        process.stdout.close()
        try:
            return_code = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
            return_code = -1
    return {'schemaVersion': 1, 'collectedAt': datetime.now(timezone.utc).isoformat(),
            'windowSeconds': 600, 'rootAccessVerified': os.geteuid() == 0,
            'systemJournalReadSucceeded': return_code == 0 and not truncated,
            'records': records, 'serializedBytes': serialized_bytes, 'messageBytes': message_bytes,
            'invalidRecords': invalid_records, 'truncated': truncated,
            'rawLogBodiesPersisted': False, 'productionModified': False}


if __name__ == '__main__':
    print(json.dumps(collect()))
