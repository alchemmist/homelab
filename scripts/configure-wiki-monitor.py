import argparse
import getpass
import json
import subprocess


PROGRAM = r'''
const { io } = require("socket.io-client");
const settings = SETTINGS;
const socket = io("http://127.0.0.1:3001", { reconnection: false });
const deadline = setTimeout(() => finish(new Error("Kuma API timed out")), 30000);
function finish(error, result) {
    clearTimeout(deadline);
    socket.close();
    if (error) {
        console.error(error.message);
        process.exitCode = 1;
    } else {
        console.log(JSON.stringify(result));
    }
}
function call(event, ...args) {
    return new Promise((resolve, reject) => socket.emit(event, ...args, result => {
        if (!result || !result.ok) reject(new Error(result?.msg || `${event} failed`));
        else resolve(result);
    }));
}
socket.on("connect_error", error => finish(error));
socket.on("connect", async () => {
    try {
        let list;
        socket.on("monitorList", value => { list = value; });
        await call("login", { username: settings.username, password: settings.password });
        await call("getMonitorList");
        if (!list) throw new Error("No monitor list received");
        const matches = Object.values(list).filter(m => m.url === settings.url);
        if (matches.length > 1) throw new Error("Multiple wiki monitors found; refusing changes");
        let id;
        let created = false;
        if (matches.length) {
            id = matches[0].id;
        } else {
            const result = await call("add", {
                name: "Socrat Wiki", type: "http", url: settings.url,
                method: "GET", interval: 60, retryInterval: 60, timeout: 30,
                maxretries: 2, maxredirects: 5, active: false,
                ignoreTls: false, upsideDown: false,
                accepted_statuscodes: ["200"], notificationIDList: {},
                kafkaProducerBrokers: [], kafkaProducerSaslOptions: {}
            });
            id = result.monitorID;
            created = true;
        }
        if (settings.activate) await call("resumeMonitor", id);
        if (settings.publish) {
            const response = await fetch("http://127.0.0.1:3001/api/status-page/socrat");
            if (!response.ok) throw new Error("Cannot read public status groups");
            const current = await response.json();
            const groups = current.publicGroupList;
            const group = groups.find(g => g.name === "Socrat apps");
            if (!group) throw new Error("Socrat apps group missing; refusing update");
            if (!groups.some(g => g.monitorList.some(m => m.id === id))) {
                const { config } = await call("getStatusPage", "socrat");
                const fs = require("fs");
                fs.writeFileSync(`/tmp/wiki-status-backup-${Date.now()}.json`,
                    JSON.stringify({ config, groups }), { mode: 0o600 });
                group.monitorList.push({ id, sendUrl: true });
                await call("saveStatusPage", "socrat", config, config.icon, groups);
            }
        }
        const result = await call("getMonitor", id);
        finish(null, { id, created, name: result.monitor.name,
            url: result.monitor.url, active: result.monitor.active });
    } catch (error) { finish(error); }
});
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='socrat-3')
    parser.add_argument('--username', default='alchemmist')
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    settings = {
        'username': args.username,
        'password': getpass.getpass('Uptime Kuma password: '),
        'url': 'https://wiki.socrat.alchemmist.xyz/',
        'activate': args.activate,
        'publish': args.publish,
    }
    program = PROGRAM.replace('SETTINGS', json.dumps(settings), 1)
    subprocess.run([
        'ssh', args.host, 'kubectl', '-n', 'uptime-kuma', 'exec', '-i',
        'deployment/uptime-kuma', '--', 'node', '-'
    ], input=program, text=True, check=True)


if __name__ == '__main__':
    main()
