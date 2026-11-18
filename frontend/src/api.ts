export async function api<T>(path: string, method = "GET", data?: unknown): Promise<T> {
  const form = data instanceof FormData;
  const response = await fetch(path, {
    method,
    credentials: "include",
    headers: data && !form ? { "Content-Type": "application/json" } : undefined,
    body: data === undefined ? undefined : form ? data : JSON.stringify(data),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = typeof payload.detail === "string" ? payload.detail :
      response.status === 422 ? "Check your input and try again." : "Request failed. Try again.";
    throw new Error(message);
  }
  return payload as T;
}

export interface Identity { demo: boolean; email: string | null }
export type Evidence = {
  id: string;
  skill: string;
  excerpt: string;
  source: string;
  source_url?: string | null;
  method: string;
  review: "pending" | "accepted" | "rejected";
};
export interface Candidate {
  name: string;
  years: number | null;
  graduation_year: number | null;
  available_from: string | null;
  authorization: string[];
  education: string[];
  experience: string[];
  projects: string[];
  evidence: Evidence[];
}
export type Profile = { version: number; profile: Candidate };
export type Value = string | boolean | number | string[] | null;
export type Patch = { field: string; operation: "add" | "remove" | "set" | "clear"; value?: Value };
export type PrefState = Record<string, Value>;
export type PrefEvent = { version: number; id: string; source: string; source_text: string | null; patch: Patch[]; created_at: string };
export type MemoryResponse = { version: number; preferences: PrefState; history: PrefEvent[] };
export type ToolCall = { name: string; status: string; elapsed_ms: number };
export type Proposal = { id: string; proposal: { changes: Patch[]; question: string | null }; provider: string; tool_calls: ToolCall[] };
export type Check = { key: string; label: string; state: "pass" | "fail" | "review" };
export type Job = {
  id: string; title: string; description: string; company: string;
  role: string; work_mode: string; employment: string; locations: string[]; skills: string[];
  salary_min: number | null; salary_max: number | null; currency: string | null; salary_period: string;
  illustrative: boolean; source_url: string | null; source: string;
};
export type Match = {
  job: Job; rank: number | null; status: "pass" | "fail" | "review"; sources: string[]; checks: Check[];
  explanation: { evidence: Evidence[]; missing: string[]; unknowns: string[] };
  scores: {
    lexical: number | null; semantic: number | null; hybrid: number | null;
    reranker: number | null; final: number | null; skill_coverage: number; preference_alignment: number;
    preference_components: Record<string, number>;
  };
};
export type Run = {
  run_id: string; profile_version: number; preference_version: number; algorithm: string;
  requested_algorithm: string; warnings: string[]; matches: Match[]; excluded: Match[];
  counts: { indexed: number; eligible: number; retrieved: number; excluded: number };
  timing: { filter_ms: number; retrieval_ms: number; rerank_ms: number; total_ms: number };
};
export type CompareState = { status: string; rank: number | null; skill_coverage: number | null; checks: Check[] };
export type Comparison = { before: CompareState; after: CompareState; corpus_size: number };
type Percentiles = { p50: number; p95: number };
export type Metric = {
  name: string; algorithm: string; ndcg_at_10: number; precision_at_5: number; recall_at_10: number; mrr: number;
  latency: { retrieval_ms: Percentiles; rerank_ms: Percentiles; total_ms: Percentiles }; mean_reranker_pairs: number;
};
export type Report = {
  jobs: number; indexed_vectors: number; judgments: number; queries: number; heldout_topics: number; index_bytes: number;
  generated_at: string; device: string; database: string; alpha: number; timing_scope: string; scope: string;
  ranking: Metric[]; rerank_depths: (Metric & { depth: number })[];
  paired_cluster_bootstrap_ndcg_delta: [number, number];
  contracts: { explanation_cases: number; grounded: number; missing_skill_correct: number; consistent: number;
    unsupported_claim_rate: number; local_preference_cases: number; local_preferences_correct: number;
    hosted_llm: { valid: number; cases: number; correct: number } | null };
};

export const defaultQuery = "AI/backend internships working on agents and search";
export const algorithmNames: Record<string, string> = {
  personalized: "Hybrid + reranker + preferences", hybrid_rerank: "Hybrid + cross-encoder",
  hybrid: "Hybrid", embedding: "Embeddings", bm25: "BM25", keyword: "Keyword overlap",
};
export const statusLabels: Record<string, string> = { pass: "Eligible", fail: "Excluded",
  review: "Needs checking", "outside pool": "Outside retrieval pool" };
export const decimal = (value: number | null, digits = 3) => value === null ? "—" : value.toFixed(digits);
export const percent = (value: number | null) => value === null ? "—" : Math.round(value * 100) + "%";
export const cityLine = (job: Job) => job.locations.length ? job.locations.join(", ") : job.work_mode === "remote" ? "Remote" : "Location unknown";
export const readableError = (error: unknown) => error instanceof Error ? error.message : "Request failed. Try again.";
