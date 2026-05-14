// Company and fiscal-year selector for constraining chat questions.

import { useMemo, useState } from "react";
import type { Company } from "../api";

type Props = {
  companies: Company[];
  selectedTicker: string | null;
  selectedYear: number | null;
  onTickerChange: (t: string) => void;
  onYearChange: (y: number | null) => void;
};

export default function CompanyPicker({
  companies,
  selectedTicker,
  selectedYear,
  onTickerChange,
  onYearChange,
}: Props) {
  const [filter, setFilter] = useState("");

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return companies;
    return companies.filter(
      (c) =>
        c.ticker.toLowerCase().includes(q) || c.name.toLowerCase().includes(q),
    );
  }, [companies, filter]);

  const selected = companies.find((c) => c.ticker === selectedTicker) ?? null;

  return (
    <div className="picker">
      <input
        type="search"
        placeholder="Filter tickers"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="picker-filter"
      />
      <ul className="picker-list">
        {filtered.map((c) => (
          <li key={c.ticker}>
            <button
              type="button"
              className={c.ticker === selectedTicker ? "selected" : ""}
              onClick={() => onTickerChange(c.ticker)}
              title={c.name}
            >
              <span className="ticker">{c.ticker}</span>
              <span className="name">{c.name}</span>
            </button>
          </li>
        ))}
        {filtered.length === 0 && <li className="empty">No match.</li>}
      </ul>
      {selected && selected.years.length > 0 && (
        <div className="year-row">
          <label htmlFor="year-select">Fiscal year</label>
          <select
            id="year-select"
            value={selectedYear ?? ""}
            onChange={(e) =>
              onYearChange(e.target.value === "" ? null : Number(e.target.value))
            }
          >
            <option value="">Any</option>
            {selected.years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </div>
      )}
    </div>
  );
}
