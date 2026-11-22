This is `packages/github` from [Quality Graph v0.2.4](https://github.com/alchemmist/quality-graph/tree/f5cef503eaf0734b9c9a0c6f88ee8206b2a6235d/packages/github), under its MIT license.
Compare this directory with `git archive f5cef503eaf0734b9c9a0c6f88ee8206b2a6235d:packages/github`
in an upstream clone.

The local changes are for strict YAML serialization: the compiler uses double-quoted or
literal scalars when needed, 80-column wrapping, and explicit document ends. The publisher
templates use the matching scalar and document style. The local package also drops the
upstream uv workspace source declaration. `uv run --locked qg generate` and `qg validate`
use this provider; the CLI and core use the pinned PyPI distributions.

This directory does not provide the Action executed by CI. In `qg.yaml`,
`runtime.publisher-action` pins both privileged jobs to the upstream release commit.
The read-only collector pin stays unchanged to preserve the base-governed graph digest.
