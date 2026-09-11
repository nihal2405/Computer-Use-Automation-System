"""Minimal repository status command; no automation commands exist yet."""

import argparse
import json

from computer_use import __version__


def main() -> int:
    parser = argparse.ArgumentParser(description="Computer-use automation scaffold")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Show implementation status")
    parser.parse_args()
    print(json.dumps({
        "project": "computer-use-automation",
        "version": __version__,
        "status": "scaffold_only",
        "discovery_implemented": False,
        "replay_implemented": False,
        "handoff_implemented": False,
        "evidence_collected": False,
    }, indent=2))
    return 0
