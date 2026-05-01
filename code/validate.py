"""
validate.py — Score output.csv against sample_support_tickets.csv
==================================================================

Usage:
    python code/validate.py

Compares the agent's output against the 10 sample tickets that have
known expected values.  The sample tickets are DIFFERENT tickets from
the 29 input tickets — they serve as calibration examples showing the
expected quality and format, not as a test set.

Prints per-ticket comparison and overall accuracy for exact-match
fields: status + request_type.

Also performs structural validation of output.csv (field presence,
allowed values, row count).
"""

import csv
from pathlib import Path

REPO_ROOT   = Path(__file__).resolve().parent.parent
SAMPLE_PATH = REPO_ROOT / "support_tickets" / "sample_support_tickets.csv"
OUTPUT_PATH = REPO_ROOT / "support_tickets" / "output.csv"
TICKETS_PATH = REPO_ROOT / "support_tickets" / "support_tickets.csv"

VALID_STATUS = {"replied", "escalated"}
VALID_TYPES  = {"product_issue", "feature_request", "bug", "invalid"}
REQUIRED_FIELDS = {"issue", "subject", "company", "response", "product_area",
                   "status", "request_type", "justification"}


def _load(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def validate_structure(outputs: list[dict], expected_count: int) -> list[str]:
    """
    Validate structural correctness of output.csv:
      - correct number of rows
      - all required fields present
      - status and request_type use allowed values
      - no empty responses or justifications
    Returns list of issues found.
    """
    issues = []

    if len(outputs) != expected_count:
        issues.append(f"Row count mismatch: expected {expected_count}, got {len(outputs)}")

    for i, row in enumerate(outputs, 1):
        # Check required fields
        missing = REQUIRED_FIELDS - set(row.keys())
        if missing:
            issues.append(f"Row {i}: missing fields {missing}")

        # Check allowed values
        status = _norm(row.get("status", ""))
        if status not in VALID_STATUS:
            issues.append(f"Row {i}: invalid status '{status}'")

        rtype = _norm(row.get("request_type", ""))
        if rtype not in VALID_TYPES:
            issues.append(f"Row {i}: invalid request_type '{rtype}'")

        # Check for empty critical fields
        if not (row.get("response") or "").strip():
            issues.append(f"Row {i}: empty response")
        if not (row.get("justification") or "").strip():
            issues.append(f"Row {i}: empty justification")
        if not (row.get("product_area") or "").strip():
            issues.append(f"Row {i}: empty product_area")

        # Check for error artifacts
        j = row.get("justification", "")
        if "Agent error" in j:
            issues.append(f"Row {i}: contains 'Agent error' in justification")
        r = row.get("response", "")
        if "unable to process" in r.lower():
            issues.append(f"Row {i}: contains generic error response")

    return issues


def compare_samples(outputs: list[dict], samples: list[dict]):
    """
    Compare output against sample tickets for calibration.
    Note: sample tickets are DIFFERENT from the 29 input tickets.
    This comparison is for format/quality calibration, not accuracy testing.
    """
    # Build lookup: (first 50 chars of issue, company) → output row
    lookup: dict[tuple, dict] = {}
    for row in outputs:
        key = (_norm(row.get("issue", ""))[:50], _norm(row.get("company", "")))
        lookup[key] = row

    print(f"\n{'#':<4} {'Status':^18} {'Request Type':^26} {'Issue (first 38 chars)'}")
    print("─" * 90)

    status_correct = req_correct = matched = total = 0

    for i, s in enumerate(samples, 1):
        issue      = s.get("Issue", "")
        company    = s.get("Company", "")
        exp_status = _norm(s.get("Status", ""))
        exp_rtype  = _norm(s.get("Request Type", ""))

        key = (_norm(issue)[:50], _norm(company))
        out = lookup.get(key)

        if out is None:
            print(f"{i:<4} {'—':^18} {'—':^26} {issue[:38]!r}")
            total += 1
            continue

        got_status = _norm(out.get("status", ""))
        got_rtype  = _norm(out.get("request_type", ""))

        sm = "✓" if got_status == exp_status else "✗"
        rm = "✓" if got_rtype  == exp_rtype  else "✗"

        status_correct += (got_status == exp_status)
        req_correct    += (got_rtype  == exp_rtype)
        matched        += 1
        total          += 1

        s_col = f"{sm} {exp_status:10s} → {got_status}"
        r_col = f"{rm} {exp_rtype:14s} → {got_rtype}"
        print(f"{i:<4} {s_col:^18} {r_col:^26} {issue[:38]!r}")

    print("─" * 90)

    if matched > 0:
        sacc = status_correct / matched * 100
        racc = req_correct    / matched * 100
        print(f"\nMatched: {matched}/{total}")
        print(f"Status accuracy     : {status_correct}/{matched} = {sacc:.0f}%")
        print(f"Request type accuracy: {req_correct}/{matched} = {racc:.0f}%")
    else:
        print(f"\nNo overlapping tickets found ({total} samples checked).")
        print("This is expected — the sample tickets are different from the 29 input tickets.")
        print("The samples serve as calibration examples for format and quality.\n")


def main():
    if not OUTPUT_PATH.exists():
        print(f"ERROR: output.csv not found — run main.py first")
        return

    outputs = _load(OUTPUT_PATH)

    # Count expected tickets
    expected = 29
    if TICKETS_PATH.exists():
        expected = len(_load(TICKETS_PATH))

    # ── Structural validation ──
    print(f"\n{'═' * 60}")
    print(f"  Output Validation Report")
    print(f"{'═' * 60}\n")

    print(f"[1/3] Structural validation of output.csv...")
    issues = validate_structure(outputs, expected)
    if issues:
        for issue in issues:
            print(f"  ✗ {issue}")
    else:
        print(f"  ✓ All {len(outputs)} rows pass structural validation")

    # ── Summary stats ──
    print(f"\n[2/3] Output summary...")
    n_replied   = sum(1 for r in outputs if _norm(r.get("status", "")) == "replied")
    n_escalated = sum(1 for r in outputs if _norm(r.get("status", "")) == "escalated")
    print(f"  Total     : {len(outputs)}")
    print(f"  Replied   : {n_replied}")
    print(f"  Escalated : {n_escalated}")

    # Product area distribution
    areas: dict[str, int] = {}
    for r in outputs:
        a = r.get("product_area", "unknown").strip()
        areas[a] = areas.get(a, 0) + 1
    print(f"\n  Product areas:")
    for area, count in sorted(areas.items(), key=lambda x: -x[1]):
        print(f"    {area:25s} {count}")

    # Request type distribution
    types: dict[str, int] = {}
    for r in outputs:
        t = _norm(r.get("request_type", "unknown"))
        types[t] = types.get(t, 0) + 1
    print(f"\n  Request types:")
    for t, count in sorted(types.items(), key=lambda x: -x[1]):
        print(f"    {t:25s} {count}")

    # ── Sample comparison (calibration only) ──
    print(f"\n[3/3] Sample ticket calibration...")
    if SAMPLE_PATH.exists():
        samples = _load(SAMPLE_PATH)
        compare_samples(outputs, samples)
    else:
        print(f"  Skipped — {SAMPLE_PATH} not found")

    print(f"{'═' * 60}\n")


if __name__ == "__main__":
    main()
