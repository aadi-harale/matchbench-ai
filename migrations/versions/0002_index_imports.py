"""Record index ingestion and freshness.

Revision ID: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "index_imports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("created_at", sa.String, nullable=False),
        sa.Column("counts", sa.JSON, nullable=False),
    )


def downgrade():
    op.drop_table("index_imports")
