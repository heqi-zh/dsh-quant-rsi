"""Prepare ignored computation dependencies from pinned upstream sources.

This downloads source files, verifies hashes and applies DQR's small adaptations.
It never installs or executes an upstream project.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def adapt(name, target, content):
    text = content.decode("utf-8")
    if name == "vnpy" and target == "array_manager.py":
        node = next(n for n in ast.parse(text).body
                    if isinstance(n, ast.ClassDef) and n.name == "ArrayManager")
        text = ("from __future__ import annotations\n"
                "from typing import Literal, overload\n"
                "import numpy as np\nimport talib\n\n"
                + "".join(text.splitlines(keepends=True)[node.lineno - 1:node.end_lineno]))
    elif name == "openevolve":
        text = text.replace("from openevolve.", "from dqr.vendor.openevolve.")
        if target == "database.py":
            text = text.replace(
                "        from dqr.vendor.openevolve.embedding import EmbeddingClient\n",
                "        if config.embedding_model:\n"
                '            raise ValueError("DQR vendored database disables embedding/network novelty search")\n')
    return text.encode("utf-8")


def fetch(entry, source, source_root):
    name = entry["provenance"]["repository"]
    if source_root is not None:
        return (source_root / name / source).read_bytes()
    repository = entry["url"].removeprefix("https://github.com/")
    url = f'https://raw.githubusercontent.com/{repository}/{entry["provenance"]["commit"]}/{source}'
    with urlopen(Request(url, headers={"User-Agent": "DQR-dependency-setup/0.1"}), timeout=30) as response:
        return response.read()


def prepare(name, entry, source_root, output):
    metadata = entry["provenance"]
    destination = output / name
    if destination.exists():
        # Existing installations are checked rather than overwritten.
        for target, info in metadata["files"].items():
            if sha256((destination / target).read_bytes()) != info["vendored_sha256"]:
                raise ValueError(f"{destination / target}: unexpected local source; inspect before replacing")
        if json.loads((destination / "provenance.json").read_text()) != metadata:
            raise ValueError(f"{destination}: unexpected provenance")
        if not (destination / "LICENSE").is_file():
            raise ValueError(f"{destination}: upstream LICENSE is missing")
        print(f"{name}: pinned local source verified")
        return
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{name}-", dir=output) as temp:
        staging = Path(temp) / name
        staging.mkdir()
        for target, info in metadata["files"].items():
            original = fetch(entry, info["source"], source_root)
            if sha256(original) != info["upstream_sha256"]:
                raise ValueError(f"{name}/{info['source']}: upstream source hash mismatch")
            content = adapt(name, target, original)
            if sha256(content) != info["vendored_sha256"]:
                raise ValueError(f"{name}/{target}: adapted source hash mismatch")
            path = staging / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            parent = path.parent
            while parent != staging.parent:
                (parent / "__init__.py").touch()
                parent = parent.parent
        (staging / "LICENSE").write_bytes(fetch(entry, "LICENSE", source_root))
        (staging / "provenance.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        shutil.move(str(staging), destination)
    print(f"{name}: prepared from {entry['url']} at {metadata['commit']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path,
                        help="Use existing vnpy/ and openevolve/ checkouts under this folder, avoiding downloads")
    parser.add_argument("--output", type=Path, default=ROOT / "runtime/dqr/vendor")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "configs/third-party.json").read_text())
    for name, entry in manifest.items():
        prepare(name, entry, args.source_root, args.output)


if __name__ == "__main__":
    main()
