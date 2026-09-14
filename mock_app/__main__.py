"""Start the local demonstration target with python -m mock_app."""

import argparse

from mock_app.app import create_app
from mock_app.scenarios import SCENARIOS


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic banking application (local demo)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default="normal",
        help="Initial scenario for new browser sessions",
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    create_app({"DEFAULT_SCENARIO": args.scenario}).run(
        host="127.0.0.1", port=args.port, debug=False
    )


if __name__ == "__main__":
    main()
