from database import SessionLocal
from models import Company
from werkzeug.security import generate_password_hash


def create_admin():
    db = SessionLocal()
    try:
        # Проверяем, есть ли уже админ
        existing_admin = db.query(Company).filter(Company.is_admin == True).first()
        if existing_admin:
            print(f"Администратор уже существует: {existing_admin.email}")
            return

        # Создаем администратора
        admin = Company(
            name="E-CarsBurg Admin",
            slug="admin",
            email="admin@ecarsburg.ru",
            password_hash=generate_password_hash("admin123"),  # Замени на безопасный пароль!
            is_admin=True
        )
        db.add(admin)
        db.commit()
        print("Администратор создан успешно!")
        print("Email: admin@ecarsburg.ru")
        print("Пароль: admin123")
    except Exception as e:
        db.rollback()
        print(f"Ошибка: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    create_admin()