// Renders a single user/assistant chat turn, including citations and XBRL facts.

import type { ChatTurn } from "../App";
import type { Citation, XbrlEvidence } from "../api";

export default function Message({ turn }: { turn: ChatTurn }) {
  return (
    <div className="turn">
      <div className="msg user">
        <div className="meta">
          <span className="role">You</span>
          {turn.ticker && <span className="scope">{turn.ticker}</span>}
          {turn.year && <span className="scope">FY{turn.year}</span>}
        </div>
        <div className="text">{turn.question}</div>
      </div>
      <div className="msg assistant">
        <div className="meta">
          <span className="role">FinEdgar</span>
          {turn.response && <RouteChip route={turn.response.route} />}
          {turn.response?.fallback_used && (
            <span className="chip chip-warn">fallback</span>
          )}
          {turn.response && (
            <span className="latency">
              {(turn.response.latency_ms / 1000).toFixed(2)}s
            </span>
          )}
        </div>
        {turn.loading && <div className="text loading">Thinking…</div>}
        {turn.error && <div className="text error">Error: {turn.error}</div>}
        {turn.response && (
          <>
            <div className="text answer">{turn.response.answer}</div>
            {turn.response.citations.length > 0 && (
              <CitationList citations={turn.response.citations} />
            )}
            {turn.response.xbrl_evidence.length > 0 && (
              <XbrlEvidenceList items={turn.response.xbrl_evidence} />
            )}
          </>
        )}
      </div>
    </div>
  );
}

function RouteChip({ route }: { route: string }) {
  const cls =
    route === "xbrl"
      ? "chip chip-xbrl"
      : route === "rag"
      ? "chip chip-rag"
      : "chip chip-hybrid";
  return <span className={cls}>{route.toUpperCase()}</span>;
}

function CitationList({ citations }: { citations: Citation[] }) {
  return (
    <details className="sources">
      <summary>{citations.length} source{citations.length === 1 ? "" : "s"}</summary>
      <ol>
        {citations.map((c) => (
          <li key={c.index}>
            <div className="cite-head">
              {c.ticker && <strong>{c.ticker}</strong>}
              {c.year && <> · FY{c.year}</>}
              {c.fiscal_period && <> · {c.fiscal_period}</>}
              {c.section && <> · {c.section}</>}
            </div>
            {c.snippet && <blockquote>{c.snippet}</blockquote>}
          </li>
        ))}
      </ol>
    </details>
  );
}

function XbrlEvidenceList({ items }: { items: XbrlEvidence[] }) {
  return (
    <details className="sources xbrl">
      <summary>{items.length} XBRL fact{items.length === 1 ? "" : "s"}</summary>
      <ul>
        {items.map((x, i) => (
          <li key={i}>
            <code>{x.concept ?? "—"}</code>
            {x.value !== null && x.value !== undefined && (
              <> = <strong>{String(x.value)}</strong></>
            )}
            {x.unit && <> {x.unit}</>}
            {x.period && <> · {x.period}</>}
            {x.form && <> · {x.form}</>}
            {x.accession && <> · {x.accession}</>}
          </li>
        ))}
      </ul>
    </details>
  );
}
