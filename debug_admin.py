from database import SessionLocal
from models import Company, ClickEvent

db = SessionLocal()
try:
    print("📊 Проверка данных для админки:")
    print("=" * 60)

    # Проверяем ВСЕ компании
    all_companies = db.query(Company).all()
    print(f"Всего компаний в базе: {len(all_companies)}")

    # Проверяем обычные компании (не админов)
    regular_companies = db.query(Company).filter(Company.is_admin == False).all()
    print(f"Обычных компаний (не админов): {len(regular_companies)}")

    for comp in regular_companies:
        clicks = db.query(ClickEvent).filter_by(company_id=comp.id).count()
        print(f"  - {comp.name} (slug: {comp.slug}, кликов: {clicks})")

    print("=" * 60)
    if len(regular_companies) == 0:
        print("⚠️  НЕТ ОБЫЧНЫХ КОМПАНИЙ! Возможно, все компании - админы?")
        for c in all_companies:
            print(f"  {c.name} - is_admin: {c.is_admin}")

finally:
    db.close()