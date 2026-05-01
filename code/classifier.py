"""
classifier.py
=============
Pre-LLM classification layer.  All functions are pure (no I/O, no API calls).

Three public functions
----------------------
    detect_company(issue, subject, company_field)  → str
    escalation_check(issue)                        → (bool, str)
    request_type_hint(issue, subject)              → str
"""

import re

# ── company keyword signals ───────────────────────────────────────────────────

_SIGNALS: dict[str, list[str]] = {
    "hackerrank": [
        r"hackerrank", r"hacker.?rank", r"\bassessment\b", r"test score",
        r"recruiter", r"\bcandidate\b", r"mock interview", r"coding test",
        r"proctoring", r"codepair", r"hiring platform", r"resume builder",
        r"certificate", r"inactivity", r"interview room", r"submission",
        r"hiring account", r"fpq", r"hackos", r"\bscreen\b", r"interviewer",
        r"skillup", r"hackerrank for work",
    ],
    "claude": [
        r"\bclaude\b", r"\banthropic\b", r"claude\.ai", r"claude api",
        r"claude pro", r"claude team", r"claude workspace", r"\bllm\b",
        r"ai model", r"lti.?key", r"aws bedrock", r"data crawl",
        r"model training", r"context window", r"conversation history",
        r"claude.?code", r"claude.?desktop",
    ],
    "visa": [
        r"visa card", r"visa\.co", r"visa support", r"traveller.?cheque",
        r"traveler.?check", r"chargeback", r"card stolen", r"stolen card",
        r"lost card", r"card blocked", r"visa credit", r"visa debit",
        r"visa prepaid", r"contactless", r"\batm\b", r"cash advance",
        r"minimum.?spend", r"merchant", r"visa india", r"virgin islands",
        r"\bvisa\b",   # broad — checked last, lower weight
    ],
}

# ── escalation patterns ───────────────────────────────────────────────────────
# Each entry: (regex_pattern, human-readable reason)
# Order matters — more specific patterns first.

_ESCALATION: list[tuple[str, str]] = [
    # ── adversarial / prompt injection ──────────────────────────────────────
    (r"show.{0,30}(?:internal|system).{0,30}(?:rules|prompt|instruction|document|logic)",
     "prompt injection: request to expose internal instructions"),
    (r"(?:display|reveal|print|output|list).{0,20}(?:retrieved|corpus|policy|logic).{0,20}(?:exact|all|internal)",
     "prompt injection: corpus/policy extraction attempt"),
    (r"ignore.{0,20}(?:previous|above|all|prior).{0,20}instruction",
     "prompt injection: instruction override"),
    (r"bypass.{0,20}(?:filter|check|policy|safety|rule)",
     "prompt injection: bypass attempt"),

    # ── destructive / illegal commands ──────────────────────────────────────
    (r"(?:delete|remove|erase|wipe).{0,15}(?:all )?files",
     "destructive command request"),
    (r"rm\s+-rf", "destructive shell command"),
    (r"format.{0,10}(?:disk|drive|system)", "destructive command"),

    # ── financial crime / fraud ──────────────────────────────────────────────
    (r"\bfraud\b", "fraud indicator"),
    (r"identity.{0,10}(?:theft|stolen|compromised)", "identity theft"),
    (r"(?:card|cheque|check).{0,10}stolen|stolen.{0,10}(?:card|cheque)",
     "stolen financial instrument"),
    (r"card.{0,10}blocked.{0,20}(?:travel|abroad|trip)",
     "blocked card while traveling — escalate for human handling"),

    # ── unauthorized access requests ─────────────────────────────────────────
    (r"restore.{0,30}access.{0,30}(?:not|even though|although).{0,20}(?:admin|owner|authori)",
     "unauthorized access escalation request"),
    (r"(?:not|no longer).{0,20}(?:admin|owner|authoriz).{0,30}(?:restore|grant|give).{0,20}access",
     "unauthorized access escalation request"),
    (r"grant.{0,20}access.{0,20}(?:without|not).{0,20}(?:permission|authoriz|approval)",
     "unauthorized access escalation request"),

    # ── score / assessment manipulation ──────────────────────────────────────
    (r"increase.{0,20}(?:my )?score",   "score manipulation request"),
    (r"(?:re.?grade|unfairly.graded)",  "grading dispute — cannot modify scores"),
    (r"(?:review|check).{0,20}(?:my )?answers.{0,30}(?:increase|change|fix)",
     "answer/score manipulation"),
    (r"tell.{0,20}company.{0,20}(?:move|advance|pass)",
     "recruiter decision override attempt"),

    # ── financial coercion ────────────────────────────────────────────────────
    (r"refund.{0,20}(?:me )?(?:today|immediately|right now|asap)",
     "immediate refund demand — human judgment required"),
    (r"ban.{0,10}seller|block.{0,10}seller|block.{0,10}merchant",
     "merchant action request — out of Visa agent scope"),

    # ── security reports ──────────────────────────────────────────────────────
    (r"security.{0,20}vulnerabilit", "security vulnerability disclosure"),
    (r"bug.{0,10}bounty",            "bug bounty report"),

    # ── financial distress ────────────────────────────────────────────────────
    (r"urgent.{0,20}cash.{0,30}(?:only|just).{0,20}(?:visa|card)",
     "urgent financial distress — escalate"),
    (r"(?:need|want).{0,20}urgent.{0,10}cash",
     "urgent cash need — escalate"),
    (r"(?:stranded|stuck).{0,30}(?:cash|money|card)",
     "financial distress while traveling"),

    # ── multilingual prompt injection ─────────────────────────────────────────
    (r"(?:affiche|montre|r[eé]v[eè]le).{0,40}(?:r[eè]gles|documents|logique|interne)",
     "prompt injection (French): reveal internal rules"),
    (r"r[eè]gles internes",
     "prompt injection (French): internal rules"),
]

# ── request type keyword signals ─────────────────────────────────────────────

_INVALID_RE = [
    r"thank(?:s| you)", r"^(?:hi|hello|hey)[.!,]?\s*$",
    r"who (?:is|was) .{1,40}(?:actor|celebrity|singer|player)",
    r"what is the (?:capital|population|president) of",
    r"actor.{0,20}iron man", r"name of the actor",
    r"give me the code to",
    r"^none\.?$",
]
_BUG_RE = [
    r"not working", r"doesn.t work", r"broken\b", r"\bdown\b",
    r"\berror\b", r"\bbug\b", r"crash", r"failing", r"\bfails\b",
    r"unable to", r"can.t (?:log|access|see|open|take|submit)",
    r"stopped working", r"not (?:loading|responding|accessible)",
    r"submissions?.{0,10}(?:not|broken|fail)",
]
_FEATURE_RE = [
    r"(?:please |can you )?add ", r"feature request",
    r"would (?:be great|love) if", r"\bsuggest\b",
    r"it would help if", r"missing feature", r"wish (?:you|it)",
]


# ── public API ────────────────────────────────────────────────────────────────

def detect_company(issue: str, subject: str, company_field: str) -> str:
    """
    Return one of: 'hackerrank' | 'claude' | 'visa' | 'unknown'

    Priority:
      1. company_field (if not None / blank)
      2. keyword scoring over issue + subject text
    """
    raw = (company_field or "").strip().lower()
    if raw and raw not in {"none", "n/a", ""}:
        if "hackerrank" in raw:   return "hackerrank"
        if "claude" in raw:       return "claude"
        if "anthropic" in raw:    return "claude"
        if "visa" in raw:         return "visa"

    text   = f"{issue} {subject}".lower()
    scores = {c: 0 for c in _SIGNALS}

    for company, patterns in _SIGNALS.items():
        for pat in patterns:
            if re.search(pat, text):
                # 'visa' broad pattern worth less to avoid false positives
                scores[company] += 1 if pat != r"\bvisa\b" else 0.5

    best  = max(scores, key=lambda c: scores[c])
    return best if scores[best] > 0 else "unknown"


def escalation_check(issue: str) -> tuple[bool, str]:
    """
    Fast regex scan for high-risk patterns.
    Returns (should_escalate, reason).
    Called BEFORE the LLM to save tokens on obvious cases.
    """
    text = issue.lower()
    for pattern, reason in _ESCALATION:
        if re.search(pattern, text):
            return True, reason
    return False, ""


def request_type_hint(issue: str, subject: str) -> str:
    """
    Lightweight keyword prior.  LLM makes the final call; this is a hint only.
    Returns: 'invalid' | 'bug' | 'feature_request' | 'product_issue'
    """
    text = f"{issue} {subject}".lower()
    for pat in _INVALID_RE:
        if re.search(pat, text):
            return "invalid"
    for pat in _BUG_RE:
        if re.search(pat, text):
            return "bug"
    for pat in _FEATURE_RE:
        if re.search(pat, text):
            return "feature_request"
    return "product_issue"
