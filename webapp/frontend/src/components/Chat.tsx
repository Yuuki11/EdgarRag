// Chat input and transcript container.

import { useEffect, useRef, useState } from "react";
import type { Company } from "../api";
import type { ChatTurn } from "../App";
import Message from "./Message";

type Props = {
  turns: ChatTurn[];
  company: Company | null;
  year: number | null;
  disabled?: boolean;
  onAsk: (q: string) => void;
};

export default function Chat({ turns, company, year, disabled = false, onAsk }: Props) {
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const q = input.trim();
    if (!q) return;
    onAsk(q);
    setInput("");
  }

  const placeholder = company
    ? `Ask about ${company.ticker}${year ? ` (FY${year})` : ""}…`
    : "Pick a company on the left to begin.";

  return (
    <div className="chat">
      <div className="chat-scroll" ref={scrollRef}>
        {turns.length === 0 && <EmptyState />}
        {turns.map((t) => (
          <Message key={t.id} turn={t} />
        ))}
      </div>
      <form className="composer" onSubmit={submit}>
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit(e as unknown as React.FormEvent);
            }
          }}
          placeholder={placeholder}
          disabled={!company || disabled}
          rows={2}
        />
        <button type="submit" disabled={!company || disabled || !input.trim()}>
          Ask
        </button>
      </form>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="empty-state">
      <h2>Single-shot QA over SEC filings.</h2>
      <p>
        Pick a ticker and fiscal year on the left, then ask a question. Numeric
        lookups are routed to the structured XBRL data; narrative questions are
        answered by a local Gemma model via Ollama.
      </p>
      <p className="hint">
        Try: <em>&ldquo;What was AAPL&rsquo;s FY2023 revenue?&rdquo;</em> or{" "}
        <em>&ldquo;What are AMD&rsquo;s major products as of FY22?&rdquo;</em>
      </p>
    </div>
  );
}
