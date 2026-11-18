import { ArrowDownRight, ArrowUpRight, BookOpen, ChevronRight, CircleAlert, Layers3, Play, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { api, decimal, defaultQuery, readableError } from "./api";
import type { Identity, MemoryResponse, Patch, Profile as CandidateRecord, Report, Run } from "./api";
import Evaluation from "./Evaluation";
import Explorer, { initialFilters, Status } from "./Explorer";
import type { Filters } from "./Explorer";
import Memory from "./Memory";
import Profile from "./Profile";

const pages = ["Explorer", "Daily matches", "Candidate profile", "Memory", "Evaluation"] as const;
type Page = typeof pages[number];
type Movement = { from: number; to: number; delta: number; gone: number };

export default function App() {
  const [page, setPage] = useState<Page>("Explorer");
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [profile, setProfile] = useState<CandidateRecord | null>(null);
  const [memory, setMemory] = useState<MemoryResponse | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [query, setQuery] = useState(defaultQuery);
  const [filters, setFilters] = useState(initialFilters);
  const [selected, setSelected] = useState<string | null>(null);
  const [showExcluded, setShowExcluded] = useState(false);
  const [busy, setBusy] = useState(true);
  const [firstLoad, setFirstLoad] = useState(true);
  const [error, setError] = useState("");
  const [accountOpen, setAccountOpen] = useState(false);
  const [movement, setMovement] = useState<Movement | null>(null);
  const previous = useRef<{ key: string; run: Run; daily: boolean } | null>(null);
  const searchGeneration = useRef(0);
  const refreshMemory = useCallback(async () => setMemory(await api<MemoryResponse>("/api/preferences")), []);
  const loadAccount = useCallback(async () => {
    await Promise.all([api<CandidateRecord>("/api/profile").then(setProfile), refreshMemory()]);
  }, [refreshMemory]);

  const search = useCallback(async (term: string, settings: Filters, daily = false, keepSelection = false) => {
    const generation = ++searchGeneration.current;
    setBusy(true); setError("");
    const key = JSON.stringify({ term, settings, daily });
    try {
      const next = await api<Run>("/api/search", "POST", {
        query: term, algorithm: settings.algorithm, location: settings.location || null,
        employment: settings.employment || null, work_mode: settings.work_mode || null,
        limit: daily ? 3 : 12, strong_only: daily,
      });
      if (generation !== searchGeneration.current) return;
      const old = previous.current;
      if (old?.key === key && old.run.preference_version !== next.preference_version) {
        const before = new Map(old.run.matches.map(row => [row.job.id, row.rank]));
        const nextIds = new Set(next.matches.map(row => row.job.id));
        setMovement({ from: old.run.preference_version, to: next.preference_version,
          delta: next.matches.filter(row => before.has(row.job.id) && before.get(row.job.id) !== row.rank).length,
          gone: [...before.keys()].filter(id => !nextIds.has(id)).length });
      } else if (old?.key !== key) setMovement(null);
      previous.current = { key, run: next, daily };
      setRun(next);
      if (!keepSelection) { setSelected(null); setShowExcluded(false); }
    } catch (problem) { if (generation === searchGeneration.current) setError(readableError(problem)); }
    finally { if (generation === searchGeneration.current) setBusy(false); }
  }, []);

  useEffect(() => {
    let active = true;
    async function boot() {
      try {
        const existing = await api<(Identity & { active: true }) | { active: false }>("/api/auth/session");
        const who: Identity = existing.active ? existing : await api<Identity>("/api/auth/demo", "POST");
        if (!active) return;
        setIdentity(who);
        await Promise.all([loadAccount(), search(defaultQuery, initialFilters)]);
      } catch (problem) {
        if (active) { setError(readableError(problem)); setBusy(false); }
      } finally { if (active) setFirstLoad(false); }
    }
    void boot();
    void api<Report>("/api/evaluation").then(data => { if (active) setReport(data); }).catch(() => {});
    return () => { active = false; };
  }, [loadAccount, search]);

  function navigate(destination: Page) {
    if (destination === page) return;
    setPage(destination);
    if (destination === "Daily matches") {
      setRun(null); void search(query, filters, true);
    } else if (destination === "Explorer" && (!run || previous.current?.daily)) {
      void search(query, filters);
    }
  }
  async function takeDemo(who: Identity) {
    setIdentity(who); setAccountOpen(false); setRun(null); setMovement(null); previous.current = null;
    setQuery(defaultQuery); setFilters(initialFilters); setPage("Explorer");
    await Promise.all([loadAccount(), search(defaultQuery, initialFilters)]);
  }
  async function savePreference(patch: Patch, version: number) {
    await api("/api/preferences", "PUT", { version, changes: [patch] });
    await refreshMemory();
  }
  function inspect() {
    setPage("Explorer"); setShowExcluded(true); setSelected("agent-senior");
    if (!run?.excluded.some(row => row.job.id === "agent-senior")) {
      setQuery(defaultQuery); setFilters(initialFilters);
      void search(defaultQuery, initialFilters, false, true);
    }
    requestAnimationFrame(() => document.getElementById("results-heading")?.scrollIntoView({ block: "start" }));
  }

  const currentDemoRun = identity?.demo && query === defaultQuery ? run : null;
  const senior = currentDemoRun?.excluded.find(row => row.job.id === "agent-senior");
  const firstMatch = currentDemoRun?.matches[0];
  return <>
    <a className="skip-link" href="#workspace">Skip to workspace</a>
    <header className="topbar">
      <div className="shell topbar-inner">
        <button type="button" className="brand" onClick={() => navigate("Explorer")} aria-label="MatchBench explorer">
          <span className="brand-mark" aria-hidden><Layers3 size={23} strokeWidth={2.2} /></span>
          <span>MatchBench <strong>AI</strong></span>
        </button>
        <nav className="top-nav" aria-label="Workspace screens">
          {pages.map(label => <button type="button" key={label} aria-current={page === label ? "page" : undefined}
            onClick={() => navigate(label)}>{label}</button>)}
        </nav>
        <button className="account-button" type="button" onClick={() => setAccountOpen(true)}>
          <span className="account-dot" aria-hidden />{identity?.demo ? "Demo session" : identity ? "Account" : "Sign in"}
        </button>
      </div>
    </header>
    <main className="shell" id="workspace">
      {page === "Explorer" && <section className="hero" aria-labelledby="hero-heading">
        <div className="hero-copy">
          <h1 id="hero-heading">Find the jobs you<br className="hero-break" /> can actually take.</h1>
          <p>MatchBench ranks jobs against your verified experience and dealbreakers, then shows the evidence behind each decision.</p>
          <div className="actions">
            <button type="button" className="primary" onClick={inspect} disabled={firstLoad}><Play size={16} aria-hidden /> Inspect a rejected match</button>
            <button type="button" className="plain" onClick={() => navigate("Evaluation")}>View benchmark <ArrowUpRight size={17} aria-hidden /></button>
          </div>
        </div>
        <div className="proof" aria-label="Example ranking decision">
          <div className="proof-head"><span><ShieldCheck size={18} aria-hidden /> Eligibility check</span><span className="proof-label">Demo corpus</span></div>
          <div className="proof-query"><SearchGlyph /><span>{defaultQuery}</span></div>
          <div className="proof-decision">
            <div><Status state="fail" /><strong>{senior?.job.title ?? "Senior AI Search & Backend Engineer"}</strong>
              <small>{senior ? senior.checks.find(check => check.key === "experience")?.label : "Requires 5+ years of experience"}</small></div>
            {senior?.scores.semantic != null && <span className="proof-score"><strong>{decimal(senior.scores.semantic, 2)}</strong><small>similarity</small></span>}
          </div>
          <div className="proof-win"><ArrowDownRight size={17} aria-hidden /><span>
            {firstMatch ? <>Top eligible match <b>{firstMatch.job.title}</b></> : "Eligible internships enter the shortlist"}
          </span></div>
        </div>
      </section>}
      {page !== "Explorer" && <div className="breadcrumb"><button type="button" onClick={() => navigate("Explorer")}>MatchBench</button>
        <ChevronRight size={14} aria-hidden />{page}</div>}
      {error && <p className="notice error" role="alert"><CircleAlert size={17} aria-hidden />{error}</p>}
      {movement && page === "Explorer" && <p className="notice movement" role="status">
        Memory v{movement.from} → v{movement.to}. {movement.delta} reordered, {movement.gone} left the visible shortlist.</p>}
      {identity && (page === "Explorer" || page === "Daily matches") && <Explorer run={run} busy={busy} query={query} setQuery={setQuery}
        filters={filters} setFilters={setFilters} onSearch={(term, settings) => { void search(term, settings); }}
        select={setSelected} selected={selected} showExcluded={showExcluded} setShowExcluded={setShowExcluded}
        daily={page === "Daily matches"} onPreference={savePreference} />}
      {!identity && firstLoad && <div className="surface empty" role="status">Starting the demo session…</div>}
      {!identity && !firstLoad && (page === "Explorer" || page === "Daily matches") &&
        <button type="button" className="secondary" onClick={() => setAccountOpen(true)}>Start a session</button>}
      {page === "Candidate profile" && <Profile key={identity?.email ?? "demo"} record={profile} demo={!!identity?.demo} onSave={setProfile} />}
      {page === "Memory" && <Memory state={memory} refresh={refreshMemory} save={savePreference} />}
      {page === "Evaluation" && <Evaluation report={report} />}
      <footer className="footer"><span>{identity?.demo ? "Illustrative postings. Demo profile cites public project evidence." : "MatchBench AI · Evidence-linked job ranking"}</span>
        <a href="/docs" target="_blank" rel="noreferrer"><BookOpen size={15} aria-hidden /> API docs <ArrowUpRight size={14} aria-hidden /></a></footer>
    </main>
    {accountOpen && <AccountPanel identity={identity} close={() => setAccountOpen(false)} start={takeDemo}
      clear={() => { setIdentity(null); setProfile(null); setMemory(null); setRun(null); previous.current = null; }} />}
  </>;
}

function SearchGlyph() { return <span className="search-glyph" aria-hidden />; }

function AccountPanel({ identity, close, start, clear }: {
  identity: Identity | null; close: () => void; start: (who: Identity) => Promise<void>; clear: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [creating, setCreating] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState("");
  const [confirming, setConfirming] = useState(false);
  useEffect(() => { dialog.current?.showModal(); }, []);
  async function auth(method: "demo" | "login" | "register") {
    setWorking(true); setNotice("");
    try { await start(await api<Identity>(`/api/auth/${method}`, "POST", method === "demo" ? undefined : { email, password })); }
    catch (problem) { setNotice(readableError(problem)); }
    finally { setWorking(false); }
  }
  async function closeSession(remove: boolean) {
    setWorking(true);
    try { await api(remove ? "/api/account" : "/api/auth/logout", remove ? "DELETE" : "POST"); clear(); close(); }
    catch (problem) { setNotice(readableError(problem)); }
    finally { setWorking(false); }
  }
  function submit(event: FormEvent) { event.preventDefault(); void auth(creating ? "register" : "login"); }
  return <dialog ref={dialog} aria-labelledby="account-heading" onCancel={close} className="account-dialog">
    <div className="section-top tight"><h2 id="account-heading">Your workspace</h2><button type="button" className="secondary" onClick={close}>Close</button></div>
    {identity && <section className="account-info"><p>{identity.demo ? "You are using an isolated demo session." : identity.email}</p>
      <div className="actions"><a className="text-link" href="/api/account/export" download="matchbench-account.json">Export data</a>
        <button type="button" className="secondary" disabled={working} onClick={() => { void closeSession(false); }}>Sign out</button>
        <button type="button" className="plain danger" onClick={() => setConfirming(true)}>Delete data</button></div>
      {confirming && <div className="notice error"><p>Delete this workspace, including saved evidence and matches?</p>
        <button type="button" className="secondary" disabled={working} onClick={() => { void closeSession(true); }}>Confirm deletion</button></div>}
    </section>}
    {(!identity || identity.demo) && <form onSubmit={submit} className="auth-form">
      <h3>{creating ? "Create an account" : "Sign in"}</h3>
      <label>Email<input type="email" autoComplete="email" required value={email} onChange={event => setEmail(event.target.value)} /></label>
      <label>Password<input type="password" autoComplete={creating ? "new-password" : "current-password"} minLength={10} maxLength={128}
        required value={password} onChange={event => setPassword(event.target.value)} /></label>
      <div className="actions"><button className="primary" disabled={working}>{creating ? "Create account" : "Sign in"}</button>
        <button type="button" className="plain" onClick={() => setCreating(!creating)}>{creating ? "Use an existing account" : "Create an account"}</button></div>
    </form>}
    {!identity && <button type="button" className="secondary" disabled={working} onClick={() => { void auth("demo"); }}>Start demo</button>}
    {notice && <p className="notice error" role="alert">{notice}</p>}
  </dialog>;
}
