// Main application shell.
//
// Owns cross-cutting browser state: authentication, routing between chat/admin
// screens, company/year selection, conversation selection, and the current chat
// turns shown in the conversation pane.

import { useEffect, useMemo, useState } from "react";
import {
  type ChatResponse,
  type Company,
  type ConversationSummary,
  type Health,
  type MessageHistory,
  type User,
  createConversation,
  deleteConversation,
  fetchCompanies,
  fetchConversationMessages,
  fetchConversations,
  fetchHealth,
  fetchMe,
  logout,
  postChat,
  renameConversation,
} from "./api";
import AdminDashboard from "./components/AdminDashboard";
import AuthScreen from "./components/AuthScreen";
import CompanyPicker from "./components/CompanyPicker";
import Chat from "./components/Chat";
import ConversationSidebar from "./components/ConversationSidebar";
import HealthBadge from "./components/HealthBadge";

export type ChatTurn = {
  id: string;
  question: string;
  ticker: string | null;
  year: number | null;
  response: ChatResponse | null;
  error: string | null;
  loading: boolean;
};

export default function App() {
  const [authChecked, setAuthChecked] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [route, setRoute] = useState(() => window.location.pathname);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [selectedYear, setSelectedYear] = useState<number | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);

  useEffect(() => {
    const onPopState = () => setRoute(window.location.pathname);
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    fetchMe()
      .then((status) => setUser(status.user))
      .catch(() => setUser(null))
      .finally(() => setAuthChecked(true));
  }, []);

  useEffect(() => {
    if (!user) return;
    fetchCompanies()
      .then((cs) => {
        setCompanies(cs);
        if (cs.length && !selectedTicker) setSelectedTicker(cs[0].ticker);
      })
      .catch((e) => setLoadError(String(e)));
    fetchHealth().then(setHealth).catch(() => setHealth(null));
    refreshConversations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const selectedCompany = useMemo(
    () => companies.find((c) => c.ticker === selectedTicker) ?? null,
    [companies, selectedTicker],
  );

  useEffect(() => {
    // When the ticker changes, reset year selection to "any year" (null).
    setSelectedYear(null);
  }, [selectedTicker]);

  async function refreshConversations(selectId?: string | null) {
    const list = await fetchConversations();
    setConversations(list);
    if (selectId !== undefined) setSelectedConversationId(selectId);
  }

  async function selectConversation(id: string) {
    setSelectedConversationId(id);
    const messages = await fetchConversationMessages(id);
    setTurns(historyToTurns(messages));
  }

  async function newConversation() {
    const conversation = await createConversation();
    await refreshConversations(conversation.id);
    setTurns([]);
  }

  async function renameSelectedConversation(id: string, currentTitle: string) {
    const nextTitle = window.prompt("Rename chat", currentTitle);
    if (!nextTitle || !nextTitle.trim()) return;
    await renameConversation(id, nextTitle.trim());
    await refreshConversations(selectedConversationId);
  }

  async function removeConversation(id: string) {
    if (!window.confirm("Delete this chat?")) return;
    await deleteConversation(id);
    if (selectedConversationId === id) {
      setSelectedConversationId(null);
      setTurns([]);
    }
    await refreshConversations(selectedConversationId === id ? null : selectedConversationId);
  }

  async function signOut() {
    await logout();
    setUser(null);
    setTurns([]);
    setConversations([]);
    setSelectedConversationId(null);
    navigate("/");
  }

  function navigate(path: string) {
    window.history.pushState({}, "", path);
    setRoute(path);
  }

  async function ask(question: string) {
    const id = crypto.randomUUID();
    const turn: ChatTurn = {
      id,
      question,
      ticker: selectedTicker,
      year: selectedYear,
      response: null,
      error: null,
      loading: true,
    };
    setTurns((prev) => [...prev, turn]);

    try {
      const resp = await postChat({
        question,
        ticker: selectedTicker,
        years: selectedYear ? [selectedYear] : null,
        conversation_id: selectedConversationId,
      });
      if (resp.conversation_id && resp.conversation_id !== selectedConversationId) {
        setSelectedConversationId(resp.conversation_id);
      }
      setTurns((prev) =>
        prev.map((t) => (t.id === id ? { ...t, response: resp, loading: false } : t)),
      );
      await refreshConversations(resp.conversation_id ?? selectedConversationId);
    } catch (e) {
      setTurns((prev) =>
        prev.map((t) =>
          t.id === id ? { ...t, error: String(e), loading: false } : t,
        ),
      );
    }
  }

  if (!authChecked) {
    return <div className="boot">Loading...</div>;
  }

  if (!user) {
    const params = new URLSearchParams(window.location.search);
    const verifyToken = params.get("token");
    const path = window.location.pathname;
    const returnPath = path === "/admin" ? "/admin" : "/";
    const mode = path.includes("reset-password")
      ? "reset"
      : path.includes("verify-email")
      ? "verify"
      : "login";
    return (
      <AuthScreen
        initialMode={mode}
        token={verifyToken}
        onAuthenticated={(nextUser) => {
          window.history.replaceState({}, "", returnPath);
          setRoute(returnPath);
          setUser(nextUser);
        }}
      />
    );
  }

  if (route === "/admin") {
    return <AdminDashboard onBack={() => navigate("/")} />;
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <header className="sidebar-header">
          <h1>FinEdgar</h1>
          <p className="tagline">Local chat over SEC filings.</p>
          <HealthBadge health={health} />
          <div className="user-row">
            <span>{user.email}</span>
            <button type="button" onClick={() => navigate("/admin")}>Admin</button>
            <button type="button" onClick={signOut}>Sign out</button>
          </div>
        </header>
        <ConversationSidebar
          conversations={conversations}
          selectedId={selectedConversationId}
          onSelect={selectConversation}
          onNew={newConversation}
          onRename={renameSelectedConversation}
          onDelete={removeConversation}
        />
        <CompanyPicker
          companies={companies}
          selectedTicker={selectedTicker}
          selectedYear={selectedYear}
          onTickerChange={setSelectedTicker}
          onYearChange={setSelectedYear}
        />
        {loadError && <div className="error">{loadError}</div>}
      </aside>
      <main className="main">
        <Chat
          turns={turns}
          company={selectedCompany}
          year={selectedYear}
          disabled={false}
          onAsk={ask}
        />
      </main>
    </div>
  );
}

function historyToTurns(messages: MessageHistory[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  for (const message of messages) {
    if (message.role === "user") {
      turns.push({
        id: message.id,
        question: message.content,
        ticker: message.ticker,
        year: message.years?.[0] ?? null,
        response: null,
        error: null,
        loading: false,
      });
    } else if (message.role === "assistant" && turns.length > 0) {
      turns[turns.length - 1] = {
        ...turns[turns.length - 1],
        response: message.response,
      };
    }
  }
  return turns;
}
