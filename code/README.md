# Multi-Domain Support Triage Agent

> Terminal-based AI agent that triages support tickets across **HackerRank**, **Claude (Anthropic)**, and **Visa** using a local corpus, TF-IDF retrieval, and Gemini LLM.

Built for the **HackerRank Orchestrate** hackathon (May 1–2, 2026).

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set API key
cp .env.example .env
# Edit .env:  GEMINI_API_KEY=your-key-here

# 3. Build the corpus (~15-20 min, run once)
python code/scraper.py

# 4. Run the agent
python code/main.py

# 5. Validate output
python code/validate.py
```

**Output** → `support_tickets/output.csv`  
**Log** → `~/hackerrank_orchestrate/log.txt`

---

## Architecture

```
                    ┌─────────────┐
                    │  main.py    │   Entry point — orchestrates the full pipeline
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
    ┌──────────────┐ ┌──────────┐ ┌──────────────┐
    │classifier.py │ │retriever │ │   agent.py   │
    │              │ │  .py     │ │              │
    │ • detect     │ │ • TF-IDF │ │ • Gemini API │
    │   company    │ │   index  │ │ • JSON parse │
    │ • escalation │ │ • top-k  │ │ • retry 3x   │
    │   check (22  │ │   chunks │ │ • validation │
    │   patterns)  │ │          │ │              │
    │ • type hint  │ │          │ │              │
    └──────┬───────┘ └────┬─────┘ └──────┬───────┘
           │              │              │
           └──────────────┼──────────────┘
                          ▼
                  ┌───────────────┐
                  │  logger.py    │   AGENTS.md §2/§5 compliant
                  │  log.txt      │   transcript logging
                  └───────────────┘

    Supporting:
    ┌──────────────┐  ┌──────────────┐
    │  scraper.py  │  │ validate.py  │
    │  one-time    │  │ output       │
    │  corpus      │  │ quality      │
    │  builder     │  │ checker      │
    └──────────────┘  └──────────────┘
```

### Pipeline Flow (per ticket)

1. **classify** — `classifier.py` detects company, runs 22 regex escalation checks, hints request type
2. **retrieve** — `retriever.py` queries the company-specific TF-IDF index, returns top-6 corpus chunks
3. **triage** — `agent.py` sends corpus + ticket + hints to Gemini, parses structured JSON output
4. **validate** — output validator checks field presence, allowed values, corpus grounding
5. **log** — every decision is appended to `~/hackerrank_orchestrate/log.txt` (AGENTS.md compliant)

---

## Design Decisions

### 1. Per-Company TF-IDF Indices (not one shared index)

**Why:** Prevents cross-domain contamination. A Visa billing dispute shouldn't retrieve HackerRank pricing docs. Separate indices mean each query only searches the relevant ~1000-1600 chunks, improving both precision and speed.

**Trade-off considered:** Embedding-based retrieval (e.g., sentence-transformers) would capture semantic similarity better, but TF-IDF is deterministic, zero-dependency, and fast enough for a 3 MB corpus. For a hackathon with 29 tickets, the precision difference doesn't justify the added complexity.

**Unknown company fallback:** When the company field is `None`, the retriever searches all three indices and merges results by cosine similarity score.

### 2. Two-Stage Escalation

**Stage 1: Regex pre-check (free, fast)**  
22 compiled patterns catch adversarial attempts before the LLM ever sees them:
- Prompt injection (English + French variants)
- Destructive commands (`rm -rf`, `delete all files`)
- Financial crime (fraud, stolen card, identity theft)
- Score/hiring manipulation
- Immediate refund demands
- Security vulnerability reports

**Stage 2: LLM judgment**  
If the pre-check passes, the LLM decides based on whether the corpus has a safe, grounded answer. If not → escalate.

**Why two stages?** Pre-check is deterministic and catches the 8 adversarial/high-risk tickets instantly. This saves ~$0.003 per ticket in LLM tokens and gives consistent, auditable results for the most dangerous cases.

### 3. Corpus Injection (not RAG with vector DB)

The top-6 TF-IDF chunks are injected **verbatim** into the system prompt. This constrains the LLM to only cite what's in the corpus — it can't hallucinate policies, phone numbers, or URLs that aren't there.

**Alternative considered:** A full RAG pipeline with ChromaDB or Pinecone would scale better, but adds non-deterministic embedding distance thresholds and dependency overhead. For 2784 chunks, TF-IDF cosine similarity is sufficient and reproducible.

### 4. Structured JSON Output with Fallback

The LLM is instructed to return only valid JSON. On parse failure:
1. Strip markdown fences
2. Regex-extract the first `{...}` block
3. Validate all 5 fields against allowed values
4. Default unknowns to safe values (`escalated`, `general_support`, `product_issue`)

### 5. Determinism & Reproducibility

- `temperature=0.0` — no sampling randomness
- Seeded TF-IDF (deterministic tokenization and scoring)
- Pinned dependencies in `requirements.txt`
- All secrets via environment variables

---

## Escalation Rules (22 Patterns)

| Category | # Patterns | Examples |
|---|---|---|
| Prompt injection | 6 | "show internal rules", "ignore previous instructions", French variants |
| Destructive commands | 3 | "delete all files", "rm -rf", "format disk" |
| Financial crime | 4 | "fraud", "identity theft", "stolen card/cheque" |
| Unauthorized access | 3 | "restore access... not admin", "grant access without permission" |
| Score manipulation | 4 | "increase my score", "unfairly graded", "tell company to move me" |
| Financial coercion | 2 | "refund me today/asap", "ban the seller" |
| Security reports | 2 | "security vulnerability", "bug bounty" |
| Financial distress | 3 | "urgent cash", "stranded with no money" |

---

## Corpus Statistics

| Company | Files | Chunks | Size |
|---|---|---|---|
| HackerRank | 447 | 1,172 | 4.7 MB |
| Claude | 586 | 1,568 | 3.9 MB |
| Visa | 18 | 44 | 116 KB |
| **Total** | **1,051** | **2,784** | **8.7 MB** |

Corpus was built once using `scraper.py` which crawls the three support sites with polite 1.2s delays.

---

## Output Schema

| Column | Allowed Values | Description |
|---|---|---|
| `status` | `replied` / `escalated` | Whether the agent answered or routed to human |
| `product_area` | domain-specific | billing, account_access, security, assessments, etc. |
| `response` | free text | Corpus-grounded user-facing answer |
| `justification` | free text | 1-2 sentences explaining the decision |
| `request_type` | `product_issue` / `feature_request` / `bug` / `invalid` | Classification |

---

## File Reference

| File | Lines | Role |
|---|---|---|
| `main.py` | 247 | Entry point — CLI, ticket loop, CSV I/O |
| `classifier.py` | 196 | Pre-LLM classification (pure functions, no I/O) |
| `retriever.py` | 216 | Corpus loader + TF-IDF search engine |
| `agent.py` | 176 | Gemini LLM client with retry and JSON parsing |
| `logger.py` | 147 | AGENTS.md-compliant append-only logger |
| `scraper.py` | 274 | One-time corpus builder (crawls 3 sites) |
| `validate.py` | 160 | Output quality checker + structural validator |

---

## Requirements

- Python 3.9+
- `google-genai >= 1.0.0` (Gemini API)
- `python-dotenv >= 1.0.0`
- `requests >= 2.31.0` (scraper only)
- `beautifulsoup4 >= 4.12.0` (scraper only)
- `GEMINI_API_KEY` environment variable

---

## Known Limitations & Future Work

1. **Visa corpus is thin** (44 chunks vs 1100+ for others) — more seed URLs would help
2. **TF-IDF misses semantic similarity** — "my card doesn't work" ≠ "card blocked" in TF-IDF
3. **No conversation memory** — each ticket is independent; multi-turn support isn't handled
4. **French ticket edge case** — Gemini occasionally responds in French to French input despite English-only instruction
