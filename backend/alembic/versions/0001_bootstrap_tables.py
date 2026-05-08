"""Bootstrap ORM tables (Postgres-compatible). Prefer `alembic revision --autogenerate` once schema stabilizes."""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    from ai_interview_analysis.db.base import Base
    import ai_interview_analysis.db.models  # noqa: F401  # noqa: PLC0415

    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    from ai_interview_analysis.db.base import Base

    Base.metadata.drop_all(bind=bind)
