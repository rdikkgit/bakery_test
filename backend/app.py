# backend/app.py
from typing import List, Optional, Generator

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    Header,
    status,
    Query,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, conint, ConfigDict

from sqlalchemy import select, text, Table, MetaData
from sqlalchemy.orm import Session

from backend.db import Base, engine, SessionLocal
from backend.models import (
    Product,
    Inventory,
    Order,
    OrderItem,
    Cafe,
    OrderStatus,
)

# -------- PDF (ReportLab) ----------
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# -------- Auth (bcrypt + JWT) ------
from passlib.hash import bcrypt
import jwt

# ================== CONFIG ==================
APP_TITLE = "Bakery API (MySQL)"
LOCAL_TZ = ZoneInfo("Asia/Almaty")  # локальное время для PDF
SECRET_KEY = os.environ.get("JWT_SECRET", "super-secret-key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 12 * 60  # 12 часов

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INVOICE_DIR = os.path.join(BASE_DIR, "invoices")
os.makedirs(INVOICE_DIR, exist_ok=True)

# =============== FASTAPI APP ===============
app = FastAPI(title=APP_TITLE)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============== DB utils ===============
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =============== Auth models/Schemas ===============
class LoginIn(BaseModel):
    login: str
    password: str

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    id: int
    cafe_id: int
    login: str
    is_admin: bool

# Таблица пользователей кафе (autoload)
_metadata = MetaData()
CafeUsers = Table("cafe_users", _metadata, autoload_with=engine)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> UserOut:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    payload = decode_token(token)
    uid = payload.get("sub")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    row = db.execute(select(CafeUsers).where(CafeUsers.c.id == int(uid))).mappings().first()
    if not row:
        raise HTTPException(status_code=401, detail="User not found")

    return UserOut(
        id=row["id"],
        cafe_id=row["cafe_id"],
        login=row["login"],
        is_admin=bool(row["is_admin"]),
    )

# =============== Pydantic Schemas ===============
class ProductOut(BaseModel):
    id: int
    name: str
    price: float
    stock: int
    model_config = ConfigDict(from_attributes=True)

class OrderItemIn(BaseModel):
    product_id: int
    qty: conint(gt=0)

class OrderCreateIn(BaseModel):
    items: List[OrderItemIn]
    comment: Optional[str] = None

class OrderItemOut(BaseModel):
    product_id: int
    name: str
    qty: int

class OrderOut(BaseModel):
    id: int
    cafe_id: int
    status: str
    items: List[OrderItemOut]

# =============== PDF helpers ===============
def _invoice_path(order_id: int) -> str:
    return os.path.join(INVOICE_DIR, f"order_{order_id}.pdf")

def _ensure_fonts():
    """
    Регистрирует DejaVuSans/DejaVuSans-Bold для корректной кириллицы.
    """
    try:
        pdfmetrics.getFont("DejaVuSans")
        pdfmetrics.getFont("DejaVuSans-Bold")
        return
    except Exception:
        pass

    local_regular = os.path.join(BASE_DIR, "fonts", "DejaVuSans.ttf")
    local_bold = os.path.join(BASE_DIR, "fonts", "DejaVuSans-Bold.ttf")

    candidates_regular = [
        local_regular,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/local/share/fonts/DejaVuSans.ttf",
    ]
    candidates_bold = [
        local_bold,
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/local/share/fonts/DejaVuSans-Bold.ttf",
    ]

    reg = next((p for p in candidates_regular if os.path.exists(p)), None)
    bold = next((p for p in candidates_bold if os.path.exists(p)), None)

    if reg and bold:
        pdfmetrics.registerFont(TTFont("DejaVuSans", reg))
        pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", bold))
    else:
        print("WARN: DejaVuSans(.ttf) не найден — кириллица в PDF может не печататься.")

def generate_invoice_pdf(db: Session, order_id: int) -> str:
    """Создаёт PDF-инвойс (с кириллицей и временем Алматы)."""
    order = db.get(Order, order_id)
    if not order:
        raise ValueError("Order not found")

    rows = (
        db.query(OrderItem, Product)
        .join(Product, OrderItem.product_id == Product.id)
        .filter(OrderItem.order_id == order_id)
        .all()
    )

    file_path = _invoice_path(order_id)
    _ensure_fonts()

    c = canvas.Canvas(file_path, pagesize=A4)
    w, h = A4
    y = h - 20 * mm

    c.setFont("DejaVuSans-Bold", 16)
    c.drawString(20 * mm, y, f"Invoice / Накладная № {order.id}")
    y -= 8 * mm

    c.setFont("DejaVuSans", 10)
    local_time = datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
    c.drawString(20 * mm, y, f"Date: {local_time} (Almaty)")
    y -= 6 * mm

    # Cafe name (если есть)
    try:
        cafe_name = db.execute(select(Cafe.name).where(Cafe.id == order.cafe_id)).scalar_one()
        c.drawString(20 * mm, y, f"Cafe: {cafe_name}")
    except Exception:
        c.drawString(20 * mm, y, f"Cafe ID: {order.cafe_id}")
    y -= 6 * mm

    status_val = getattr(order.status, "value", order.status)
    c.drawString(20 * mm, y, f"Status: {status_val}")
    y -= 10 * mm

    # Комментарий
    if getattr(order, "comment", None):
        c.setFont("DejaVuSans-Bold", 10)
        c.drawString(20 * mm, y, "Комментарий:")
        c.setFont("DejaVuSans", 10)
        c.drawString(50 * mm, y, (order.comment or "")[:90])
        y -= 10 * mm

    # Шапка таблицы
    c.setFont("DejaVuSans-Bold", 11)
    c.drawString(20 * mm, y, "Название")
    c.drawString(100 * mm, y, "Кол-во")
    c.drawString(120 * mm, y, "Цена")
    c.drawString(150 * mm, y, "Сумма")
    y -= 6 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm

    c.setFont("DejaVuSans", 10)
    total = 0.0
    for oi, p in rows:
        line_total = float(oi.price) * oi.qty
        total += line_total

        c.drawString(20 * mm, y, p.name[:50])
        c.drawRightString(115 * mm, y, str(oi.qty))
        c.drawRightString(140 * mm, y, f"{float(oi.price):.2f}")
        c.drawRightString(190 * mm, y, f"{line_total:.2f}")
        y -= 6 * mm

        if y < 30 * mm:
            c.showPage()
            _ensure_fonts()
            c.setFont("DejaVuSans", 10)
            y = h - 20 * mm

    y -= 6 * mm
    c.setFont("DejaVuSans-Bold", 12)
    c.drawRightString(190 * mm, y, f"ИТОГО: {total:.2f}")

    c.showPage()
    c.save()
    return file_path

# =============== Endpoints ===============
@app.get("/", tags=["health"])
def root(db: Session = Depends(get_db)):
    # простая проверка соединения с БД
    db.execute(select(Product.id).limit(1))
    return {"message": "Bakery API is alive"}

# --- Auth ---
@app.post("/auth/login", response_model=TokenOut, tags=["auth"])
def login(payload: LoginIn, db: Session = Depends(get_db)):
    row = db.execute(select(CafeUsers).where(CafeUsers.c.login == payload.login)).mappings().first()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not bcrypt.verify(payload.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": row["id"]})
    return TokenOut(access_token=token)

@app.get("/auth/me", response_model=UserOut, tags=["auth"])
def whoami(user: UserOut = Depends(get_current_user)):
    return user

# --- Products ---
@app.get("/products", response_model=List[ProductOut], tags=["products"])
def list_products(db: Session = Depends(get_db)):
    rows = (
        db.execute(
            select(
                Product.id,
                Product.name,
                Product.price,
                Inventory.qty,
            )
            .join(Inventory, Inventory.product_id == Product.id, isouter=True)
            .order_by(Product.id)
        ).all()
    )
    return [{"id": r[0], "name": r[1], "price": float(r[2] or 0), "stock": int(r[3] or 0)} for r in rows]

# --- Orders ---
@app.post("/orders", response_model=OrderOut, status_code=201, tags=["orders"])
def create_order(payload: OrderCreateIn, db: Session = Depends(get_db), user: UserOut = Depends(get_current_user)):
    if not payload.items:
        raise HTTPException(status_code=400, detail="Items required")

    # Проверка продуктов
    product_ids = {it.product_id for it in payload.items}
    products = {p.id: p for p in db.execute(select(Product).where(Product.id.in_(product_ids))).scalars().all()}
    if len(products) != len(product_ids):
        missing = sorted(product_ids - set(products.keys()))
        raise HTTPException(status_code=400, detail=f"Products not found: {missing}")

    order = Order(cafe_id=user.cafe_id, status=OrderStatus.pending, comment=payload.comment or "")
    db.add(order)
    db.flush()

    for it in payload.items:
        db.add(OrderItem(order_id=order.id, product_id=it.product_id, qty=it.qty, price=products[it.product_id].price))

    db.commit()
    db.refresh(order)

    out_items = []
    for oi in order.items:
        name = db.get(Product, oi.product_id).name
        out_items.append(OrderItemOut(product_id=oi.product_id, name=name, qty=oi.qty))

    return OrderOut(id=order.id, cafe_id=order.cafe_id, status=order.status.value, items=out_items)

@app.post("/orders/{order_id}/confirm", tags=["orders"])
def confirm_order(order_id: int, db: Session = Depends(get_db), user: UserOut = Depends(get_current_user)):
    order = db.execute(
        select(Order).where(Order.id == order_id, Order.cafe_id == user.cafe_id)
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != OrderStatus.pending:
        raise HTTPException(status_code=400, detail="Order not in pending state")

    # списываем остаток
    for it in order.items:
        inv = db.execute(select(Inventory).where(Inventory.product_id == it.product_id)).scalar_one_or_none()
        if not inv or inv.qty < it.qty:
            raise HTTPException(status_code=409, detail=f"Insufficient stock for product_id={it.product_id}")
        inv.qty -= it.qty

    order.status = OrderStatus.confirmed
    db.commit()

    # создаем/обновляем PDF
    try:
        generate_invoice_pdf(db, order_id)
    except Exception as e:
        print(f"PDF generation error for order {order_id}: {e}")

    return {"ok": True, "status": order.status.value, "invoice_url": f"/orders/{order_id}/invoice"}

@app.get("/orders/{order_id}", response_model=OrderOut, tags=["orders"])
def get_order(order_id: int, db: Session = Depends(get_db), user: UserOut = Depends(get_current_user)):
    order = db.execute(
        select(Order).where(Order.id == order_id, Order.cafe_id == user.cafe_id)
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    out_items = []
    for oi in order.items:
        name = db.get(Product, oi.product_id).name
        out_items.append(OrderItemOut(product_id=oi.product_id, name=name, qty=oi.qty))

    return OrderOut(id=order.id, cafe_id=order.cafe_id, status=order.status.value, items=out_items)

@app.get("/orders/{order_id}/invoice", summary="Скачать PDF-инвойс", tags=["orders"])
def get_invoice(order_id: int, db: Session = Depends(get_db), user: UserOut = Depends(get_current_user)):
    order = db.execute(
        select(Order).where(Order.id == order_id, Order.cafe_id == user.cafe_id)
    ).scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    path = _invoice_path(order_id)
    if not os.path.exists(path):
        generate_invoice_pdf(db, order_id)

    return FileResponse(path, media_type="application/pdf", filename=f"invoice_order_{order_id}.pdf")

@app.get("/orders/my", tags=["orders"])
def list_my_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: UserOut = Depends(get_current_user),
):
    offset = (page - 1) * page_size
    rows = db.execute(
        select(Order.id, Order.status, Order.created_at)
        .where(Order.cafe_id == user.cafe_id)
        .order_by(Order.id.desc())
        .offset(offset)
        .limit(page_size)
    ).all()

    # считаем total для каждого заказа
    result = []
    for oid, st, created_at in rows:
        total = db.execute(
            select(OrderItem.price, OrderItem.qty).where(OrderItem.order_id == oid)
        ).all()
        s = sum(float(p) * q for p, q in total)
        result.append(
            {
                "id": oid,
                "status": getattr(st, "value", st),
                "created_at": created_at,
                "total": round(s, 2),
            }
        )
    return result
