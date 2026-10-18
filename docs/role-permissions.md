# TechFlow roles and permissions

Staff capabilities below additionally require the corresponding task group.
See [feature permissions and migration](FEATURES_RELEASE.md)
for `orders`, `inventory`, `content`, `warranty`, `support`, and `reports`.
New staff start with no task groups; existing staff retain inventory/orders/warranty.
Admin assigns grants at `/admin/staff`. Changes apply on the next request.

| Capability | Admin | Staff | Client |
|---|---|---|---|
| Admin dashboard | Full access | Denied | Denied |
| Business dashboard | View | View | Denied |
| Catalog, categories, suppliers | Manage | Manage | Public product catalog only |
| Purchase receipts | Create and process | Denied | Denied |
| Internal sales orders | View and process all | Create and process own | Denied |
| Online client orders | View and process all | View and process | Place orders and view own only |
| Customers and inventory | Manage / full history | Existing scoped inventory views | Own profile is used for delivery |
| Account creation | Admin created by CLI | Admin creates and activates/deactivates | Self registration; role fixed to `client` |

Authorization is enforced on server routes and in order services. Client storefront orders are created as `draft`; stock is changed only when staff/admin completes the order in the existing transaction workflow. Product prices and stock are re-read under database row locks during checkout. Existing customer snapshots and historical orders are retained.

The storefront currently accepts an order request only. It does not collect payment or promise stock reservation before staff confirmation. Client pages live in a separate storefront layout; no administrator link is rendered there, and direct client requests to admin routes remain denied by server-side decorators.

Client features include product search, category filtering, sorting and pagination; product detail; guest cart with quantity edits; account registration and login; customer profile and delivery-address changes; checkout; private order list/details; and cancellation while an order is still waiting for staff.

## Schema update

Migration `c052_clients` follows `w052_guards`. It expands the users role check and adds a nullable, unique `customers.user_id` foreign key. The field is nullable so existing customer profiles remain valid and unchanged. The downgrade deliberately refuses to remove the client role while client accounts exist.

Apply on the local development database first, after confirming `DATABASE_URL` or the local `.env` points to the local MySQL service:

```powershell
docker compose exec web flask --app wsgi db upgrade
```

The matching production migration command, when separately approved and backed up, is:

```bash
sudo docker compose --env-file /etc/techflow/app.env -f docker-compose.prod.yml run --rm web flask --app wsgi db upgrade
```

Do not run the production command as part of local development. Back up RDS and review the release before applying it to AWS.
