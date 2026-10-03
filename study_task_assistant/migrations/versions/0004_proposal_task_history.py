"""Keep proposal history without blocking deletion of confirmed tasks."""

from alembic import op
import sqlalchemy as sa


revision = "0004_proposal_task_history"
down_revision = "0003_task_proposals"
branch_labels = None
depends_on = None

FK_NAME = "fk_task_proposals_task_id_tasks"
NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def upgrade() -> None:
    foreign_keys = sa.inspect(op.get_bind()).get_foreign_keys("task_proposals")
    task_fk = next(fk for fk in foreign_keys if fk["constrained_columns"] == ["task_id"])
    with op.batch_alter_table("task_proposals", naming_convention=NAMING) as batch_op:
        batch_op.drop_constraint(task_fk["name"] or FK_NAME, type_="foreignkey")


def downgrade() -> None:
    with op.batch_alter_table("task_proposals", naming_convention=NAMING) as batch_op:
        batch_op.create_foreign_key(FK_NAME, "tasks", ["task_id"], ["id"])
