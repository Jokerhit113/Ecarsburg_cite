from database import SessionLocal
from models import Company, ROLE_ADMIN
from werkzeug.security import generate_password_hash


def create_admin():
    db = SessionLocal()
    try:
        existing_admin = db.query(Company).filter(Company.role == ROLE_ADMIN).first()
        if existing_admin:
            # ensure role/is_admin sync
            existing_admin.role = ROLE_ADMIN
            existing_admin.is_admin = True
            db.commit()
            print(f"Администратор уже существует: логин «{existing_admin.slug}» ({existing_admin.email})")
            return

        admin = Company(
            name="E-CarsBurg Admin",
            slug="admin",
            email="admin@ecarsburg.ru",
            password_hash=generate_password_hash("admin123"),
            is_admin=True,
            role=ROLE_ADMIN,
        )
        db.add(admin)
        db.commit()
        print("Главный администратор создан!")
        print("Логин: admin")
        print("Пароль: admin123")
    except Exception as e:
        db.rollback()
        print(f"Ошибка: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    create_admin()
