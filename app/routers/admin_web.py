# app/routers/admin_web.py
import os
from typing import Optional
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from pathlib import Path
import csv, io
from datetime import datetime

from app.database import get_db
from app.models import User, Roster
from app.models_persistent import Period, ReportP, ReportHistoryP

from starlette.responses import Response

router = APIRouter(prefix="", tags=["admin-web"])
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "changeme")

# --- helpers ---
def is_admin(request: Request) -> bool:
    return bool(request.session.get("is_admin"))

def require_admin(request: Request) -> Optional[RedirectResponse]:
    if not is_admin(request):
        next_url = request.url.path
        return RedirectResponse(url=f"/admin/login?next={next_url}", status_code=303)
    return None

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

def _normalize_grade(s: str) -> str:
    if not s: return ""
    x = s.strip().lower()
    m = {
        "staff":"Staff","doctor":"Doctor",
        "master":"Master","m":"Master",
        "bachelor":"Bachelor","bacholar":"Bachelor","bachelar":"Bachelor","b":"Bachelor",
        "researcher":"Researcher", "r":"Researcher"
    }
    return m.get(x, s.strip().title())

# --- auth pages ---
@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": request.query_params.get("e")})

@router.post("/admin/login")
async def admin_login(request: Request, token: str = Form(...), next: str = Form(default="/admin")):
    if token != ADMIN_TOKEN:
        return RedirectResponse(url="/admin/login?e=1", status_code=303)
    request.session["is_admin"] = True
    return RedirectResponse(url=next or "/admin", status_code=303)

@router.get("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)

# --- dashboard ---
@router.get("/admin", response_class=HTMLResponse)
async def admin_home(request: Request, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard:
        return guard
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
    counts = {r["status"]: int(r["n"]) for r in rows}
    return templates.TemplateResponse(
        "admin_home.html",
        {"request": request, "period": cur, "total": int(total), "counts": counts,
         "just_reset": request.query_params.get("reset") == "1"}
    )

@router.post("/admin/periods/reset")
async def admin_reset_period(request: Request, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard:
        return guard
    cur = get_or_create_current_period(db)
    cur.ended_at = datetime.utcnow()
    db.add(cur)
    db.flush()
    new = Period(seq=cur.seq + 1)
    db.add(new)
    db.commit()
    return RedirectResponse(url="/admin?reset=1", status_code=303)

# --- absentees ---
@router.get("/admin/absentees", response_class=HTMLResponse)
async def admin_absentees(request: Request, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard:
        return guard
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
    rows = [dict(r) for r in db.execute(sql, {"pid": cur.id}).mappings().all()]
    return templates.TemplateResponse("admin_absentees.html", {"request": request, "period": cur, "rows": rows})

# --- roster upload ---
@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request):
    guard = require_admin(request)
    if guard:
        return guard
    return templates.TemplateResponse("admin_users.html", {"request": request, "ok": request.query_params.get("ok")})

@router.post("/admin/users/upload")
async def admin_users_upload(
    request: Request,
    csvfile: UploadFile = File(...),
    replace: bool = Form(default=False),   # ← 置換モード
    db: Session = Depends(get_db),
):
    guard = require_admin(request)
    if guard:
        return guard

    content = csvfile.file.read().decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(content))

    # 置換モードなら、まず全Rosterを is_active=False に落とす
    if replace:
        db.query(Roster).update({Roster.is_active: False})

    seen_user_ids = set()
    for row in reader:
        email = (row.get('email') or '').strip()
        name  = (row.get('name')  or '').strip()
        if not email or not name:
            continue
        user = db.query(User).filter(User.email == email).one_or_none()
        if not user:
            user = User(email=email, name=name)
            db.add(user)
            db.flush()
        # upsert
        group_name = row.get('group_name') or None
        is_active = (str(row.get('is_active', 'true')).lower() in ('true','1','yes','y'))
        if not user.roster:
            user.roster = Roster(user_id=user.id, group_name=group_name, is_active=is_active)
        else:
            user.roster.group_name = group_name
            user.roster.is_active = is_active
        seen_user_ids.add(user.id)

    db.commit()
    return RedirectResponse(url="/admin/users?ok=1", status_code=303)

# ===== Reports list (HTML) =====
@router.get("/admin/reports", response_class=HTMLResponse)
async def admin_reports(request: Request, status: str | None = None, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard:
        return guard
    cur = get_or_create_current_period(db)

    # フィルタ（safe/evacuating/need_help/unknown のいずれか、空なら全件）
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

    return templates.TemplateResponse(
        "admin_reports.html",
        {"request": request, "period": cur, "rows": rows, "status": status}
    )

# ===== Report detail (HTML) =====
@router.get("/admin/reports/{user_id}", response_class=HTMLResponse)
async def admin_report_detail(user_id: str, request: Request, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard:
        return guard
    cur = get_or_create_current_period(db)
    sql = text("""
        SELECT u.id AS user_id, u.name, u.email, rro.group_name,
               rp.status, rp.updated_at,
               rp.shelter_type, rp.shelter_name, rp.shelter_addr,
               rp.shelter_lat, rp.shelter_lng,
               rp.damage_level, rp.damage_notes
        FROM reports_p rp
        JOIN users u        ON u.id = rp.user_id
        LEFT JOIN rosters rro ON rro.user_id = u.id
        WHERE rp.period_id = :pid AND rp.user_id = :uid
        LIMIT 1
    """)
    row = db.execute(sql, {"pid": cur.id, "uid": user_id}).mappings().first()
    if not row:
        # 未報告の場合は404相当で一覧へ戻す
        return RedirectResponse(url="/admin/reports", status_code=303)
    return templates.TemplateResponse("admin_report_detail.html", {"request": request, "period": cur, "r": dict(row)})

# ===== CSV export (HTML操作からDL) =====
@router.get("/admin/reports/export")
async def admin_reports_export(request: Request, status: str | None = None, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard:
        return guard
    cur = get_or_create_current_period(db)

    status_filter = ""
    params = {"pid": cur.id}
    if status:
        status_filter = " AND rp.status = :status "
        params["status"] = status

    sql = text(f"""
        SELECT u.name, u.email, COALESCE(rro.group_name,'') AS group_name,
               rp.status, rp.updated_at,
               COALESCE(rp.shelter_type,'') AS shelter_type,
               COALESCE(rp.shelter_name,'') AS shelter_name,
               COALESCE(rp.shelter_addr,'') AS shelter_addr,
               COALESCE(rp.damage_level,'') AS damage_level,
               COALESCE(rp.damage_notes,'') AS damage_notes
        FROM reports_p rp
        JOIN users u        ON u.id = rp.user_id
        LEFT JOIN rosters rro ON rro.user_id = u.id
        WHERE rp.period_id = :pid
        {status_filter}
        ORDER BY rp.updated_at DESC
    """)
    rows = [dict(r) for r in db.execute(sql, params).mappings().all()]

    # CSV生成
    import csv, io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        "name","email","group_name","status","updated_at",
        "shelter_type","shelter_name","shelter_addr",
        "damage_level","damage_notes"
    ])
    writer.writeheader()
    writer.writerows(rows)
    csv_bytes = buf.getvalue().encode("utf-8-sig")  # Excel対策でBOMつき

    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="reports_period_{cur.seq}.csv"'}
    )

@router.get("/admin/users/template.csv")
async def download_roster_template(request: Request):
    guard = require_admin(request)
    if guard:
        return guard
    rows = [
        ["grade","name","email","dept","phone","group_name","is_active"],
        ["Staff","Alice","alice@example.com","DeptA","090-0000-0000","Lab-A","true"],
        ["Doctor","Dr. Bob","bob@example.com","DeptB","090-0000-0001","Lab-B","true"],
        ["Master","Carol","", "DeptA","","Lab-A","true"],
        ["Bachelor","Dave","","DeptC","","Lab-C","false"],
        ["Researcher","Eve","eve@example.com","DeptR","","Lab-R","true"],
    ]
    import io, csv
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    data = buf.getvalue().encode("utf-8-sig")
    return Response(content=data, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="roster_template.csv"'})

@router.post("/admin/users/delete_by_email")
async def admin_users_delete_by_email(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    guard = require_admin(request)
    if guard:
        return guard
    user = db.query(User).filter(User.email == email).one_or_none()
    if user and user.roster:
        db.delete(user.roster)  # Rosterだけ削除
        db.commit()
        return RedirectResponse(url="/admin/users?ok=del1", status_code=303)
    return RedirectResponse(url="/admin/users?err=notfound", status_code=303)

@router.post("/admin/users/delete_csv")
async def admin_users_delete_csv(
    request: Request,
    csvfile: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    guard = require_admin(request)
    if guard:
        return guard

    content = csvfile.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    n = 0
    for row in reader:
        email = (row.get("email") or "").strip()
        if not email:
            continue
        user = db.query(User).filter(User.email == email).one_or_none()
        if user and user.roster:
            db.delete(user.roster)
            n += 1
    db.commit()
    return RedirectResponse(url=f"/admin/users?ok=del{n}", status_code=303)