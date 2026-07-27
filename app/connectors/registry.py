from typing import Dict, Type
from app.connectors.base import Connector

class ConnectorRegistry:
    """
    Dynamic Factory Registry for auto-registering and retrieving Workplace & Dev Connectors.
    Supports seamless scaling across 10–13+ apps.
    """

    _registry: Dict[str, Type[Connector]] = {}

    @classmethod
    def register(cls, source_app: str):
        """Decorator to register a connector class under a source_app key."""
        def decorator(subclass: Type[Connector]):
            cls._registry[source_app.lower()] = subclass
            return subclass
        return decorator

    @classmethod
    def get_connector(cls, source_app: str) -> Connector:
        """Instantiates and returns the connector for a given source_app name."""
        app_key = source_app.lower()
        if app_key not in cls._registry:
            raise ValueError(f"No connector registered for source app '{source_app}'. Registered apps: {list(cls._registry.keys())}")
        return cls._registry[app_key]()

    @classmethod
    def list_registered_apps(cls) -> list[str]:
        """Returns list of all registered source apps."""
        return list(cls._registry.keys())
