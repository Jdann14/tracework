from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field

Name = str

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Column(StrictModel):
    name: str
    type: str
    nullable: bool = True

class Dataset(StrictModel):
    id: str
    name: str
    schema_: list[Column] = Field(alias="schema")
    rows: int

class Workspace(StrictModel):
    id: str
    name: str
    created_at: str

class Source(StrictModel):
    id: str
    workspace_id: str
    name: str

class SourceVersion(StrictModel):
    id: str
    source_id: str
    dataset_id: str
    hash: str
    original_name: str
    created_at: str

class Check(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    sql: str = Field(min_length=1, max_length=20000)
    severity: Literal["blocking", "warning"] = "blocking"
    description: str = ""

class Step(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    title: str = Field(min_length=1, max_length=120)
    sql: str = Field(min_length=1, max_length=30000)
    depends_on: list[str] = Field(max_length=30)
    checks: list[Check] = Field(default_factory=list, max_length=20)

class SourceInput(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}$")
    columns: dict[str, str] = Field(default_factory=dict)

class PipelineSpec(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=5000)
    assumptions: list[str] = Field(min_length=1, max_length=30)
    sources: list[SourceInput] = Field(min_length=1, max_length=20)
    steps: list[Step] = Field(min_length=1, max_length=20)
    output: str
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

class Pipeline(StrictModel):
    id: str
    workspace_id: str
    title: str

class PipelineVersion(StrictModel):
    id: str
    pipeline_id: str
    number: int
    parent_id: str | None
    spec: PipelineSpec
    hash: str

class Settings(StrictModel):
    timeout_seconds: int = Field(default=45, ge=1, le=120)
    memory_mb: int = Field(default=512, ge=64, le=1024)
    max_output_rows: int = Field(default=100000, ge=1, le=1000000)
    threads: int = Field(default=2, ge=1, le=4)

class RunRequest(StrictModel):
    version_id: str
    inputs: dict[str, str]
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    settings: Settings = Field(default_factory=Settings)
    request_key: str = Field(min_length=1, max_length=100)

class Run(StrictModel):
    id: str
    workspace_id: str
    version_id: str
    status: str
    inputs: dict[str, str]
    parameters: dict[str, Any]
    settings: Settings

class StepExecution(StrictModel):
    run_id: str
    name: str
    status: str
    error: str | None = None

class Artifact(StrictModel):
    id: str
    run_id: str
    step: str
    dataset_id: str
    hash: str

class Finding(StrictModel):
    id: str
    run_id: str
    artifact_id: str
    title: str
    detail: str
    evidence: dict[str, Any]
