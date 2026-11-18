import { BadgeCheck, ExternalLink, FileText, Plus, UploadCloud } from "lucide-react";
import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { api, readableError } from "./api";
import type { Candidate, Evidence, Profile as ProfileData } from "./api";

export default function Profile({ record, demo, onSave }: {
  record: ProfileData | null; demo: boolean; onSave: (profile: ProfileData) => void;
}) {
  const [draft, setDraft] = useState<Candidate | null>(null);
  const [notice, setNotice] = useState("");
  const [working, setWorking] = useState(false);
  const [newSkill, setNewSkill] = useState("");
  const [newExcerpt, setNewExcerpt] = useState("");
  const candidate = draft ?? record?.profile;
  function update(patch: Partial<Candidate>) {
    if (candidate) setDraft({ ...candidate, ...patch });
  }
  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const body = new FormData();
    body.set("file", file);
    setWorking(true); setNotice("");
    try {
      const parsed = await api<ProfileData>("/api/profile/extract", "POST", body);
      setDraft(parsed.profile);
      setNotice("Résumé extracted. Review the excerpts and save to update your profile.");
    } catch (error) { setNotice(readableError(error)); }
    finally { setWorking(false); }
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!record || !candidate) return;
    setWorking(true);
    try {
      const updated = await api<ProfileData>("/api/profile", "PUT", { version: record.version, profile: {
        ...candidate, education: candidate.education.filter(line => line.trim()),
        experience: candidate.experience.filter(line => line.trim()), projects: candidate.projects.filter(line => line.trim()),
      } });
      onSave(updated); setDraft(null); setNotice("Profile saved. Future searches will use this evidence.");
    } catch (error) { setNotice(readableError(error)); }
    finally { setWorking(false); }
  }
  function addEvidence() {
    if (!candidate || !newSkill.trim() || !newExcerpt.trim()) return;
    const entry: Evidence = { id: crypto.randomUUID(), skill: newSkill.trim(), excerpt: newExcerpt.trim(),
      source: "Candidate entry", method: "candidate", review: "accepted" };
    update({ evidence: [...candidate.evidence, entry] });
    setNewSkill(""); setNewExcerpt("");
  }

  return <section className="surface page-section">
    <div className="section-top"><div><h2>Candidate profile</h2><p>Review which skills the search can cite and where each claim comes from.</p></div>
      <label className="secondary upload"><UploadCloud size={17} aria-hidden /> Import résumé
        <input type="file" accept=".pdf,.docx,.txt" disabled={working} onChange={upload} aria-label="Import résumé" />
      </label>
    </div>
    {demo && <p className="info-line"><FileText size={16} aria-hidden /> Demo profile uses public project evidence and a zero-year experience setting for the eligibility scenario.</p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {!candidate ? <p className="empty">Loading the candidate profile…</p> : <form onSubmit={save}>
      <div className="input-grid profile-inputs">
        <label>Name<input value={candidate.name} maxLength={120} onChange={event => update({ name: event.target.value })} /></label>
        <label>Professional experience in years<input type="number" min={0} max={70} step={.1} value={candidate.years ?? ""}
          onChange={event => update({ years: event.target.value === "" ? null : Number(event.target.value) })} /></label>
        <label>Graduation year<input type="number" min={1900} max={2150} value={candidate.graduation_year ?? ""}
          onChange={event => update({ graduation_year: event.target.value === "" ? null : Number(event.target.value) })} /></label>
      </div>
      <div className="input-grid">
        {(["experience", "education", "projects"] as const).map(field => <label key={field}>{field[0].toUpperCase() + field.slice(1)}
          <textarea rows={3} value={candidate[field].join("\n")} onChange={event => update({ [field]: event.target.value.split("\n") })} />
        </label>)}
      </div>
      <div className="section-top tight"><div><h3>Skill evidence</h3><p>Accept each excerpt you want the ranking to use.</p></div></div>
      <ul className="evidence-table">
        {candidate.evidence.map((item, index) => <li key={item.id}>
          <div className="evidence-skill"><BadgeCheck size={19} aria-hidden /><strong>{item.skill}</strong></div>
          <div><p>{item.excerpt}</p>{item.source_url ?
            <a href={item.source_url} target="_blank" rel="noreferrer">{item.source} <ExternalLink size={13} aria-hidden /></a> : <small>{item.source}</small>}</div>
          <label><span className="sr-only">Review {item.skill}</span><select value={item.review}
            onChange={event => update({ evidence: candidate.evidence.map((entry, at) => at === index ?
              { ...entry, review: event.target.value as Evidence["review"] } : entry) })}>
            <option value="pending">Needs review</option><option value="accepted">Accepted</option><option value="rejected">Rejected</option>
          </select></label>
        </li>)}
      </ul>
      {!candidate.evidence.length && <p className="muted">Import a résumé or add a specific project excerpt.</p>}
      <div className="row-form evidence-add">
        <label>Skill<input value={newSkill} maxLength={120} onChange={event => setNewSkill(event.target.value)} /></label>
        <label className="grow">Supporting excerpt<input value={newExcerpt} maxLength={600} onChange={event => setNewExcerpt(event.target.value)} /></label>
        <button type="button" className="secondary" onClick={addEvidence} disabled={!newSkill.trim() || !newExcerpt.trim()}><Plus size={16} aria-hidden /> Add evidence</button>
      </div>
      <div className="actions">
        <button className="primary" disabled={!draft || working}>Save profile</button>
        {draft && <button type="button" className="secondary" disabled={working} onClick={() => { setDraft(null); setNotice(""); }}>Discard edits</button>}
      </div>
    </form>}
  </section>;
}
