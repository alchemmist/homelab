<h1>
  <img src="assets/rancher/socrat-logo.png" alt="" width="60" height="60" align="center">
  &nbsp;&nbsp;&nbsp;Socrat homelab
</h1>

[![CI](https://github.com/alchemmist/homelab/actions/workflows/quality-graph-push.yml/badge.svg?branch=main)](https://github.com/alchemmist/homelab/actions/workflows/quality-graph-push.yml)

Socrat is my home Kubernetes cluster. It runs the public Socrat Wiki,
PostgreSQL for the applications, and Grafana so I can see how the machines
and services are doing.

I keep the configuration here so I can answer two questions without logging
into a node: how is a service supposed to run, and when did that change?
[Ansible](ansible/) configures the hosts. [Argo CD](deploy/argocd/apps/)
keeps the applications in sync with Git, so a deployment change starts with
a diff I can review and test.

Start with the **[Socrat Wiki](https://wiki.socrat.alchemmist.xyz/)** for the
public documentation (in Russian). If you’re working on the cluster, start with the [operator documentation](docs/README.md):
[what runs where](docs/context/context.md) and [how to check a change](docs/quality/README.md).
