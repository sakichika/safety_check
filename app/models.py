from sqlalchemy.orm import declarative_base, relationship, Mapped, mapped_column
from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, Float, UniqueConstraint
import uuid
from datetime import datetime

Base = declarative_base()

def uuid_str() -> str:
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)

    email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    grade: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    dept: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    role: Mapped[str] = mapped_column(String(20), default='member', nullable=False)

    roster = relationship("Roster", back_populates="user", uselist=False)

    __table_args__ = (
        UniqueConstraint('grade', 'name', name='uq_users_grade_name'),
    )


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(10), default='live') # 'live' | 'drill'
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default='open') # 'open' | 'closed'


class Roster(Base):
    __tablename__ = "rosters"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    group_name: Mapped[str | None] = mapped_column(String(200), nullable=True)


    user = relationship("User", back_populates="roster")


    __table_args__ = (UniqueConstraint('user_id', name='uq_rosters_user'),)


class Report(Base):
    __tablename__ = "reports"
    incident_id: Mapped[str] = mapped_column(String(36), ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


    status: Mapped[str] = mapped_column(String(20), nullable=False) # 'safe' | 'evacuating' | 'need_help' | 'unknown'
    shelter_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    shelter_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    shelter_addr: Mapped[str | None] = mapped_column(String(300), nullable=True)
    shelter_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    shelter_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    damage_level: Mapped[str | None] = mapped_column(String(20), nullable=True) # 'none'|'minor'|'moderate'|'severe'
    damage_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ReportHistory(Base):
    __tablename__ = "report_history"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    incident_id: Mapped[str] = mapped_column(String(36), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    diff: Mapped[str | None] = mapped_column(Text, nullable=True) # store JSON text


class Token(Base):
    __tablename__ = "tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    incident_id: Mapped[str] = mapped_column(String(36), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)