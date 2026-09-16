"""Add users and ownership to tasks without claiming legacy tasks."""

from alembic import op
import sqlalchemy as sa


revision = "0002_users_and_owners"
down_revision = "0001_initial_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(
            sa.Column(
                "owner_id",
                sa.Integer(),
                sa.ForeignKey("users.id", name="fk_tasks_owner_id_users"),
                nullable=True,
            )
        )
    op.create_index("ix_tasks_owner_id", "tasks", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_owner_id", table_name="tasks")
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_column("owner_id")
    op.drop_table("users")
