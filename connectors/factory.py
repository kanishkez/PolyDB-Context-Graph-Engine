"""
Connector factory — instantiate correct connector from config
"""
from connectors.base import BaseConnector
from connectors.postgres_connector import PostgreSQLConnector
from connectors.mysql_connector import MySQLConnector
from connectors.trino_connector import TrinoConnector


def get_connector(config: dict) -> BaseConnector:
    db_type = config.get("type", "").lower()
    if db_type in ("postgresql", "postgres"):
        return PostgreSQLConnector(config)
    elif db_type == "mysql":
        return MySQLConnector(config)
    elif db_type == "trino":
        return TrinoConnector(config)
    else:
        raise ValueError(f"Unsupported database type: {db_type}")
