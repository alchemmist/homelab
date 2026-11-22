"""Verify generated alert graphs without writing repository files."""

from scripts.alert_graphs import ROOT, inventory, outputs


def main() -> None:
    """Compare each generated artifact to the committed copy."""
    generated, _ = outputs(inventory())
    for path, content in generated.items():
        if not path.exists() or path.read_text() != content:
            raise SystemExit("Generated alert graph file differs: " + str(path.relative_to(ROOT)))


if __name__ == "__main__":
    main()
