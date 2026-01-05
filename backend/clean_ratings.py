#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cleaned.py — Cloud Shell-friendly batch processor

Workflow (no args):
  - Reads *.json from INPUT_DIR (default: ./data/incoming)
  - For each file:
      * detect description field
      * classify visa sponsorship as YES / No / Maybe (OpenAI with regex fallback)  [now also looks at job_title]
      * fill missing apply_link using job_title + company_name + discovery_input.location (keeps existing apply_link)
      * compute 'likely_to_sponsor' (50–90%) for YES/Maybe using description_text + salary_formatted
      * write two outputs to OUTPUT_DIR (default: ./job-board/public):
          - <name>_labeled.json (all records with labels + possibly enriched apply_link + likely_to_sponsor)
          - <name>_filtered_yes_maybe.json (No records removed)

Environment:
  - OPENAI_API_KEY must be set to use the OpenAI classifier. If missing, rules fallback is used.
  - Optional search providers for apply_link enrichment (only if APPLY_LINK is blank). Provide any ONE of:
      * SERPAPI_KEY           (https://serpapi.com/)
      * SERPER_API_KEY        (https://serper.dev/)
      * BRAVE_API_KEY         (https://brave.com/search/api/)
      * BING_API_KEY          (legacy; deprecating)
    If none provided, we will NOT hit the web; we only use a safe fallback to any existing 'url' field when it looks like a job posting.
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
from urllib.parse import urlparse
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

# Search providers (any one is fine)
SERPAPI_KEY    = os.environ.get("SERPAPI_KEY")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY")
BRAVE_API_KEY  = os.environ.get("BRAVE_API_KEY")
BING_API_KEY   = os.environ.get("BING_API_KEY")

# Rate limiting for web calls
SEARCH_SLEEP_SEC = float(os.environ.get("SEARCH_SLEEP_SEC", "0.6"))

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

# Acceptable job domains
JOB_DOMAINS_HINTS = [
    "greenhouse.io", "boards.greenhouse.io", "lever.co", "workable.com", "jobs.lever.co",
    "smartrecruiters.com", "myworkdayjobs.com", "workday.com", "successfactors.com",
    "applytojob.com", "jobvite.com", "icims.com", "paylocity.com", "ashbyhq.com",
    "recruitee.com", "teamtailor.com", "bamboohr.com", "tal.net", "civilservicejobs.service.gov.uk",
    "nhs.jobs", "trac.jobs", "indeed.com", "indeed.co.uk", "linkedin.com", "glassdoor.com",
    "careers", "jobs", "vacancies"
]

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

def get_title(rec: Dict[str, Any]) -> str:
    return str(rec.get("job_title") or rec.get("title") or "").strip()

def get_salary_formatted(rec: Dict[str, Any]) -> str:
    # handle both 'salary_formatted' and common typo 'salary_fomratted'
    return str(rec.get("salary_formatted") or rec.get("salary_fomratted") or "").strip()

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
        return "Maybe", "Empty description/title"
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

def call_openai(label_context: str, full_context: str, job_title: str) -> Tuple[str, str]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set")
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    system = (
        "You are a precise classifier for job ads. Decide if the role offers visa sponsorship.\n"
        "Consider BOTH the job title and the description. If the title implies sponsorship (e.g., 'Tier 2 Visa Sponsorship'), that is strong evidence.\n"
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
                "job_title": job_title[:200],
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

# ---------- Salary parsing & rating ----------
SALARY_NUM = re.compile(r'(?i)(?:£|\$|€)?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([kK])?')
HOURLY_OR_DAILY = re.compile(r'(?i)\b(per\s*(hour|hr|day|diem)|/h|/hr|/day)\b')
ANNUAL_HINT = re.compile(r'(?i)\b(per\s*(annum|year)|pa|p\.a\.|annual|annum|year)\b')

def parse_salary_annual(s: str) -> Optional[float]:
    if not s: 
        return None
    if HOURLY_OR_DAILY.search(s) and not ANNUAL_HINT.search(s):
        return None  # skip non-annual to avoid bad penalties
    nums = []
    for m in SALARY_NUM.finditer(s):
        raw = m.group(1)
        has_k = bool(m.group(2))
        try:
            val = float(raw.replace(",", ""))
            if has_k:
                val *= 1000.0
            nums.append(val)
        except Exception:
            continue
    if not nums:
        return None
    return max(nums)  # use the higher figure if a range is present

def clamp(v: float, lo: int = 50, hi: int = 90) -> int:
    v = int(round(v))
    if v < lo: return lo
    if v > hi: return hi
    return v

def compute_likely_to_sponsor(label: str, combined_text: str, salary_formatted: str) -> Optional[int]:
    # Only for YES/Maybe
    up = (label or "").upper()
    if up == "NO":
        return None
    base = 80 if up == "YES" else 65  # YES naturally higher than Maybe

    # textual cues
    if any(r.search(combined_text) for r in POS_RE):
        base += 5
    if any(r.search(combined_text) for r in MAYBE_RE):
        base -= 5

    # salary penalty if < 42k
    annual = parse_salary_annual(salary_formatted)
    if annual is not None and annual < 42000:
        base -= 10

    return clamp(base, 50, 90)

# ---------- Core classification ----------
def classify_record(rec: Dict[str, Any], desc_key: Optional[str]) -> Dict[str, Any]:
    title = get_title(rec)
    desc = extract_text(rec, desc_key)
    combined = (title + ". " + desc).strip() if title else desc

    # Build window on combined text (title + description)
    window, full = focus_window(combined)

    try:
        label, reason = call_openai(window, full, title)
    except Exception:
        label, reason = fallback_rules(combined)
        reason = f"{reason} (fallback)"

    out = dict(rec)
    out["visa_sponsorship"] = label
    out["visa_sponsorship_reason"] = reason

    # Feature 2: likely_to_sponsor for YES/Maybe, using description + salary_formatted
    salary_str = get_salary_formatted(rec)
    rating = compute_likely_to_sponsor(label, combined, salary_str)
    if rating is not None:
        out["likely_to_sponsor"] = rating  # integer 50–90
    return out

def classify_records(records: List[Dict[str, Any]], provided_key: Optional[str]=None) -> Tuple[List[Dict[str, Any]], Dict[str, int], Optional[str]]:
    desc_key = provided_key or detect_desc_key(records)
    labeled = [classify_record(r, desc_key) for r in records]
    counts = {"YES": 0, "No": 0, "Maybe": 0}
    for r in labeled:
        counts[r["visa_sponsorship"]] = counts.get(r["visa_sponsorship"], 0) + 1
    return labeled, counts, desc_key

# ------------------------
# Apply-link enrichment
# ------------------------
def is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")

def is_probable_job_url(u: str, company_tokens: List[str], job_tokens: List[str]) -> bool:
    try:
        p = urlparse(u)
    except Exception:
        return False
    host = (p.netloc or "").lower()
    path = (p.path or "").lower()
    # must be http(s)
    if p.scheme not in ("http", "https"):
        return False
    # Host hints for known ATS / job boards
    for h in JOB_DOMAINS_HINTS:
        if h in host:
            return True
    # If company token appears in host and path looks job-ish
    if any(tok in host for tok in company_tokens) and any(w in path for w in ("job", "jobs", "careers", "vacancy", "vacancies", "apply")):
        return True
    # Path contains apply and job tokens
    if "apply" in path and any(tok in path for tok in job_tokens):
        return True
    return False

def company_tokens(name: str) -> List[str]:
    toks = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower()).split()
    bad = {"ltd","limited","plc","inc","llc","gmbh","bv","sa","ag","co","company","foundation","trust","nhs"}
    return [t for t in toks if t not in bad]

def job_tokens(title: str) -> List[str]:
    return [t for t in re.sub(r"[^a-z0-9 ]+"," ", (title or "").lower()).split() if len(t) > 2][:6]

def build_query(title: str, company: str, location: str) -> str:
    q = " ".join([s for s in [title, company, location, "apply"] if s])
    return q.strip()

def search_serpapi(query: str) -> List[str]:
    if not SERPAPI_KEY: return []
    params = {
        "engine": "google", "q": query, "num": "6", "hl": "en", "gl": "uk", "api_key": SERPAPI_KEY
    }
    r = requests.get("https://serpapi.com/search.json", params=params, timeout=30)
    if r.status_code != 200: return []
    data = r.json()
    links = []
    for it in data.get("organic_results", [])[:6]:
        link = it.get("link")
        if link: links.append(link)
    return links

def search_serper(query: str) -> List[str]:
    if not SERPER_API_KEY: return []
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type":"application/json"}
    r = requests.post("https://google.serper.dev/search", headers=headers, json={"q": query, "num": 6}, timeout=30)
    if r.status_code != 200: return []
    data = r.json()
    links = [it.get("link") for it in data.get("organic", []) if it.get("link")]
    return links[:6]

def search_brave(query: str) -> List[str]:
    if not BRAVE_API_KEY: return []
    headers = {"Accept":"application/json", "X-Subscription-Token": BRAVE_API_KEY}
    r = requests.get("https://api.search.brave.com/res/v1/web/search", headers=headers, params={"q": query, "count": 6, "country":"gb"}, timeout=30)
    if r.status_code != 200: return []
    data = r.json()
    links = [it.get("url") for it in data.get("web", {}).get("results", []) if it.get("url")]
    return links[:6]

def search_bing(query: str) -> List[str]:
    if not BING_API_KEY: return []
    headers = {"Ocp-Apim-Subscription-Key": BING_API_KEY}
    r = requests.get("https://api.bing.microsoft.com/v7.0/search", headers=headers, params={"q": query, "count": 6, "mkt":"en-GB"}, timeout=30)
    if r.status_code != 200: return []
    data = r.json()
    links = [it.get("url") for it in data.get("webPages", {}).get("value", []) if it.get("url")]
    return links[:6]

def best_search_links(query: str) -> List[str]:
    for fn in (search_serpapi, search_serper, search_brave, search_bing):
        try:
            links = fn(query)
            if links:
                return links
        except Exception:
            continue
        finally:
            time.sleep(SEARCH_SLEEP_SEC)
    return []

def enrich_apply_links(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for rec in records:
        rec2 = dict(rec)  # copy
        existing = rec2.get("apply_link")
        if not is_blank(existing):
            out.append(rec2)
            continue  # do not touch existing apply_link

        # Build query
        title = rec2.get("job_title") or rec2.get("title") or ""
        company = rec2.get("company_name") or rec2.get("employer") or ""
        location = ""
        di = rec2.get("discovery_input") or {}
        if isinstance(di, dict):
            location = di.get("location") or ""
        if not (title or company):
            out.append(rec2)  # nothing to search with
            continue

        query = build_query(title, company, location)
        comp_toks = company_tokens(company)
        jtoks = job_tokens(title)

        # If a generic 'url' looks like a job link, use that as first fallback (no web calls)
        url_fallback = rec2.get("url") or rec2.get("job_url") or rec2.get("link")
        if isinstance(url_fallback, str) and is_probable_job_url(url_fallback, comp_toks, jtoks):
            rec2["apply_link"] = url_fallback
            out.append(rec2)
            continue

        # Otherwise try web search if a provider is set
        if any([SERPAPI_KEY, SERPER_API_KEY, BRAVE_API_KEY, BING_API_KEY]):
            links = best_search_links(query)
            chosen = None
            for u in links:
                if is_probable_job_url(u, comp_toks, jtoks):
                    chosen = u
                    break
            if not chosen and links:
                chosen = links[0]
            if chosen:
                rec2["apply_link"] = chosen
        # else: leave blank (no web provider configured)
        out.append(rec2)
    return out

def filter_yes_maybe(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in records if str(r.get("visa_sponsorship","")).strip().upper() in {"YES","MAYBE"}]

# ------------------------
# Processing
# ------------------------
def process_file(path: Path, out_dir: Path) -> Dict[str, Any]:
    name = path.stem
    records = load_json_records(path)

    # Classify first (now uses title + description; adds likely_to_sponsor)
    labeled, counts, desc_key = classify_records(records)

    # Enrich apply_link ONLY where blank
    labeled = enrich_apply_links(labeled)

    # Then filter
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
    parser = argparse.ArgumentParser(description="Batch classify visa sponsorship, enrich apply_link, and filter out 'No'.")
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
