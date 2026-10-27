"""Check local analysis tools without reading or executing a target project."""

import argparse
import json
import subprocess
import sys

from counting import find_scc
from node_runtime import resolve_node


def check(executable):
    if not executable:
        return dict(status="unavailable", version=None)
    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=10, check=True
        )
        return dict(status="ready", version=result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return dict(status="unavailable", version=None)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--node")
    cli.add_argument("--scc")
    args = cli.parse_args()
    print(
        json.dumps(
            dict(
                python=sys.version.split()[0],
                node=resolve_node(args.node),
                scc=check(find_scc(args.scc)),
                network="not-used",
            ),
            ensure_ascii=False,
        )
    )
