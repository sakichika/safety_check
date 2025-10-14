# app/models_persistent.py
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, ForeignKey, Float, Integer
from datetime import datetime
from app.models import Base  # 既存の Base を共有
import uuid

def uuid_str() -> str:
    return str(uuid.uuid4())

class Period(Base):
    __tablename__ = "periods"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    seq: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class ReportP(Base):
    __tablename__ = "reports_p"  # 現在期間の最新レコード（period×userで一意）
    period_id: Mapped[str] = mapped_column(String(36), ForeignKey("periods.id", ondelete="CASCADE"), primary_key=True)
    user_id:   Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False)  # 'safe'|'evacuating'|'need_help'|'unknown'
    shelter_name: Mapped[str | None] = mapped_column(String(200))
    shelter_type: Mapped[str | None] = mapped_column(String(50))
    shelter_addr: Mapped[str | None] = mapped_column(String(300))
    shelter_lat: Mapped[float | None] = mapped_column(Float)
    shelter_lng: Mapped[float | None] = mapped_column(Float)
    damage_level: Mapped[str | None] = mapped_column(String(20))
    damage_notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class ReportHistoryP(Base):
    __tablename__ = "report_history_p"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    period_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    diff: Mapped[str | None] = mapped_column(Text)
