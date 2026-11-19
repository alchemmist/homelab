# Parallel 56 lane 50 checkpoint

One committed source repair: `charts/monori/values.yaml` now has two spaces
before the existing frontend-placement comment.

The composed document, parse events, scalar tags, scalar values, and alias
sharing are unchanged. `frontNodeName` remains `socrat-0`. Image tags, digests,
claims, and the other values are unchanged. No versions or identities were edited.

## Checks

Parent tool prefix: `/Users/antonmoss/code/worktrees/homelab-quality-strict-continuation/.venv/bin`.
Worker cwd and `quality/yamllint.yaml` were used. Commands used `subprocess`
equivalent `check=False` and were not retried.

- Lane yamllint findings: 610 before, 609 after.
- This file: 1 `comments` finding before, 0 after.
- `yamllint -c quality/yamllint.yaml -` on the previous file text: exit 1.
- `yamllint -c quality/yamllint.yaml charts/monori/values.yaml`: exit 0.
- Compose graph equal: true. Parse events equal: true. `safe_load` equal: true.
- Alias shares: 0 before, 0 after.
- `ruff version`: exit 0 (`ruff 0.15.12`).
- `mypy --version`: exit 0 (`mypy 2.4.1`).
- Ruff and mypy were not pointed at this YAML file. They check Python, and this
  lane's allocated change has no Python source.
- Allocation `offlineScheduledTests` is empty. No test module reads
  `charts/monori/values.yaml`.

## Not committed

Indenting `charts/alertmanager/Chart.yaml` removed its indentation finding but
changed the dependencies sequence `flow_style` from unset to explicit block.
That file was restored and is not part of this commit.

## Remaining

609 yamllint findings remain on the other allocated files, including line length,
quotes, indentation, document markers, and braces. Those were left in place.
