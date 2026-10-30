import { useState, useMemo } from "react";
import { sendFeedback } from "../api";

const BADGE = {
  supported: ["badge green", "supported"],
  contradicted: ["badge red", "contradicted"],
  disputed: ["badge yellow", "disputed"],
};

function getDomain(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function buildMarkdownDraft(report) {
  if (!report) return "";
  let md = `# Research Report: ${report.brief || "Untitled"}\n\n`;
  if (report.bottom_line) {
    md += `## Bottom Line\n${report.bottom_line}\n\n`;
  }
  if (report.changes?.length > 0) {
    md += `## What Changed Since Prior Research\n`;
    for (const ch of report.changes) {
      md += `- ${ch}\n`;
    }
    md += "\n";
  }
  if (report.sections?.length > 0) {
    for (const sec of report.sections) {
      md += `## ${sec.sub_question}\n\n${sec.narrative}\n\n`;
      if (sec.claims?.length > 0) {
        md += `### Verified Claims\n`;
        for (const c of sec.claims) {
          const v = report.claim_verdicts?.[c.id] || "unverified";
          const cites = c.citation_urls?.length > 0 ? ` (Sources: ${c.citation_urls.join(", ")})` : "";
          md += `- [${v.toUpperCase()}] ${c.text}${cites}\n`;
        }
        md += "\n";
      }
    }
  }
  if (report.open_questions?.length > 0) {
    md += `## Open Questions\n`;
    for (const q of report.open_questions) {
      md += `- ${q}\n`;
    }
    md += "\n";
  }
  if (report.sources_cited?.length > 0) {
    md += `## Bibliography (Sources Cited)\n`;
    for (const s of report.sources_cited) {
      md += `- [${s.title || s.url}](${s.url})\n`;
    }
    md += "\n";
  }
  return md;
}

function ClaimRow({ runId, claim, proof, isOpen, onToggle }) {
  const [voted, setVoted] = useState(0);
  const verdict = proof?.verdict;
  const [cls, label] = verdict ? BADGE[verdict] || BADGE.disputed : ["badge", "unverified"];
  return (
    <li className="claim-row">
      <div className="claim-line">
        <button type="button" className={cls} onClick={onToggle} title="Toggle verification proof">
          {label}
        </button>
        <span className="claim-text">{claim.text}</span>
        <span className="claim-cites">
          {claim.citation_urls?.map((u, i) => (
            <a key={i} href={u} target="_blank" rel="noreferrer">[{i + 1}]</a>
          ))}
        </span>
        {voted !== 0 ? (
          <span className="claimed-feedback">{voted > 0 ? "helpful ✓" : "not helpful ✓"}</span>
        ) : (
          <span className="feedback-btns">
            <button type="button" onClick={() => { setVoted(1); sendFeedback(runId, claim.id, true, claim.text); }}>👍</button>
            <button type="button" onClick={() => { setVoted(-1); sendFeedback(runId, claim.id, false, claim.text); }}>👎</button>
          </span>
        )}
      </div>
      {isOpen && proof && (
        <div className="claim-proof">
          <strong>Verification proof</strong>
          <p>{proof.reason}</p>
          {proof.votes?.length > 0 && (
            <div className="claim-votes">
              <strong>Model votes (final round):</strong>
              <ul>
                {proof.votes.map((v, i) => (
                  <li key={i}>
                    <span className={`badge ${v.verdict === "supported" ? "green" : v.verdict === "contradicted" ? "red" : "yellow"}`}>
                      {v.verdict}
                    </span>{" "}
                    {v.model?.split("/").pop()} — {v.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {proof.prosecution && (
            <div className="claim-prosecution">
              <strong>⚖️ Prosecutor's counter-evidence hunt:</strong>
              <p>{proof.prosecution}</p>
            </div>
          )}
          <small>
            {proof.web_checked
              ? "⚖️ Models disagreed → Tavily live-web re-check performed"
              : "✓ All verifier models agreed on first pass"}
          </small>
        </div>
      )}
    </li>
  );
}

export default function ReportView({ runId, report }) {
  const [viewMode, setViewMode] = useState("report");
  const [copied, setCopied] = useState(false);
  const [showAllUnused, setShowAllUnused] = useState(false);
  const markdownDraft = useMemo(() => buildMarkdownDraft(report), [report]);
  const allClaimIds = report?.sections?.flatMap((s) => s.claims?.map((c) => c.id) || []) || [];
  const firstClaimId = allClaimIds[0];
  const [expandedIds, setExpandedIds] = useState(() => new Set(firstClaimId ? [firstClaimId] : []));
  const [prevFirstClaimId, setPrevFirstClaimId] = useState(firstClaimId);

  if (firstClaimId !== prevFirstClaimId) {
    setPrevFirstClaimId(firstClaimId);
    setExpandedIds(new Set(firstClaimId ? [firstClaimId] : []));
  }

  if (!report || report.error) return null;

  const handleCopyDraft = async () => {
    try {
      await navigator.clipboard.writeText(markdownDraft);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // fallback if clipboard api fails
    }
  };

  const toggleClaim = (id) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const allOpen = allClaimIds.length > 0 && allClaimIds.every((id) => expandedIds.has(id));
  const toggleAll = () => {
    if (allOpen) {
      setExpandedIds(new Set());
    } else {
      setExpandedIds(new Set(allClaimIds));
    }
  };

  const summary = report.verdict_summary || {};
  return (
    <div className="report">
      <div className="report-meta">
        <span className={`badge ${report.depth === "quick" ? "yellow" : report.depth === "deep" ? "" : "green"}`}>
          {report.depth || "standard"} research
        </span>
        {report.run_summary?.tf_tokens_run !== undefined && (
          <span className="badge green" title="Run cost">
            ⚡ {(report.run_summary.tf_tokens_run || 0).toLocaleString()} tokens · {report.run_summary.tavily_searches_run || report.run_summary.searches_used || 0} searches
          </span>
        )}
        {report.persona && <span className="muted">for a {report.persona}</span>}
        {allClaimIds.length > 0 && viewMode === "report" && (
          <button type="button" className="btn-toggle-proofs" onClick={toggleAll}>
            {allOpen ? "Collapse All Proofs" : "Expand All Proofs"}
          </button>
        )}
      </div>

      <div className="view-mode-tabs">
        <button
          type="button"
          className={viewMode === "report" ? "active" : ""}
          onClick={() => setViewMode("report")}
        >
          Executive Report & Proofs
        </button>
        <button
          type="button"
          className={viewMode === "draft" ? "active" : ""}
          onClick={() => setViewMode("draft")}
        >
          Full Research Draft (Markdown)
        </button>
      </div>

      {viewMode === "draft" ? (
        <div className="draft-view-container">
          <div className="draft-actions">
            <span className="muted">Complete compiled draft text with cited sources and bottom line</span>
            <button type="button" className="btn-copy-draft" onClick={handleCopyDraft}>
              {copied ? "Copied! ✓" : "📋 Copy Draft to Clipboard"}
            </button>
          </div>
          <pre className="markdown-draft">{markdownDraft}</pre>
        </div>
      ) : (
        <>
          {Object.keys(summary).length > 0 && (
            <div className="verdict-strip">
              {Object.entries(summary).map(([k, n]) => (
                <span key={k} className={`badge ${k === "supported" ? "green" : k === "contradicted" ? "red" : "yellow"}`}>
                  {n} {k}
                </span>
              ))}
            </div>
          )}
          {report.bottom_line && (
            <div className="bottom-line">
              <strong>Bottom line</strong>
              <p>{report.bottom_line}</p>
            </div>
          )}
          {report.changes?.length > 0 && (
            <div className="delta-box">
              <strong>What changed since your last research:</strong>
              <ul>{report.changes.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </div>
          )}
          {report.notes_considered > 0 && (
            <p className="muted">💡 Considered {report.notes_considered} private note{report.notes_considered === 1 ? "" : "s"} for this topic — their content stays yours.</p>
          )}
          {report.sections?.map((sec, i) => (
            <section key={i}>
              <h3>{sec.sub_question}</h3>
              <p>{sec.narrative}</p>
              {sec.claims?.length > 0 && (
                <ul className="claims">
                  {sec.claims.map((c) => (
                    <ClaimRow
                      key={c.id}
                      runId={runId}
                      claim={c}
                      proof={report.claim_proofs?.[c.id]}
                      isOpen={expandedIds.has(c.id)}
                      onToggle={() => toggleClaim(c.id)}
                    />
                  ))}
                </ul>
              )}
            </section>
          ))}
          {report.open_questions?.length > 0 && (
            <section>
              <h3>Open questions</h3>
              <ul>{report.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
            </section>
          )}
          {report.sources_cited?.length > 0 && (
            <section className="sources-cited-section">
              <div className="section-header-row">
                <h3>Sources cited</h3>
                <span className="badge green">{report.sources_cited.length} authoritative links</span>
              </div>
              <p className="muted">Directly grounded citations supporting load-bearing claims in this report.</p>
              <div className="source-cards-grid">
                {report.sources_cited.map((s, i) => (
                  <a
                    key={i}
                    href={s.url}
                    target="_blank"
                    rel="noreferrer"
                    className="source-card"
                    title={s.url}
                  >
                    <div className="source-card-top">
                      <span className="domain-badge">{getDomain(s.url)}</span>
                      <span className="source-index">#{i + 1} ↗</span>
                    </div>
                    <div className="source-card-title">{s.title || s.url}</div>
                  </a>
                ))}
              </div>
            </section>
          )}
          {report.sources_unused?.length > 0 && (
            <section className="transparency-pool-section">
              <div className="transparency-card">
                <div className="transparency-header">
                  <div className="transparency-title-group">
                    <h3>⚖️ Transparency Pool (Evaluated Web Evidence)</h3>
                    <span className="badge yellow">{report.sources_unused.length} uncited sources</span>
                  </div>
                  {report.sources_unused.length > 5 && (
                    <button
                      type="button"
                      className="btn-toggle-sources"
                      onClick={() => setShowAllUnused(!showAllUnused)}
                    >
                      {showAllUnused
                        ? "Collapse to 5"
                        : `Show all ${report.sources_unused.length} evaluated sources`}
                    </button>
                  )}
                </div>
                <p className="transparency-explanation">
                  Tavily retrieved these live web sources during grounding, but Vera's drafter &amp; verifier
                  discarded them as redundant, unverified, or irrelevant to prevent hallucinated trivia and keep your report focused.
                </p>
                <ul className="transparency-list">
                  {(showAllUnused ? report.sources_unused : report.sources_unused.slice(0, 5)).map((s, i) => (
                    <li key={i} className="transparency-item">
                      <span className="domain-pill">{getDomain(s.url)}</span>
                      <a href={s.url} target="_blank" rel="noreferrer" className="transparency-link">
                        {s.title || s.url} <span className="arrow">↗</span>
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
