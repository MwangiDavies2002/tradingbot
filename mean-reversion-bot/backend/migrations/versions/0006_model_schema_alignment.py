"""Align the migrated schema with the SQLAlchemy model schema."""
from alembic import op
import sqlalchemy as sa


revision = "0006_model_schema_alignment"
down_revision = "0005_paper_trade_approval"
branch_labels = None
depends_on = None


def _table_names(connection):
    return set(sa.inspect(connection).get_table_names())


def _column_names(connection, table):
    return {column["name"] for column in sa.inspect(connection).get_columns(table)}


def _index_names(connection, table):
    return {index["name"] for index in sa.inspect(connection).get_indexes(table)}


def upgrade():
    connection = op.get_bind()
    tables = _table_names(connection)

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("hashed_password", sa.String(255), nullable=False),
            sa.Column("deriv_api_key", sa.String(255), nullable=True),
            sa.Column("deriv_account_id", sa.String(64), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_login", sa.DateTime(), nullable=True),
        )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    if "similarity_clusters" not in tables:
        op.create_table(
            "similarity_clusters",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("strategy_family", sa.String(64), nullable=False),
            sa.Column("centroid_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    indexes = _index_names(connection, "similarity_clusters")
    if "ix_similarity_clusters_strategy_family" not in indexes:
        op.create_index("ix_similarity_clusters_strategy_family",
                        "similarity_clusters", ["strategy_family"])

    if "strategy_combinations" not in tables:
        op.create_table(
            "strategy_combinations",
            sa.Column("fingerprint", sa.String(64), primary_key=True),
            sa.Column("strategy_name", sa.String(64), nullable=False),
            sa.Column("version", sa.String(16), nullable=False, server_default="1.0.0"),
            sa.Column("instrument", sa.String(32), nullable=False),
            sa.Column("timeframe", sa.String(8), nullable=False),
            sa.Column("parameters_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="candidate"),
            sa.Column("cluster_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_run_at", sa.DateTime(), nullable=True),
        )
    indexes = _index_names(connection, "strategy_combinations")
    for name, columns in (
        ("ix_strategy_combinations_cluster_id", ["cluster_id"]),
        ("ix_strategy_combinations_instrument", ["instrument"]),
        ("ix_strategy_combinations_status", ["status"]),
        ("ix_strategy_combinations_strategy_name", ["strategy_name"]),
        ("ix_strategy_combinations_timeframe", ["timeframe"]),
    ):
        if name not in indexes:
            op.create_index(name, "strategy_combinations", columns)

    if "exploration_rounds" not in tables:
        op.create_table(
            "exploration_rounds",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("current_batch", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("total_candidates", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tested_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    for table in ("backtest_results", "equity_snapshots", "paper_trades", "signals", "trades"):
        columns = _column_names(connection, table)
        if "user_id" not in columns:
            with op.batch_alter_table(table) as batch_op:
                batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
                batch_op.create_foreign_key(
                    f"fk_{table}_user_id_users", "users", ["user_id"], ["id"])
                batch_op.create_index(f"ix_{table}_user_id", ["user_id"])

    backtest_columns = _column_names(connection, "backtest_results")
    with op.batch_alter_table("backtest_results") as batch_op:
        if "combination_id" not in backtest_columns:
            batch_op.add_column(sa.Column("combination_id", sa.String(64), nullable=True))
            batch_op.create_foreign_key(
                "fk_backtest_results_combination_id_strategy_combinations",
                "strategy_combinations", ["combination_id"], ["fingerprint"])
            batch_op.create_index("ix_backtest_results_combination_id", ["combination_id"])
        for name, column in (
            ("expectancy_r", sa.Column("expectancy_r", sa.Float(), nullable=True)),
            ("expectancy_r_lb", sa.Column("expectancy_r_lb", sa.Float(), nullable=True)),
            ("mae_avg", sa.Column("mae_avg", sa.Float(), nullable=True)),
            ("mfe_avg", sa.Column("mfe_avg", sa.Float(), nullable=True)),
            ("exit_efficiency", sa.Column("exit_efficiency", sa.Float(), nullable=True)),
            ("market_analysis_json", sa.Column("market_analysis_json", sa.JSON(), nullable=True)),
            ("feedback_json", sa.Column("feedback_json", sa.JSON(), nullable=True)),
        ):
            if name not in backtest_columns:
                batch_op.add_column(column)


def downgrade():
    raise RuntimeError(
        "Model-alignment history is retained; destructive downgrade requires a reviewed recovery migration")
