"""
main.py — Entry point for the Multi-Domain Support Triage Agent
===============================================================

Usage
-----
    cd <repo-root>
    python code/main.py

Reads:   support_tickets/support_tickets.csv
Writes:  support_tickets/output.csv
Log:     ~/hackerrank_orchestrate/log.txt

Environment
-----------
    GEMINI_API_KEY      required — set in .env or shell
"""

import csv
import os
import sys
import time
from pathlib import Path

# Allow `python code/main.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

from agent      import TriageAgent
from classifier import detect_company, escalation_check, request_type_hint
from logger     import (
    is_onboarded, record_agreement, session_start,
    log_turn, log_run_complete,
)
from retriever  import Retriever

# ── paths ─────────────────────────────────────────────────────────────────────

REPO_ROOT    = Path(__file__).resolve().parent.parent
TICKETS_PATH = REPO_ROOT / "support_tickets" / "support_tickets.csv"
OUTPUT_PATH  = REPO_ROOT / "support_tickets" / "output.csv"

OUTPUT_FIELDS = [
    "issue", "subject", "company",
    "response", "product_area", "status", "request_type", "justification",
]

# ── terminal colours ──────────────────────────────────────────────────────────

B  = "\033[1m"          # bold
G  = "\033[92m"         # green
Y  = "\033[93m"         # yellow
R  = "\033[91m"         # red
RE = "\033[0m"          # reset


def _col(s: str, c: str) -> str:
    return f"{c}{s}{RE}"


def _banner():
    print(f"""
{B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RE}
{B}  Multi-Domain Support Triage Agent{RE}
  HackerRank Orchestrate · May 2026
  Model: gemini-2.5-flash
{B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RE}
""")


# ── onboarding gate (AGENTS.md §3) ────────────────────────────────────────────

def _onboard():
    print(f"""
{B}Welcome to HackerRank Orchestrate.{RE}

Ground rules (AGENTS.md):
  1. Solo challenge — you are the author of this submission.
  2. Any AI tool may be used to help build (Cursor, Claude Code, etc.)
  3. Agent must conform to the entry-point contract in AGENTS.md §6.
  4. Never commit secrets — use environment variables / .env.
  5. Every turn is logged to ~/hackerrank_orchestrate/log.txt.
  6. Submit on the HackerRank Community Platform.

Type {B}I agree{RE} and press Enter to continue: """, end="")

    answer = input().strip()
    if answer.lower() != "i agree":
        print("Onboarding cancelled.  Run again and type 'I agree' to proceed.")
        sys.exit(0)

    record_agreement()
    print(f"\n{G}✓ Agreement recorded.{RE}\n")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    _banner()

    # Load .env
    load_dotenv(REPO_ROOT / ".env")

    # API key
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print(f"{R}ERROR: GEMINI_API_KEY not set.{RE}")
        print("Add GEMINI_API_KEY=your-key to .env, then run again.")
        sys.exit(1)

    # AGENTS.md onboarding gate
    if not is_onboarded():
        _onboard()

    session_start()
    log_turn(
        title            = "Agent initialisation",
        user_prompt      = "python code/main.py",
        response_summary = "Agent started. Loading corpus and TF-IDF index.",
        actions          = ["Loaded .env", "Checked AGENTS.md onboarding"],
    )

    # ── 1. Load corpus + index ────────────────────────────────────────────────
    print(f"{B}[1/4] Loading corpus and building TF-IDF index...{RE}")
    retriever = Retriever()
    print()

    # ── 2. Read tickets ───────────────────────────────────────────────────────
    print(f"{B}[2/4] Reading tickets...{RE}")
    if not TICKETS_PATH.exists():
        print(f"{R}ERROR: {TICKETS_PATH} not found.{RE}")
        sys.exit(1)

    tickets: list[dict] = []
    with open(TICKETS_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tickets.append(row)

    print(f"  {len(tickets)} tickets loaded.\n")

    # ── 3. Process each ticket ────────────────────────────────────────────────
    print(f"{B}[3/4] Triaging tickets...{RE}\n")
    agent   = TriageAgent(api_key=api_key)
    results = []

    for i, ticket in enumerate(tickets, 1):
        issue       = (ticket.get("Issue")   or "").strip()
        subject     = (ticket.get("Subject") or "").strip()
        company_raw = (ticket.get("Company") or "").strip()

        display = subject or issue[:60]
        print(f"  [{i:02d}/{len(tickets)}] {display!r}")

        # classify
        company       = detect_company(issue, subject, company_raw)
        pre_esc, why  = escalation_check(issue)
        hint          = request_type_hint(issue, subject)

        esc_str = _col("PRE-ESC", Y) if pre_esc else "ok"
        print(f"          company={company}  escalation={esc_str}  hint={hint}")
        if pre_esc:
            print(f"          reason : {why}")

        # retrieve
        chunks = retriever.retrieve(issue + " " + subject, company)
        print(f"          chunks ={len(chunks)}")

        # triage
        result = agent.triage(
            issue             = issue,
            subject           = subject,
            company           = company,
            chunks            = chunks,
            type_hint         = hint,
            pre_escalate      = pre_esc,
            escalation_reason = why,
        )

        sc = G if result.status == "replied" else Y
        print(f"          {_col(result.status.upper(), sc)}"
              f"  area={result.product_area}  type={result.request_type}\n")

        # log
        log_turn(
            title        = f"Ticket {i:02d}: {display[:55]}",
            user_prompt  = (
                f"Company: {company_raw}\n"
                f"Subject: {subject}\n"
                f"Issue  : {issue[:400]}"
            ),
            response_summary = (
                f"status={result.status}, area={result.product_area}, "
                f"type={result.request_type}. "
                f"Pre-escalate={pre_esc} ({why or 'none'}). "
                f"Chunks={len(chunks)}. "
                f"Justification: {result.justification[:200]}"
            ),
            actions = [
                f"detect_company        → {company}",
                f"escalation_check      → {pre_esc} ({why or 'clean'})",
                f"retriever.retrieve    → {len(chunks)} chunks",
                f"TriageAgent.triage    → {result.status}",
            ],
        )

        results.append({
            "issue":         issue,
            "subject":       subject,
            "company":       company_raw,
            "response":      result.response,
            "product_area":  result.product_area,
            "status":        result.status,
            "request_type":  result.request_type,
            "justification": result.justification,
        })

        time.sleep(0.35)   # stay within API rate limits

    # ── 4. Write output ───────────────────────────────────────────────────────
    print(f"{B}[4/4] Writing output.csv...{RE}")
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in OUTPUT_FIELDS})

    n_esc     = sum(1 for r in results if r["status"] == "escalated")
    n_replied = len(results) - n_esc

    log_run_complete(len(results), n_esc, str(OUTPUT_PATH))

    print(f"""
{B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RE}
{G}✓ Done!{RE}  {len(results)} tickets processed.
  Replied  : {_col(str(n_replied), G)}
  Escalated: {_col(str(n_esc), Y)}

  Output → support_tickets/output.csv
  Log    → ~/hackerrank_orchestrate/log.txt
{B}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RE}
""")


if __name__ == "__main__":
    main()
