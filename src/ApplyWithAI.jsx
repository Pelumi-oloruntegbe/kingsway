import { useLocation, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import "./App.css";

export default function ApplyWithAI() {
  const { state } = useLocation();
  const navigate = useNavigate();
  const job = state?.job;

  const [cv, setCv] = useState("");
  const [letter, setLetter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedStyle, setSelectedStyle] = useState("summary");
  const [rewrittenCv, setRewrittenCv] = useState(""); 
  const [editAction, setEditAction] = useState("longer"); 
  const [cvReview, setCvReview] = useState(null);  


  // If someone hits this route directly, send them home
  useEffect(() => {
    if (!job) navigate("/");
  }, [job, navigate]);

  async function generateLetter() {
    try {
      setLoading(true);
      setError("");
      setLetter("");


      // 1) Validate first
    const review = await validateCv();
    if (!review) return; // validation error surfaced already
    if (review.enough === false) {
      // Show advice and do not proceed automatically
      setError(
        `Your CV seems incomplete for this JD (score ${review.score}). ` +
        (review.advice || "Please add more detail.")
      );
      return;
    }

    // 2) Proceed to generate if enough

      const res = await fetch("/api/cover-letter", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          cv_text: cv,
          job: {
            job_title: job?.job_title,
            company_name: job?.company_name,
            description: job?.description,
            discovery_input: { location: job?.discovery_input?.location || "" }
          },
          style: selectedStyle
        }),
      });

      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setLetter(data.letter);
    } catch (e) {
      console.error(e);
      setError("Failed to generate letter.");
    } finally {
      setLoading(false);
    }
  }

  // call the rewrite endpoint to create a JD-matched CV
  async function rewriteAsCv() {
    try {
      setLoading(true);
      setError("");
      setRewrittenCv("");

      const res = await fetch("/api/rewrite-to-cv", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          cv_text: cv,                 // user’s original CV text
          // letter,                      // optional: reuse generated letter if present
          job: {
            job_title: job?.job_title,
            company_name: job?.company_name,
            description: job?.description,
            discovery_input: { location: job?.discovery_input?.location || "" }
          }
        }),
      });

      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setRewrittenCv(data.cv);
    } catch (e) {
      console.error(e);
      setError("Failed to rewrite CV.");
    } finally {
      setLoading(false);
    }
  }

  // to modify letter
  async function modifyLetter() {
  try {
    setLoading(true);
    setError("");

    const res = await fetch("/api/edit-letter", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        action: editAction,       
        letter,                   // current letter text
        cv_text: cv,              // useful context for edits
        job: {
          job_title: job?.job_title,
          company_name: job?.company_name,
          description: job?.description || "",
          discovery_input: { location: job?.discovery_input?.location || "" }
        }
      }),
    });

    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    setLetter(data.letter);      // replace with edited letter
  } catch (e) {
    console.error(e);
    setError("Failed to modify letter.");
  } finally {
    setLoading(false);
  }
  }

  async function validateCv() {
  try {
    const res = await fetch("/api/validate-cv", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        cv_text: cv,
        job: {
          job_title: job?.job_title,
          company_name: job?.company_name,
          description: job?.description || "",
          discovery_input: { location: job?.discovery_input?.location || "" }
        }
      })
    });
    const text = await res.text();
    if (!res.ok) throw new Error(text);
    const data = JSON.parse(text);
    setCvReview(data);
    return data;
  } catch (e) {
    console.error(e);
    setError("CV validation failed.");
    return null;
  }
  }

  return (
    <div className="page">
      <div className="apply-page">
        <button className="btn-link" onClick={() => navigate(-1)}>← Back</button>
        <h1>Apply with our AI tool</h1>

        {job && (
        <div className="job-card" style={{ marginTop: 12 }}>
          <h2 className="job-title">{job.job_title}</h2>
          <p className="job-meta">
            {job.company_name} — {job?.discovery_input?.location}
          </p>
           <p className="job-meta">
            {job.description.substring(0, 700)}
            ... 
            <p>Click to read full job description</p>
          </p>
        </div>
        )}

        <div className="panel">
        <label className="label">Paste your CV text</label>
        <textarea
          className="textarea"
          rows={10}
          placeholder="Paste your CV here…"
          value={cv}
          onChange={(e) => setCv(e.target.value)}
        />
        <label className="label">Choose cover letter style</label>
        <select
          className="select"
          value={selectedStyle}
          onChange={(e) => setSelectedStyle(e.target.value)}
        >
          <option value="summary">Summary Cover Letter</option>
          <option value="detailed">Detailed Cover Letter</option>
          <option value="speculative">Speculative Cover Letter</option>
        </select>   
        <button
          className="btn"
          onClick={generateLetter}
          disabled={!cv || !job?.description || loading}
          title={!cv ? "Paste your CV first" : ""}
        >
          {loading ? "Generating…" : "Generate cover letter"}
        </button>
        
        <button
            className="btn btn-secondary"
            onClick={rewriteAsCv}
            disabled={!cv || !job?.description || loading}
            title={!cv ? "Paste your CV first" : ""}
          >
            {loading ? "Rewriting…" : "Rewrite as CV (match JD)"}
          </button>


        {error && <p className="error">{error}</p>}
        </div>

        {letter && (
        <div className="letter-panel">
          <h3>Cover Letter</h3>
          <pre className="letter">{letter}</pre>
          <div className="btn-row">
            <button
              className="btn btn-secondary"
              onClick={() => navigator.clipboard.writeText(letter)}
            >
              Copy to clipboard
            </button>
           
        <label className="label"> Modify Cover letter </label>
        <select
          className="select"
          value={editAction}
          onChange={(e) => setEditAction(e.target.value)}
        >
          <option value="concise">More Concise</option>
          <option value="detailed">More Detailed </option>
          <option value="Personal"> More Personal </option>
          <option value="Friendly"> More Friendly </option>
          <option value="Creative"> More Creative </option>
          <option value="Formal"> More Formal </option>
          <option value="Impactful"> More Impactful </option>

        </select> 

        <button
        className="btn"
        onClick={modifyLetter}
        disabled={!letter || loading}
      >
        {loading ? "Editing…" : "Apply change"}
        </button>

          </div>
        </div>
        )}
        {rewrittenCv && (
        <div className="letter-panel">
          <h3>JD-matched CV (Draft)</h3>
          <pre className="letter">{rewrittenCv}</pre>
          <div className="btn-row">
            <button
              className="btn btn-secondary"
              onClick={() => navigator.clipboard.writeText(rewrittenCv)}
            >
              Copy CV to clipboard
            </button>
          </div>
        </div>
        )}
      </div>
      <div className="footer">
    <div className="footer-content">
    <div className="footer-main-row">
      <div className="footer-brand">
        <div className="logo">
          <img src="/logo.png" alt="Company Logo"/>
        </div>
        <span className="footer-tagline">
          Discover verified visa-sponsored jobs worldwide.
        </span>
        <div className="footer-social">
          <span className="social-link">LinkedIn</span>
          <span className="social-link">Twitter</span>
          <span className="social-link">Instagram</span>
        </div>
      </div>

      {/* Email Subscription */}
      <div className="footer-subscription">
        <h3>Get Visa Job Alerts</h3>
        <span className="subscribe-description">
          Weekly opportunities in your inbox
        </span>
        
        <div className="subscribe-form">
          <div className="email-input-group">
            <input
              type="email"
              placeholder="Your email"
              className="email-input"
            />
            <button className="subscribe-btn">
              <span>Subscribe</span>
            </button>
          </div>
        </div>
      </div>
    </div>
    </div>
    <div className="footer-bottom">
    <span className="copyright">
      © {new Date().getFullYear()} Offer Leta. All rights reserved.
    </span>
    </div>
      </div>

    </div>
  );
}
