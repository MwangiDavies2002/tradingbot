"""Immutable instrument revisions for explicitly pinned execution plans."""
from alembic import op
import sqlalchemy as sa

revision = "0003_instrument_catalog"
down_revision = "0002_research_registry"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if not sa.inspect(connection).has_table("instrument_revisions"):
        op.create_table("instrument_revisions",
            sa.Column("spec_hash", sa.String(64), primary_key=True),
            sa.Column("instrument_id", sa.String(128), nullable=False),
            sa.Column("venue", sa.String(64), nullable=False),
            sa.Column("venue_symbol", sa.String(64), nullable=False),
            sa.Column("revision", sa.String(64), nullable=False),
            sa.Column("spec", sa.JSON(), nullable=False),
            sa.Column("registered_at", sa.DateTime(), nullable=False),
            sa.Column("registered_by_role", sa.String(16), nullable=False),
            sa.UniqueConstraint("venue", "venue_symbol", "revision", name="uq_instrument_venue_revision"))
    existing = {i["name"] for i in sa.inspect(connection).get_indexes("instrument_revisions")}
    for column in ("instrument_id", "venue"):
        name = f"ix_instrument_revisions_{column}"
        if name not in existing:
            op.create_index(name, "instrument_revisions", [column])
    if connection.dialect.name == "sqlite":
        for verb in ("UPDATE", "DELETE"):
            op.execute(f"CREATE TRIGGER IF NOT EXISTS instrument_revisions_no_{verb.lower()} BEFORE {verb} ON instrument_revisions BEGIN SELECT RAISE(ABORT, 'Research records are append-only'); END")
    elif connection.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS instrument_revisions_immutable ON instrument_revisions")
        op.execute("CREATE TRIGGER instrument_revisions_immutable BEFORE UPDATE OR DELETE ON instrument_revisions FOR EACH ROW EXECUTE FUNCTION reject_research_mutation()")


def downgrade():
    raise RuntimeError("Instrument history is retained; destructive downgrade requires a reviewed recovery migration")
