<h1>
  <img src="assets/rancher/socrat-logo.png" alt="" width="60" height="60" align="center">
  &nbsp;&nbsp;&nbsp;Socrat homelab
</h1>

[![CI](https://github.com/alchemmist/homelab/actions/workflows/quality-graph-push.yml/badge.svg?branch=main)](https://github.com/alchemmist/homelab/actions/workflows/quality-graph-push.yml)

This repository describes how I run Socrat, my home Kubernetes cluster.
[Ansible](ansible/) configures the machines. [Argo CD](deploy/argocd/apps/) keeps the applications in sync with Git.

- [What runs where](llm-wiki/context.md)
- [How to check a change](docs/quality/README.md)
