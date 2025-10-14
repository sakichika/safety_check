from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
from pathlib import Path
from fastapi.templating import Jinja2Templates   # ← これが必要

from app.database import get_db
from app.models import User, Incident, Roster, Report, ReportHistory
from app.schemas import ReportIn, ReportOut

# テンプレートの絶対パス（uvicornのカレントに依存しない）
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
router = APIRouter(prefix="", tags=["public"])


@router.get("/f/{incident_code}", response_class=HTMLResponse)
def public_form(incident_code: str, request: Request, db: Session = Depends(get_db)):
    inc = db.query(Incident).filter(Incident.code == incident_code).one_or_none()
    if not inc or inc.status != 'open':
        raise HTTPException(status_code=404, detail="Incident not found or closed")
    return templates.TemplateResponse("public_form.html", {"request": request, "incident": inc})


@router.post("/public/report/{incident_code}")
def submit_report(
    incident_code: str,
    email: str = Form(default=None),
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
    inc = db.query(Incident).filter(Incident.code == incident_code).one_or_none()
    if not inc or inc.status != 'open':
        raise HTTPException(status_code=404, detail="Incident not found or closed")

    if not email:
        raise HTTPException(status_code=400, detail="Email required for identification")

    user = db.query(User).filter(User.email == email).one_or_none()
    if not user or not user.roster or user.roster.is_active is False:
        raise HTTPException(status_code=400, detail="Email not in active roster")


    # upsert latest report
    rep = db.query(Report).filter(Report.incident_id == inc.id, Report.user_id == user.id).one_or_none()
    payload = dict(status=status, shelter_name=shelter_name, shelter_type=shelter_type,
        shelter_addr=shelter_addr, shelter_lat=shelter_lat, shelter_lng=shelter_lng,
        damage_level=damage_level, damage_notes=damage_notes)


    if rep:
    # history snapshot
        hist = ReportHistory(incident_id=inc.id, user_id=user.id, diff=f"updated_at={datetime.utcnow().isoformat()}")
        db.add(hist)
        for k, v in payload.items():
            setattr(rep, k, v)
    else:
        rep = Report(incident_id=inc.id, user_id=user.id, **payload)
        db.add(rep)
    db.commit()

    return RedirectResponse(url=f"/f/{incident_code}?ok=1", status_code=303)


@router.get("/public/me/{incident_code}", response_model=ReportOut)
def my_latest(incident_code: str, email: str, db: Session = Depends(get_db)):
    inc = db.query(Incident).filter(Incident.code == incident_code).one_or_none()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    user = db.query(User).filter(User.email == email).one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    rep = db.query(Report).filter(Report.incident_id == inc.id, Report.user_id == user.id).one_or_none()
    if not rep:
        raise HTTPException(status_code=404, detail="No report yet")
    return ReportOut(incident_id=rep.incident_id, user_id=rep.user_id, status=rep.status, updated_at=rep.updated_at)