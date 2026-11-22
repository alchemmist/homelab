---
title: "Сеть и доступ"
weight: 40
---


Для веб-приложений используются публичный HTTPS, личный Authentik/MFA и отдельные права сервиса. Сеть не подменяет авторизацию.

- [VPN и NetBird: разные назначения]({{< relref "network/vpn.md" >}}).
- [Доступ администратора к нодам по SSH]({{< relref "network/ssh.md" >}}).
- [Как получить доступ и исключения из SSO]({{< relref "start/access.md" >}}).
- [Как сервису получить VPN-доступ]({{< relref "network/service-vpn.md" >}}).

### Monori public access

Use `https://monori.alchemmist.xyz/` without a hosts-file override. When both entrances pass HTTPS checks, public DNS returns HOME and Moscow, including for clients using foreign recursive resolvers. The Dutch public ingress is not advertised for this hostname. Cached answers can persist across a refresh (TTL 60 seconds). Moscow is an alternative public entrance, not an independent backend site. This policy is specific to Monori, not every service in the zone.
