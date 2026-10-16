# Author: Pär-Ola Zander, Södertörn University
# SPDX-License-Identifier: MIT
"""Run bounded, tool-free Feynman synthesis and collect session usage."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess


MODELS = json.loads(Path(__file__).with_name("feynman_models.json").read_text())


def prepare_budget(ledger, budget_usd=None, reuse=False):
    if budget_usd is not None and (not math.isfinite(budget_usd) or budget_usd <= 0):
        raise SystemExit("--budget-usd must be a finite positive amount.")
    if reuse:
        budget = json.loads(ledger.read_text())
        for key in ("budget_usd", "reserved_usd"):
            value = budget.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise SystemExit("Invalid budget ledger.")
        if budget["budget_usd"] <= 0 or budget["reserved_usd"] > budget["budget_usd"] or not isinstance(budget.get("requests"), list):
            raise SystemExit("Invalid budget ledger.")
        if budget_usd is not None:
            if budget_usd < budget["budget_usd"]:
                raise SystemExit("An existing ceiling can only be retained or raised.")
            if budget_usd != budget["budget_usd"]:
                budget.setdefault("ceiling_changes", []).append({"from": budget["budget_usd"], "to": budget_usd})
                budget["budget_usd"] = budget_usd
    else:
        if ledger.exists():
            raise SystemExit("Refusing to reset an existing budget.")
        budget = {"budget_usd": budget_usd if budget_usd is not None else 0.50,
                  "reserved_usd": 0, "requests": []}
    ledger.write_text(json.dumps(budget, indent=2))
    return budget


def run(run_dir, feynman, budget_ledger=None, budget_usd=None,
        model="gpt-4.1", max_output_tokens=5000):
    model = model.removeprefix("openai/")
    if model not in MODELS:
        raise SystemExit("Unsupported model; this guarded runner supports the configured OpenAI models only.")
    if not 1 <= max_output_tokens <= MODELS[model]["max_output_tokens"]:
        raise SystemExit("--max-output-tokens exceeds the supported range for this model.")
    if (run_dir / "sessions").exists() or (run_dir / "usage.json").exists():
        raise SystemExit("Use a new run directory; refusing to mix sessions.")
    if budget_ledger is None and (run_dir / "budget.json").exists():
        raise SystemExit("Use a new run directory; refusing to reset an existing budget.")
    ledger = budget_ledger or run_dir / "budget.json"
    prompt = (run_dir / "brief.txt").read_text() + "\n\n" + (run_dir / "evidence.txt").read_text()
    budget = prepare_budget(ledger, budget_usd, reuse=budget_ledger is not None)
    previous_requests = len(budget["requests"])
    env = os.environ.copy()
    guard = Path(__file__).with_name("feynman_budget.cjs").resolve()
    env["NODE_OPTIONS"] = (env.get("NODE_OPTIONS", "") + f' --require "{guard}"').strip()
    env["FEYNMAN_BUDGET_LEDGER"] = str(ledger.resolve())
    env["FEYNMAN_MODEL"] = model
    env["FEYNMAN_MAX_OUTPUT_TOKENS"] = str(max_output_tokens)
    (run_dir / "run-config.json").write_text(json.dumps({
        "model": model, "max_output_tokens": max_output_tokens,
        "budget_usd": budget["budget_usd"], "budget_ledger": str(ledger.resolve()),
        "pricing_per_million_usd": MODELS[model], "tools_enabled": False,
    }, indent=2))
    with (run_dir / "console.txt").open("w") as log:
        process = subprocess.run([feynman, "--new-session", "--session-dir", str(run_dir / "sessions"),
                                  "--model", f"openai/{model}", "--thinking", "off", "--prompt", prompt],
                                 env=env, stdout=log, stderr=subprocess.STDOUT)
    messages = []
    for session in sorted((run_dir / "sessions").glob("*.jsonl")):
        for line in session.read_text().splitlines():
            item = json.loads(line)
            if item.get("type") == "message" and item["message"].get("role") == "assistant":
                messages.append(item["message"])
    usage = {"model": sorted({m.get("model", "") for m in messages}), "calls": len(messages)}
    for field in ["input", "cacheRead", "output", "totalTokens"]:
        usage[field] = sum(m.get("usage", {}).get(field, 0) for m in messages)
    usage["estimated_cost_usd"] = (usage["input"] * MODELS[model]["input"]
                                   + usage["cacheRead"] * MODELS[model]["cached_input"]
                                   + usage["output"] * MODELS[model]["output"]) / 1_000_000
    usage["feynman_logged_cost_usd"] = sum(m.get("usage", {}).get("cost", {}).get("total", 0) for m in messages)
    usage["process_exit_code"] = process.returncode
    (run_dir / "usage.json").write_text(json.dumps(usage, indent=2))
    print(json.dumps(usage, indent=2))
    if len(json.loads(ledger.read_text())["requests"]) <= previous_requests:
        raise SystemExit("No guarded API request recorded; inspect console.txt.")
    if not messages:
        raise SystemExit("No model response recorded; inspect console.txt.")
    text = "\n".join(c["text"] for c in messages[-1].get("content", []) if c.get("type") == "text")
    (run_dir / "response.txt").write_text(text)
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    candidates = json.loads(text)
    quote_mode = isinstance(candidates.get("quotes"), list) and bool(candidates["quotes"])
    passage_mode = (isinstance(candidates.get("selections"), list)
                    and bool(candidates["selections"])
                    and all(isinstance(item, dict)
                            and isinstance(item.get("passage_id"), str)
                            for item in candidates["selections"]))
    if not quote_mode and not passage_mode:
        raise SystemExit("No quotation candidates or passage-ID selections in response.")
    config_path = run_dir / "run-config.json"
    config = json.loads(config_path.read_text())
    config["output_mode"] = "passage_ids" if passage_mode else "quotes"
    config_path.write_text(json.dumps(config, indent=2))
    (run_dir / "candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--feynman", default="feynman")
    parser.add_argument("--budget-ledger", type=Path, help="Reuse the original ledger for a repair without resetting the budget.")
    parser.add_argument("--budget-usd", type=float, help="Explicit total ceiling, not extra allowance. Default: 0.50 for new runs; existing ceiling for shared ledgers.")
    parser.add_argument("--model", default="gpt-4.1", help="Default: gpt-4.1. Also supports gpt-4.1-mini, gpt-4.1-nano, and gpt-5-mini; optional openai/ prefix.")
    parser.add_argument("--max-output-tokens", type=int, default=5000, help="Per-response output cap (default: 5000).")
    args = parser.parse_args()
    run(args.run_dir, args.feynman, args.budget_ledger, args.budget_usd,
        args.model, args.max_output_tokens)
