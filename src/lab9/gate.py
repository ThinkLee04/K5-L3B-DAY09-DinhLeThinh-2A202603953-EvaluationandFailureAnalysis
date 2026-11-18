"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []

    # Reports are JSON in normal operation, but callers and tests can construct
    # them directly. Reject non-finite values explicitly (JSON's NaN extension
    # otherwise sneaks through comparisons).
    metrics = pr.get("metrics")
    if not isinstance(metrics, dict):
        problems.append("metrics_missing_or_invalid")
    else:
        for metric, value in metrics.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                problems.append(f"metric_invalid:{metric}")

    manifest = pr.get("manifest") or {}
    rows = pr.get("rows")
    if not isinstance(rows, list):
        rows = []
        problems.append("rows_missing_or_invalid")
    seeds = manifest.get("seeds")
    items = manifest.get("items")
    if isinstance(items, int) and isinstance(seeds, list):
        expected = items * len(seeds)
        if len(rows) != expected:
            problems.append(f"row_count:{len(rows)}!={expected}")

    def pair_set(report_rows: list) -> set[tuple[object, object]]:
        pairs = []
        for row in report_rows:
            if not isinstance(row, dict) or "item_id" not in row or "seed" not in row:
                problems.append("row_identity_missing")
                continue
            pairs.append((row["item_id"], row["seed"]))
        if len(pairs) != len(set(pairs)):
            problems.append("duplicate_item_seed")
        return set(pairs)

    pr_pairs = pair_set(rows)
    base_rows = base.get("rows", [])
    base_pairs = pair_set(base_rows if isinstance(base_rows, list) else [])
    if pr_pairs != base_pairs:
        problems.append("item_seed_set_differs_from_baseline")

    if pr.get("evaluator_failures"):
        problems.append("evaluator_failures")
    graded_ids = [
        m.get("id") for m in spec.get("metrics", [])
        if isinstance(m, dict) and m.get("id")
        and m.get("level") != "system"
        and "pass_hat_k" not in str(m.get("grader", ""))
    ]
    for row in rows:
        if isinstance(row, dict):
            for metric in graded_ids:
                if row.get(metric) is None:
                    problems.append(f"row_metric_missing:{metric}")
                    break

    # A slice is attached to an item, not to a particular seed. Detect tags
    # changed on any trial for that item, then compare the canonical mapping.
    def item_slices(report_rows: list) -> dict:
        mapping = {}
        for row in report_rows:
            if not isinstance(row, dict) or "item_id" not in row:
                continue
            tags = row.get("slices", [])
            if not isinstance(tags, (list, tuple, set)):
                tags = []
                problems.append("slice_tags_invalid")
            tags = frozenset(tags)
            item = row["item_id"]
            if item in mapping and mapping[item] != tags:
                problems.append(f"slice_tags_inconsistent:{item}")
            mapping[item] = tags
        return mapping

    pr_slices, base_slices = item_slices(rows), item_slices(base_rows if isinstance(base_rows, list) else [])
    for item in pr_slices.keys() & base_slices.keys():
        if pr_slices[item] != base_slices[item]:
            problems.append(f"slice_tags_changed:{item}")

    # Ratchet applies only when both specs describe the same eval-set version.
    if base_spec and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        def check_ratchet(current: dict, previous: dict, label: str) -> None:
            if previous.get("blocking") and not current.get("blocking"):
                problems.append(f"ratchet_blocking:{label}")
            old_th, new_th = previous.get("threshold", {}), current.get("threshold", {})
            for key in ("min", "max", "max_increase"):
                if key in old_th and (key not in new_th or
                        (key == "min" and new_th[key] < old_th[key]) or
                        (key in ("max", "max_increase") and new_th[key] > old_th[key])):
                    problems.append(f"ratchet_threshold:{label}/{key}")
            if old_th.get("no_significant_drop") and not new_th.get("no_significant_drop"):
                problems.append(f"ratchet_no_significant_drop:{label}")

        old_metrics = {m.get("id"): m for m in base_spec.get("metrics", []) if isinstance(m, dict)}
        new_metrics = {m.get("id"): m for m in spec.get("metrics", []) if isinstance(m, dict)}
        for mid, previous in old_metrics.items():
            if mid not in new_metrics:
                problems.append(f"ratchet_metric_removed:{mid}")
            else:
                check_ratchet(new_metrics[mid], previous, str(mid))

        def slices_by_key(s: dict) -> dict:
            return {(x.get("name"), x.get("metric")): x for x in s.get("slices", []) if isinstance(x, dict)}
        old_slices, new_slices = slices_by_key(base_spec), slices_by_key(spec)
        for key, previous in old_slices.items():
            label = f"slice:{key[0]}/{key[1]}"
            if key not in new_slices:
                problems.append(f"ratchet_slice_removed:{label}")
                continue
            current = new_slices[key]
            if previous.get("blocking") and not current.get("blocking"):
                problems.append(f"ratchet_blocking:{label}")
            if "min" in previous and ("min" not in current or current["min"] < previous["min"]):
                problems.append(f"ratchet_threshold:{label}/min")
            if "max" in previous and ("max" not in current or current["max"] > previous["max"]):
                problems.append(f"ratchet_threshold:{label}/max")
            if previous.get("no_significant_drop") and not current.get("no_significant_drop"):
                problems.append(f"ratchet_no_significant_drop:{label}")

    # Keep the gate output concise and deterministic even when several rows
    # expose the same class of integrity problem.
    return sorted(set(problems))


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices", []):
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        val = sum(a.values()) / len(a) if a else None
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "min" in s and val < s["min"]:
            verdict = "fail"
        if s.get("no_significant_drop"):
            keys = sorted(set(a) & set(b))
            if not keys:
                verdict = "missing"
            else:
                d, lo, hi = stats.paired_bootstrap(
                    [a[k] for k in keys], [b[k] for k in keys],
                    n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027),
                    confidence=bs.get("confidence", 0.95),
                )
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(
            verdict, "BLOCK" if s.get("blocking") else "warn")
        lines.append(f"  {sid:<36} {val!s:<8} {json.dumps({k: s[k] for k in ('min', 'no_significant_drop') if k in s}):<34} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
