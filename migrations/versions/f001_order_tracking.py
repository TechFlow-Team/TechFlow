"""Order fulfillment history, preserving the inventory accounting states."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

revision = 'f001_orders'
down_revision = 'c052_clients'
branch_labels = depends_on = None


def upgrade():
    op.add_column('sales_orders', sa.Column('fulfillment_status', sa.String(20), nullable=False, server_default='waiting'))
    op.execute("UPDATE sales_orders SET fulfillment_status = CASE WHEN status = 'draft' THEN 'waiting' ELSE status END")
    op.create_table('order_events',
        sa.Column('id', mysql.BIGINT(unsigned=True), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('order_id', mysql.BIGINT(unsigned=True), sa.ForeignKey('sales_orders.id', ondelete='RESTRICT'), nullable=False, index=True),
        sa.Column('actor_id', mysql.BIGINT(unsigned=True), sa.ForeignKey('users.id', ondelete='RESTRICT'), index=True),
        sa.Column('status', sa.String(20), nullable=False), sa.Column('note', sa.String(1000)),
        mysql_engine='InnoDB', mysql_charset='utf8mb4', mysql_collate='utf8mb4_unicode_ci')
    op.execute("INSERT INTO order_events (order_id, actor_id, status, note, created_at) SELECT id, NULL, fulfillment_status, 'Trạng thái tại thời điểm nâng cấp; không suy diễn lịch sử trước đó', CURRENT_TIMESTAMP FROM sales_orders")


def downgrade():
    op.drop_table('order_events')
    op.drop_column('sales_orders', 'fulfillment_status')
