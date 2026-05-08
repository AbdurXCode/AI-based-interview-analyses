import pathlib
import sys

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Project root → src on sys.path
_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ai_interview_analysis.core.settings import clear_settings_cache, get_settings
from ai_interview_analysis.db.base import Base
from ai_interview_analysis.db import models as _models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    clear_settings_cache()
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        url=_url(),
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
