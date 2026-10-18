"""Import business tables for SQLAlchemy and Alembic discovery."""
from app.models.user import User
from app.models.order_event import OrderEvent
from app.models.content import BlogPost, BlogComment, ProductReview
from app.models.engagement import Favorite, SupportConversation, SupportMessage
from app.models.business import Business
from app.models.category import Category
from app.models.product import Product
from app.models.purchase import PurchaseReceipt, PurchaseReceiptItem
from app.models.sale import SalesOrder, SalesOrderItem
from app.models.stock_movement import StockMovement
from app.models.audit_log import AuditLog
from app.models.customer import Customer
from app.models.warranty import WarrantyCoverage, WarrantyDevice, WarrantyTicket, WarrantyEvent

__all__ = [
    "User", "Business", "Category", "Product", "PurchaseReceipt",
    "PurchaseReceiptItem", "SalesOrder", "SalesOrderItem", "StockMovement", "AuditLog", "Customer",
    "WarrantyCoverage", "WarrantyDevice", "WarrantyTicket", "WarrantyEvent",
    "OrderEvent", "BlogPost", "BlogComment", "ProductReview", "Favorite", "SupportConversation", "SupportMessage",
]
