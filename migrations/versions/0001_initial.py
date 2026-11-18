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
    Base.metadata.create_all(connection)


def downgrade():
    Base.metadata.drop_all(op.get_bind())
