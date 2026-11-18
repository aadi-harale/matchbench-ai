# Implementation plan

1. Complete source review, architecture and schemas.
2. Implement jobs, migrations, incremental ingestion and reproducible seed data.
3. Implement PDF, DOCX and text extraction, evidence review and versioning.
4. Build keyword, BM25, cosine and hybrid retrieval, then cross-encoder reranking.
5. Apply hard gates and bounded personalization; capture provenance and add counterfactual recomputation.
6. Persist preference events and feedback, introduce bounded typed tools, validate proposals and require confirmation.
7. Run ranking and agent evaluation before frontend construction. Test fairness, security, fallback and startup.
8. Build the recruiter-friendly UI, including Candidate Profile, Explorer, Daily Matches, Match Detail, Memory and Evaluation.
9. Package Compose and CI, deploy and verify. Finish setup, measured claims, interview guide and the demo script.

## Recruiter entry point

Lead with “Find the jobs you can actually take.” A short line identifies a job ranking and evaluation tool. The first screen shows a real seeded search with an eligible internship and lets the recruiter open a semantically similar role excluded for experience. The before/after inspector is the main interaction. Search, evidence review, preference changes and reproducible metrics are available in the same app.

The desktop uses a left-aligned shortlist and selected decision, stacked in reading order on narrow screens. IBM Plex Sans is for the interface, IBM Plex Mono for identifiers and data. Palette roles are workspace `#F3F7FB`, surface `#FFFFFF`, ink `#172938`, action `#1546B0`, pass `#356147`, blocker `#9D2727`. Use explicit role labels and source links. Status, evidence and comparison controls carry the visual hierarchy. Verify at 320, 768, 1024 and 1440 pixels, keyboard focus, motion preferences, and text contrast before shipping.
