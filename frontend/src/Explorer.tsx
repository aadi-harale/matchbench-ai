import { ArrowRight, Check, ChevronDown, CircleHelp, ExternalLink, GitCompareArrows, MapPin, Search, X } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";
import {
  algorithmNames, api, cityLine, decimal, percent, readableError, statusLabels,
} from "./api";
import type { Comparison, Match, Patch, Run } from "./api";

export type Filters = { algorithm: string; location: string; employment: string; work_mode: string };
export const initialFilters = { algorithm: "personalized", location: "", employment: "", work_mode: "" };
export const feedbackChoices = [
  "Interested", "Not relevant", "Wrong location", "Too senior", "Too junior",
  "Wrong technology", "Not this company", "More like this", "Less like this",
];

export function Status({ state }: { state: string }) {
  const Icon = state === "pass" ? Check : state === "fail" ? X : CircleHelp;
  return <span className={`status status-${state.split(" ")[0]}`}><Icon size={13} aria-hidden />{statusLabels[state] ?? state}</span>;
}

type ExplorerProps = {
  run: Run | null; busy: boolean; query: string; setQuery: (value: string) => void;
  filters: Filters; setFilters: (value: Filters) => void; onSearch: (query: string, filters: Filters) => void;
  selected: string | null; select: (id: string) => void; showExcluded: boolean;
  setShowExcluded: (value: boolean) => void; daily: boolean;
  onPreference: (patch: Patch, version: number) => Promise<void>;
};
export default function Explorer({
  run, busy, query, setQuery, filters, setFilters, onSearch, selected, select, showExcluded,
  setShowExcluded, daily, onPreference,
}: ExplorerProps) {
  const [filterOpen, setFilterOpen] = useState(false);
  const matches = showExcluded && !daily ? run?.excluded ?? [] : run?.matches ?? [];
  const detail = matches.find(row => row.job.id === selected) ?? matches[0];
  const submit = (event: FormEvent) => { event.preventDefault(); if (query.trim().length >= 2) onSearch(query, filters); };
  const choose = (id: string) => {
    select(id);
    if (window.matchMedia("(max-width: 760px)").matches) {
      requestAnimationFrame(() => {
        document.getElementById("match-detail")?.focus({ preventScroll: true });
        document.getElementById("match-detail")?.scrollIntoView({ block: "start" });
      });
    }
  };
  return <section aria-labelledby="results-heading" className="workbench">
    {!daily && <form onSubmit={submit} className="search-form">
      <label className="search-input"><Search size={20} aria-hidden />
        <span className="sr-only">Search job postings</span>
        <input type="search" value={query} onChange={event => setQuery(event.target.value)}
          required minLength={2} maxLength={480} placeholder="Search by role, technology or work you want to do" />
      </label>
      <button className="secondary filter-button" type="button" aria-expanded={filterOpen} onClick={() => setFilterOpen(!filterOpen)}>
        Filters <ChevronDown size={16} aria-hidden />
      </button>
      <button className="primary search-button" disabled={busy}>Search</button>
      {filterOpen && <div className="filter-options">
        <label>Ranking method<select value={filters.algorithm} onChange={event => setFilters({ ...filters, algorithm: event.target.value })}>
          {Object.entries(algorithmNames).map(([key, label]) => <option value={key} key={key}>{label}</option>)}
        </select></label>
        <label>City<input value={filters.location} placeholder="Any city" onChange={event => setFilters({ ...filters, location: event.target.value })} /></label>
        <label>Employment<select value={filters.employment} onChange={event => setFilters({ ...filters, employment: event.target.value })}>
          <option value="">Any type</option><option value="internship">Internship</option><option value="full-time">Full-time</option><option value="contract">Contract</option>
        </select></label>
        <label>Work mode<select value={filters.work_mode} onChange={event => setFilters({ ...filters, work_mode: event.target.value })}>
          <option value="">Any mode</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="on-site">On-site</option>
        </select></label>
      </div>}
    </form>}
    {run?.warnings.map(warning => <p className="notice" role="status" key={warning}>{warning}</p>)}
    <div className="workbench-heading">
      <div>
        <h2 id="results-heading">{daily ? "Daily matches" : "Ranked results"}</h2>
        <p>{run ? `${run.counts.indexed} jobs searched using ${algorithmNames[run.algorithm] ?? run.algorithm}` : "Search the indexed postings."}</p>
      </div>
      {!daily && <div className="segmented" aria-label="Result list">
        <button type="button" aria-pressed={!showExcluded} onClick={() => setShowExcluded(false)}>Ranked {run ? <span>{run.counts.retrieved}</span> : null}</button>
        <button type="button" aria-pressed={showExcluded} onClick={() => setShowExcluded(true)}>Set aside {run ? <span>{run.counts.excluded}</span> : null}</button>
      </div>}
    </div>
    <div className="work-split" aria-busy={busy}>
      <div className="job-list" aria-label={showExcluded ? "Set-aside postings" : "Ranked postings"}>
        {busy && !run && <p className="empty">Ranking the indexed jobs…</p>}
        {!busy && !matches.length && <p className="empty">{daily ? "No strong matches today. Try the explorer to inspect more postings." : "No results in this view. Try another search or change your filters."}</p>}
        {matches.map(entry => <button type="button" key={entry.job.id}
          className={`job-row ${detail?.job.id === entry.job.id ? "selected" : ""}`}
          aria-pressed={detail?.job.id === entry.job.id} onClick={() => choose(entry.job.id)}>
          <span className="row-copy">
            <strong>{entry.job.title}</strong>
            <span>{entry.job.company} <span className="row-divider">/</span> {cityLine(entry.job)}</span>
            {entry.rank === null && <span className={`row-reason ${entry.status}`}>
              {entry.checks.find(item => item.state === entry.status)?.label ?? statusLabels[entry.status]}
            </span>}
          </span>
          <span className="row-decision">
            <Status state={entry.status} />
            {entry.rank !== null && <span className="rank-number" aria-label={`Rank ${entry.rank}`}>#{entry.rank}</span>}
          </span>
        </button>)}
      </div>
      {detail && run && <Detail key={`${run.run_id}-${detail.job.id}`} match={detail} run={run} onPreference={onPreference} />}
    </div>
  </section>;
}

function Detail({ match, run, onPreference }: { match: Match; run: Run; onPreference: ExplorerProps["onPreference"] }) {
  const { job, scores, explanation } = match;
  const [tab, setTab] = useState<"fit" | "trace" | "compare">("fit");
  const options = [
    ...job.locations.map(value => ({ change: "allow_location", value, label: `Accept ${value}` })),
    ...explanation.missing.map(value => ({ change: "add_skill", value, label: `Add evidence for ${value}` })),
    ...(match.checks.some(check => check.key === "role") ? [{ change: "remove_role_exclusion", value: null, label: "Allow this role family" }] : []),
    ...(match.checks.some(check => check.key === "pay" && check.state !== "pass") ? [{ change: "remove_pay_constraint", value: null, label: "Relax the pay constraint" }] : []),
  ];
  const [scenario, setScenario] = useState(options.findIndex(option => option.change === "add_skill") >= 0 && match.status === "pass"
    ? options.findIndex(option => option.change === "add_skill") : 0);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [feedback, setFeedback] = useState("");
  const [suggestion, setSuggestion] = useState<{ patch: Patch; version: number } | null>(null);
  const [notice, setNotice] = useState("");
  const [working, setWorking] = useState(false);
  const [feedbackBusy, setFeedbackBusy] = useState(false);

  async function compare(event: FormEvent) {
    event.preventDefault();
    const choice = options[scenario];
    if (!choice) return;
    setWorking(true);
    setNotice("");
    try {
      setComparison(await api<Comparison>(`/api/runs/${run.run_id}/counterfactual`, "POST",
        { job_id: job.id, change: choice.change, value: choice.value }));
    } catch (error) { setNotice(readableError(error)); }
    finally { setWorking(false); }
  }
  async function record(event: FormEvent) {
    event.preventDefault();
    if (!feedback) return;
    setFeedbackBusy(true);
    try {
      const response = await api<{ recorded: string; suggestion: Patch | null; version: number }>("/api/feedback", "POST",
        { run_id: run.run_id, job_id: job.id, kind: feedback });
      setNotice(`Feedback saved: ${response.recorded}.`);
      setSuggestion(response.suggestion ? { patch: response.suggestion, version: response.version } : null);
    } catch (error) { setNotice(readableError(error)); }
    finally { setFeedbackBusy(false); }
  }

  return <article className="match-detail" id="match-detail" tabIndex={-1} aria-label="Selected match decision">
    <div className="match-top">
      <div className="match-state"><Status state={match.status} />{match.rank && <span className="mono">Rank #{match.rank}</span>}</div>
      <h3>{job.title}</h3>
      <p className="job-meta"><strong>{job.company}</strong><span><MapPin size={14} aria-hidden /> {cityLine(job)}</span><span>{job.work_mode}</span>
        <span>{job.salary_min === null ? "Pay undisclosed" : job.salary_max === 0 && job.salary_min === 0 ? "Unpaid" :
          `${new Intl.NumberFormat("en-IN", { style: "currency", currency: job.currency ?? "INR", maximumFractionDigits: 0 }).format(job.salary_min)}/${job.salary_period}`}
        </span></p>
      {match.status !== "pass" && <div className={`decision-note ${match.status}`}>
        <strong>{match.status === "fail" ? "Why it was excluded" : "What needs checking"}</strong>
        <p>{match.checks.filter(item => item.state === match.status).map(item => item.label).join(". ")}.</p>
        {scores.semantic !== null && <span className="mono">Raw semantic similarity {decimal(scores.semantic)}</span>}
      </div>}
    </div>
    <div className="detail-tabs" aria-label="Match information">
      <button type="button" aria-pressed={tab === "fit"} onClick={() => setTab("fit")}>Why it fits</button>
      <button type="button" aria-pressed={tab === "trace"} onClick={() => setTab("trace")}>Decision trace</button>
      <button type="button" aria-pressed={tab === "compare"} onClick={() => setTab("compare")}><GitCompareArrows size={15} aria-hidden /> What if?</button>
    </div>
    <div className="detail-body">
      {tab === "fit" && <>
        <p className="job-description">{job.description}</p>
        <section className="fit-section"><h4>Evidence in your profile</h4>
          {explanation.evidence.length ? <ul className="evidence-mini">
            {explanation.evidence.map(item => <li key={item.id}><Check size={14} aria-hidden />
              <div><strong>{item.skill}</strong><p>{item.excerpt}</p>
                {item.source_url ? <a href={item.source_url} target="_blank" rel="noreferrer">{item.source} <ExternalLink size={12} aria-hidden /></a> :
                  <small>{item.source}</small>}</div></li>)}
          </ul> : <p className="muted">This posting has no verified skill evidence in the current profile.</p>}
        </section>
        <div className="fit-grid">
          <section><h4>Missing evidence</h4><p>{explanation.missing.join(", ") || "All listed skills have evidence."}</p></section>
          <section><h4>Needs checking</h4><p>{explanation.unknowns.join(". ") || "No open eligibility checks."}</p></section>
        </div>
        {job.source_url && <a className="text-link" href={job.source_url} target="_blank" rel="noreferrer">View original posting <ExternalLink size={14} aria-hidden /></a>}
      </>}
      {tab === "trace" && <>
        <p className="trace-id mono">Run {run.run_id.slice(0, 10)} <span>/</span> Profile v{run.profile_version} <span>/</span> Memory v{run.preference_version}</p>
        <h4>Eligibility checks</h4>
        <ul className="decision-checks">{match.checks.length ? match.checks.map(item => <li key={item.key}><Status state={item.state} /><span>{item.label}</span></li>) :
          <li>No active hard constraints for this result.</li>}</ul>
        <h4>Ranking signals</h4>
        <dl className="signal-grid">
          {[["BM25 / keyword", decimal(scores.lexical)], ["Cosine similarity", decimal(scores.semantic)],
            ["Hybrid score", decimal(scores.hybrid)], ["Cross-encoder raw", decimal(scores.reranker)],
            ["Skill coverage", percent(scores.skill_coverage)], ["Preference alignment", decimal(scores.preference_alignment)],
            ["Final score", decimal(scores.final)], ["Final rank", match.rank === null ? "—" : `#${match.rank}`]].map(([label, value]) =>
            <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
        </dl>
        <p className="muted">Retrieval stages: {match.sources.join(", ") || "Eligibility audit"}. Scores are ranking signals.</p>
        <a className="text-link" href={`/api/runs/${run.run_id}`} target="_blank" rel="noreferrer">Open stored run <ExternalLink size={14} aria-hidden /></a>
      </>}
      {tab === "compare" && <section className="comparison">
        <h4>Counterfactual Match Inspector</h4>
        <p>Change one input and recompute the ranking on this run’s job snapshot. Saved preferences stay as recorded.</p>
        {options.length ? <form onSubmit={compare} className="row-form">
          <label className="grow">Hypothetical change<select value={scenario} onChange={event => { setScenario(Number(event.target.value)); setComparison(null); }}>
            {options.map((option, index) => <option key={option.label} value={index}>{option.label}</option>)}</select></label>
          <button type="submit" className="primary" disabled={working}>{working ? "Comparing…" : "Compare"}</button>
        </form> : <p className="muted">Choose a role with a required skill, listed city, or active exclusion to compare.</p>}
        {comparison && <div className="compare-grid" aria-live="polite">
          {[["Recorded decision", comparison.before], ["With hypothetical change", comparison.after]].map(([heading, state]) => {
            const snapshot = state as Comparison["before"];
            return <div key={heading as string}><h5>{heading as string}</h5><Status state={snapshot.status} />
              <strong>{snapshot.rank === null ? "Unranked" : `Rank #${snapshot.rank}`}</strong>
              <span>Skill coverage {percent(snapshot.skill_coverage)}</span>
              {snapshot.checks.filter(item => item.state !== "pass").map(item => <small key={item.key}>{item.label}</small>)}
            </div>;
          })}
        </div>}
      </section>}
      {notice && <p className="notice" role="status">{notice}</p>}
      {tab === "fit" && <form onSubmit={record} className="row-form feedback-form">
        <label className="grow">Feedback<select value={feedback} onChange={event => setFeedback(event.target.value)}>
          <option value="">Choose a reason</option>{feedbackChoices.map(reason => <option key={reason}>{reason}</option>)}
        </select></label>
        <button className="secondary" disabled={!feedback || feedbackBusy}>Save feedback</button>
      </form>}
      {suggestion && <div className="notice">
        <p>Suggested memory update: {suggestion.patch.value?.toString()}</p>
        <button type="button" className="secondary" onClick={() => {
          void onPreference(suggestion.patch, suggestion.version).then(() => {
            setNotice("Preference saved."); setSuggestion(null);
          }).catch(error => setNotice(readableError(error)));
        }}>Confirm update <ArrowRight size={14} aria-hidden /></button>
      </div>}
    </div>
  </article>;
}
