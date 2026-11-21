"""Prove reali sequenziali su fixture sintetiche intenzionalmente versionabili."""
import argparse
import hashlib
import json
import math
import platform
from datetime import datetime, timezone
from pathlib import Path

from app.domain import CompileInput
from app.interpreter import OllamaClient, SYSTEM_PROMPT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    cases = json.loads(Path("tests/fixtures/m0_cases.json").read_text())
    client = OllamaClient()
    report = {"started_utc": datetime.now(timezone.utc).isoformat(),
              "system_prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
              "python": platform.python_version(), "machine": platform.machine(),
              "settings": {"num_ctx": 8192, "num_predict": 1200, "temperature": 0,
                           "think": False, "keep_alive": "5m", "timeout_s": 120},
              "note": "Solo fixture sintetiche; A09 segue A05 sullo stesso client senza ereditarne lo stato.",
              "runs": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for model in args.model:
        for case in cases:
            result = client.compile(CompileInput.model_validate(case["input"]), model)
            run = {"model": model, "case": case["id"], "thermal_note": "first in model batch" if case is cases[0] else "subsequent in model batch",
                   "result": result.model_dump()}
            report["runs"].append(run)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            m = result.metrics
            print(f"{model} {case['id']}: {result.status}, {m.wall_s:.2f}s, in={m.prompt_tokens}, out={m.output_tokens}", flush=True)
    summaries = []
    for model in args.model:
        runs = [r for r in report["runs"] if r["model"] == model]
        warm = runs[1:]

        def p95(values):
            values = sorted(v for v in values if v is not None)
            return values[math.ceil(.95 * len(values)) - 1] if values else None

        summaries.append({"model": model, "n": len(runs), "n_warm_proxy": len(warm),
                          "structural_proposals": sum(r["result"]["structural_checks_passed"] for r in runs),
                          "p95_prompt_tokens_nearest_rank": p95([r["result"]["metrics"]["prompt_tokens"] for r in runs]),
                          "p95_warm_wall_s_nearest_rank": p95([r["result"]["metrics"]["wall_s"] for r in warm])})
    report["summaries"] = summaries
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return int(any(not r["result"]["confirmation_allowed"] for r in report["runs"]))


if __name__ == "__main__":
    raise SystemExit(main())
