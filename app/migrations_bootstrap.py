# app/migrations_bootstrap.py
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

def run_bootstrap_migrations(engine: Engine) -> None:
    """
    最小限の“その場しのぎ”マイグレーション。
    - users に grade 列が無ければ追加（既存行は 'Staff' をセット）
    - Postgres なら (grade, name) の一意制約を追加（存在しなければ）
    - reports_p に contact_email が無ければ追加
    ※ SQLite では NOT NULL/制約の追加はテーブル再作成が必要なため、厳密性は緩めています
    """
    insp = inspect(engine)
    with engine.begin() as conn:
        # ---- users.grade ----
        ucols = {c["name"] for c in insp.get_columns("users")}
        if "grade" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN grade VARCHAR(20)"))
            conn.execute(text("UPDATE users SET grade = 'Staff' WHERE grade IS NULL"))
            try:
                if engine.url.get_backend_name().startswith("postgresql"):
                    conn.execute(text("ALTER TABLE users ALTER COLUMN grade SET NOT NULL"))
            except Exception:
                # SQLite等は無視
                pass

        # ---- users unique (grade, name) for Postgres only ----
        try:
            if engine.url.get_backend_name().startswith("postgresql"):
                uqs = {uq["name"] for uq in insp.get_unique_constraints("users")}
                if "uq_users_grade_name" not in uqs:
                    conn.execute(text("ALTER TABLE users ADD CONSTRAINT uq_users_grade_name UNIQUE (grade, name)"))
        except Exception:
            pass

        # ---- reports_p.contact_email ----
        if insp.has_table("reports_p"):
            rpcols = {c["name"] for c in insp.get_columns("reports_p")}
            if "contact_email" not in rpcols:
                conn.execute(text("ALTER TABLE reports_p ADD COLUMN contact_email VARCHAR(320)"))
                conn.execute(text("UPDATE reports_p SET contact_email = '' WHERE contact_email IS NULL"))
