"""
Security layer — filter sensitive schemas/columns, enforce access control
"""
from typing import Optional, Set, List, Dict, Any
from config import settings


class SecurityService:

    def __init__(self):
        self._sensitive_patterns: List[str] = settings.SENSITIVE_COLUMN_PATTERNS
        self._excluded_schemas: Set[str] = set(settings.EXCLUDED_SCHEMAS)
        # user_id → set of accessible source_dbs (empty set = all)
        self._user_permissions: Dict[str, Set[str]] = {}

    # ─── Registration ─────────────────────────────────────────────────────────

    def grant_access(self, user_id: str, source_dbs: List[str]):
        self._user_permissions[user_id] = set(source_dbs)

    def revoke_access(self, user_id: str, source_db: str):
        if user_id in self._user_permissions:
            self._user_permissions[user_id].discard(source_db)

    # ─── Checks ───────────────────────────────────────────────────────────────

    def is_schema_allowed(self, schema_name: str) -> bool:
        return schema_name.lower() not in self._excluded_schemas

    def is_column_sensitive(self, column_name: str) -> bool:
        col_lower = column_name.lower()
        return any(pat in col_lower for pat in self._sensitive_patterns)

    def can_access_db(self, user_id: Optional[str], source_db: str) -> bool:
        if not user_id:
            return True  # No auth configured = open access
        perms = self._user_permissions.get(user_id)
        if perms is None:
            return True  # Unknown user = allow (configurable)
        return len(perms) == 0 or source_db in perms

    # ─── Filtering ────────────────────────────────────────────────────────────

    def filter_context(
        self,
        context: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Remove inaccessible tables and sensitive columns from context dict."""
        filtered = {}
        for node_id, node_data in context.items():
            source_db = node_data.get("source_db", "")
            schema = node_data.get("schema", "")

            if not self.is_schema_allowed(schema):
                continue
            if not self.can_access_db(user_id, source_db):
                continue

            # Filter columns
            safe_data = dict(node_data)
            safe_cols = [
                c for c in node_data.get("columns", [])
                if not self.is_column_sensitive(c)
            ]
            safe_data["columns"] = safe_cols
            filtered[node_id] = safe_data

        return filtered

    def filter_table_list(
        self,
        node_ids: List[str],
        user_id: Optional[str] = None,
    ) -> List[str]:
        """Filter a list of table node_ids by access control."""
        if not user_id:
            return node_ids
        return [
            nid for nid in node_ids
            if self.can_access_db(user_id, nid.split(":")[0])
        ]


security_service = SecurityService()
