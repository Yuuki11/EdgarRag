// Read-only operator dashboard backed by `/api/admin/overview`.

import { useEffect, useState } from "react";
import type { AdminOverview } from "../api";
import { fetchAdminOverview } from "../api";

type Props = {
  onBack: () => void;
};

export default function AdminDashboard({ onBack }: Props) {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      setOverview(await fetchAdminOverview());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <main className="admin-page">
      <header className="admin-topbar">
        <div>
          <h1>Admin</h1>
          <p>Runtime, data, and auth state for the FinEdgar deployment.</p>
        </div>
        <div className="admin-actions">
          <a href="/metrics" target="_blank" rel="noreferrer">Metrics</a>
          <a href="/healthz" target="_blank" rel="noreferrer">Health</a>
          <button type="button" onClick={refresh} disabled={loading}>
            {loading ? "Refreshing" : "Refresh"}
          </button>
          <button type="button" onClick={onBack}>Chat</button>
        </div>
      </header>

      {error && <div className="admin-error">{error}</div>}
      {!overview && !error && <div className="admin-loading">Loading admin overview...</div>}

      {overview && (
        <div className="admin-content">
          <section className="admin-section">
            <div className="section-head">
              <h2>System State</h2>
              <span>Updated {formatTime(overview.generated_at)}</span>
            </div>
            <div className="metric-grid">
              {overview.metrics.map((metric) => (
                <article className="metric-card" key={metric.label}>
                  <span className={`status-dot status-${metric.status}`} />
                  <div>
                    <p>{metric.label}</p>
                    <strong>{String(metric.value ?? "unknown")}</strong>
                    {metric.detail && <small>{metric.detail}</small>}
                  </div>
                </article>
              ))}
            </div>
          </section>

          <section className="admin-section two-column">
            <div>
              <div className="section-head">
                <h2>Runtime</h2>
              </div>
              <dl className="admin-dl">
                <Row label="Environment" value={overview.runtime.environment} />
                <Row label="Release" value={overview.runtime.release} />
                <Row
                  label="Kubernetes"
                  value={overview.runtime.running_in_kubernetes ? "yes" : "no"}
                />
                <Row label="Pod" value={overview.runtime.pod_name ?? "local process"} />
                <Row label="Namespace" value={overview.runtime.namespace ?? "n/a"} />
                <Row label="Node" value={overview.runtime.node_name ?? "n/a"} />
              </dl>
            </div>

            <div>
              <div className="section-head">
                <h2>Data Artifacts</h2>
              </div>
              <div className="artifact-list">
                {overview.data_artifacts.map((artifact) => (
                  <div className="artifact-row" key={artifact.name}>
                    <span className={`status-dot ${artifact.present ? "status-ok" : "status-warn"}`} />
                    <div>
                      <strong>{artifact.name}</strong>
                      <code>{artifact.path}</code>
                      <small>
                        {artifact.present ? `${artifact.files} files` : "missing"}
                        {artifact.detail ? ` · ${artifact.detail}` : ""}
                      </small>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="admin-section">
            <div className="section-head">
              <h2>Recent Auth Events</h2>
            </div>
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Event</th>
                    <th>Email</th>
                    <th>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.recent_auth_events.length === 0 && (
                    <tr>
                      <td colSpan={3}>No auth events recorded yet.</td>
                    </tr>
                  )}
                  {overview.recent_auth_events.map((event, index) => (
                    <tr key={`${event.created_at}-${index}`}>
                      <td>{event.event_type}</td>
                      <td>{event.email ?? "n/a"}</td>
                      <td>{formatTime(event.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

function formatTime(value: string) {
  return new Date(value).toLocaleString();
}
