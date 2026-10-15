import argparse
import ipaddress
import json
import re
import socket
import struct
import subprocess


ETH_P_ARP = 0x0806


def ipv4(value):
    if not isinstance(value, str):
        raise ValueError('Expected an IPv4 address string')
    address = ipaddress.IPv4Address(value)
    if address.is_multicast or address.is_unspecified or address.is_loopback or str(address) == '255.255.255.255':
        raise ValueError('Expected a unicast IPv4 address')
    return str(address)


def mac_bytes(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', value):
        raise ValueError('Invalid MAC address')
    result = bytes.fromhex(value.replace(':', ''))
    if result[0] & 1 or result == bytes(6):
        raise ValueError('Expected a nonzero unicast MAC address')
    return result


def validate_config(config):
    if not isinstance(config, dict) or set(config) != {'interface', 'address', 'vip', 'neighbors'}:
        raise ValueError('Invalid configuration fields')
    interface = config['interface']
    if not isinstance(interface, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,14}', interface):
        raise ValueError('Invalid interface name')
    result = {'interface': interface, 'address': ipv4(config['address']), 'vip': ipv4(config['vip']), 'neighbors': []}
    if result['address'] == result['vip']:
        raise ValueError('Physical address and VIP must differ')
    if not isinstance(config['neighbors'], list) or not config['neighbors']:
        raise ValueError('Expected a nonempty neighbor list')
    for neighbor in config['neighbors']:
        if not isinstance(neighbor, dict) or set(neighbor) != {'address', 'mac'}:
            raise ValueError('Invalid neighbor fields')
        address = ipv4(neighbor['address'])
        if address in (result['address'], result['vip']):
            raise ValueError('Neighbor address must differ from local addresses')
        mac_bytes(neighbor['mac'])
        result['neighbors'].append({'address': address, 'mac': neighbor['mac']})
    return result


def read_interface(interface):
    output = subprocess.run(['ip', '-j', 'address', 'show', 'dev', interface], check=True, capture_output=True, text=True, timeout=2)
    records = json.loads(output.stdout)
    if len(records) != 1 or records[0].get('ifname') != interface:
        raise ValueError('Expected exactly the configured interface')
    return records[0]


def arp_request(source_mac, source_address, target_mac, target_address):
    sender = mac_bytes(source_mac)
    target = mac_bytes(target_mac)
    return target + sender + struct.pack('!H', ETH_P_ARP) + struct.pack('!HHBBH', 1, 0x0800, 6, 4, 1) + sender + socket.inet_aton(ipv4(source_address)) + target + socket.inet_aton(ipv4(target_address))


def frames_for_interface(config, state):
    config = validate_config(config)
    if state.get('ifname') != config['interface']:
        raise ValueError('Interface does not match configuration')
    mac_bytes(state.get('address'))
    assigned = {entry['local'] for entry in state.get('addr_info', []) if entry.get('family') == 'inet' and 'local' in entry}
    if config['address'] not in assigned:
        raise ValueError('Physical address is not assigned to the interface')
    sources = [config['address']]
    if config['vip'] in assigned:
        sources.append(config['vip'])
    return [arp_request(state['address'], source, neighbor['mac'], neighbor['address']) for source in sources for neighbor in config['neighbors']]


def announce(config):
    config = validate_config(config)
    frames = frames_for_interface(config, read_interface(config['interface']))
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ARP)) as connection:
        connection.settimeout(1)
        connection.bind((config['interface'], 0))
        for frame in frames:
            if connection.send(frame) != len(frame):
                raise OSError('Incomplete ARP frame transmission')
    return len(frames)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    with open(args.config, encoding='utf-8') as stream:
        announce(json.load(stream))


if __name__ == '__main__':
    main()
