"""Round trip only on the explicitly dedicated, disposable migration database.

Run in the test network with MYSQL_DATABASE=techflow_backlog_migration.
Never accepts a development or production database.
"""
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask_migrate import downgrade, upgrade
from sqlalchemy import text

from app import create_app
from app.extensions import db
from app.migration_policy import include_object


def main():
    application = create_app()
    with application.app_context():
        assert application.testing
        assert db.engine.url.host == 'db-test'
        assert db.engine.url.database == 'techflow_backlog_migration'
        with db.engine.connect() as connection:
            assert connection.scalar(text('SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE()')) == 0, 'Use a fresh dedicated migration database.'
        upgrade(revision='c052_clients')
        with db.engine.begin() as connection:
            connection.execute(text("INSERT INTO users (full_name,username,password_hash,role) VALUES ('Migration fixture','migration-fixture','disabled-test-only','staff')"))
            connection.execute(text("INSERT INTO categories (code,name) VALUES ('MIG','Migration fixture')"))
            connection.execute(text("INSERT INTO products (sku,name,category_id,purchase_price,selling_price,stock_quantity) VALUES ('MIG','Migration fixture',1,10,20,7)"))
            connection.execute(text("INSERT INTO sales_orders (order_code,customer_name,created_by,order_date,status,total_amount) VALUES ('MIG','Legacy snapshot',1,'2026-01-01','completed',40)"))
            before = connection.execute(text('SELECT customer_name,status,total_amount FROM sales_orders WHERE id=1')).one()
        upgrade()
        with db.engine.connect() as connection:
            assert connection.scalar(text('SELECT stock_quantity FROM products WHERE id=1')) == 7
            assert tuple(connection.execute(text('SELECT customer_name,status,total_amount FROM sales_orders WHERE id=1')).one()) == tuple(before)
            assert connection.scalar(text('SELECT fulfillment_status FROM sales_orders WHERE id=1')) == 'completed'
            assert connection.scalar(text('SELECT task_groups FROM users WHERE id=1')) == 'inventory,orders,warranty'
            event = connection.execute(text('SELECT actor_id,status,note FROM order_events WHERE order_id=1')).one()
            assert event.actor_id is None and event.status == 'completed' and 'không suy diễn' in event.note
            context = MigrationContext.configure(connection, opts={'include_object': include_object})
            assert compare_metadata(context, db.metadata) == []
        downgrade(revision='c052_clients')
        with db.engine.connect() as connection:
            assert connection.scalar(text('SELECT stock_quantity FROM products WHERE id=1')) == 7
            assert tuple(connection.execute(text('SELECT customer_name,status,total_amount FROM sales_orders WHERE id=1')).one()) == tuple(before)
        upgrade()
        with db.engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={'include_object': include_object})
            assert compare_metadata(context, db.metadata) == []
        print('Backlog migration upgrade / downgrade / re-upgrade: PASS; legacy stock and snapshots preserved.')


if __name__ == '__main__':
    main()
