"""
logger.py
=========
AGENTS.md-compliant transcript logger.

Writes every session start and conversation turn to:
    macOS/Linux:  $HOME/hackerrank_orchestrate/log.txt
    Windows:      %USERPROFILE%/hackerrank_orchestrate/log.txt

Rules (from AGENTS.md §2):
  - Append-only — never rewrite prior entries
  - Never log secrets (API keys are auto-redacted)
  - Shared across all agents/sessions in this repo
"""

import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

_IST      = timezone(timedelta(hours=5, minutes=30))
_LOG_PATH = Path.home() / "hackerrank_orchestrate" / "log.txt"
REPO_ROOT = Path(__file__).resolve().parent.parent
_DEADLINE = datetime(2026, 5, 2, 11, 0, 0, tzinfo=_IST)


# ── internal helpers ──────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(_IST).isoformat()


def _time_remaining() -> str:
    delta   = _DEADLINE - datetime.now(_IST)
    total_m = max(0, int(delta.total_seconds() / 60))
    d, rem  = divmod(total_m, 1440)
    h, m    = divmod(rem, 60)
    return f"{d}d {h}h {m}m"


def _redact(text: str) -> str:
    """Strip API keys and secrets before writing to the log."""
    text = re.sub(r"sk-ant-[A-Za-z0-9\-_]{10,}", "[REDACTED]", text)   # Anthropic
    text = re.sub(r"AIza[A-Za-z0-9\-_]{30,}", "[REDACTED]", text)       # Gemini
    text = re.sub(r"sk-[A-Za-z0-9]{40,}", "[REDACTED]", text)           # OpenAI
    return text


def _ensure():
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _LOG_PATH.exists():
        _LOG_PATH.touch()


def _write(block: str):
    _ensure()
    with open(_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(block + "\n")


# ── public API ────────────────────────────────────────────────────────────────

def is_onboarded() -> bool:
    """Return True if AGENTS.md agreement has been recorded for this repo."""
    _ensure()
    marker = f"AGREEMENT RECORDED: {REPO_ROOT}"
    try:
        return marker in _LOG_PATH.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False


def record_agreement():
    block = f"""
## [{_now_iso()}] ONBOARDING COMPLETE

AGREEMENT RECORDED: {REPO_ROOT}
Agent: main.py (support-triage-agent)
Language: py
System Time: {_now_iso()}
Time Remaining: {_time_remaining()} until 2026-05-02T11:00:00+05:30
"""
    _write(block)


def session_start():
    block = f"""
## [{_now_iso()}] SESSION START

Agent: main.py (support-triage-agent)
Repo Root: {REPO_ROOT}
Branch: main
Worktree: main
Parent Agent: none
Language: py
Time Remaining: {_time_remaining()}
"""
    _write(block)


def log_turn(
    title:            str,
    user_prompt:      str,
    response_summary: str,
    actions:          list[str],
):
    """Append a §5.2 per-turn entry to the log."""
    actions_str = "\n".join(f"* {a}" for a in (actions or ["(none)"]))
    block = f"""
## [{_now_iso()}] {_redact(title[:80])}

User Prompt (verbatim, secrets redacted):
{_redact(user_prompt[:800])}

Agent Response Summary:
{_redact(response_summary)}

Actions:
{actions_str}

Context:
tool=main.py (support-triage-agent)
branch=main
repo_root={REPO_ROOT}
worktree=main
parent_agent=none
"""
    _write(block)


def log_run_complete(n_total: int, n_escalated: int, output_path: str):
    log_turn(
        title            = f"Run complete — {n_total} tickets processed",
        user_prompt      = f"python code/main.py  [{n_total} tickets from support_tickets.csv]",
        response_summary = (
            f"Processed {n_total} tickets. "
            f"Replied: {n_total - n_escalated}. "
            f"Escalated: {n_escalated}. "
            f"Output written to {output_path}."
        ),
        actions = [
            "Read support_tickets/support_tickets.csv",
            f"Called Gemini {n_total} times (model: gemini-2.5-flash)",
            f"Wrote {n_total} rows to support_tickets/output.csv",
            f"Log file: {_LOG_PATH}",
        ],
    )
