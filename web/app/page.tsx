"use client";

import { FormEvent, useEffect, useState } from "react";

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8001";
const AGENT = process.env.NEXT_PUBLIC_AGENT_URL ?? "http://localhost:8000";

type Customer = {
  id: string;
  name: string;
  region: string;
  mobile_plan: string | null;
  home_internet: string | null;
  contract: string | null;
  account_status: string;
  overdue_balance_eur: number;
  travel_pass_enabled: boolean;
};

type AgentReply =
  | { type: "answer"; text: string }
  | { type: "approval"; interrupt_id: string; tool: string; input: Record<string, unknown> };

type Message =
  | { role: "user" | "agent" | "error"; text: string }
  | { role: "approval"; reply: Extract<AgentReply, { type: "approval" }>; decided?: boolean };

export default function Home() {
  const [token, setToken] = useState<string | null>(null);
  const [me, setMe] = useState<Customer | null>(null);

  useEffect(() => {
    // localStorage only exists in the browser, so read the saved session after mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setToken(localStorage.getItem("token"));
  }, []);

  useEffect(() => {
    if (!token) return;
    fetch(`${BACKEND}/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setMe)
      .catch(() => {
        localStorage.removeItem("token"); // expired or invalid session
        setToken(null);
      });
  }, [token]);

  function logout() {
    if (token) fetch(`${AGENT}/chat`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
    localStorage.removeItem("token");
    setToken(null);
    setMe(null);
  }

  if (!token) return <Login onLogin={(t) => { localStorage.setItem("token", t); setToken(t); }} />;
  if (!me) return <main className="center">Loading…</main>;
  return (
    <main className="layout">
      <Profile me={me} onLogout={logout} />
      <Chat token={token} />
    </main>
  );
}

function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [customerId, setCustomerId] = useState("C1001");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const r = await fetch(`${BACKEND}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ customer_id: customerId, password }),
      });
      if (!r.ok) return setError("Wrong customer ID or password");
      onLogin((await r.json()).token);
    } catch {
      setError("Backend is not reachable");
    }
  }

  return (
    <main className="center">
      <form className="card login" onSubmit={submit}>
        <h1>NovaTel</h1>
        <label>
          Customer ID
          <input value={customerId} onChange={(e) => setCustomerId(e.target.value)} required />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit">Log in</button>
        <p className="hint">Test customers C1001–C1004, password: demo</p>
      </form>
    </main>
  );
}

function Profile({ me, onLogout }: { me: Customer; onLogout: () => void }) {
  const rows: [string, string][] = [
    ["Customer ID", me.id],
    ["Region", me.region],
    ["Mobile plan", me.mobile_plan ?? "—"],
    ["Home internet", me.home_internet ?? "—"],
    ["Contract", me.contract ?? "—"],
    ["Account status", me.account_status],
    ["Overdue balance", `€${me.overdue_balance_eur.toFixed(2)}`],
    ["Travel Pass", me.travel_pass_enabled ? "on" : "off"],
  ];
  return (
    <aside className="card">
      <h2>{me.name}</h2>
      <dl>
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      <button className="secondary" onClick={onLogout}>Log out</button>
    </aside>
  );
}

function Chat({ token }: { token: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);

  async function call(path: string, body: object) {
    setBusy(true);
    try {
      const r = await fetch(`${AGENT}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
      const reply: AgentReply = await r.json();
      setMessages((m) => [...m, reply.type === "answer" ? { role: "agent", text: reply.text } : { role: "approval", reply }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "error", text: `Agent error: ${(e as Error).message}` }]);
    } finally {
      setBusy(false);
    }
  }

  function send(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    call("/chat", { message: text });
  }

  function decide(index: number, interruptId: string, approved: boolean) {
    setMessages((m) => m.map((msg, i) => (i === index ? { ...msg, decided: true } : msg)));
    call("/chat/approve", { interrupt_id: interruptId, approved });
  }

  return (
    <section className="card chat">
      <div className="messages" aria-live="polite">
        {messages.length === 0 && <p className="hint">Ask about your plan, roaming, billing or a connection problem.</p>}
        {messages.map((m, i) =>
          m.role === "approval" ? (
            <div key={i} className="msg approval">
              <strong>Operator approval: the agent wants to call {m.reply.tool}</strong>
              <pre>{JSON.stringify(m.reply.input, null, 2)}</pre>
              {!m.decided && (
                <div className="actions">
                  <button onClick={() => decide(i, m.reply.interrupt_id, true)} disabled={busy}>Approve</button>
                  <button className="secondary" onClick={() => decide(i, m.reply.interrupt_id, false)} disabled={busy}>Reject</button>
                </div>
              )}
            </div>
          ) : (
            <div key={i} className={`msg ${m.role}`}>{m.text}</div>
          ),
        )}
        {busy && <div className="msg agent">…</div>}
      </div>
      <form className="composer" onSubmit={send}>
        <input
          aria-label="Message"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message"
          disabled={busy || messages.some((m) => m.role === "approval" && !m.decided)}
        />
        <button type="submit" disabled={busy}>Send</button>
      </form>
    </section>
  );
}
