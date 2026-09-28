"""Alembic environment.

* The database URL comes from application settings (ERP_DATABASE_URL, default database ERP_LOGISTICS).
* Online mode creates the target MySQL database (utf8mb4) if it does not exist yet, so a fresh server needs only
  `alembic upgrade head` to build every table.
* Offline mode (`alembic upgrade head --sql`) emits plain SQL — see migrations/sql/ for the generated script.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, engine_from_config, pool, text
from sqlalchemy.engine import URL, make_url

from app.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
DB_URL = get_settings().database_url
config.set_main_option("sqlalchemy.url", DB_URL.replace("%", "%%"))
target_metadata = Base.metadata


def ensure_database(url: str) -> None:
    """CREATE DATABASE IF NOT EXISTS <name> CHARACTER SET utf8mb4 (MySQL/MariaDB only)."""
    u = make_url(url)
    if not u.get_backend_name().startswith("mysql") or not u.database:
        return
    name = u.database.replace("`", "")
    server_url = URL.create(u.drivername, username=u.username, password=u.password, host=u.host, port=u.port,
                            query=u.query)  # same server, no database selected
    server = create_engine(server_url, poolclass=pool.NullPool)
    with server.connect() as conn:
        conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{name}` "
                          "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
    server.dispose()


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, compare_type=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    ensure_database(DB_URL)
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.",
                                     poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
