import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BiBuildings, BiCurrentLocation} from "react-icons/bi";
import { GoSponsorTiers } from "react-icons/go";
import { FiMenu, FiX } from 'react-icons/fi';
import { MdOutlinePayments } from "react-icons/md";
import "./App.css";

export default function JobsPage() {
  const [jobs, setJobs] = useState([]);
  const [q, setQ] = useState("");
  const [loc, setLoc] = useState("All");
  const navigate = useNavigate();
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    fetch("/data_fetch_16_09_2025_filtered_yes_maybe_ratings.json").then(r => r.json()).then(setJobs);
  }, []);
  useEffect(() => {
    const checkScreenSize = () => {
      setIsMobile(window.innerWidth <= 768);
    };

    // Initial check
    checkScreenSize();

    // Add listener
    window.addEventListener('resize', checkScreenSize);

    // Close menu when resizing to desktop
    if (window.innerWidth > 768) {
      setIsMenuOpen(false);
    }

    // Cleanup
    return () => window.removeEventListener('resize', checkScreenSize);
  }, []);

  // Close menu when clicking outside (for mobile)
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (isMenuOpen && isMobile && !e.target.closest('.menu') && !e.target.closest('.burger-menu')) {
        setIsMenuOpen(false);
      }
    };

    document.addEventListener('click', handleClickOutside);
    return () => document.removeEventListener('click', handleClickOutside);
  }, [isMenuOpen, isMobile]);

  // Prevent body scroll when menu is open
  useEffect(() => {
    if (isMenuOpen && isMobile) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = 'unset';
    }

    return () => {
      document.body.style.overflow = 'unset';
    };
  }, [isMenuOpen, isMobile]);

  const toggleMenu = () => {
    setIsMenuOpen(!isMenuOpen);
  };

  const closeMenu = () => {
    if (isMobile) {
      setIsMenuOpen(false);
    }
  };
  const locations = useMemo(() => {
    const s = new Set(jobs.map(j => j?.discovery_input?.location).filter(Boolean));
    return ["All", ...Array.from(s).sort((a,b)=>a.localeCompare(b))];
  }, [jobs]);

  const filteredJobs = useMemo(() => {
    const query = q.trim().toLowerCase();
    return jobs.filter(j => {
      const title = (j.job_title || "").toLowerCase();
      const company = (j.company_name || "").toLowerCase();
      const location = (j?.discovery_input?.location || "").toLowerCase();
      const matchQuery = !query || title.includes(query) || company.includes(query) || location.includes(query);
      const matchLoc = loc === "All" || location === loc.toLowerCase();
      return matchQuery && matchLoc;
    });
  }, [jobs, q, loc]);

  return (
    <div className="page">
      <header className="controls">

        
        <div className="logo">
          <img src="/logo.png" alt="My Logo"/>
        </div>

        <nav class="header">

          <div className={`menu ${isMenuOpen ? 'active' : ''}`}>
        <a href="#sponsored-jobs" onClick={closeMenu}>
          Sponsored Jobs
        </a>
        <a href="#ai-tool" onClick={closeMenu}>
          Learn About Our AI Tool
        </a>
        <a href="#how-it-works" onClick={closeMenu}>
          How It Works
        </a>
        <a href="#companies" onClick={closeMenu}>
          Companies
        </a>
      </div>
        <button 
        className={`burger-menu ${isMenuOpen ? 'active' : ''}`}
        onClick={toggleMenu}
        aria-label={isMenuOpen ? "Close menu" : "Open menu"}
        aria-expanded={isMenuOpen}
      >
        {isMenuOpen ? (
          <FiX className="burger-icon" aria-hidden="true" />
        ) : (
          <FiMenu className="burger-icon" aria-hidden="true" />
        )}
        
      </button>

      {isMenuOpen && isMobile && (
        <div className="menu-overlay" onClick={() => setIsMenuOpen(false)} />
      )}
        </nav>
      </header>
      <div className="hero">
        <div>Find your dream remote job Abroad.</div>
        <span>Discover verified jobs that offer visa sponsorship — in the US, UK, Canada, Europe, and Australia.</span>
        <div className="controls-right">
          <input
            className="input"
            type="text"
            placeholder="Search title, company, location…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <select className="select" value={loc} onChange={(e) => setLoc(e.target.value)}>
            {locations.map(L => <option key={L} value={L}>{L}</option>)}
          </select>
        </div>
      </div>
      <div className="jobs-grid">
        {filteredJobs.map((job, idx) => (
          <div key={idx} className="job-card">
            <h2 className="job-title">{job.job_title}</h2>
            <div className="job-meta">
              <span><BiBuildings size={20}/><p>{job.company_name}</p></span>
              <span><BiCurrentLocation size={20}/><p>{job?.discovery_input?.location}</p></span>
              <span><GoSponsorTiers size={20}/><p>{job.likely_to_sponsor}%</p></span>
              <span><MdOutlinePayments size={20}/><p>{job.salary_formatted}</p></span>  
            </div> 
            <hr /> 
            <div className="job-duration">
              <p>posted 3 days ago</p>
            </div>
            <div className="btn-row">
              {job.apply_link && (
                <a
                  className="btn"
                  href={job.apply_link}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Apply
                </a>
              )}

              <button
                className="btn btn-secondary"
                onClick={() => navigate("/apply-with-ai", { state: { job } })}
              >
                Apply with our AI tool
              </button>
            </div>
          </div>
        ))}
      </div>
      <div className="work-section">
        <div className="work-title">
          <span>How It Works</span>
          <span>We make visa sponsorship job hunting simple and transparent. No more guessing which employers will sponsor you.</span>
        </div>
        <div className="work-grid">
          <div className="work-card">
            <span></span>
            <h3>Choose Your Details</h3>
            <p>Select the visa you want, your location preferences, education level, and experience.</p>
          </div>
          <div className="work-card">
            <span></span>
            <h3>Choose Your Details</h3>
            <p>Select the visa you want, your location preferences, education level, and experience.</p>
          </div>
          <div className="work-card">
            <span></span>
            <h3>Choose Your Details</h3>
            <p>Select the visa you want, your location preferences, education level, and experience.</p>
          </div>
          <div className="work-card">
            <span></span>
            <h3>Choose Your Details</h3>
            <p>Select the visa you want, your location preferences, education level, and experience.</p>
          </div>
        </div>
        <div className="work-sponsor">
          <span></span>
          <div className="sponsor">Verified Sponsorship Data</div>
          <p>All our sponsorship information is verified through official government databases and employer partnerships. We update our data monthly to ensure accuracy and relevance.</p>
        </div>
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
