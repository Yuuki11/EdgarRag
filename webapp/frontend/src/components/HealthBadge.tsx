// Compact app/model/data health indicator shown in the main header.

import type { Health } from "../api";

export default function HealthBadge({ health }: { health: Health | null }) {
  if (!health) {
    return <span className="badge badge-unknown">checking…</span>;
  }
  const ok = health.ollama_reachable && health.indexed_companies > 0;
  return (
    <div className="health">
      <span className={ok ? "badge badge-ok" : "badge badge-warn"}>
        {ok ? "all-local" : "degraded"}
      </span>
      <span className="health-detail">
        {health.ollama_reachable ? "Ollama ✓" : "Ollama ✗"}
        {" · "}
        {health.indexed_companies} indexed
        {health.xbrl_cache_warm ? " · XBRL ✓" : ""}
        {" · "}
        {health.compute_mode === "cpu" ? "RAM-only" : "GPU auto"}
      </span>
    </div>
  );
}
