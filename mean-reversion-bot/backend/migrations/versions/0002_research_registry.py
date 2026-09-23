"""Append-only research families, trial requests and terminal outcomes."""
from alembic import op
import sqlalchemy as sa

revision = "0002_research_registry"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if not sa.inspect(connection).has_table("research_families"):
        op.create_table("research_families",
            sa.Column("family_id", sa.String(32), primary_key=True),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("hypothesis", sa.Text(), nullable=False),
            sa.Column("trial_keys", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("created_by_role", sa.String(16), nullable=False))
    if not sa.inspect(connection).has_table("research_runs"):
        op.create_table("research_runs",
            sa.Column("run_id", sa.String(32), primary_key=True),
            sa.Column("family_id", sa.String(32), sa.ForeignKey("research_families.family_id"), nullable=False),
            sa.Column("trial_key", sa.String(64), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("operation", sa.String(64), nullable=False),
            sa.Column("dataset_version", sa.String(256), nullable=False),
            sa.Column("parent_run_id", sa.String(32), sa.ForeignKey("research_runs.run_id")),
            sa.Column("request_hash", sa.String(64), nullable=False),
            sa.Column("implementation_hash", sa.String(64), nullable=False),
            sa.Column("runtime", sa.JSON(), nullable=False),
            sa.Column("input_payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("created_by_role", sa.String(16), nullable=False),
            sa.UniqueConstraint("family_id", "trial_key", name="uq_research_family_trial"))
    if not sa.inspect(connection).has_table("research_outcomes"):
        op.create_table("research_outcomes",
            sa.Column("run_id", sa.String(32), sa.ForeignKey("research_runs.run_id"), primary_key=True),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("report", sa.JSON()), sa.Column("artifact_hash", sa.String(64)),
            sa.Column("error", sa.Text()), sa.Column("completed_at", sa.DateTime(), nullable=False),
            sa.Column("completed_by_role", sa.String(16), nullable=False))
    for table, columns in {"research_families": ["name"],
                           "research_runs": ["family_id", "operation", "created_at"],
                           "research_outcomes": ["status"]}.items():
        existing = {i["name"] for i in sa.inspect(connection).get_indexes(table)}
        for column in columns:
            name = f"ix_{table}_{column}"
            if name not in existing:
                op.create_index(name, table, [column])
    if connection.dialect.name == "postgresql":
        op.execute("CREATE OR REPLACE FUNCTION reject_research_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Research records are append-only'; END; $$")
    for table in ("research_families", "research_runs", "research_outcomes"):
        if connection.dialect.name == "sqlite":
            for verb in ("UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{verb.lower()} BEFORE {verb} ON {table} BEGIN SELECT RAISE(ABORT, 'Research records are append-only'); END")
        elif connection.dialect.name == "postgresql":
            op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
            op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION reject_research_mutation()")


def downgrade():
    raise RuntimeError("Research history is retained; destructive downgrade requires a reviewed recovery migration")
