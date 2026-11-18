# Security

## Data boundary

MatchBench accepts profile text and preferences. Uploaded PDF, DOCX, or text content is size- and type-checked, parsed in memory, and the original file is not retained. Candidate-owned records are scoped by user ID. Export and account deletion include versioned personal records. Demo visitors receive isolated disposable accounts.

## Controls

- Passwords use Argon2; sessions use signed HTTP-only cookies and `Secure` in production.
- Mutation routes validate same-origin requests when the browser supplies an Origin header. Production should also enforce a strict trusted-host/proxy policy.
- PostgreSQL row-level security is enabled. Public Supabase roles have no table grants; the API uses a dedicated backend role.
- Ranking input excludes identity and protected characteristics. A regression perturbs candidate names and requires identical output.
- Agent output is schema- and policy-validated, bounded to three attempts, recorded as a pending proposal, and cannot change memory until confirmation.
- Request IDs and aggregate latency/error counters exclude résumé text and raw preference messages.
- Model files and input artifacts are revisioned or hashed for replay.

## Operational requirements

Set a unique high-entropy `SESSION_SECRET`, `SECURE_COOKIES=true`, a least-privilege `DATABASE_URL`, and secret-provider variables only in the hosting platform. Rotate a secret immediately if it enters logs or Git history. Run dependency, container, and secret scans in the release pipeline. Per-process demo throttling is not sufficient for multiple replicas; use a shared rate limiter before real user traffic.

## Reporting

Do not open a public issue containing candidate data or credentials. Send a private report to the repository owner with the affected route, impact, and a minimal reproduction. This educational deployment has no bug-bounty program or SLA.

## Known limitations

The system has not completed an external penetration test. CSRF defense relies on same-origin browser behavior plus signed cookies, and rate limiting is process-local. The demo corpus is non-sensitive and illustrative; do not upload a private résumé to the public preview.
