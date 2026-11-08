"""journal append-only trigger (перенос из A2A Маркет, см. NOTICE.md)

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION journal_protect() RETURNS trigger AS $$
        BEGIN
            -- Удалять можно только при сбросе демо-сценария, с явно включённым флагом
            IF TG_OP IN ('DELETE', 'TRUNCATE')
               AND current_setting('app.journal_reset', true) = 'on' THEN
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NULL;
            END IF;
            RAISE EXCEPTION 'Журнал только для добавления: операция % запрещена', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER journal_protect_row BEFORE UPDATE OR DELETE ON journal
        FOR EACH ROW EXECUTE FUNCTION journal_protect();
    """)
    op.execute("""
        CREATE TRIGGER journal_protect_truncate BEFORE TRUNCATE ON journal
        FOR EACH STATEMENT EXECUTE FUNCTION journal_protect();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS journal_protect_truncate ON journal")
    op.execute("DROP TRIGGER IF EXISTS journal_protect_row ON journal")
    op.execute("DROP FUNCTION IF EXISTS journal_protect()")
