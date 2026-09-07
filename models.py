from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime
from database import Base


class Company(Base):
    __tablename__ = 'companies'

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # Название компании (отображается в таблице лидеров)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Уникальный slug для реферальной ссылки (придумывает пользователь)
    # Например: ecarsburg.ru/company/avto-premium
    slug: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    # Краткое описание компании (для отображения на сайте)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    # Данные для входа
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Флаг администратора
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


    # Связь с кликами
    clicks: Mapped[list["ClickEvent"]] = relationship(
        "ClickEvent",
        back_populates="company",
        cascade="all, delete-orphan"
    )

    # Методы для Flask-Login
    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)


class ClickEvent(Base):
    __tablename__ = 'click_events'

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('companies.id'), nullable=False, index=True)

    # Для защиты от накрутки
    ip_address: Mapped[str] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str] = mapped_column(String(255), nullable=True)

    clicked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    # Связь с компанией
    company: Mapped["Company"] = relationship("Company", back_populates="clicks")


class UserAction(Base):
    __tablename__ = 'user_actions'

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # IP пользователя (для группировки действий одного пользователя)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=True, index=True)

    # User Agent (браузер, ОС)
    user_agent: Mapped[str] = mapped_column(String(500), nullable=True)

    # Тип действия: 'referral_click', 'social_button_click', 'page_view'
    action_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Детали действия (например, название соцсети: 'telegram', 'vk', 'instagram')
    action_detail: Mapped[str] = mapped_column(String(100), nullable=True)

    # Реферальная ссылка, по которой пришел пользователь (если есть)
    referral_slug: Mapped[str] = mapped_column(String(50), nullable=True, index=True)

    # URL страницы, на которой произошло действие
    page_url: Mapped[str] = mapped_column(String(500), nullable=True)

    # Время действия
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)