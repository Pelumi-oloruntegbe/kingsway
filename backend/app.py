import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

app = Flask(__name__)
# Allow your dev frontends. Tighten for prod.
CORS(app, resources={r"/api/*": {
    "origins": ["http://localhost:5173", "https://*.cloudshell.dev"]
}})

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")  # <-- read by NAME, not the value
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-4o-mini"  # or your preferred model

SYSTEM_PROMPT = """
You are an expert cover-letter writer. Your job is to:
- Read the job description (JD), infer its core requirements.
- Read the candidate’s CV, find evidence (skills/projects/results) that match those requirements.
- Write a tailored, professional cover letter (~500 words), with:
  - A concise opening showing enthusiasm and fit.
  - 1–2 focused body paragraphs that map JD requirements to CV evidence.
  - Specific action verbs and, where possible, outcomes/metrics.
  - A brief closing with availability/next steps.

Rules:
- Use ONLY facts present in the CV or the JD. Do not invent.
- Prefer concrete actions (“built”, “led”, “optimised”, “deployed”) over generic claims.
- If a JD requirement has no matching CV evidence, either omit it or acknowledge transferable experience—do not fabricate.

"""

def build_cv_review_prompt(cv_text: str, job: dict) -> str:
    title = job.get("job_title") or job.get("title") or "Unknown Title"
    company = job.get("company_name") or job.get("company") or "Unknown Company"
    location = (job.get("discovery_input") or {}).get("location", "")
    description = job.get("description") or ""

    return f"""
You are not a strict reviewer, check if the candidates CV has  jobs titles, company names and dates of employment

JOB
- Title: {title}
- Company: {company}
- Location: {location}

JOB DESCRIPTION (JD)
{description[:4000]}

CANDIDATE CV TEXT
{cv_text[:8000]}

TASK
Assess whether the CV text contains at least any of these relevant roles, skills/tech, responsibilities, projects, impact/results, dates/employers, and education/certs.

Respond ONLY in JSON with this exact shape:

{{
  "enough": true|false,
  "score": <integer 0-100>,
  "missing": [ "short bullet of a missing info", ... ],
  "advice": "1-3 sentences telling the candidate what to add next"
}}
"""











def build_user_prompt(cv_text: str, job: dict, style: str = "summary") -> str:
    title = job.get("job_title") or job.get("title") or "Unknown Title"
    company = job.get("company_name") or job.get("company") or "Unknown Company"
    location = (job.get("discovery_input") or {}).get("location", "")
    description = job.get("description") or ""

    if style == "summary":
        return f"""
You are writing a *Summary cover letter*.

JOB INFORMATION
- Title: {title}
- Company: {company}
- Location: {location}

JOB DESCRIPTION
{description[:6000]}

CANDIDATE CV
{cv_text[:9000]}

TASK
Write a ~500-word cover letter that:
- Summarises the candidate’s experience from the CV.
- Clearly highlights skills and experiences that match the JD.
- Uses a concise, professional style.
Output only the final letter text.
"""

    elif style == "detailed":
        return f"""
You are writing a *Detailed cover letter*.

JOB INFORMATION
- Title: {title}
- Company: {company}
- Location: {location}

JOB DESCRIPTION
{description[:6000]}

CANDIDATE CV
{cv_text[:9000]}

TASK
Write a 1500-word cover letter that:
- Summarises the key responsibilities from the JD.
- For each responsibility, match it to relevant skills/actions in the CV.
- Use a narrative STAR flavour (Situation, Task, Action, Result) but in flowing prose.
- Put the candidate in the best possible light while staying plausible.
Output only the final letter text.
"""

    elif style == "speculative":
        return f"""
You are writing a *Speculative cover letter* (JD is light).

JOB INFORMATION
- Title: {title}
- Company: {company}
- Location: {location}

CANDIDATE CV
{cv_text[:9000]}

TASK
Write a ~500-word cover letter that:
- Focuses primarily on the candidate’s CV and personal experiences.
- Summarises strengths, career path, and ambitions.
- Mentions the company/role briefly but keeps emphasis on the person.
- Style: confident, enthusiastic, professional.
Output only the final letter text.
"""

    else:
        return f"Invalid style selected. Got: {style}"

def build_rewrite_cv_prompt(cv_text: str, job: dict, letter: str | None = None) -> str:
    title = job.get("job_title") or job.get("title") or "Unknown Title"
    company = job.get("company_name") or job.get("company") or "Unknown Company"
    location = (job.get("discovery_input") or {}).get("location", "")
    description = job.get("description") or ""

    # We prefer to tailor from the CV + JD; if a cover letter is present,
    # we let the model mine additional phrasing, but the CV content must
    # stay factual and concise.
    return f"""
You are an expert technical CV writer.

JOB INFORMATION
- Title: {title}
- Company: {company}
- Location: {location}

JOB DESCRIPTION (JD)
{description[:6000]}

CANDIDATE CV (SOURCE FACTS)
{cv_text[:9000]}

OPTIONAL COVER LETTER (REFERENCE PHRASES ONLY — facts must still come from CV/JD)
{(letter or "")[:6000]}

TASK
Rewrite the candidate's CV so it best matches the JD while remaining truthful.
- Use standard CV structure (no personal info needed):
  1) Profile / Summary (3–5 lines)
  2) Core Skills (bullet list; align with JD terminology where applicable)
  3) Experience (reverse-chronological; 2–4 bullets per role; action verbs; results/metrics where present)
  4) Education / Certifications (if any appear in CV)
- Map JD responsibilities to relevant CV evidence. Do NOT invent new tools, employers, or dates.
- Keep to ~1 page worth of concise content. UK/US-neutral spelling is fine.
- Output plain text/markdown only (no analysis).

Output only the rewritten CV.
"""


# to modify result

def build_edit_prompt(action: str, letter: str, cv_text: str, job: dict) -> str:
    title = job.get("job_title") or job.get("title") or "Unknown Title"
    company = job.get("company_name") or job.get("company") or "Unknown Company"
    location = (job.get("discovery_input") or {}).get("location", "")
    description = job.get("description") or ""

    guidance = ""
    if action == "Concise":
        guidance = "Expand the letter by roughly 20% while keeping it concise and professional."
    elif action == "Detailed":
        guidance = "Tighten the letter by roughly 20%, keeping only the most relevant, high-impact lines."
    elif action == "Personal":
        guidance = ("Add concrete, truthful detail from the CV and JD—skills, tools, projects, responsibilities, "
                    "and outcomes/metrics where present. Do not invent facts.")
    elif action == "Creative":
        guidance = ("Restructure the body to follow a STAR-like narrative (Situation, Task, Action, Result) "
                    "while remaining flowing prose. Keep opening and closing succinct.")
    elif action == "Regenerate":
        guidance = "Regenerate a fresh version with the same goals and tone."
    elif action == "Formal":
             guidance = ("Change tone to formal tone and use formal languadge and descriptions")
    elif action == "Impactful":
             guidance = ("Emphasize achievement and goals mentioned in the CV")
    else:
        guidance = "Improve clarity and alignment with the JD and CV without changing the meaning."

    return f"""
You are editing an existing tailored cover letter.

JOB INFORMATION
- Title: {title}
- Company: {company}
- Location: {location}

JOB DESCRIPTION (JD)
{description[:6000]}

CANDIDATE CV (SOURCE FACTS)
{cv_text[:9000]}

CURRENT LETTER
{letter[:9000]}

EDIT INSTRUCTIONS
- {guidance}
- Keep the letter professional and tailored to the JD.
- Use only facts present in the CV or JD; do not invent.
- Output only the final letter text (no analysis or bullets).
"""



def call_openai(prompt: str) -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing OPENAI_API_KEY environment variable.")
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
    }
    r = requests.post(OPENAI_URL, headers=headers, json=payload, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"OpenAI error {r.status_code}: {r.text}")
    data = r.json()
    return data["choices"][0]["message"]["content"]

@app.post("/api/cover-letter")
def cover_letter():
    try:
        body = request.get_json(force=True)
        cv_text = (body.get("cv_text") or "").strip()
        job = body.get("job") or {}
        style = (body.get("style") or "summary").lower()

        if not cv_text:
            return jsonify({"error": "cv_text is required"}), 400
        if style != "speculative" and not (job.get("description") or ""):
            return jsonify({"error": "job.description is required for non-speculative styles"}), 400

        prompt = build_user_prompt(cv_text, job, style)  # <-- pass style
        letter = call_openai(prompt)
        return jsonify({"letter": letter})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
        
@app.post("/api/rewrite-to-cv")
def rewrite_to_cv():
    """
    JSON body:
    {
      "cv_text": "string",           # required
      "job": { ... },                # required (needs .description for best results)
      "letter": "string | null"      # optional; if present, can be used for phrasing
    }
    """
    try:
        body = request.get_json(force=True)
        cv_text = (body.get("cv_text") or "").strip()
        job = body.get("job") or {}
        letter = (body.get("letter") or "").strip()

        if not cv_text:
            return jsonify({"error": "cv_text is required"}), 400
        if not (job.get("description") or ""):
            return jsonify({"error": "job.description is required"}), 400

        prompt = build_rewrite_cv_prompt(cv_text, job, letter or None)
        rewritten = call_openai(prompt)
        return jsonify({"cv": rewritten})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/edit-letter")
def edit_letter():
    """
    JSON body:
    {
      "action": "longer" | "shorter" | "detail" | "star" | "regenerate",
      "letter": "string",   # required
      "cv_text": "string",  # recommended
      "job": { ... }        # recommended (with .description for best results)
    }
    """
    try:
        body = request.get_json(force=True)
        action = (body.get("action") or "regenerate").lower()
        letter = (body.get("letter") or "").strip()
        cv_text = (body.get("cv_text") or "").strip()
        job = body.get("job") or {}

        if not letter:
            return jsonify({"error": "letter is required"}), 400

        prompt = build_edit_prompt(action, letter, cv_text, job)
        edited = call_openai(prompt)
        return jsonify({"letter": edited})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.post("/api/validate-cv")
def validate_cv():
    try:
        body = request.get_json(force=True)
        cv_text = (body.get("cv_text") or "").strip()
        job = body.get("job") or {}

        if not cv_text:
            return jsonify({"error": "cv_text is required"}), 400
        # For a fair validation, prefer to have JD (but don't hard-fail if missing)
        if not (job.get("description") or ""):
            return jsonify({"error": "job.description is recommended for validation"}), 400

        prompt = build_cv_review_prompt(cv_text, job)
        raw = call_openai(prompt)
        # Try parsing JSON answer from the model
        import json
        data = json.loads(raw)
        # basic shape guardrails
        data.setdefault("enough", False)
        data.setdefault("score", 0)
        data.setdefault("missing", [])
        data.setdefault("advice", "")
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500



if __name__ == "__main__":
    # Dev server (use gunicorn for prod)
    app.run(host="0.0.0.0", port=5000, debug=True)
