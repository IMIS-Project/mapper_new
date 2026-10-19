from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base
from backend.models.types import ParameterTypeValue, YesNoBoolean

if TYPE_CHECKING:
    from backend.models.endpoint import ApiEndpoint


class ParameterMapping(Base):
    """One source_parameter -> target_parameter transformation rule."""

    __tablename__ = "api_endpoint_parameter_mapping"

    __table_args__ = (
        Index(
            "idx_parameter_mappings_lookup",
            "api_endpoint_id",
            "is_active",
        ),
    )

    id: Mapped[int] = mapped_column(
        "id",
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    api_endpoint_id: Mapped[int] = mapped_column(
        "api_endpoint_id",
        Integer,
        ForeignKey("api_endpoint.id", ondelete="CASCADE"),
        nullable=False,
    )

    source_parameter: Mapped[str] = mapped_column(
        "source_parameter",
        String(255),
        nullable=False,
    )

    target_parameter: Mapped[str] = mapped_column(
        "target_parameter",
        String(255),
        nullable=False,
    )

    data_type: Mapped[str | None] = mapped_column(
        "data_type",
        String(20),
    )

    parameter_type: Mapped[str | None] = mapped_column(
        "parameter_type",
        ParameterTypeValue(),
    )

    is_active: Mapped[bool] = mapped_column(
        "is_active",
        YesNoBoolean(),
        nullable=False,
    )

    endpoint: Mapped["ApiEndpoint"] = relationship(
        back_populates="parameters",
    )
