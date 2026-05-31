from fastapi import APIRouter, HTTPException, status

from app.services.dataset_registry import DatasetRegistry

router = APIRouter(prefix="/datasets", tags=["Datasets"])


@router.get("")
def list_datasets():
    registry = DatasetRegistry()
    return {
        "datasets": registry.list_datasets()
    }


@router.get("/{dataset_id}")
def get_dataset(dataset_id: str):
    registry = DatasetRegistry()
    dataset = registry.get_dataset(dataset_id)

    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found.",
        )

    return dataset