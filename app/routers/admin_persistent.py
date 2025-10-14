# app/routers/admin_persistent.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from typing import List
from datetime import datetime
from pydantic import BaseModel

from app.database import get_db
from app.models import Roster
from app.models_persistent import Period

from app.deps import require_admin_header_or_session as require_admin

class PeriodOut(BaseModel):
    id: str
    seq: int
    started_at: datetime
    ended_at: datetime | None

class SummaryItem(BaseModel):
    status: str
    n: int

class SummaryOut(BaseModel):
    total_roster: int
    counts: List[SummaryItem]

class Absentee(BaseModel):
    id: str
    name: str
    email: str
    group_name: str | None

class ReportRow(BaseModel):
    user_id: str
    name: str
    email: str
    group_name: str | None
    status: str
    updated_at: datetime
    shelter_type: str | None
    shelter_name: str | None
    shelter_addr: str | None
    damage_level: str | None

router = APIRouter(prefix="/admin/api", tags=["admin-api"])

def get_or_create_current_period(db: Session) -> Period:
    cur = db.query(Period).filter(Period.ended_at.is_(None)).one_or_none()
    if cur:
        return cur
    max_seq = db.query(func.max(Period.seq)).scalar() or 0
    cur = Period(seq=int(max_seq) + 1)
    db.add(cur)
    db.commit()
    db.refresh(cur)
    return cur

@router.get("/periods/current", response_model=PeriodOut)
def current_period(db: Session = Depends(get_db), _=Depends(require_admin)):
    cur = get_or_create_current_period(db)
    return PeriodOut(id=cur.id, seq=cur.seq, started_at=cur.started_at, ended_at=cur.ended_at)

@router.post("/periods/reset", response_model=PeriodOut)
def reset_period(db: Session = Depends(get_db), _=Depends(require_admin)):
    cur = get_or_create_current_period(db)
    cur.ended_at = datetime.utcnow()
    db.add(cur)
    db.flush()
    new = Period(seq=cur.seq + 1)
    db.add(new)
    db.commit()
    db.refresh(new)
    return PeriodOut(id=new.id, seq=new.seq, started_at=new.started_at, ended_at=new.ended_at)

@router.get("/summary", response_model=SummaryOut)
def summary_current(db: Session = Depends(get_db), _=Depends(require_admin)):
    cur = get_or_create_current_period(db)
    total = db.query(Roster).filter(Roster.is_active == True).count()
    sql = text("""
        WITH roster AS ( SELECT user_id FROM rosters WHERE is_active = TRUE )
        SELECT COALESCE(rp.status, 'no_report') AS status, COUNT(*) AS n
        FROM roster r
        LEFT JOIN reports_p rp ON rp.user_id = r.user_id AND rp.period_id = :pid
        GROUP BY COALESCE(rp.status, 'no_report')
        ORDER BY status
    """)
    rows = db.execute(sql, {"pid": cur.id}).mappings().all()
    counts = [SummaryItem(status=r["status"], n=int(r["n"])) for r in rows]
    return SummaryOut(total_roster=int(total), counts=counts)

@router.get("/absentees", response_model=List[Absentee])
def absentees_current(db: Session = Depends(get_db), _=Depends(require_admin)):
    cur = get_or_create_current_period(db)
    sql = text("""
        SELECT u.id, u.name, u.email, rro.group_name
        FROM rosters rro
        JOIN users u ON u.id = rro.user_id
        LEFT JOIN reports_p rp
          ON rp.user_id = u.id AND rp.period_id = :pid
        WHERE rro.is_active = TRUE
          AND rp.user_id IS NULL
        ORDER BY u.name
    """)
    rows = db.execute(sql, {"pid": cur.id}).mappings().all()
    return [Absentee(**row) for row in rows]

@router.get("/reports", response_model=List[ReportRow])
def list_reports(status: str | None = None, db: Session = Depends(get_db), _=Depends(require_admin)):
    cur = get_or_create_current_period(db)
    status_filter = ""
    params = {"pid": cur.id}
    if status:
        status_filter = " AND rp.status = :status "
        params["status"] = status

    sql = text(f"""
        SELECT u.id AS user_id, u.name, u.email, rro.group_name,
               rp.status, rp.updated_at,
               rp.shelter_type, rp.shelter_name, rp.shelter_addr,
               rp.damage_level
        FROM reports_p rp
        JOIN users u        ON u.id = rp.user_id
        LEFT JOIN rosters rro ON rro.user_id = u.id
        WHERE rp.period_id = :pid
        {status_filter}
        ORDER BY rp.updated_at DESC
    """)
    rows = [dict(r) for r in db.execute(sql, params).mappings().all()]
    return rows

# 詳細（user_id指定）
@router.get("/reports/{user_id}", response_model=ReportRow | None)
def get_report(user_id: str, db: Session = Depends(get_db), _=Depends(require_admin)):
    cur = get_or_create_current_period(db)
    sql = text("""
        SELECT u.id AS user_id, u.name, u.email, rro.group_name,
               rp.status, rp.updated_at,
               rp.shelter_type, rp.shelter_name, rp.shelter_addr,
               rp.damage_level
        FROM reports_p rp
        JOIN users u        ON u.id = rp.user_id
        LEFT JOIN rosters rro ON rro.user_id = u.id
        WHERE rp.period_id = :pid AND rp.user_id = :uid
        LIMIT 1
    """)
    row = db.execute(sql, {"pid": cur.id, "uid": user_id}).mappings().first()
    return dict(row) if row else None