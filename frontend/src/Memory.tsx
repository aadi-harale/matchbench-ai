import { Braces, Check, History, MessageSquare, X } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";
import { api, readableError } from "./api";
import type { MemoryResponse, Patch, Proposal, Value } from "./api";

const fields: Record<string, string> = {
  employment: "Employment type", locations: "Accepted cities", excluded_locations: "Excluded cities",
  allow_relocation: "Open to relocation", paid_only: "Paid roles only", minimum_stipend: "Minimum INR per month",
  denied_roles: "Excluded roles", denied_companies: "Excluded companies", preferred_roles: "Preferred roles",
  less_roles: "Show fewer of these roles", preferred_skills: "Preferred technologies", preferred_work_modes: "Preferred work modes",
};
const hardFields = ["employment", "locations", "excluded_locations", "allow_relocation", "paid_only", "minimum_stipend", "denied_roles", "denied_companies"];
const examples = ["No frontend-heavy roles", "Show me less frontend", "Allow Hyderabad", "At least INR 30k per month"];
function description(patch: Patch) {
  const field = fields[patch.field] ?? patch.field;
  return patch.operation === "clear" ? `Reset ${field.toLowerCase()}` :
    `${field}: ${patch.operation === "remove" ? "remove " : patch.operation === "add" ? "add " : ""}${patch.value?.toString() ?? "any"}`;
}
function show(value: Value) {
  if (value === null || (Array.isArray(value) && value.length === 0)) return "Any";
  if (value === true) return "Yes";
  if (value === false) return "No";
  return Array.isArray(value) ? value.join(", ") : value.toString();
}

export default function Memory({ state, refresh, save }: {
  state: MemoryResponse | null; refresh: () => Promise<void>; save: (patch: Patch, version: number) => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [edit, setEdit] = useState("locations");
  const [value, setValue] = useState("");
  async function ask(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setProposal(null); setNotice("");
    try { setProposal(await api<Proposal>("/api/agent", "POST", { text })); }
    catch (error) { setNotice(readableError(error)); }
    finally { setBusy(false); }
  }
  async function confirm() {
    if (!proposal) return;
    setBusy(true);
    try {
      const next = await api<{ version: number }>(`/api/agent/${proposal.id}/confirm`, "POST");
      await refresh(); setProposal(null); setNotice(`Saved to memory v${next.version}. The explorer uses it on the next search.`);
    } catch (error) { setNotice(readableError(error)); }
    finally { setBusy(false); }
  }
  async function reject() {
    if (!proposal) return;
    setBusy(true);
    try {
      await api(`/api/agent/${proposal.id}/reject`, "POST");
      setProposal(null); setNotice("Proposal rejected. Saved memory was not changed.");
    } catch (error) { setNotice(readableError(error)); }
    finally { setBusy(false); }
  }
  async function direct(patch: Patch) {
    if (!state) return;
    setBusy(true);
    try { await save(patch, state.version); setNotice("Preference saved. Run a new search to see the effect."); }
    catch (error) { setNotice(readableError(error)); }
    finally { setBusy(false); }
  }
  function setDirect(event: FormEvent) {
    event.preventDefault();
    const previous = state?.preferences[edit];
    const converted = Array.isArray(previous) ? value.split(",").map(item => item.trim()).filter(Boolean)
      : typeof previous === "boolean" ? value === "true"
        : edit === "minimum_stipend" ? Number(value) : value;
    void direct(!value.trim() ? { field: edit, operation: "clear" } : { field: edit, operation: "set", value: converted });
  }
  return <div className="memory-layout">
    <section className="surface page-section">
      <h2>Feedback &amp; memory</h2>
      <p className="intro">Say what should change. Review the structured edit before it affects your matches.</p>
      <form className="agent-form" onSubmit={ask}>
        <label><MessageSquare size={17} aria-hidden /> Preference message<textarea rows={3} value={text} minLength={2} required
          maxLength={600} placeholder="I’m open to Hyderabad for backend roles…" onChange={event => setText(event.target.value)} /></label>
        <div className="prompt-buttons">{examples.map(example => <button type="button" key={example}
          onClick={() => setText(example)}>{example}</button>)}</div>
        <button className="primary" disabled={busy}>{busy ? "Working…" : "Interpret preference"}</button>
      </form>
      {proposal && <section className="proposal">
        <div className="section-top tight"><h3><Braces size={18} aria-hidden /> Proposed change</h3><span className="quiet-label">{proposal.provider}</span></div>
        {proposal.proposal.question && <p>{proposal.proposal.question}</p>}
        {proposal.proposal.changes.length > 0 && <>
          <ul>{proposal.proposal.changes.map((patch, index) => <li key={index}>{description(patch)}</li>)}</ul>
          <div className="actions"><button type="button" className="primary" disabled={busy} onClick={() => { void confirm(); }}><Check size={17} aria-hidden /> Confirm change</button>
            <button type="button" className="secondary" disabled={busy} onClick={() => { void reject(); }}><X size={16} aria-hidden /> Reject</button></div>
        </>}
        <details className="tool-disclosure"><summary>Tool calls</summary>
          <ul>{proposal.tool_calls.map((call, index) => <li key={index}><code>{call.name}</code> {call.status} · {call.elapsed_ms.toFixed(2)} ms</li>)}</ul>
        </details>
      </section>}
      {notice && <p className="notice" role="status">{notice}</p>}
      {state && <form className="row-form memory-editor" onSubmit={setDirect}>
        <label>Preference<select value={edit} onChange={event => { setEdit(event.target.value); setValue(""); }}>
          {Object.entries(fields).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select></label>
        {typeof state.preferences[edit] === "boolean" ? <label className="grow">Value<select value={value} onChange={event => setValue(event.target.value)}>
          <option value="">Reset</option><option value="true">Yes</option><option value="false">No</option>
        </select></label> : edit === "employment" ? <label className="grow">Value<select value={value} onChange={event => setValue(event.target.value)}>
          <option value="">Any</option><option value="internship">Internship</option><option value="full-time">Full-time</option><option value="contract">Contract</option>
        </select></label> : <label className="grow">Value<input type={edit === "minimum_stipend" ? "number" : "text"} min={0} value={value}
          onChange={event => setValue(event.target.value)} placeholder={Array.isArray(state.preferences[edit]) ? "Comma-separated values" : "Blank resets the field"} /></label>}
        <button className="secondary" disabled={busy}>Save edit</button>
      </form>}
    </section>
    <section className="surface page-section saved-memory">
      <div className="section-top tight"><h2>Saved memory</h2><span className="quiet-label">v{state?.version ?? "—"}</span></div>
      {state && <>{[["Dealbreakers", hardFields], ["Ranking preferences", Object.keys(fields).filter(key => !hardFields.includes(key))]].map(([label, group]) =>
        <div key={label as string}><h3>{label as string}</h3>
          <dl>{(group as string[]).map(key => <div key={key}><dt>{fields[key]}</dt><dd>{Array.isArray(state.preferences[key]) && state.preferences[key].length ?
            <div className="pills">{state.preferences[key].map(item => <button type="button" className="pill" key={item} disabled={busy}
              aria-label={`Remove ${item} from ${fields[key]}`} onClick={() => { void direct({ field: key, operation: "remove", value: item }); }}>
              {item}<X size={13} aria-hidden /></button>)}</div> : show(state.preferences[key])}</dd></div>)}</dl>
        </div>)}
        <div className="history"><h3><History size={17} aria-hidden /> Event history</h3>
          {!state.history.length && <p className="muted">Saved changes will appear here.</p>}
          <ol>{state.history.map(event => <li key={event.id}><span className="mono">v{event.version}</span>
            <div><strong>{event.source_text ?? event.source}</strong><small>{event.patch.map(description).join(" · ")}</small></div></li>)}</ol>
        </div></>}
    </section>
  </div>;
}
