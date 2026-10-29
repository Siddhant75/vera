import { useState } from "react";
import { sendFeedback } from "../api";

const BADGE = {
  supported: ["badge green", "supported"],
  contradicted: ["badge red", "contradicted"],
  disputed: ["badge yellow", "disputed"],
};

function ClaimRow({ runId, claim, proof }) {
  const [voted, setVoted] = useState(0);
  const [open, setOpen] = useState(false);
  const verdict = proof?.verdict;
  const [cls, label] = verdict ? BADGE[verdict] || BADGE.disputed : ["badge", "unverified"];
  return (
    <li className="claim-row">
      <div className="claim-line">
        <button type="button" className={cls} onClick={() => setOpen(!open)} title="Show verification proof">
          {label}
        </button>
        <span className="claim-text">{claim.text}</span>
        <span className="claim-cites">
          {claim.citation_urls.map((u, i) => (
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
      {open && proof && (
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
  if (!report || report.error) return null;
  return (
    <div className="report">
      {report.changes?.length > 0 && (
        <div className="delta-box">
          <strong>What changed since your last research:</strong>
          <ul>{report.changes.map((c, i) => <li key={i}>{c}</li>)}</ul>
        </div>
      )}
      {report.sections.map((sec, i) => (
        <section key={i}>
          <h3>{sec.sub_question}</h3>
          <p>{sec.narrative}</p>
          {sec.claims.length > 0 && (
            <ul className="claims">
              {sec.claims.map((c) => (
                <ClaimRow key={c.id} runId={runId} claim={c}
                          proof={report.claim_proofs?.[c.id]} />
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
      {report.sources_unused?.length > 0 && (
        <section>
          <h3>Sources Vera saw but didn't cite</h3>
          <p className="muted">Fetched from the live web but not needed for any claim — judge them yourself.</p>
          <ul className="unused-sources">
            {report.sources_unused.map((s, i) => (
              <li key={i}><a href={s.url} target="_blank" rel="noreferrer">{s.title || s.url}</a></li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
