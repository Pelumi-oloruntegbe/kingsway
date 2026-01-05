import { useState } from "react";
import "./App.css"; // still reuse your styles

export default function JobCard({ job }) {
  const [expanded, setExpanded] = useState(false);

  const fullText = job.description || "";
  const shortText = fullText.length > 100
    ? fullText.slice(0, 100) + "..."
    : fullText;

  return (
    <div className="job-card">
      <h2 className="job-title">{job.job_title}</h2>
      <p className="job-meta">
        {job.company_name} — {job?.discovery_input?.location}
      </p>

      <p className="job-desc">
        {expanded ? fullText : shortText}
        {fullText.length > 100 && (
          <button
            className="toggle-btn"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? " Show less" : " Read more"}
          </button>
        )}
      </p>

      {job.apply_link && (
        <a
          href={job.apply_link}
          target="_blank"
          rel="noopener noreferrer"
          className="apply-btn"
        >
          Apply
        </a>
      )}
    </div>
  );
}
