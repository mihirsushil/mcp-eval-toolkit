"""Versioned cases; only query and context cross the model boundary."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Call(StrictModel):
    tool: str = Field(min_length=1)
    arguments: dict
    absent_or_null: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def disjoint(self):
        if set(self.arguments) & set(self.absent_or_null):
            raise ValueError("an argument cannot be both required and absent-or-null")
        return self


class Expected(StrictModel):
    action: Literal["call", "clarify", "no_call"]
    acceptable: list[Call] = Field(default_factory=list)
    rubric: str = Field(min_length=1)

    @model_validator(mode="after")
    def action_matches_calls(self):
        if (self.action == "call") != bool(self.acceptable):
            raise ValueError("only call cases must have one or more acceptable calls")
        return self


class Case(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    family: str = Field(min_length=1)
    context: str
    request: str = Field(min_length=1)
    expected: Expected
    reason: str = Field(min_length=1)

    def query(self) -> str:
        return f"Context: {self.context}\n\nRequest: {self.request}"


class Suite(StrictModel):
    version: Literal[1]
    split: Literal["dev", "heldout"]
    cases: list[Case] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate case IDs")
        return self


def load_suite(path: Path) -> Suite:
    return Suite.model_validate(yaml.safe_load(path.read_text()))


def select_suite(root: Path, split: str, final_report: bool = False) -> Suite:
    if split == "heldout" and not final_report:
        raise ValueError("held-out model access requires --final-report; freeze changes first")
    suite = load_suite(root / "cases" / "poker" / f"{split}.yaml")
    if suite.split != split:
        raise ValueError("suite split does not match requested split")
    return suite
