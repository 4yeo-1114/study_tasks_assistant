from pathlib import Path

from alembic import command
from alembic.config import Config


def upgrade_database(url: str) -> None:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
