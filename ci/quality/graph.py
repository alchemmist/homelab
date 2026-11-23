"""Use the released QG compiler, applying repository YAML style to its outputs."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, override

import yaml
from qg_cli.project import Project
from yaml.tokens import ScalarToken

if TYPE_CHECKING:
    from quality_graph_core.provider import GeneratedProject


def workflow_style(source: str) -> str:
    """Preserve keys, comments and commands; normalize quoted values and document end."""
    result = source
    for token in reversed(list(yaml.scan(source))):
        if not isinstance(token, ScalarToken) or token.style != "'":
            continue
        start, end = token.start_mark.index, token.end_mark.index
        if source[end : end + 1] == ":":  # A quoted key such as 'on', not a value.
            continue
        value = token.value
        if "\n" in value:
            line = source[source.rfind("\n", 0, start) + 1 : start]
            indent = len(line) - len(line.lstrip()) + 4
            replacement = yaml.safe_dump(value, default_style="|", width=80).rstrip("\n")
            header, *lines = replacement.splitlines()
            replacement = header + "\n" + "\n".join(" " * indent + line[2:] for line in lines)
        else:
            replacement = yaml.safe_dump(value, width=1000).removesuffix("...\n").rstrip("\n")
            if replacement.startswith("'"):
                replacement = json.dumps(value, ensure_ascii=False)
        result = result[:start] + replacement + result[end:]
    result = result.rstrip("\n") + "\n...\n"
    if json.dumps(yaml.safe_load(source)) != json.dumps(yaml.safe_load(result)):
        msg = "Formatting changed the generated workflow"
        raise ValueError(msg)
    return result.replace("and run qg generate.", "and run make graph-generate.", 1)


class RepositoryGraph(Project):
    """Let upstream manage all paths, overwrites, retired files and freshness checks."""

    @override
    def render(self) -> GeneratedProject:
        """Keep the provider manifest and graph digest unchanged."""
        generated = super().render()
        return replace(
            generated,
            files=tuple(
                replace(item, content=workflow_style(item.content))
                if item.path.suffix == ".yml"
                else item
                for item in generated.files
            ),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("generate", "validate"))
    project = RepositoryGraph.open(Path.cwd())
    if parser.parse_args().action == "generate":
        project.generate()
    else:
        problems = project.validate().problems
        if problems:
            raise SystemExit("\n".join(problems))
