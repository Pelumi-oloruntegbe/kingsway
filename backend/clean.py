#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cleaned.py — Cloud Shell-friendly batch processor

Workflow (no args):
  - Reads *.json from INPUT_DIR (default: ./data/incoming)
  - For each file:
      * detect description field
      * classify visa sponsorship as YES / No / Maybe (OpenAI with regex fallback)
      * write two outputs to OUTPUT_DIR (default: ./data/processed):
          - <name>_labeled.json (all records with labels)
          - <name>_filtered_yes_maybe.json (No records removed)

Environment:
  - OPENAI_API_KEY must be set to use the OpenAI classifier. If missing, rules fallback is used.
  - Override input/output dirs via env:
      * INPUT_DIR=./my_in  OUTPUT_DIR=./my_out  python cleaned.py

Optional CLI:
  python cleaned.py --file path/to/file.json
"""
import os
import re
import json
import html
import time
import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

# ------------------------
# Config
# ------------------------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")  # read by NAME, not value
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

INPUT_DIR = Path(os.environ.get("INPUT_DIR", "./data/incoming"))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "./job-board/public"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ------------------------
# Heuristics and regexes
# ------------------------
CANDIDATE_KEYS = [
    "description_text", "description", "job_description", "job_desc", "jobDescription",
    "details", "content", "job_description_formatted", "job_description_html",
    "job_description_long", "job_details", "summary"
]
SENT_SPLIT = re.compile(r'(?<=[\.\!\?])\s+|\n+')
TAG_RE = re.compile(r"<[^>]+>")

NEG_PATTERNS = [
    r'\bno\b[^\.!\?]*\bvisa\s+sponsorship\b',
    r'\bvisa\s+sponsorship\s+(is\s+)?(not\s+available|unavailable)\b',
    r'\bnot\b[^\.!\?]*\boffer\b[^\.!\?]*\b(sponsorship|visa)\b',
    r'\bdo(?:es)?\s+not\b[^\.!\?]*\b(sponsor|provide|offer)\b',
    r'\bcannot\b[^\.!\?]*\b(sponsor|provide|offer)\b',
    r'\bunable\b[^\.!\?]*\b(sponsor|provide|offer)\b',
    r'\bno\s+sponsorship\b',
    r'\bnot\s+able\s+to\s+sponsor\b',
    r'\bwon\'?t\s+(provide|offer)\b[^\.!\?]*\b(sponsorship|visa)\b',
    r'\bright\s+to\s+work\b[^\.!\?]*\bwithout\b[^\.!\?]*\b(sponsorship|visa)\b',
    r'\bvisa\s+sponsorship\b[^\.!\?]*\bnot\b[^\.!\?]*\bavailable\b',
    r'\bvisa\s+sponsorship\b[^\.!\?]*\bnot\b[^\.!\?]*\bprovided\b',
    r'\bwe\s+cannot\s+consider\s+candidates\s+requiring\s+sponsorship\b',
    r'\bvisa\s+sponsorship\s+not\s+available\b',
    r'\bdo\s+not\s+provid\w*\s+(visa\s+)?sponsorship\b',
]
POS_PATTERNS = [
    r'\bvisa\s+sponsorship\s+(is\s+)?(available|provided|offered)\b(?![^\.!\?]*(?:subject\s+to|T&Cs|depending|already\s+residing|already\s+in\s+the\s+UK))',
    r'\bwe\s+can\s+(provide|offer)\b[^\.!\?]*\b(visa\s+sponsorship|sponsorship)\b(?![^\.!\?]*(?:subject\s+to|T&Cs|depending|already\s+residing|already\s+in\s+the\s+UK))',
    r'\bwill\s+(provide|offer)\b[^\.!\?]*\b(visa\s+sponsorship|sponsorship)\b(?![^\.!\?]*(?:subject\s+to|T&Cs|depending|already\s+residing|already\s+in\s+the\s+UK))',
    r'\bcan\s+sponsor\b[^\.!\?]*(skilled\s*worker|tier\s*2|work\s+visa)\b(?![^\.!\?]*(?:subject\s+to|T&Cs|depending|already\s+residing|already\s+in\s+the\s+UK))',
    r'\bcertificate\s+of\s+sponsorship\b[^\.!\?]*(provided|available|offered)\b(?![^\.!\?]*(?:subject\s+to|T&Cs|depending|already\s+residing|already\s+in\s+the\s+UK))',
    r'\bsponsorship\b[^\.!\?]*\bavailable\b(?![^\.!\?]*(?:subject\s+to|T&Cs|depending|already\s+residing|already\s+in\s+the\s+UK))',
]
MAYBE_PATTERNS = [
    r'\bmay\s+(consider|offer|provide)\b[^\.!\?]*\b(visa\s+sponsorship|sponsorship)\b',
    r'\bpossible\b[^\.!\?]*\b(visa\s+sponsorship|sponsorship)\b',
    r'\bdepending\s+on\b[^\.!\?]*(eligibility|experience|role|criteria)\b[^\.!\?]*\b(sponsorship|visa)\b',
    r'\bcase\s+by\s+case\b[^\.!\?]*\b(sponsorship|visa)\b',
    r'\bsubject\s+to\b[^\.!\?]*\b(visa|sponsorship)\b',
    r'\bexceptional\s+cases\b[^\.!\?]*\b(sponsorship|visa)\b',
    r'\bfor\s+the\s+right\s+candidate\b[^\.!\?]*\b(sponsorship|visa)\b',
    r'\bT&Cs\s+apply\b[^\.!\?]*\b(sponsorship|visa)\b',
    r'\b(already\s+residing|already\s+in)\s+the\s+UK\b[^\.!\?]*\b(visa|sponsorship)\b',
    r'\bUK\s+only\b[^\.!\?]*\b(sponsorship|visa)\b',
]
NEG_RE = [re.compile(p, flags=re.I) for p in NEG_PATTERNS]
POS_RE = [re.compile(p, flags=re.I) for p in POS_PATTERNS]
MAYBE_RE = [re.compile(p, flags=re.I) for p in MAYBE_PATTERNS]

# ------------------------
# Helpers
# ------------------------
def load_json_records(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        first = f.read(1); f.seek(0)
        if first == "[":
            recs = json.load(f)
        else:
            recs = [json.loads(line) for line in f if line.strip()]
    if not isinstance(recs, list):
        raise ValueError(f"{path} must contain a list of records or JSONL")
    return recs

def detect_desc_key(records: List[Dict[str, Any]]) -> Optional[str]:
    counts = {}
    for rec in records[:250]:
        if isinstance(rec, dict):
            for k in rec.keys():
                if k in CANDIDATE_KEYS:
                    counts[k] = counts.get(k, 0) + 1
    if counts:
        return "description_text" if "description_text" in counts else sorted(counts.items(), key=lambda x: (-x[1], x[0]))[0][0]
    adhoc = {}
    for rec in records[:250]:
        for k in (rec.keys() if isinstance(rec, dict) else []):
            if re.search(r'description', k, flags=re.I):
                adhoc[k] = adhoc.get(k, 0) + 1
    if adhoc:
        return sorted(adhoc.items(), key=lambda x: (-x[1], x[0]))[0][0]
    return None

def clean_text(text: str) -> str:
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    t = html.unescape(text)
    if "<" in t and ">" in t:
        t = TAG_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def extract_text(rec: Dict[str, Any], desc_key: Optional[str]) -> str:
    if desc_key and isinstance(rec, dict) and desc_key in rec and isinstance(rec[desc_key], str):
        return clean_text(rec[desc_key])
    for k in CANDIDATE_KEYS:
        if isinstance(rec, dict) and k in rec and isinstance(rec[k], str) and rec[k].strip():
            return clean_text(rec[k])
    return ""

def focus_window(text: str, window_sentences: int = 1, max_chars: int = 1600) -> Tuple[str, str]:
    sentences = [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]
    full_trunc = (text[:max_chars] + "…") if len(text) > max_chars else text
    if not sentences:
        return full_trunc, full_trunc
    idx = None
    for i, s in enumerate(sentences):
        if re.search(r'\bvisa\s+sponsorship\b', s, flags=re.I) or re.search(r'\bsponsorship\b', s, flags=re.I):
            idx = i; break
    if idx is None:
        win = " ".join(sentences[: min(3, len(sentences))])
        return win, full_trunc
    start = max(0, idx-1); end = min(len(sentences), idx+2)
    return " ".join(sentences[start:end]), full_trunc

def fallback_rules(text: str) -> Tuple[str, str]:
    if not text.strip():
        return "Maybe", "Empty description"
    sentences = [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]
    joined = " ".join(sentences) if sentences else text
    verdicts = []
    for i, s in enumerate(sentences):
        if re.search(r'\b(visa\s+sponsorship|sponsorship)\b', s, flags=re.I):
            window = " ".join(sentences[max(0, i-1):min(len(sentences), i+2)])
            if any(p.search(window) for p in NEG_RE):
                verdicts.append("No")
            elif any(p.search(window) for p in MAYBE_RE):
                verdicts.append("Maybe")
            elif any(p.search(window) for p in POS_RE):
                verdicts.append("YES")
    if verdicts:
        if "No" in verdicts: return "No", "Negative near 'sponsorship'"
        if "Maybe" in verdicts: return "Maybe", "Caveats near 'sponsorship'"
        if "YES" in verdicts: return "YES", "Positive near 'sponsorship'"
    if any(p.search(joined) for p in NEG_RE): return "No", "Global negatives"
    if any(p.search(joined) for p in MAYBE_RE): return "Maybe", "Global caveats"
    if any(p.search(joined) for p in POS_RE): return "YES", "Global positives"
    return "Maybe", "Inconclusive"

def call_openai(label_context: str, full_context: str) -> Tuple[str, str]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    system = (
        "You are a precise classifier for job ads. Decide if the description supports that visa sponsorship "
        "is available.\n"
        "Output strictly JSON with keys: label (one of YES, No, Maybe) and rationale (<=20 words).\n"
        "Decision policy (apply in this order):\n"
        "1) Negative language like 'no sponsorship', 'cannot sponsor', or 'right to work without sponsorship' => 'No'.\n"
        "2) Explicit, unqualified 'visa sponsorship available/provided/offered' => 'YES'.\n"
        "3) Conditional or unclear ('may consider', 'case by case', 'subject to', 'depending on') => 'Maybe'.\n"
        "If inconclusive, return 'Maybe'. Keep answers terse."
    )
    payload = {
        "model": MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps({
                "focused_window": label_context[:2000],
                "full_context_hint": full_context[:2000]
            })}
        ],
    }
    resp = requests.post(OPENAI_URL, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    obj = json.loads(content)
    label = str(obj.get("label", "Maybe")).strip()
    rationale = str(obj.get("rationale", "")).strip()
    up = label.upper()
    if up == "YES": return "YES", rationale
    if up == "NO": return "No", rationale
    return "Maybe", rationale

def classify_record(rec: Dict[str, Any], desc_key: Optional[str]) -> Dict[str, Any]:
    text = extract_text(rec, desc_key)
    window, full = focus_window(text)
    try:
        label, reason = call_openai(window, full)
    except Exception:
        label, reason = fallback_rules(text)
        reason = f"{reason} (fallback)"
    out = dict(rec)
    out["visa_sponsorship"] = label
    out["visa_sponsorship_reason"] = reason
    return out

def classify_records(records: List[Dict[str, Any]], provided_key: Optional[str]=None) -> Tuple[List[Dict[str, Any]], Dict[str, int], Optional[str]]:
    desc_key = provided_key or detect_desc_key(records)
    labeled = [classify_record(r, desc_key) for r in records]
    counts = {"YES": 0, "No": 0, "Maybe": 0}
    for r in labeled:
        counts[r["visa_sponsorship"]] = counts.get(r["visa_sponsorship"], 0) + 1
    return labeled, counts, desc_key

def filter_yes_maybe(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in records if str(r.get("visa_sponsorship","")).strip().upper() in {"YES","MAYBE"}]

def process_file(path: Path, out_dir: Path) -> Dict[str, Any]:
    name = path.stem
    records = load_json_records(path)
    labeled, counts, desc_key = classify_records(records)
    filtered = filter_yes_maybe(labeled)

    labeled_path = out_dir / f"{name}_labeled.json"
    filtered_path = out_dir / f"{name}_filtered_yes_maybe.json"

    labeled_path.write_text(json.dumps(labeled, ensure_ascii=False, indent=2), encoding="utf-8")
    filtered_path.write_text(json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "file": str(path),
        "desc_key": desc_key,
        "counts": counts,
        "kept": len(filtered),
        "out_labeled": str(labeled_path),
        "out_filtered": str(filtered_path)
    }

def main():
    parser = argparse.ArgumentParser(description="Batch classify visa sponsorship and filter out 'No'.")
    parser.add_argument("--file", help="Process a single JSON file (array or JSONL). If omitted, process all *.json in INPUT_DIR.")
    args = parser.parse_args()

    if args.file:
        src = Path(args.file)
        if not src.exists():
            print(f"[ERR] File not found: {src}")
            return
        report = process_file(src, OUTPUT_DIR)
        print(json.dumps(report, indent=2))
        return

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(INPUT_DIR.glob("*.json"))
    if not files:
        print(f"[INFO] No JSON files found in {INPUT_DIR}. Place files there or use --file.")
        return

    summary = []
    for i, f in enumerate(files, 1):
        print(f"[{i}/{len(files)}] Processing {f.name} ...")
        try:
            report = process_file(f, OUTPUT_DIR)
            print(f"  -> kept {report['kept']} | desc_key={report['desc_key']}")
            summary.append(report)
        except Exception as e:
            print(f"  !! error: {e}")

    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
