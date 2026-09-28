"""Durable hypothetical paper-trade ledger."""
from alembic import op
import sqlalchemy as sa

revision = "0004_paper_trades"
down_revision = "0003_instrument_catalog"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if not sa.inspect(connection).has_table("paper_trades"):
        op.create_table(
            "paper_trades",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("signal_id", sa.String(64), nullable=True),
            sa.Column("symbol", sa.String(64), nullable=False),
            sa.Column("timeframe", sa.String(8), nullable=False),
            sa.Column("direction", sa.String(8), nullable=False),
            sa.Column("entry_price", sa.Float(), nullable=False),
            sa.Column("stop_loss", sa.Float(), nullable=False),
            sa.Column("take_profit", sa.Float(), nullable=False),
            sa.Column("exit_price", sa.Float(), nullable=True),
            sa.Column("quantity", sa.Float(), nullable=False, server_default="1"),
            sa.Column("pnl", sa.Float(), nullable=True),
            sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("regime", sa.String(32), nullable=False, server_default="unknown"),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(12), nullable=False, server_default="open"),
            sa.Column("created_by_role", sa.String(16), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
        )
    existing = {index["name"] for index in sa.inspect(connection).get_indexes("paper_trades")}
    for column in ("signal_id", "symbol", "status", "created_at"):
        name = f"ix_paper_trades_{column}"
        if name not in existing:
            op.create_index(name, "paper_trades", [column])


def downgrade():
    raise RuntimeError("Paper trade history is retained; destructive downgrade requires a reviewed recovery migration")
