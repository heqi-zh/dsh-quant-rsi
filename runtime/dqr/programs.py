"""Explicit operator programs, previews, and actual OpenEvolve archival (no search)."""
import json
from datetime import date
from pathlib import Path

from .engine import panel
from .operators import evaluate_program, frame_from_bars, validate_program, provenance_hash
from .storage import canonical, digest, read, write
from .vendor.openevolve.config import DatabaseConfig
from .vendor.openevolve.database import Program, ProgramDatabase


def archive_evaluation(folder, program_id, program, evaluation):
    # One replay/config per database prevents ranking incompatible evaluations.
    location = Path(folder) / "openevolve"
    database = ProgramDatabase(DatabaseConfig(db_path=str(location), num_islands=1,
                                              population_size=32, archive_size=8,
                                              feature_dimensions=["complexity"], random_seed=42))
    metrics = evaluation["candidate"]["metrics"]
    score = evaluation["return_delta"] - max(0, metrics["max_drawdown"] - evaluation["config"]["max_drawdown"])
    if program_id not in database.programs:
        database.add(Program(id=program_id, code=canonical(program), language="json",
                             metrics=dict(metrics, combined_score=score),
                             metadata={"evaluation": str(Path(folder) / "evaluation.json"),
                                       "optimized": False, "automatically_promoted": False,
                                       "score_definition": "return_delta - max(0, drawdown - drawdown_limit)"}))
    database.save(str(location))
    return {"database": str(location), "program_id": program_id, "search_executed": False}


def preview(runtime, snapshot_id, as_of, program, save=False):
    date.fromisoformat(as_of)
    validate_program(program)
    # Preview has no future rows and never simulates trades.
    bars = [bar for bar in panel(runtime.snapshot(snapshot_id)) if bar["date"] < as_of]
    if not bars:
        raise ValueError("no observations available before as_of")
    features, trace = evaluate_program(frame_from_bars(bars), program)
    identity = digest({"program": program, "operators": provenance_hash()})
    result = {"program_id": identity, "visible_nav_date": bars[-1]["date"],
              "values": features.filter(features["datetime"] == bars[-1]["date"]).to_dicts(),
              "operator_trace": trace, "evaluated": False, "promoted": False}
    if save:
        write(runtime.directory / "programs" / (identity + ".json"), program)
        result["saved_draft"] = str(runtime.directory / "programs" / (identity + ".json"))
    return result
