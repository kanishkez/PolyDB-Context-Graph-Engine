"""
Abstract base connector for all database types
"""
from abc import ABC, abstractmethod
from typing import List
from models.unified import NormalizedTable, NormalizedRelationship


class BaseConnector(ABC):
    """
    All connectors must implement extract_tables and extract_relationships.
    Connectors are stateless — instantiate, extract, discard.
    """

    def __init__(self, connection_config: dict):
        self.config = connection_config
        self.source_db = connection_config["name"]
        self.source_type = connection_config["type"]

    @abstractmethod
    async def extract_tables(self) -> List[NormalizedTable]:
        """Extract all accessible tables with column metadata."""
        ...

    @abstractmethod
    async def extract_relationships(self) -> List[NormalizedRelationship]:
        """Extract all FK + inferred relationships."""
        ...

    @abstractmethod
    async def test_connection(self) -> bool:
        """Verify connectivity."""
        ...
