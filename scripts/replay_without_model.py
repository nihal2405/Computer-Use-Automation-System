"""Replay verification entry point: fail immediately if any model code is imported."""

import importlib.abc
import os
import sys


class NoModel(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split(".")[0] in {
            "openai",
            "anthropic",
            "litellm",
            "mock_app",
        } or fullname.startswith(("computer_use.discovery", "google.genai", "google.generativeai")):
            raise RuntimeError("Model or mock-app import forbidden during replay verification")


sys.meta_path.insert(0, NoModel())
for name in list(os.environ):
    if name.endswith("_API_KEY"):
        del os.environ[name]

from computer_use.cli import main  # noqa: E402 -- install import guards before loading replay

sys.argv.insert(1, "replay")
sys.exit(main())
