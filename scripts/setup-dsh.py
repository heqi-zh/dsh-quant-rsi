"""Install locked DSH locally, compile tools, and initialize only the DQR profile."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", default=os.environ.get("DQR_NODE") or shutil.which("node"))
    parser.add_argument("--pnpm", default=os.environ.get("DQR_PNPM") or shutil.which("pnpm"))
    args = parser.parse_args()
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies"
    node = args.node or str(bundled / "node/bin/node")
    pnpm = args.pnpm or str(bundled / "bin/fallback/pnpm")
    if not Path(node).is_file() or not Path(pnpm).is_file():
        parser.error("Node 22.19+ and pnpm 11 required; supply --node and --pnpm")
    env = dict(os.environ)
    env.update(DSH_HOME=str(ROOT / ".dsh"), DSH_TELEMETRY_DISABLED="1")
    env["PATH"] = str(Path(node).parent) + os.pathsep + str(Path(pnpm).parent) + os.pathsep + env.get("PATH", "")
    def run(command, **kwargs):
        subprocess.run(command, cwd=ROOT, env=env, check=True, **kwargs)
    run([pnpm, "install", "--frozen-lockfile", "--store-dir", str(ROOT / ".pnpm-store")])
    run([node, str(ROOT / "node_modules/typescript/bin/tsc"), "-p", "tools/tsconfig.json"])
    dsh = [node, str(ROOT / "node_modules/@deepseek-ai/dsh/lib/bin.js")]
    # Never replace an existing profile: --from-default-profile is destructive.
    manifest = ROOT / ".dsh/profiles/dqr-research/package.json"
    if not manifest.exists():
        run(dsh + ["--profile", "dqr-research", "--from-default-profile", "headless", "--dump-config"], stdout=subprocess.DEVNULL)
    saved = json.loads(manifest.read_text())
    if saved.get("dsh", {}).get("profile", {}).get("bundles") != ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless"]:
        raise ValueError("Existing dqr-research profile has unexpected bundles; inspect before changing it")
    run(dsh + ["plugin", "--profile", "dqr-research", "add", "link:./tools", "--store-dir", str(ROOT / ".pnpm-store")])
    print("DQR DSH profile ready; no model call performed")


if __name__ == "__main__":
    main()
