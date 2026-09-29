"""ORM models: users, daily usage, saved routes."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    plan: Mapped[str] = mapped_column(String(32), default="free", nullable=False)  # free | pro
    stripe_customer_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    paypal_subscription_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    forecasts_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    usage_rows: Mapped[list["UsageDaily"]] = relationship(back_populates="user")
    saved_routes: Mapped[list["SavedRoute"]] = relationship(back_populates="user")


class UsageDaily(Base):
    __tablename__ = "usage_daily"
    __table_args__ = (UniqueConstraint("subject_key", "day", name="uq_usage_subject_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    day: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD UTC
    routes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chats: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user: Mapped[User | None] = relationship(back_populates="usage_rows")


class SavedRoute(Base):
    __tablename__ = "saved_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    start_lat: Mapped[str] = mapped_column(String(32), nullable=False)
    start_lon: Mapped[str] = mapped_column(String(32), nullable=False)
    end_lat: Mapped[str] = mapped_column(String(32), nullable=False)
    end_lon: Mapped[str] = mapped_column(String(32), nullable=False)
    start_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    end_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="saved_routes")
