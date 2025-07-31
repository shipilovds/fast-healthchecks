"""This module provides a health check class for FastAPI Async SQLAlchemy.

Classes:
    FastAPIAsyncSQLAlchemyHealthCheck: A class to perform health checks on a database using fastapi_async_sqlalchemy.

Usage:
    The FastAPIAsyncSQLAlchemyHealthCheck class can be used to perform health checks on a database by
    using the existing fastapi_async_sqlalchemy global session or creating a separate connection.

Example:
    # Using existing global db session (default)
    health_check = FastAPIAsyncSQLAlchemyHealthCheck()

    # Using separate connection with DSN
    health_check = FastAPIAsyncSQLAlchemyHealthCheck.from_dsn(
        "postgresql+asyncpg://username:password@localhost:5432/dbname"
    )

    result = await health_check()
    print(result.healthy)
"""

from traceback import format_exc
from typing import TYPE_CHECKING, Any, TypeAlias

from fast_healthchecks.checks._base import DEFAULT_HC_TIMEOUT, HealthCheck
from fast_healthchecks.compat import PYDANTIC_INSTALLED
from fast_healthchecks.models import HealthCheckResult

IMPORT_ERROR_MSG = "fastapi_async_sqlalchemy is not installed. Install it with `pip install fastapi-async-sqlalchemy`."
SQLALCHEMY_ERROR_MSG = "sqlalchemy[asyncio] is not installed. Install it with `pip install 'sqlalchemy[asyncio]'`."

try:
    from fastapi_async_sqlalchemy import db
except ImportError as exc:
    raise ImportError(IMPORT_ERROR_MSG) from exc

try:
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy import text
except ImportError as exc:
    raise ImportError(SQLALCHEMY_ERROR_MSG) from exc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

if PYDANTIC_INSTALLED:
    from pydantic import AnyUrl
else:  # pragma: no cover
    AnyUrl: TypeAlias = str  # type: ignore[no-redef]


class FastAPIAsyncSQLAlchemyHealthCheck(HealthCheck[HealthCheckResult]):
    """Health check class for FastAPI Async SQLAlchemy.

    Attributes:
        _name (str): The name of the health check.
        _dsn (str | None): The database DSN for separate connection.
        _timeout (float): The timeout for the connection.
        _engine (AsyncEngine | None): The SQLAlchemy async engine for separate connections.
    """

    __slots__ = (
        "_name",
        "_dsn",
        "_timeout",
        "_engine",
    )

    _name: str
    _dsn: str | None
    _timeout: float
    _engine: "AsyncEngine | None"

    def __init__(
        self,
        *,
        dsn: str | None = None,
        timeout: float = DEFAULT_HC_TIMEOUT,
        name: str = "FastAPI Async SQLAlchemy",
    ) -> None:
        """Initializes the FastAPIAsyncSQLAlchemyHealthCheck instance.

        Args:
            dsn (str | None): The database DSN for separate connection. If None, uses global db session.
            timeout (float): The timeout for the connection.
            name (str): The name of the health check.
        """
        self._name = name
        self._dsn = dsn
        self._timeout = timeout
        self._engine = None

        # Create engine for separate connection if DSN provided
        if dsn:
            self._engine = create_async_engine(
                dsn,
                pool_pre_ping=True,
                pool_recycle=300,
                future=True,
            )

    @classmethod
    def from_dsn(
        cls,
        dsn: "AnyUrl | str",
        *,
        name: str = "FastAPI Async SQLAlchemy",
        timeout: float = DEFAULT_HC_TIMEOUT,
    ) -> "FastAPIAsyncSQLAlchemyHealthCheck":
        """Creates a FastAPIAsyncSQLAlchemyHealthCheck instance from a DSN.

        Args:
            dsn (AnyUrl | str): The DSN for the database.
            name (str): The name of the health check.
            timeout (float): The timeout for the connection.

        Returns:
            FastAPIAsyncSQLAlchemyHealthCheck: The health check instance.
        """
        return cls(
            dsn=str(dsn),
            timeout=timeout,
            name=name,
        )

    async def _check_with_global_session(self) -> HealthCheckResult:
        """Perform health check using the global db session."""
        try:
            # Check if db session is available
            if not hasattr(db, 'session') or db.session is None:
                error_msg = "Global db session is not available"
                print(f"[HEALTH_CHECK_DEBUG] {error_msg}")  # Debug log
                return HealthCheckResult(
                    name=self._name,
                    healthy=False,
                    error_details=error_msg
                )

            # Execute simple query
            result = await db.session.execute(text("SELECT 1"))
            health_value = result.scalar()

            if health_value != 1:
                error_msg = "Health check query returned unexpected value"
                print(f"[HEALTH_CHECK_DEBUG] {error_msg}")  # Debug log
                return HealthCheckResult(
                    name=self._name,
                    healthy=False,
                    error_details=error_msg
                )

            return HealthCheckResult(name=self._name, healthy=True)

        except BaseException as e:  # noqa: BLE001
            error_details = format_exc()
            print(f"[HEALTH_CHECK_DEBUG] Exception caught: {type(e).__name__}: {str(e)}")  # Debug log
            print(f"[HEALTH_CHECK_DEBUG] Full traceback: {error_details}")  # Debug log
            return HealthCheckResult(
                name=self._name,
                healthy=False,
                error_details=error_details
            )

    async def _check_with_separate_connection(self) -> HealthCheckResult:
        """Perform health check using a separate connection."""
        session: AsyncSession | None = None
        try:
            if not self._engine:
                return HealthCheckResult(
                    name=self._name,
                    healthy=False,
                    error_details="Database engine is not available"
                )

            # Create session
            session = AsyncSession(self._engine)

            # Execute simple query
            result = await session.execute(text("SELECT 1"))
            health_value = result.scalar()

            if health_value != 1:
                return HealthCheckResult(
                    name=self._name,
                    healthy=False,
                    error_details="Health check query returned unexpected value"
                )

            return HealthCheckResult(name=self._name, healthy=True)

        except BaseException:  # noqa: BLE001
            return HealthCheckResult(
                name=self._name,
                healthy=False,
                error_details=format_exc()
            )
        finally:
            if session:
                await session.close()

    async def __call__(self) -> HealthCheckResult:
        """Performs the health check.

        Returns:
            HealthCheckResult: The result of the health check.
        """
        if self._dsn:
            return await self._check_with_separate_connection()
        else:
            return await self._check_with_global_session()

    def to_dict(self) -> dict[str, Any]:
        """Converts the FastAPIAsyncSQLAlchemyHealthCheck object to a dictionary.

        Returns:
            A dictionary with the health check attributes.
        """
        return {
            "name": self._name,
            "dsn": self._dsn,
            "timeout": self._timeout,
        }

    async def __aenter__(self) -> "FastAPIAsyncSQLAlchemyHealthCheck":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - cleanup engine if created."""
        if self._engine:
            await self._engine.dispose()
