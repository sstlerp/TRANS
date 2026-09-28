"""Import every model module so `Base.metadata` is complete (Alembic, create_all)."""
from app.models.base import Base  # noqa: F401
from app.models.org import *  # noqa: F401,F403
from app.models.fleet import *  # noqa: F401,F403
from app.models.compliance import *  # noqa: F401,F403
from app.models.finance import *  # noqa: F401,F403
from app.models.imports import *  # noqa: F401,F403
from app.models.operations import *  # noqa: F401,F403
from app.models.tyres import *  # noqa: F401,F403
from app.models.system import *  # noqa: F401,F403
