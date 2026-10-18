"""Explicit staff task grants; preserve capabilities of existing staff."""
from alembic import op
import sqlalchemy as sa

revision = 'f002_permissions'
down_revision = 'f001_orders'
branch_labels = depends_on = None


def upgrade():
    op.add_column('users', sa.Column('task_groups', sa.String(200), nullable=False, server_default=''))
    op.execute("UPDATE users SET task_groups = 'inventory,orders,warranty' WHERE role = 'staff'")


def downgrade():
    op.drop_column('users', 'task_groups')
