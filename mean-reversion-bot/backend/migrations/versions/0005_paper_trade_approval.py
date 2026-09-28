"""Approval state for hypothetical paper trades."""
from alembic import op
import sqlalchemy as sa

revision = "0005_paper_trade_approval"
down_revision = "0004_paper_trades"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns("paper_trades")}
    if "approval_status" not in columns:
        op.add_column("paper_trades", sa.Column("approval_status", sa.String(16), nullable=False, server_default="not_requested"))
    indexes = {index["name"] for index in sa.inspect(connection).get_indexes("paper_trades")}
    if "ix_paper_trades_approval_status" not in indexes:
        op.create_index("ix_paper_trades_approval_status", "paper_trades", ["approval_status"])


def downgrade():
    raise RuntimeError("Paper approval history is retained; destructive downgrade requires a reviewed recovery migration")