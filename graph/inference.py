"""
Relationship inference — find hidden relationships via naming patterns
"""
from typing import List, Tuple
from difflib import SequenceMatcher
from models.unified import NormalizedTable, NormalizedRelationship, RelationshipType
from config import settings


def infer_relationships(tables: List[NormalizedTable]) -> List[NormalizedRelationship]:
    """
    Detect inferred relationships without LLM:
    1. *_id columns that match table names (high confidence)
    2. Column naming similarity across tables (lower confidence)
    """
    inferred = []
    table_name_map = {}
    for t in tables:
        base = t.table_name.lower()
        variants = {base}
        if base.endswith("s"):
            variants.add(base[:-1])
        else:
            variants.add(f"{base}s")
        if base.endswith("ies"):
            variants.add(base[:-3] + "y")
        elif base.endswith("y"):
            variants.add(base[:-1] + "ies")
        for v in variants:
            table_name_map.setdefault(v, t)

    for table in tables:
        for col in table.columns:
            col_lower = col.name.lower()

            # Pattern 1: column ends in _id → look for matching table
            if col_lower.endswith("_id") and not col.is_primary_key:
                candidate_table_name = col_lower[:-3]  # strip _id
                if candidate_table_name in table_name_map:
                    target = table_name_map[candidate_table_name]
                    # Find primary key of target
                    pk_cols = [c for c in target.columns if c.is_primary_key]
                    to_col = pk_cols[0].name if pk_cols else "id"

                    inferred.append(NormalizedRelationship(
                        source_db=table.source_db,
                        from_schema=table.schema_name,
                        from_table=table.table_name,
                        from_column=col.name,
                        to_schema=target.schema_name,
                        to_table=target.table_name,
                        to_column=to_col,
                        relationship_type=RelationshipType.INFERRED_ID,
                        confidence=0.85,
                    ))

    # Pattern 2: naming similarity between non-PK columns across tables
    # Only run if below threshold to avoid O(n^3) cost
    if len(tables) < 100:
        inferred += _similarity_inference(tables, table_name_map)

    return inferred


def _similarity_inference(
    tables: List[NormalizedTable],
    table_name_map: dict
) -> List[NormalizedRelationship]:
    """Low-confidence inferences based on column name similarity."""
    inferred = []
    threshold = settings.INFERENCE_CONFIDENCE_THRESHOLD

    for i, t1 in enumerate(tables):
        for t2 in tables[i + 1:]:
            if t1.source_db != t2.source_db:
                continue
            for c1 in t1.columns:
                if c1.is_primary_key or c1.is_sensitive:
                    continue
                for c2 in t2.columns:
                    if c2.is_primary_key or c2.is_sensitive:
                        continue
                    sim = SequenceMatcher(
                        None, c1.name.lower(), c2.name.lower()
                    ).ratio()
                    if sim >= threshold and c1.data_type == c2.data_type:
                        inferred.append(NormalizedRelationship(
                            source_db=t1.source_db,
                            from_schema=t1.schema_name,
                            from_table=t1.table_name,
                            from_column=c1.name,
                            to_schema=t2.schema_name,
                            to_table=t2.table_name,
                            to_column=c2.name,
                            relationship_type=RelationshipType.NAMING_SIMILARITY,
                            confidence=round(sim, 2),
                        ))

    return inferred
