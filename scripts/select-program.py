"""Explicit local version selection; never exposed as a model tool."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from dqr.operators import validate_program, provenance_hash
from dqr.storage import digest, read, write


def select(root, replay_id):
    if len(replay_id) != 64 or any(c not in "0123456789abcdef" for c in replay_id):
        raise ValueError("invalid replay ID")
    folder = root / "data/monthly" / replay_id
    program = validate_program(read(folder / "program.json"))
    manifest, evaluation = read(folder / "manifest.json"), read(folder / "evaluation.json")
    identity = digest({"program": program, "operators": provenance_hash()})
    if identity != manifest["program_id"] or identity != evaluation["program_id"]:
        raise ValueError("program or operator version differs from evaluated artifact")
    path = root / "strategies/operators-current.json"
    previous = read(path)
    write(root / "data/program-selections" / (uuid.uuid4().hex + ".json"),
          {"selected_at": datetime.now(timezone.utc).isoformat(), "replay_id": replay_id,
           "previous_program": previous, "selected_program": program, "selection": "explicit local CLI", "automatic": False})
    write(path, program)
    return identity


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", required=True, help="Explicitly select the exact evaluated program for subsequent daily analysis")
    args = parser.parse_args()
    print(select(ROOT, args.replay))
