"""The Reflex config."""

from __future__ import annotations

import importlib
import os
import sys
import urllib.parse
from typing import Any, Dict, List, Optional

from reflex import constants
from reflex.base import Base
from reflex.utils import console


class DBConfig(Base):
    """Database config."""

    engine: str
    username: Optional[str] = ""
    password: Optional[str] = ""
    host: Optional[str] = ""
    port: Optional[int] = None
    database: str

    @classmethod
    def postgresql(
        cls,
        database: str,
        username: str,
        password: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = 5432,
    ) -> DBConfig:
        """Create an instance with postgresql engine.

        Args:
            database: Database name.
            username: Database username.
            password: Database password.
            host: Database host.
            port: Database port.

        Returns:
            DBConfig instance.
        """
        return cls(
            engine="postgresql",
            username=username,
            password=password,
            host=host,
            port=port,
            database=database,
        )

    @classmethod
    def postgresql_psycopg2(
        cls,
        database: str,
        username: str,
        password: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = 5432,
    ) -> DBConfig:
        """Create an instance with postgresql+psycopg2 engine.

        Args:
            database: Database name.
            username: Database username.
            password: Database password.
            host: Database host.
            port: Database port.

        Returns:
            DBConfig instance.
        """
        return cls(
            engine="postgresql+psycopg2",
            username=username,
            password=password,
            host=host,
            port=port,
            database=database,
        )

    @classmethod
    def sqlite(
        cls,
        database: str,
    ) -> DBConfig:
        """Create an instance with sqlite engine.

        Args:
            database: Database name.

        Returns:
            DBConfig instance.
        """
        return cls(
            engine="sqlite",
            database=database,
        )

    def get_url(self) -> str:
        """Get database URL.

        Returns:
            The database URL.
        """
        host = (
            f"{self.host}:{self.port}" if self.host and self.port else self.host or ""
        )
        username = urllib.parse.quote_plus(self.username) if self.username else ""
        password = urllib.parse.quote_plus(self.password) if self.password else ""

        if username:
            path = f"{username}:{password}@{host}" if password else f"{username}@{host}"
        else:
            path = f"{host}"

        return f"{self.engine}://{path}/{self.database}"


class Config(Base):
    """A Reflex config."""

    class Config:
        """Pydantic config for the config."""

        validate_assignment = True

    # The name of the app.
    app_name: str

    # The log level to use.
    loglevel: constants.LogLevel = constants.LogLevel.INFO

    # The port to run the frontend on.
    frontend_port: int = 3000

    # The port to run the backend on.
    backend_port: int = 8000

    # The backend url the frontend will connect to.
    api_url: str = f"http://localhost:{backend_port}"

    # The url the frontend will be hosted on.
    deploy_url: Optional[str] = f"http://localhost:{frontend_port}"

    # The url the backend will be hosted on.
    backend_host: str = "0.0.0.0"

    # The database url.
    db_url: Optional[str] = "sqlite:///reflex.db"

    # The redis url.
    redis_url: Optional[str] = None

    # Telemetry opt-in.
    telemetry_enabled: bool = True

    # The bun path
    bun_path: str = constants.DEFAULT_BUN_PATH

    # List of origins that are allowed to connect to the backend API.
    cors_allowed_origins: List[str] = ["*"]

    # Tailwind config.
    tailwind: Optional[Dict[str, Any]] = None

    # Timeout when launching the gunicorn server. TODO(rename this to backend_timeout?)
    timeout: int = 120

    # Whether to enable or disable nextJS gzip compression.
    next_compression: bool = True

    # The event namespace for ws connection
    event_namespace: Optional[str] = None

    # Params to remove eventually.
    # Additional frontend packages to install. (TODO: these can be inferred from the imports)
    frontend_packages: List[str] = []

    # For rest are for deploy only.
    # The rxdeploy url.
    rxdeploy_url: Optional[str] = None

    # The username.
    username: Optional[str] = None

    def __init__(self, *args, **kwargs):
        """Initialize the config values.

        Args:
            *args: The args to pass to the Pydantic init method.
            **kwargs: The kwargs to pass to the Pydantic init method.
        """
        super().__init__(*args, **kwargs)

        # Check for deprecated values.
        self.check_deprecated_values(**kwargs)

        # Update the config from environment variables.
        self.update_from_env()

    @staticmethod
    def check_deprecated_values(**kwargs):
        """Check for deprecated config values.

        Args:
            **kwargs: The kwargs passed to the config.

        Raises:
            ValueError: If a deprecated config value is found.
        """
        if "db_config" in kwargs:
            raise ValueError("db_config is deprecated - use db_url instead")
        if "admin_dash" in kwargs:
            raise ValueError(
                "admin_dash is deprecated in the config - pass it as a param to rx.App instead"
            )
        if "env_path" in kwargs:
            raise ValueError(
                "env_path is deprecated - use environment variables instead"
            )

    def update_from_env(self):
        """Update the config from environment variables.


        Raises:
            ValueError: If an environment variable is set to an invalid type.
        """
        # Iterate over the fields.
        for key, field in self.__fields__.items():
            # The env var name is the key in uppercase.
            env_var = os.environ.get(key.upper())

            # If the env var is set, override the config value.
            if env_var is not None:
                if key.upper() != "DB_URL":
                    console.info(
                        f"Overriding config value {key} with env var {key.upper()}={env_var}"
                    )

                # Convert the env var to the expected type.
                try:
                    env_var = field.type_(env_var)
                except ValueError:
                    console.error(
                        f"Could not convert {key.upper()}={env_var} to type {field.type_}"
                    )
                    raise

                # Set the value.
                setattr(self, key, env_var)

    def get_event_namespace(self) -> Optional[str]:
        """Get the websocket event namespace.

        Returns:
            The namespace for websocket.
        """
        if self.event_namespace:
            return f'/{self.event_namespace.strip("/")}'

        event_url = constants.Endpoint.EVENT.get_url()
        return urllib.parse.urlsplit(event_url).path


def get_config(reload: bool = False) -> Config:
    """Get the app config.

    Args:
        reload: Re-import the rxconfig module from disk

    Returns:
        The app config.
    """
    from reflex.config import Config

    sys.path.insert(0, os.getcwd())
    try:
        rxconfig = __import__(constants.CONFIG_MODULE)
        if reload:
            importlib.reload(rxconfig)
        return rxconfig.config

    except ImportError:
        return Config(app_name="")  # type: ignore
