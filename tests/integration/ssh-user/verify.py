#!/usr/bin/env python3
"""Opt-in real Ansible/OpenSSH acceptance on two disposable Linux containers.

Uses an ALREADY RUNNING Docker-compatible engine, never starts a VM, mounts a
host directory, publishes a port, contacts cluster nodes or reads personal keys.
Private test keys and containers are removed in finally/TemporaryDirectory.
"""
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
IMAGE = 'homelab-ssh-user-fixture:local'
USER = 'ssh_fixture'


def run(args, expected=0, **kw):
    p = subprocess.run(args, capture_output=True, text=True, timeout=kw.pop('timeout', 180), **kw)
    if p.returncode != expected:
        # Fixture output contains public data only, but keep it private to avoid
        # copying verbose Ansible/module output into unrelated transcripts.
        raise RuntimeError('Fixture command failed: '+args[0]+'; exit='+str(p.returncode)+'\n'+p.stdout[-2500:]+p.stderr[-1000:])
    return p.stdout


def main():
    run(['docker', 'info', '--format', '{{.ServerVersion}}'])
    run(['docker', 'build', '-q', '-t', IMAGE, str(Path(__file__).parent)], timeout=300)
    containers = []
    try:
        with tempfile.TemporaryDirectory(prefix='homelab-ssh-user-') as folder:
            d = Path(folder)
            for number in [1, 2]:run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(d/('key'+str(number)))])
            for suffix in ['a', 'b']:
                name = 'homelab-ssh-fixture-'+uuid.uuid4().hex[:10]+'-'+suffix
                run(['docker', 'run', '-d', '--network=none', '--name', name, IMAGE]); containers.append(name)
            hosts = {name: {'ansible_host': name, 'ansible_connection': 'community.docker.docker',
                           'ansible_user': 'root', 'ansible_become': True,
                           'ansible_python_interpreter': '/usr/bin/python3'} for name in containers}
            inventory = d/'inventory.json'
            inventory.write_text(json.dumps({'all': {'children': {'Socrat': {'hosts': hosts}}}}))
            def execute(container, *args):return run(['docker', 'exec', container, *args])
            def play(key=1, check=False, expected=0, name=USER):
                return run(['ansible-playbook', '-i', str(inventory), 'playbooks/ssh-user.yml',
                            '-e', 'ssh_username='+name, '-e', 'ssh_public_key_file='+str(d/('key'+str(key)+'.pub'))]
                           +(['--check'] if check else []), expected=expected, cwd=ROOT/'ansible')
            # Wait for sshd host keys; not an infrastructure-outage sleep/poll.
            for container in containers:
                for _ in range(30):
                    p = subprocess.run(['docker', 'exec', container, 'test', '-f', '/etc/ssh/ssh_host_ed25519_key.pub'], capture_output=True)
                    if p.returncode == 0:break
                    time.sleep(.1)
            play(check=True)
            for container in containers:
                p = subprocess.run(['docker', 'exec', container, 'id', USER], capture_output=True)
                assert p.returncode != 0, 'check mode created an account'
            play()
            def login(container, key):
                execute(container, 'mkdir', '-p', '/tmp/ssh-fixture')
                run(['docker', 'cp', str(d/('key'+str(key))), container+':/tmp/ssh-fixture/key'])
                execute(container, 'chmod', '600', '/tmp/ssh-fixture/key')
                public = execute(container, 'cat', '/etc/ssh/ssh_host_ed25519_key.pub').split()
                known = '[127.0.0.1]:2222 '+' '.join(public[:2])+'\n'
                run(['docker', 'exec', '-i', container, 'sh', '-c', 'cat > /tmp/ssh-fixture/known_hosts'], input=known)
                result = execute(container, 'ssh', '-i', '/tmp/ssh-fixture/key', '-p', '2222',
                    '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
                    '-o', 'UserKnownHostsFile=/tmp/ssh-fixture/known_hosts', '-o', 'HostKeyAlgorithms=ssh-ed25519',
                    '-o', 'ConnectTimeout=5', USER+'@127.0.0.1', 'id', '-un')
                assert result.strip() == USER
            for container in containers:login(container, 1)
            # Repeated apply is really idempotent on BOTH nodes.
            result = play()
            recaps = re.findall(r'changed=(\d+)', result)
            assert len(recaps) == 2 and set(recaps) == {'0'}, 'repeat apply was not idempotent'
            play(key=2)
            for container in containers:
                login(container, 1); login(container, 2)
                assert len(execute(container, 'cat', '/home/'+USER+'/.ssh/authorized_keys').splitlines()) == 2
            # Preserve existing options for an already-present key.
            first = (d/'key1.pub').read_text().split()
            second = (d/'key2.pub').read_text().split()
            restricted = 'no-agent-forwarding '+' '.join(first[:2])+'\n'+' '.join(second[:2])+'\n'
            run(['docker', 'exec', '-i', containers[0], 'sh', '-c', 'cat > /home/'+USER+'/.ssh/authorized_keys'], input=restricted)
            play()
            assert execute(containers[0], 'cat', '/home/'+USER+'/.ssh/authorized_keys').startswith('no-agent-forwarding ')
            # Missing key on exactly one node is repaired, not skipped by username.
            execute(containers[1], 'rm', '/home/'+USER+'/.ssh/authorized_keys')
            play()
            for container in containers:login(container, 1)
            assert len(execute(containers[0], 'cat', '/home/'+USER+'/.ssh/authorized_keys').splitlines()) == 2
            # Missing account on one node is recreated without touching the other.
            execute(containers[1], 'userdel', '-r', USER)
            play()
            for container in containers:login(container, 1)
            # A privileged existing user blocks the run BEFORE adding keys anywhere.
            execute(containers[0], 'useradd', '-m', '-G', 'sudo', 'priv_fixture')
            execute(containers[1], 'useradd', '-m', 'priv_fixture')
            play(expected=2, name='priv_fixture')
            for container in containers:
                p = subprocess.run(['docker', 'exec', container, 'test', '-e', '/home/priv_fixture/.ssh/authorized_keys'], capture_output=True)
                assert p.returncode != 0, 'preflight failure still granted a key'
            # Direct sudoers grants are rejected too, not just sudo-group membership.
            for container in containers:execute(container, 'useradd', '-m', 'direct_priv_fixture')
            run(['docker', 'exec', '-i', containers[0], 'sh', '-c', 'cat > /etc/sudoers.d/fixture'],
                input='direct_priv_fixture ALL=(root) NOPASSWD: /usr/bin/true\n')
            play(expected=2, name='direct_priv_fixture')
            for container in containers:
                p = subprocess.run(['docker', 'exec', container, 'test', '-e', '/home/direct_priv_fixture/.ssh/authorized_keys'], capture_output=True)
                assert p.returncode != 0
            # A symlink on one node blocks all key writes, including the other node.
            for container in containers:execute(container, 'useradd', '-m', 'link_fixture')
            execute(containers[0], 'mkdir', '/tmp/ssh-path-sentinel')
            execute(containers[0], 'ln', '-s', '/tmp/ssh-path-sentinel', '/home/link_fixture/.ssh')
            play(expected=2, name='link_fixture')
            for container in containers:
                p = subprocess.run(['docker', 'exec', container, 'test', '-e', '/home/link_fixture/.ssh/authorized_keys'], capture_output=True)
                assert p.returncode != 0
            # Existing inventory remains authoritative for inventory-managed accounts.
            before = [execute(c, 'cat', '/home/'+USER+'/.ssh/authorized_keys') for c in containers]
            for entry in hosts.values():
                entry['homelab_users'] = [{'name': USER, 'state': 'present', 'authorized_keys': [(d/'key1.pub').read_text().strip()], 'hosts': containers}]
            inventory.write_text(json.dumps({'all': {'children': {'Socrat': {'hosts': hosts}}}}))
            play(); play(key=2, expected=2)
            assert [execute(c, 'cat', '/home/'+USER+'/.ssh/authorized_keys') for c in containers] == before
            print('PASS: two Linux nodes; check-mode no account/key changes; create/login; repeat changed=0; additive key preservation; existing options preserved; missing key/account repaired; sudo group/direct grants, symlinks and inventory conflicts rejected before key writes.')
    finally:
        for container in containers:
            subprocess.run(['docker', 'rm', '-f', container], capture_output=True)


if __name__ == '__main__':main()
