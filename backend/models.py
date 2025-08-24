from sqlalchemy import Column, Integer, String, ForeignKey, Numeric, Enum, UniqueConstraint, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy import DateTime
from .db import Base
import enum

class OrderStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    canceled = "canceled"

class Cafe(Base):
    __tablename__ = "cafes"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    api_key = Column(String(64), unique=True, index=True)

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    price = Column(Numeric(10, 2), nullable=False, default=0)
    unit = Column(String(20), nullable=False, default="pcs")  # ← ОБЯЗАТЕЛЬНО
    sku  = Column(String(64), unique=True, index=True)

class Inventory(Base):
    __tablename__ = "inventory"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, unique=True)
    qty = Column(Integer, nullable=False, default=0)
    product = relationship("Product")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    cafe_id = Column(Integer, ForeignKey("cafes.id"), nullable=False)
    status = Column(Enum(OrderStatus), nullable=False, default=OrderStatus.pending)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    cafe = relationship("Cafe")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    
    comment = Column(String, nullable=True)   # ← вот это


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    qty = Column(Integer, nullable=False)
    price = Column(Numeric(10, 2), nullable=False)  # ← обязательно
    # связи (можно без них, но полезно)
    order = relationship("Order", back_populates="items")
    product = relationship("Product")


# --- Учётная запись пользователя кафе ---
class CafeUser(Base):
    __tablename__ = "cafe_users"

    id = Column(Integer, primary_key=True, index=True)
    cafe_id = Column(Integer, ForeignKey("cafes.id"))  # если у тебя таблица называется 'cafe', см. SQL ниже
    login = Column(String(64), unique=True, nullable=False)      # ЛОГИН (username)
    password_hash = Column(String(255), nullable=False)          # bcrypt-хэш пароля
    phone = Column(String(32), nullable=True)                    # опционально: контактный телефон
    is_admin = Column(Boolean, nullable=False, default=False)    # админ пекарни
    created_at = Column(DateTime, server_default=func.now())


