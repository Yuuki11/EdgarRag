// Login, registration, email verification, forgot-password, and reset-password
// screen. Token-bearing URLs are handled here before returning to the main app.

import { useMemo, useState } from "react";
import {
  forgotPassword,
  login,
  register,
  resetPassword,
  verifyEmail,
  type User,
} from "../api";

type Mode = "login" | "register" | "forgot" | "reset" | "verify";

type Props = {
  initialMode?: Mode;
  token?: string | null;
  onAuthenticated: (user: User) => void;
};

export default function AuthScreen({ initialMode = "login", token, onAuthenticated }: Props) {
  const [mode, setMode] = useState<Mode>(initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const title = useMemo(() => {
    if (mode === "register") return "Create account";
    if (mode === "forgot") return "Reset password";
    if (mode === "reset") return "Choose new password";
    if (mode === "verify") return "Verify email";
    return "Sign in";
  }, [mode]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    setMessage("");
    try {
      if (mode === "login") {
        const status = await login(email, password);
        if (status.user) onAuthenticated(status.user);
      } else if (mode === "register") {
        await register(email, password);
        setMessage("Verification email sent. In local console mode, copy the link from the backend logs.");
        setMode("login");
      } else if (mode === "forgot") {
        await forgotPassword(email);
        setMessage("Password reset instructions sent if the account exists.");
      } else if (mode === "reset") {
        const status = await resetPassword(token ?? "", password);
        setMessage("Password reset. Sign in with your new password.");
        if (status.user) setEmail(status.user.email);
        setMode("login");
      } else if (mode === "verify") {
        await verifyEmail(token ?? "");
        setMessage("Email verified. You can sign in now.");
        setMode("login");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-page">
      <form className="auth-panel" onSubmit={submit}>
        <h1>FinEdgar</h1>
        <h2>{title}</h2>
        {(mode === "login" || mode === "register" || mode === "forgot") && (
          <label>
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
            />
          </label>
        )}
        {(mode === "login" || mode === "register" || mode === "reset") && (
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              minLength={mode === "login" ? 1 : 12}
              required
            />
          </label>
        )}
        {message && <div className="notice">{message}</div>}
        {error && <div className="error">{error}</div>}
        <button type="submit" disabled={loading}>
          {loading ? "Working..." : title}
        </button>
        <div className="auth-links">
          {mode !== "login" && <button type="button" onClick={() => setMode("login")}>Sign in</button>}
          {mode !== "register" && <button type="button" onClick={() => setMode("register")}>Create account</button>}
          {mode !== "forgot" && <button type="button" onClick={() => setMode("forgot")}>Forgot password</button>}
        </div>
      </form>
    </main>
  );
}
