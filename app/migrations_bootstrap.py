# app/migrations_bootstrap.py
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

def run_bootstrap_migrations(engine: Engine) -> None:
    """
    仕様変更に伴う最小限のその場マイグレーション（Postgres向け）。
    - users に grade 列が無ければ追加
    - users.email の NOT NULL を解除
    - users.email のユニーク制約があれば削除
    - (grade, name) の一意制約を追加
    - reports_p.contact_email が無ければ追加（使っていれば）
    """
    insp = inspect(engine)

    with engine.begin() as conn:
        # users テーブルがない環境（完全新規）は何もしなくてよい
        if not insp.has_table("users"):
            return

        # --- users: grade 列を追加 ---
        ucols = {c["name"]: c for c in insp.get_columns("users")}
        if "grade" not in ucols:
            conn.execute(text("ALTER TABLE users ADD COLUMN grade VARCHAR(20)"))
            conn.execute(text("UPDATE users SET grade = 'Staff' WHERE grade IS NULL"))
            # Postgres なら NOT NULL 付与
            if engine.url.get_backend_name().startswith("postgresql"):
                conn.execute(text("ALTER TABLE users ALTER COLUMN grade SET NOT NULL"))

        # --- users: email の NOT NULL を解除 ---
        if "email" in ucols and not ucols["email"].get("nullable", True):
            if engine.url.get_backend_name().startswith("postgresql"):
                conn.execute(text("ALTER TABLE users ALTER COLUMN email DROP NOT NULL"))
            # SQLite は列の NULL 変更が難しいためスキップ（必要なら local.db を削除して再生成）

        # --- users: email のユニーク制約を除去（共有メールや空メールを許容） ---
        try:
            if engine.url.get_backend_name().startswith("postgresql"):
                # 代表的な名前を両方試す（自動生成名 / 手動名）
                conn.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key"))
                conn.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS uq_users_email"))
        except Exception:
            pass

        # --- users: (grade, name) にユニーク制約 ---
        try:
            if engine.url.get_backend_name().startswith("postgresql"):
                uqs = {uq["name"] for uq in insp.get_unique_constraints("users")}
                if "uq_users_grade_name" not in uqs:
                    conn.execute(text("ALTER TABLE users ADD CONSTRAINT uq_users_grade_name UNIQUE (grade, name)"))
        except Exception:
            pass

        # --- reports_p: contact_email 列を追加（使っている場合のみ） ---
        if insp.has_table("reports_p"):
            rpcols = {c["name"] for c in insp.get_columns("reports_p")}
            if "contact_email" not in rpcols:
                conn.execute(text("ALTER TABLE reports_p ADD COLUMN contact_email VARCHAR(320)"))
                # 既存行は空文字に
                conn.execute(text("UPDATE reports_p SET contact_email = '' WHERE contact_email IS NULL"))
