"""Normalize the existing client-link unique index name to match ORM metadata."""
from alembic import op
import sqlalchemy as sa

revision = 'f005_client_index'
down_revision = 'f004_engagement'
branch_labels = depends_on = None


def upgrade():
    indexes = {index['name'] for index in sa.inspect(op.get_bind()).get_indexes('customers')}
    if 'user_id' in indexes and 'uq_customers_user_id' not in indexes:
        op.execute('ALTER TABLE customers RENAME INDEX user_id TO uq_customers_user_id')


def downgrade():
    indexes = {index['name'] for index in sa.inspect(op.get_bind()).get_indexes('customers')}
    if 'uq_customers_user_id' in indexes and 'user_id' not in indexes:
        op.execute('ALTER TABLE customers RENAME INDEX uq_customers_user_id TO user_id')
