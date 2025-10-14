from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Dict, DefaultDict
from collections import defaultdict
import csv, io


from app.database import get_db
from app.models import User, Incident, Roster, Report
from app.schemas import IncidentCreate, IncidentOut, Absentee, SummaryItem, SummaryOut, UserIn
from app.deps import require_admin


router = APIRouter(prefix="/admin", tags=["admin"])

@router.post("/incidents",response_model=IncidentOut)
def create_incident(payload: IncidentCreate, db: Session = Depends(get_db), _=Depends(require_admin)):
    inc = Incident(code=payload.code, title=payload.title, description=payload.description, kind=payload.kind)
    db.add(inc)
    db.commit()
    db.refresh(inc)
    return IncidentOut(id=inc.id, code=inc.code, title=inc.title, status=inc.status, started_at=inc.started_at)

@router.get("/incidents/{incident_id}/absentees", response_model=List[Absentee])
def absentees(incident_id: str, db: Session = Depends(get_db), _=Depends(require_admin)):
    sql = text(
        """
        SELECT u.id, u.name, u.email, rro.group_name
        FROM rosters rro
        JOIN users u ON u.id = rro.user_id
        LEFT JOIN reports rep
        ON rep.user_id = u.id AND rep.incident_id = :incident_id
        WHERE rro.is_active = TRUE
        AND rep.user_id IS NULL
        ORDER BY u.name
        """
    )
    rows = db.execute(sql, {"incident_id": incident_id}).mappings().all()
    return [Absentee(**row) for row in rows]

@router.get("/incidents/{incident_id}/summary", response_model=SummaryOut)
def summary(incident_id: str, db: Session = Depends(get_db), _=Depends(require_admin)):
    # total roster
    total = db.query(Roster).filter(Roster.is_active == True).count()


    # status counts including no_report via left join
    sql = text(
        """
        WITH roster AS (
        SELECT user_id, group_name FROM rosters WHERE is_active = TRUE
        )
        SELECT COALESCE(rep.status, 'no_report') AS status, COUNT(*) AS n
        FROM roster r
        LEFT JOIN reports rep ON rep.user_id = r.user_id AND rep.incident_id = :incident_id
        GROUP BY COALESCE(rep.status, 'no_report')
        ORDER BY status
        """
    )
    counts = [dict(row) for row in db.execute(sql, {"incident_id": incident_id}).mappings().all()]


    # by group
    sql2 = text(
        """
        WITH base AS (
        SELECT rro.group_name, COALESCE(rep.status, 'no_report') AS status
        FROM rosters rro
        LEFT JOIN reports rep ON rep.user_id = rro.user_id AND rep.incident_id = :incident_id
        WHERE rro.is_active = TRUE
        )
        SELECT group_name, status, COUNT(*) AS n
        FROM base
        GROUP BY group_name, status
        ORDER BY group_name, status
        """
    )
    by_group_rows = [dict(row) for row in db.execute(sql2, {"incident_id": incident_id}).mappings().all()]
    grouped: DefaultDict[str, List[SummaryItem]] = defaultdict(list)
    for r in by_group_rows:
        grouped[r["group_name"] or "-"] .append(SummaryItem(status=r["status"], n=int(r["n"])) )


    return SummaryOut(
        total_roster=int(total),
        counts=[SummaryItem(status=c["status"], n=int(c["n"])) for c in counts],
        by_group=dict(grouped)
    )

@router.post("/users/import")
def import_users(csvfile: UploadFile = File(...), db: Session = Depends(get_db), _=Depends(require_admin)):
    content = csvfile.file.read().decode('utf-8')
    reader = csv.DictReader(io.StringIO(content))
    upserted = 0
    for row in reader:
        email = row.get('email', '').strip()
        name = row.get('name', '').strip()
        if not email or not name:
            continue
        user = db.query(User).filter(User.email == email).one_or_none()
        if not user:
            user = User(email=email, name=name)
            db.add(user)
            db.flush() # to get id
        # update optional fields
        user.dept = row.get('dept') or user.dept
        user.phone = row.get('phone') or user.phone
        # roster
        group_name = row.get('group_name') or None
        is_active = (row.get('is_active', 'true').lower() in ('true', '1', 'yes', 'y'))
        if not user.roster:
            user.roster = Roster(user_id=user.id, group_name=group_name, is_active=is_active)
        else:
            user.roster.group_name = group_name
            user.roster.is_active = is_active
        upserted += 1
    db.commit()
    return {"upserted": upserted}