import { BarChart3, Download, GitBranch } from "lucide-react";
import { decimal } from "./api";
import type { Report } from "./api";

export default function Evaluation({ report }: { report: Report | null }) {
  if (!report) return <section className="surface page-section"><h2>Evaluation</h2><p>Measured results are loading or unavailable.</p></section>;
  const highest = Math.max(...report.ranking.map(method => method.ndcg_at_10));
  const disclaimer = report.paired_cluster_bootstrap_ndcg_delta.map(value => value.toFixed(3)).join(" to ");
  return <div className="evaluation-layout">
    <section className="surface page-section">
      <div className="section-top">
        <div><h2>Ranking benchmark</h2><p>Six ranking variants measured against the same held-out judgments.</p></div>
        <a className="secondary" href="/api/evaluation" download="matchbench-benchmark.json"><Download size={16} aria-hidden /> Raw results</a>
      </div>
      <div className="bench-metadata">
        <span><strong>{report.queries}</strong> held-out queries</span>
        <span><strong>{report.jobs}</strong> illustrative jobs</span>
        <span><strong>{report.judgments.toLocaleString()}</strong> query–job grades</span>
        <span><strong>{(report.index_bytes / 1024).toFixed(1)} KiB</strong> index payload</span>
      </div>
      <h3 className="inline-heading"><BarChart3 size={18} aria-hidden /> nDCG@10 by ranking method</h3>
      <ul className="bar-list">
        {report.ranking.map(metric => <li key={metric.algorithm}>
          <span>{metric.name}</span>
          <div className="bar-track" aria-hidden><div className={`bar-fill ${metric.ndcg_at_10 === highest ? "best" : ""}`} style={{ width: `${metric.ndcg_at_10 * 100}%` }} /></div>
          <strong className="mono">{decimal(metric.ndcg_at_10)}</strong>
        </li>)}
      </ul>
      <div className="table-scroll"><table className="metrics-table">
        <caption className="sr-only">Held-out ranking quality and latency</caption>
        <thead><tr><th>Method</th><th>P@5</th><th>R@10</th><th>MRR</th><th>nDCG@10</th><th>p50 total</th><th>p95 total</th></tr></thead>
        <tbody>{report.ranking.map(metric => <tr key={metric.algorithm}>
          <th scope="row">{metric.name}</th><td>{decimal(metric.precision_at_5)}</td><td>{decimal(metric.recall_at_10)}</td>
          <td>{decimal(metric.mrr)}</td><td>{decimal(metric.ndcg_at_10)}</td>
          <td>{metric.latency.total_ms.p50.toFixed(1)} ms</td><td>{metric.latency.total_ms.p95.toFixed(1)} ms</td>
        </tr>)}</tbody>
      </table></div>
      <p className="fine-print">{report.scope} Precision, recall and MRR treat grades 2–3 as relevant. Paired topic-bootstrap 95% interval for personalized minus embeddings nDCG@10: {disclaimer}.</p>
      <p className="fine-print">{report.timing_scope} {report.device} / {report.database}. Vector fusion weight {report.alpha}. {report.indexed_vectors} job embeddings.</p>
    </section>
    <section className="surface page-section">
      <h3 className="inline-heading"><GitBranch size={18} aria-hidden /> Cross-encoder cost</h3>
      <div className="table-scroll"><table className="metrics-table">
        <caption className="sr-only">Measured reranking depth tradeoffs</caption>
        <thead><tr><th>Depth cap</th><th>Mean pairs</th><th>nDCG@10</th><th>p95 retrieval</th><th>p95 reranking</th></tr></thead>
        <tbody>{report.rerank_depths.map(metric => <tr key={metric.depth}>
          <th scope="row">{metric.depth}</th><td>{metric.mean_reranker_pairs}</td><td>{decimal(metric.ndcg_at_10)}</td>
          <td>{metric.latency.retrieval_ms.p95.toFixed(1)} ms</td><td>{metric.latency.rerank_ms.p95.toFixed(1)} ms</td>
        </tr>)}</tbody>
      </table></div>
    </section>
    <section className="surface page-section">
      <h3>Explanation and agent evaluation</h3>
      <div className="bench-metadata">
        <span><strong>{report.contracts.grounded}/{report.contracts.explanation_cases}</strong> evidence-grounded cases</span>
        <span><strong>{report.contracts.missing_skill_correct}/{report.contracts.explanation_cases}</strong> missing skills correctly reported</span>
        <span><strong>{report.contracts.local_preferences_correct}/{report.contracts.local_preference_cases}</strong> local preference cases correct</span>
      </div>
      <p className="fine-print">These are deterministic contract checks. {report.contracts.hosted_llm ?
        `Hosted model completed ${report.contracts.hosted_llm.valid}/${report.contracts.hosted_llm.cases} valid responses.` :
        "Hosted model measurements require a configured provider."}</p>
    </section>
  </div>;
}
