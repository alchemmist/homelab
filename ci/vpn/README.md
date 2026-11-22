# VPN helpers exercised by Quality Graph

`make tests-fast` exercises the VPN hardening, panel-session and UDP probe contracts
with fixtures. The CLI smoke invokes `vpn-backend-audit.py --render` only. Do not
execute this directory as a batch: it also contains operator commands with live
apply modes. `vpn-home-session.py` is an operator companion, not a CI entrypoint.
