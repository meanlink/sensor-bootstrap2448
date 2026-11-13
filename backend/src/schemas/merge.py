from pydantic import BaseModel, Field


class MergeInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    dataset_ids: list[int] = Field(min_length=2, max_length=50)


class MergePreviewInput(BaseModel):
    dataset_ids: list[int] = Field(min_length=2, max_length=50)
