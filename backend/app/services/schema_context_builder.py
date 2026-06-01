from typing import Any

from app.services.dataset_registry import get_dataset_by_id


def build_schema_context(dataset_id: str) -> dict[str, Any] | None:
    dataset = get_dataset_by_id(dataset_id)

    if dataset is None:
        return None

    schema_profile = dataset.get("schema_profile")

    if schema_profile is None:
        return None

    return {
        "dataset_id": dataset["dataset_id"],
        "table_name": dataset["table_name"],
        "row_count": dataset["row_count"],
        "column_count": dataset["column_count"],
        "schema_profile": schema_profile,
    }
