from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime
from database import Base


# Уровни доступа
ROLE_ADMIN = 'admin'           # 1. Главный администратор
ROLE_SUPERVISOR = 'supervisor' # 2. Супервайзер
ROLE_PARTNER = 'partner'       # 3. Партнёр (компания)
# 4. Пользователь — без аккаунта, только главная


class Company(Base):
    __tablename__ = 'companies'

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    slug: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Устаревший флаг — синхронизируется с role для совместимости
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    # Роль: admin | supervisor | partner
    role: Mapped[str] = mapped_column(String(20), default=ROLE_PARTNER, nullable=False, index=True)

    # Кто создал аккаунт (супервайзер или админ)
    created_by_id: Mapped[int] = mapped_column(ForeignKey('companies.id'), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    clicks: Mapped[list["ClickEvent"]] = relationship(
        "ClickEvent",
        back_populates="company",
        cascade="all, delete-orphan"
    )

    created_by = relationship("Company", remote_side=[id], foreign_keys=[created_by_id])

    # --- Flask-Login ---
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

    # --- Роли ---
    def get_role(self) -> str:
        if self.role:
            return self.role
        return ROLE_ADMIN if self.is_admin else ROLE_PARTNER

    def has_role(self, *roles) -> bool:
        return self.get_role() in roles

    @property
    def is_main_admin(self) -> bool:
        return self.get_role() == ROLE_ADMIN

    @property
    def is_supervisor(self) -> bool:
        return self.get_role() == ROLE_SUPERVISOR

    @property
    def is_partner(self) -> bool:
        return self.get_role() == ROLE_PARTNER

    @property
    def is_staff(self) -> bool:
        """Админ или супервайзер — доступ в админку (разный объём)"""
        return self.get_role() in (ROLE_ADMIN, ROLE_SUPERVISOR)

    @property
    def role_label(self) -> str:
        return {
            ROLE_ADMIN: 'Главный администратор',
            ROLE_SUPERVISOR: 'Супервайзер',
            ROLE_PARTNER: 'Партнёр',
        }.get(self.get_role(), 'Пользователь')


class ClickEvent(Base):
    __tablename__ = 'click_events'

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey('companies.id'), nullable=False, index=True)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str] = mapped_column(String(255), nullable=True)
    clicked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    company: Mapped["Company"] = relationship("Company", back_populates="clicks")


class UserAction(Base):
    __tablename__ = 'user_actions'

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=True, index=True)
    user_agent: Mapped[str] = mapped_column(String(500), nullable=True)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action_detail: Mapped[str] = mapped_column(String(100), nullable=True)
    referral_slug: Mapped[str] = mapped_column(String(50), nullable=True, index=True)
    page_url: Mapped[str] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Bonus(Base):
    __tablename__ = 'bonuses'

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    icon: Mapped[str] = mapped_column(String(20), nullable=False, default='🎁')
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SiteSetting(Base):
    __tablename__ = 'site_settings'

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
