"""Create versioned MatchBench records.

Revision ID: 0001
"""
from alembic import op

from matchbench.db import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(connection, tables=initial_tables())


def downgrade():
    Base.metadata.drop_all(op.get_bind(), tables=initial_tables())


def initial_tables():
    names = (
        "users", "candidate_profiles", "candidate_evidence", "preference_events", "jobs", "job_versions",
        "job_embeddings", "match_runs", "match_results", "feedback_events", "agent_runs", "tool_calls",
    )
    return [Base.metadata.tables[name] for name in names]
