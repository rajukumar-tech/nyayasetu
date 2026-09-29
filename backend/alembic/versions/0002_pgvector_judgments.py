"""pgvector judgment passages (PostgreSQL only)

The retrieval code currently builds its hybrid (BM25 + LSA) index in-process from
data/judgments/*.jsonl (see docs/DECISIONS.md D-009). This table is where passages and
their embeddings live once the public HC corpus is large enough to need the database.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("""
        CREATE TABLE IF NOT EXISTS judgment_passages (
            id TEXT PRIMARY KEY,
            citation TEXT NOT NULL,
            court TEXT,
            decided_on DATE,
            url TEXT,
            text TEXT NOT NULL,
            synthetic BOOLEAN NOT NULL DEFAULT FALSE,
            tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
            embedding vector(64)
        )""")
    op.execute("CREATE INDEX IF NOT EXISTS ix_jp_tsv ON judgment_passages USING GIN (tsv)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_jp_emb ON judgment_passages USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP TABLE IF EXISTS judgment_passages")
