"""Account approval/creation metadata, revoked session tokens, auto-resolved alerts.

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("created_by", sa.String(32), nullable=True))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET approved_at = CURRENT_TIMESTAMP WHERE active")
    op.add_column("alerts", sa.Column("auto_resolved", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table("revoked_tokens",
                    sa.Column("jti", sa.String(64), primary_key=True),
                    sa.Column("user_id", sa.String(32), nullable=True),
                    sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_table("revoked_tokens")
    op.drop_column("alerts", "auto_resolved")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "created_by")
    op.drop_column("users", "created_at")
    op.drop_column("users", "approved_at")
