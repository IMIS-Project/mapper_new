from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


def _now() -> datetime:
    return datetime.now()


def _gen_uuid() -> str:
    return str(uuid.uuid4())


class Workflow(Base):
    """A configurable workflow sequence composed of steps (nodes)."""

    __tablename__ = "workflows"
    __table_args__ = (
        Index("idx_workflows_slug", "slug", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_gen_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(50), default="manual", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )

    steps: Mapped[list["WorkflowStep"]] = relationship(
        "WorkflowStep",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowStep.step_order",
    )

    runs: Mapped[list["WorkflowRun"]] = relationship(
        "WorkflowRun",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="desc(WorkflowRun.ran_at)",
    )


class WorkflowStep(Base):
    """An individual step or node in a workflow pipeline."""

    __tablename__ = "workflow_steps"
    __table_args__ = (
        UniqueConstraint("workflow_id", "step_key", name="uq_wf_step_key"),
        Index("idx_wf_step_order", "workflow_id", "step_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_gen_uuid)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    step_key: Mapped[str] = mapped_column(String(100), nullable=False)
    step_type: Mapped[str] = mapped_column(String(50), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now, nullable=False
    )

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="steps")


class WorkflowRun(Base):
    """Historical execution trace for a workflow."""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("idx_wf_run_history", "workflow_id", "ran_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_gen_uuid)
    workflow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="RUNNING")
    trigger_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    step_results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    final_output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="runs")
