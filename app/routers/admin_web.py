# app/routers/admin_web.py
import os
import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.database import get_db
from app.models import Roster, User
from app.models_persistent import Period

router = APIRouter(prefix="", tags=["admin-web"])

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "changeme")


# ===== Helpers =====

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
    """Normalize grade/affiliation labels used as part of user identity."""
    x = (s or "").strip().lower()
    mapping = {
        "staff": "Staff",
        "doctor": "Doctor",
        "dr": "Doctor",
        "phd": "Doctor",
        "d": "Doctor",
        "master": "Master",
        "m": "Master",
        "bachelor": "Bachelor",
        "bacholar": "Bachelor",
        "bachelar": "Bachelor",
        "undergraduate": "Bachelor",
        "b": "Bachelor",
        "researcher": "Researcher",
        "r": "Researcher",
    }
    return mapping.get(x, (s or "").strip().title())


def _is_truthy(v: object, default: bool = False) -> bool:
    if v is None or v == "":
        return default
    return str(v).strip().lower() in ("true", "1", "yes", "y", "on", "active", "有効", "アクティブ")


def _redirect_users(ok: str | None = None, err: str | None = None) -> RedirectResponse:
    if err:
        return RedirectResponse(url=f"/admin/users?err={err}", status_code=303)
    if ok:
        return RedirectResponse(url=f"/admin/users?ok={ok}", status_code=303)
    return RedirectResponse(url="/admin/users", status_code=303)


def _query_roster_rows(db: Session):
    sql = text("""
        SELECT
            u.id,
            u.grade,
            u.name,
            u.email,
            u.dept,
            u.phone,
            COALESCE(r.group_name, '') AS group_name,
            COALESCE(r.is_active, FALSE) AS is_active,
            CASE WHEN r.id IS NULL THEN FALSE ELSE TRUE END AS in_roster
        FROM users u
        LEFT JOIN rosters r ON r.user_id = u.id
        ORDER BY
            CASE u.grade
                WHEN 'Staff' THEN 1
                WHEN 'Doctor' THEN 2
                WHEN 'Researcher' THEN 3
                WHEN 'Master' THEN 4
                WHEN 'Bachelor' THEN 5
                ELSE 99
            END,
            u.grade,
            u.name
    """)
    return [dict(r) for r in db.execute(sql).mappings().all()]


# ===== Auth pages =====

@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse(
        "admin_login.html",
        {"request": request, "error": request.query_params.get("e")},
    )


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


# ===== Dashboard =====

@router.get("/admin", response_class=HTMLResponse)
async def admin_home(request: Request, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard:
        return guard

    cur = get_or_create_current_period(db)
    total = db.query(Roster).filter(Roster.is_active == True).count()

    sql = text("""
        WITH roster AS (SELECT user_id FROM rosters WHERE is_active = TRUE)
        SELECT COALESCE(rp.status, 'no_report') AS status, COUNT(*) AS n
        FROM roster r
        LEFT JOIN reports_p rp
          ON rp.user_id = r.user_id AND rp.period_id = :pid
        GROUP BY COALESCE(rp.status, 'no_report')
        ORDER BY status
    """)
    rows = db.execute(sql, {"pid": cur.id}).mappings().all()
    counts = {r["status"]: int(r["n"]) for r in rows}

    return templates.TemplateResponse(
        "admin_home.html",
        {
            "request": request,
            "period": cur,
            "total": int(total),
            "counts": counts,
            "just_reset": request.query_params.get("reset") == "1",
        },
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


@router.get("/admin/periods/reset")
async def admin_reset_period_get_redirect():
    return RedirectResponse(url="/admin", status_code=303)


# ===== Absentees page =====

@router.get("/admin/absentees", response_class=HTMLResponse)
async def admin_absentees(request: Request, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard:
        return guard

    cur = get_or_create_current_period(db)
    sql = text("""
        SELECT
            u.id,
            u.grade,
            u.name,
            u.email,
            u.dept,
            u.phone,
            r.group_name,
            r.is_active
        FROM rosters r
        JOIN users u ON u.id = r.user_id
        LEFT JOIN reports_p rp
          ON rp.user_id = u.id AND rp.period_id = :pid
        WHERE r.is_active = TRUE
          AND rp.user_id IS NULL
        ORDER BY
            CASE u.grade
                WHEN 'Staff' THEN 1
                WHEN 'Doctor' THEN 2
                WHEN 'Researcher' THEN 3
                WHEN 'Master' THEN 4
                WHEN 'Bachelor' THEN 5
                ELSE 99
            END,
            u.grade,
            u.name
    """)
    rows = [dict(r) for r in db.execute(sql, {"pid": cur.id}).mappings().all()]
    return templates.TemplateResponse(
        "admin_absentees.html",
        {
            "request": request,
            "period": cur,
            "rows": rows,
            "ok": request.query_params.get("ok"),
            "err": request.query_params.get("err"),
        },
    )


# ===== Users / Roster management =====

@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard:
        return guard

    rows = _query_roster_rows(db)
    return templates.TemplateResponse(
        "admin_users.html",
        {
            "request": request,
            "rows": rows,
            "ok": request.query_params.get("ok"),
            "err": request.query_params.get("err"),
        },
    )


@router.get("/admin/users/create_one")
async def admin_users_create_one_get():
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/admin/users/create_one")
async def admin_users_create_one(
    request: Request,
    grade: str = Form(...),
    name: str = Form(...),
    email: str | None = Form(default=None),
    dept: str | None = Form(default=None),
    phone: str | None = Form(default=None),
    group_name: str | None = Form(default=None),
    is_active: str | None = Form(default="true"),
    db: Session = Depends(get_db),
):
    guard = require_admin(request)
    if guard:
        return guard

    grade_norm = _normalize_grade(grade)
    name = (name or "").strip()
    email = (email or "").strip() or None

    if not grade_norm or not name:
        return _redirect_users(err="grade_name_required")

    # 本人一意キーは grade + name
    user = db.query(User).filter(User.grade == grade_norm, User.name == name).one_or_none()
    if not user:
        user = User(grade=grade_norm, name=name, email=email, dept=(dept or None), phone=(phone or None))
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return _redirect_users(err="duplicate_or_constraint")
    else:
        # 既存なら更新として扱う
        user.email = email
        user.dept = dept or None
        user.phone = phone or None

    if not user.roster:
        user.roster = Roster(user_id=user.id)

    user.roster.group_name = group_name or None
    user.roster.is_active = _is_truthy(is_active, default=True)

    db.commit()
    return _redirect_users(ok="created")


@router.post("/admin/users/update_one")
async def admin_users_update_one(
    request: Request,
    user_id: str = Form(...),
    grade: str = Form(...),
    name: str = Form(...),
    email: str | None = Form(default=None),
    dept: str | None = Form(default=None),
    phone: str | None = Form(default=None),
    group_name: str | None = Form(default=None),
    is_active: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    guard = require_admin(request)
    if guard:
        return guard

    user = db.query(User).filter(User.id == user_id).one_or_none()
    if not user:
        return _redirect_users(err="nouser")

    grade_norm = _normalize_grade(grade)
    name = (name or "").strip()
    email = (email or "").strip() or None

    if not grade_norm or not name:
        return _redirect_users(err="grade_name_required")

    # grade+name の重複チェック
    other = db.query(User).filter(
        User.grade == grade_norm,
        User.name == name,
        User.id != user_id,
    ).one_or_none()
    if other:
        return _redirect_users(err="duplicate_grade_name")

    user.grade = grade_norm
    user.name = name
    user.email = email
    user.dept = dept or None
    user.phone = phone or None

    if not user.roster:
        user.roster = Roster(user_id=user.id)

    user.roster.group_name = group_name or None
    user.roster.is_active = _is_truthy(is_active, default=False)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _redirect_users(err="duplicate_or_constraint")

    return _redirect_users(ok="updated")


@router.post("/admin/users/{user_id}/toggle_active")
async def admin_users_toggle_active(request: Request, user_id: str, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard:
        return guard

    user = db.query(User).filter(User.id == user_id).one_or_none()
    if not user:
        return _redirect_users(err="nouser")

    if not user.roster:
        user.roster = Roster(user_id=user.id, is_active=True)
    else:
        user.roster.is_active = not bool(user.roster.is_active)

    db.commit()
    return _redirect_users(ok="toggle")


@router.post("/admin/users/{user_id}/delete")
async def admin_users_delete(
    request: Request,
    user_id: str,
    mode: str = Form(default="roster"),  # "roster" or "user"
    db: Session = Depends(get_db),
):
    guard = require_admin(request)
    if guard:
        return guard

    user = db.query(User).filter(User.id == user_id).one_or_none()
    if not user:
        return _redirect_users(err="nouser")

    if mode == "user":
        db.delete(user)  # reports_p 等は FK CASCADE に依存
    else:
        # 履歴や報告を残したい通常運用では roster だけ削除
        if user.roster:
            db.delete(user.roster)

    db.commit()
    return _redirect_users(ok="deleted")


@router.post("/admin/users/upload")
async def admin_users_upload(
    request: Request,
    csvfile: UploadFile = File(...),
    replace: bool = Form(default=False),
    db: Session = Depends(get_db),
):
    guard = require_admin(request)
    if guard:
        return guard

    content = csvfile.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))

    if replace:
        # CSVに載っていない人は無効化する置換モード
        db.query(Roster).update({Roster.is_active: False})

    upserted = 0
    for row in reader:
        grade = _normalize_grade(row.get("grade") or "")
        name = (row.get("name") or "").strip()
        if not grade or not name:
            continue

        user = db.query(User).filter(User.grade == grade, User.name == name).one_or_none()
        if not user:
            user = User(grade=grade, name=name)
            db.add(user)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                return _redirect_users(err="duplicate_or_constraint")

        email = (row.get("email") or "").strip()
        user.email = email or None
        user.dept = (row.get("dept") or "").strip() or None
        user.phone = (row.get("phone") or "").strip() or None

        group_name = (row.get("group_name") or "").strip() or None
        is_active = _is_truthy(row.get("is_active"), default=True)

        if not user.roster:
            user.roster = Roster(user_id=user.id)
        user.roster.group_name = group_name
        user.roster.is_active = is_active

        upserted += 1

    db.commit()
    return _redirect_users(ok=f"uploaded_{upserted}")


@router.get("/admin/users/template.csv")
async def download_roster_template(request: Request):
    guard = require_admin(request)
    if guard:
        return guard

    rows = [
        ["grade", "name", "email", "dept", "phone", "group_name", "is_active"],
        ["Staff", "Alice", "alice@example.com", "DeptA", "090-0000-0000", "Lab-A", "true"],
        ["Doctor", "Dr. Bob", "bob@example.com", "DeptB", "090-0000-0001", "Lab-B", "true"],
        ["Master", "Carol", "", "DeptA", "", "Lab-A", "true"],
        ["Bachelor", "Dave", "", "DeptC", "", "Lab-C", "false"],
        ["Researcher", "Eve", "eve@example.com", "DeptR", "", "Lab-R", "true"],
    ]

    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    data = buf.getvalue().encode("utf-8-sig")

    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="roster_template.csv"'},
    )


@router.post("/admin/users/delete_csv")
async def admin_users_delete_csv(
    request: Request,
    csvfile: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """CSVで roster から除外。grade+name があればそれを優先、なければ email で検索。"""
    guard = require_admin(request)
    if guard:
        return guard

    content = csvfile.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    n = 0

    for row in reader:
        grade = _normalize_grade(row.get("grade") or "")
        name = (row.get("name") or "").strip()
        email = (row.get("email") or "").strip()

        q = db.query(User)
        if grade and name:
            user = q.filter(User.grade == grade, User.name == name).one_or_none()
        elif email:
            user = q.filter(User.email == email).one_or_none()
        else:
            continue

        if user and user.roster:
            db.delete(user.roster)
            n += 1

    db.commit()
    return _redirect_users(ok=f"delete_csv_{n}")


# ===== Reports list / CSV export =====

@router.get("/admin/reports", response_class=HTMLResponse)
async def admin_reports(request: Request, status: str | None = None, db: Session = Depends(get_db)):
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
        SELECT
            u.id AS user_id,
            u.grade,
            u.name,
            u.email,
            r.group_name,
            rp.contact_email,
            rp.status,
            rp.updated_at,
            rp.shelter_type,
            rp.shelter_name,
            rp.shelter_addr,
            rp.damage_level
        FROM reports_p rp
        JOIN users u ON u.id = rp.user_id
        LEFT JOIN rosters r ON r.user_id = u.id
        WHERE rp.period_id = :pid
        {status_filter}
        ORDER BY rp.updated_at DESC
    """)
    rows = [dict(r) for r in db.execute(sql, params).mappings().all()]

    return templates.TemplateResponse(
        "admin_reports.html",
        {"request": request, "period": cur, "rows": rows, "status": status},
    )


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
        SELECT
            u.grade,
            u.name,
            COALESCE(u.email, '') AS roster_email,
            COALESCE(r.group_name, '') AS group_name,
            COALESCE(rp.contact_email, '') AS contact_email,
            rp.status,
            rp.updated_at,
            COALESCE(rp.shelter_type, '') AS shelter_type,
            COALESCE(rp.shelter_name, '') AS shelter_name,
            COALESCE(rp.shelter_addr, '') AS shelter_addr,
            COALESCE(rp.damage_level, '') AS damage_level,
            COALESCE(rp.damage_notes, '') AS damage_notes
        FROM reports_p rp
        JOIN users u ON u.id = rp.user_id
        LEFT JOIN rosters r ON r.user_id = u.id
        WHERE rp.period_id = :pid
        {status_filter}
        ORDER BY rp.updated_at DESC
    """)
    rows = [dict(r) for r in db.execute(sql, params).mappings().all()]

    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "grade", "name", "roster_email", "group_name", "contact_email",
            "status", "updated_at", "shelter_type", "shelter_name",
            "shelter_addr", "damage_level", "damage_notes",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)
    data = buf.getvalue().encode("utf-8-sig")

    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="reports_period_{cur.seq}.csv"'},
    )


@router.get("/admin/reports/{user_id}", response_class=HTMLResponse)
async def admin_report_detail(user_id: str, request: Request, db: Session = Depends(get_db)):
    guard = require_admin(request)
    if guard:
        return guard

    cur = get_or_create_current_period(db)
    sql = text("""
        SELECT
            u.id AS user_id,
            u.grade,
            u.name,
            u.email,
            r.group_name,
            rp.contact_email,
            rp.status,
            rp.updated_at,
            rp.shelter_type,
            rp.shelter_name,
            rp.shelter_addr,
            rp.shelter_lat,
            rp.shelter_lng,
            rp.damage_level,
            rp.damage_notes
        FROM reports_p rp
        JOIN users u ON u.id = rp.user_id
        LEFT JOIN rosters r ON r.user_id = u.id
        WHERE rp.period_id = :pid AND rp.user_id = :uid
        LIMIT 1
    """)
    row = db.execute(sql, {"pid": cur.id, "uid": user_id}).mappings().first()
    if not row:
        return RedirectResponse(url="/admin/reports", status_code=303)

    return templates.TemplateResponse(
        "admin_report_detail.html",
        {"request": request, "period": cur, "r": dict(row)},
    )
