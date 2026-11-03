# Disposable test containers only. No cluster resources/VMs are created.
FROM node:24.11.1-bookworm-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends python3 openssh-server sudo util-linux > /dev/null && rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_*
RUN mkdir -p /run/sshd && printf 'Port 2222\nListenAddress 127.0.0.1\nPubkeyAuthentication yes\nUsePAM yes\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n' > /etc/ssh/sshd_config.d/fixture.conf
CMD ["sh", "-c", "ssh-keygen -A >/dev/null && exec /usr/sbin/sshd -D -e"]
