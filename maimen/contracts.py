"""Versioned, bounded demo HTTP commands. No checkout or arbitrary tools."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CreateSession(DTO):
    mode: Literal["demo"] = "demo"


class Versions(DTO):
    scene_revision: int = Field(ge=0)
    plan_revision: int = Field(ge=0)


class Select(DTO):
    type: Literal["select_card"]
    ordinal: int = Field(ge=1, le=3)


class Replace(DTO):
    type: Literal["replace_item"]
    from_sku: str = Field(min_length=1, max_length=80)
    to_sku: str = Field(min_length=1, max_length=80)


class Undo(DTO):
    type: Literal["undo"]


class Collect(DTO):
    type: Literal["collect"]
    name: str = Field(min_length=1, max_length=60)


class Text(DTO):
    type: Literal["text"]
    text: str = Field(min_length=1, max_length=500)


class Command(Versions):
    command_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    turn_id: str = Field(min_length=1, max_length=80)
    action: Annotated[Select | Replace | Undo | Collect | Text, Field(discriminator="type")]


class Snapshot(DTO):
    session_id: str
    revision: int
    mode: Literal["demo"]
    scene_revision: int
    plan_revision: int
    cards: list[dict]
    draft: dict | None
    quote: dict | None
    collections: list[dict]
    can_undo: bool


class CommandResult(DTO):
    command_id: str
    snapshot: Snapshot
