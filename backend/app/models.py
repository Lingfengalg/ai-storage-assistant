"""Shared domain contract. Lengths are integer millimetres, x=right/y=back/z=up."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Size(Model):
    width: int = Field(gt=0, le=10000, strict=True)
    depth: int = Field(gt=0, le=10000, strict=True)
    height: int = Field(gt=0, le=10000, strict=True)


class Placement(Model):
    shelf_id: str
    # Compartment index within the shelf; x is the horizontal offset inside that compartment.
    column: int = Field(default=0, ge=0, le=3, strict=True)
    x: int = Field(ge=0, strict=True)
    y: int = Field(ge=0, strict=True)
    rotated: bool = False


class Shelf(Model):
    id: str
    name: str
    size: Size
    elevation: int = Field(ge=0, strict=True)
    columns: int = Field(default=1, ge=1, le=4, strict=True)
    divider: int = Field(default=18, ge=0, le=100, strict=True)


class Item(Model):
    id: str
    name: str
    category: str
    size: Size
    placement: Placement
    movable: bool = True
    allow_rotation: bool = True
    status: Literal["stored", "taken_out"] = "stored"
    measurement_source: Literal["synthetic", "manual", "sensor"] = "synthetic"


class Scene(Model):
    id: str
    name: str
    version: int = Field(ge=1)
    unit: Literal["mm"] = "mm"
    source: Literal["synthetic", "user"] = "synthetic"
    shelves: list[Shelf] = Field(min_length=1, max_length=10)
    items: list[Item] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_ids(self):
        for records in [self.shelves, self.items]:
            if len({r.id for r in records}) != len(records):
                raise ValueError("IDs must be unique")
        return self


class VersionedRequest(Model):
    expected_version: int = Field(ge=1, strict=True)


class Mutation(VersionedRequest):
    request_id: str = Field(min_length=8, max_length=100)


class InventoryRequest(Mutation):
    item_id: str
    action: Literal["take", "return"]


class LockRequest(Mutation):
    movable: bool


class ApplyRequest(Mutation):
    execution_confirmed: Literal[True]


class StructureRequest(Model):
    """External cabinet dimensions in mm; the backend derives the shelf Scene."""

    name: str = Field(min_length=1, max_length=100)
    rows: int = Field(ge=1, le=10, strict=True)
    columns: int = Field(ge=1, le=4, strict=True)
    width: int = Field(gt=0, le=10000, strict=True)
    depth: int = Field(gt=0, le=10000, strict=True)
    height: int = Field(gt=0, le=10000, strict=True)
    board: int = Field(default=18, ge=0, le=100, strict=True)
    divider: int = Field(default=18, ge=0, le=100, strict=True)


class Plan(Model):
    id: str
    input_version: int
    algorithm: Literal["greedy-shelf-v1"] = "greedy-shelf-v1"
    status: Literal["FEASIBLE", "NO_SOLUTION_FOUND"]
    placements: dict[str, Placement]
    unplaced_item_ids: list[str]
    moved_count: int
    notes: list[str]
