import asyncio
import importlib.util
import inspect
import sys

# added by me
from collections.abc import Iterable
from logging.config import fileConfig

# NOTE: noqa: F401 for don't clear unused imports, when make clean
import alembic_postgresql_enum  # noqa: F401
from alembic import context
from alembic.environment import MigrationContext
from alembic.operations import MigrationScript
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from core.config import settings
from core.db import Base

ROOT_PATH = settings.ROOT_PATH
MODULES_PATH = ROOT_PATH / "modules"


def load_all_models():
    """
    Load all SQLAlchemy model classes from models.py files in app folders within MODULES_PATH.

    Returns:
        list: A list of all model classes that inherit from Base.
    """
    all_models = []
    # Get all directories in MODULES_PATH
    app_dirs = [d for d in MODULES_PATH.iterdir() if d.is_dir()]

    for app_dir in app_dirs:
        models_path = app_dir / "models.py"
        if models_path.exists():
            module_name = f"modules.{app_dir.name}.models"

            try:
                models_module = sys.modules[module_name]
            except KeyError:
                models_module = importlib.import_module(module_name)

            # Find all classes in the module that are subclasses of Base
            for name, obj in inspect.getmembers(models_module):
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, Base)
                    and obj.__module__ == models_module.__name__
                ):
                    all_models.append(obj)

    return all_models


# Call function to load models dynamically
load_all_models()


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

config.set_main_option("sqlalchemy.url", settings.database.DATABASE_URI)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Custom Config
        include_schemas=True,
        version_table="alembic_version",
        version_table_schema=target_metadata.schema,
    )

    context.execute(
        f'CREATE SCHEMA IF NOT EXISTS "{settings.database.SCHEMA_NAME}"'
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    with connection.begin():
        connection.execute(
            text(
                f'CREATE SCHEMA IF NOT EXISTS "{settings.database.SCHEMA_NAME}"'
            )
        )

    # this callback is used to prevent Alembic from generating empty migrations
    def process_revision_directives(
        context: MigrationContext,
        revision: str | Iterable[str | None] | Iterable[str],
        directives: list[MigrationScript],
    ):
        assert config.cmd_opts is not None
        if getattr(config.cmd_opts, "autogenerate", False):
            script = directives[0]
            assert script.upgrade_ops is not None
            if script.upgrade_ops.is_empty():
                directives[:] = []

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        process_revision_directives=process_revision_directives,
        # Custom Config
        include_schemas=True,
        version_table="alembic_version",
        version_table_schema=target_metadata.schema,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
