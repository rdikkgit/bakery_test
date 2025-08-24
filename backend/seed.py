

# backend/seed.py
from backend.db import SessionLocal
from backend.models import Cafe, Product, Inventory
import secrets

def main():
    db = SessionLocal()
    try:
        # Кафе
        if not db.query(Cafe).count():
            db.add_all([
                Cafe(name="Cafe Central", api_key=secrets.token_hex(16)),
                Cafe(name="Bitter Beans", api_key=secrets.token_hex(16)),
            ])

        # Продукты
        if not db.query(Product).count():
            prods = [
                Product(name="Круассан классический", price=3.20, unit="pcs", sku="CR-CLASSIC"),
                Product(name="Круассан миндальный", price=4.10, unit="pcs", sku="CR-ALMOND"),
                Product(name="Синнамон ролл", price=4.50, unit="pcs", sku="CIN-ROLL"),
                Product(name="Багет", price=2.80, unit="pcs", sku="BAGUETTE"),
            ]
            db.add_all(prods)
            db.flush()
            inv = [Inventory(product_id=p.id, qty=100) for p in prods]
            db.add_all(inv)

        db.commit()
        print("✅ Seed OK — тестовые данные добавлены")
    except Exception as e:
        db.rollback()
        print("❌ Ошибка сидера:", e)
        raise
    finally:
        db.close()

if __name__ == "__main__":
    main()
