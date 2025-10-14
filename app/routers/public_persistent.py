# app/routers/public_persistent.py
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import select
from typing import Optional
from datetime import datetime
from pathlib import Path

from app.database import get_db
from app.models import User, Roster
from app.models_persistent import Period, ReportP, ReportHistoryP

router = APIRouter(prefix="", tags=["public-persistent"])
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

def _normalize_grade(s: str) -> str:
    s = (s or "").strip().lower()
    m = {"staff":"Staff","doctor":"Doctor","master":"Master","m":"Master",
         "bachelor":"Bachelor","bacholar":"Bachelor","bachelar":"Bachelor","b":"Bachelor",
         "researcher":"Researcher", "r":"Researcher"}
    return m.get(s, (s or "").title())

@router.get("/public/roster")
def public_roster(db: Session = Depends(get_db)):
    # 現在アクティブな名簿（属性→氏名リスト）
    rows = db.query(User.grade, User.name)\
             .join(Roster, Roster.user_id == User.id)\
             .filter(Roster.is_active == True)\
             .order_by(User.grade, User.name).all()
    grouped = {}
    for g, n in rows:
        grouped.setdefault(g, []).append(n)
    return grouped

@router.get("/f", response_class=HTMLResponse)
def public_form(request: Request, db: Session = Depends(get_db)):
    cur = db.query(Period).filter(Period.ended_at.is_(None)).one_or_none()
    return templates.TemplateResponse("public_form_persistent.html", {"request": request, "period": cur})

@router.post("/public/report")
def submit_report(
    grade: str = Form(...),          # ← 属性を受け取る
    name: str  = Form(...),          # ← 氏名を受け取る
    email: str = Form(...),          # ← 連絡用メール（必須だが識別には使わない）
    status: str = Form(...),
    shelter_name: Optional[str] = Form(default=None),
    shelter_type: Optional[str] = Form(default=None),
    shelter_addr: Optional[str] = Form(default=None),
    shelter_lat: Optional[float] = Form(default=None),
    shelter_lng: Optional[float] = Form(default=None),
    damage_level: Optional[str] = Form(default=None),
    damage_notes: Optional[str] = Form(default=None),
    db: Session = Depends(get_db)
):
    cur = db.query(Period).filter(Period.ended_at.is_(None)).one_or_none()
    if not cur:
        raise HTTPException(status_code=503, detail="Reporting period is not open")

    g = _normalize_grade(grade)
    user = db.query(User).join(Roster, Roster.user_id == User.id)\
            .filter(User.grade == g, User.name == name, Roster.is_active == True)\
            .one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="Selected user not in active roster")

    rep = db.query(ReportP).filter(ReportP.period_id == cur.id, ReportP.user_id == user.id).one_or_none()
    payload = dict(
        contact_email=email,  # ← 連絡用メールとして保存
        status=status, shelter_name=shelter_name, shelter_type=shelter_type,
        shelter_addr=shelter_addr, shelter_lat=shelter_lat, shelter_lng=shelter_lng,
        damage_level=damage_level, damage_notes=damage_notes
    )

    if rep:
        hist = ReportHistoryP(period_id=cur.id, user_id=user.id, diff=f"updated_at={datetime.utcnow().isoformat()}")
        db.add(hist)
        for k, v in payload.items():
            setattr(rep, k, v)
    else:
        rep = ReportP(period_id=cur.id, user_id=user.id, **payload)
        db.add(rep)
    db.commit()
    return RedirectResponse(url="/f?ok=1", status_code=303)

@router.get("/public/me")
def my_latest(grade: str, name: str, db: Session = Depends(get_db)):
    cur = db.query(Period).filter(Period.ended_at.is_(None)).one_or_none()
    if not cur:
        raise HTTPException(status_code=404, detail="No open period")
    g = _normalize_grade(grade)
    user = db.query(User).filter(User.grade == g, User.name == name).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    rep = db.query(ReportP).filter(ReportP.period_id == cur.id, ReportP.user_id == user.id).one_or_none()
    if not rep:
        raise HTTPException(status_code=404, detail="No report yet")
    return {"period_id": rep.period_id, "user_id": rep.user_id, "status": rep.status, "updated_at": rep.updated_at, "contact_email": rep.contact_email}
