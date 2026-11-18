import argparse
import json
from pathlib import Path

from .config import DATA, Settings
from .db import engine_for, sessions
from .ingest import ingest, read_records
from .models import Models, download_models


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m matchbench.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("models", help="Download pinned quantized MiniLM models")
    index = commands.add_parser("ingest", help="Ingest a normalized JSON array or CSV")
    index.add_argument("file", type=Path, nargs="?", default=DATA / "jobs.json")
    index.add_argument("--lexical-only", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if args.command == "models":
        download_models(settings.model_dir)
        return
    engine = engine_for(settings.database_url)
    with sessions(engine).begin() as session:
        print(json.dumps(ingest(session, read_records(args.file), Models(settings.model_dir),
                                lexical_only=args.lexical_only), indent=2))


if __name__ == "__main__":
    main()
