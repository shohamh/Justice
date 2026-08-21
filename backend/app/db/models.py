from __future__ import annotations

import enum as _enum
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Enum, Float, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Soldier(Base):
    __tablename__ = "soldiers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    personal_number: Mapped[str] = mapped_column(Text, unique=True)
    full_name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    # Derived display label only (priority: admin > commander > duty_manager > soldier),
    # recomputed by app.services.dm_scope.recompute_role(). Never authoritative for
    # authorization — see is_commander()/is_duty_manager() in app.auth.authz.
    role: Mapped[str] = mapped_column(
        Enum("soldier", "commander", "duty_manager", "admin", name="soldier_role"),
        server_default="soldier",
        default="soldier",
    )
    hierarchy_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )
    enrolled_at: Mapped[date] = mapped_column(
        Date, server_default=text("CURRENT_DATE"), default=None
    )
    left_at: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    email: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    email_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    theme_preference: Mapped[str] = mapped_column(
        Text, server_default=text("'system'"), default="system"
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    token_version: Mapped[int] = mapped_column(Integer, server_default=text("1"), default=1)
    failed_login_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    gender: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    is_officer: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    is_career: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    rank: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    rank_track: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    next_rank_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    next_rank_date_overridden: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    current_rank_since: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    bahad1_graduate: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    has_military_driving_license: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=None
    )
    military_driving_license_expiry: Mapped[date | None] = mapped_column(
        Date, nullable=True, default=None
    )
    enlistment_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    mandatory_end_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    discharge_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    last_mitvahim_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    last_alal_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    profile_picture_url: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, default=None)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, default=None)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class HierarchyLevelType(Base):
    __tablename__ = "hierarchy_level_types"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    key: Mapped[str] = mapped_column(String(50), unique=True)
    label: Mapped[str] = mapped_column(String(200))
    rank: Mapped[int] = mapped_column(Integer, unique=True)


class HierarchyNode(Base):
    __tablename__ = "hierarchy_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    level: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id"), nullable=True, default=None
    )
    commander_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id"), nullable=True, default=None
    )
    # NOT NULL at the DB level; the hierarchy service always assigns this before commit.
    path_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class HierarchyTransferRequest(Base):
    __tablename__ = "hierarchy_transfer_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    to_node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id"))
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id"))
    from_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id"), nullable=True, default=None
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id"), nullable=True, default=None
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class RangeType(str, _enum.Enum):
    laser = "laser"
    live = "live"
    alal = "alal"


class DutyType(Base):
    __tablename__ = "duty_types"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    name: Mapped[str] = mapped_column(Text, unique=True)
    score_per_day: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    requirements: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'"), default_factory=dict
    )
    reserve_ratio: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), server_default=text("0.000"), default=Decimal("0.000")
    )
    reserve_minimum: Mapped[int] = mapped_column(
        server_default=text("0"), default=0
    )
    is_external: Mapped[bool] = mapped_column(Boolean, default=False)
    contact_name: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    contact_phone: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    start_time: Mapped[time | None] = mapped_column(sa.Time, nullable=True, default=None)
    end_time: Mapped[time | None] = mapped_column(sa.Time, nullable=True, default=None)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    eligible_node_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True, default=None
    )
    requires_weapon: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    required_range_type: Mapped[str | None] = mapped_column(
        Enum(RangeType, name="range_type"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class DutyLocation(Base):
    __tablename__ = "duty_locations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    name: Mapped[str] = mapped_column(Text)
    base: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class ExemptionType(Base):
    __tablename__ = "exemption_types"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    name: Mapped[str] = mapped_column(Text, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    is_global: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    is_medical: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    is_commander_exemption: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    forbids_weapons: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class ExemptionDutyTypeMap(Base):
    __tablename__ = "exemption_duty_type_map"

    exemption_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exemption_types.id", ondelete="CASCADE"), primary_key=True
    )
    duty_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_types.id", ondelete="CASCADE"), primary_key=True
    )


class ExemptionDutyLocationMap(Base):
    __tablename__ = "exemption_duty_location_map"

    exemption_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exemption_types.id", ondelete="CASCADE"), primary_key=True
    )
    duty_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_locations.id", ondelete="CASCADE"), primary_key=True
    )


class SoldierExemption(Base):
    __tablename__ = "soldier_exemptions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    exemption_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exemption_types.id", ondelete="RESTRICT")
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soldiers.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soldiers.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)


class DutyAssignment(Base):
    __tablename__ = "duty_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    duty_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_types.id", ondelete="RESTRICT")
    )
    duty_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_locations.id", ondelete="RESTRICT")
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[str] = mapped_column(Text, server_default=text("'00:00'"), default="00:00")  # "HH:MM"
    end_time: Mapped[str] = mapped_column(Text, server_default=text("'23:59'"), default="23:59")    # "HH:MM"
    status: Mapped[str] = mapped_column(
        Text, server_default=text("'published'"), default="published"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soldiers.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    duty_shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_shifts.id", ondelete="SET NULL"), nullable=True, default=None
    )
    is_reserve: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    batch_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    algorithm_job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("algorithm_jobs.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    norm_score_before: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )
    norm_score_after: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )
    candidate_rank: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    candidate_pool_size: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    called_up_from: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    called_up_to: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    forced_call_up_multiplier: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2), nullable=True, default=None
    )
    weapon_ineligible: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    weapon_ineligible_reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    weapon_ineligible_detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    range_info_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    range_info_covered_by_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    range_info_covering_range_type: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    range_info_detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class DutyDayOverride(Base):
    __tablename__ = "duty_day_overrides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    duty_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_assignments.id", ondelete="CASCADE")
    )
    date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    effective_soldier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soldiers.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soldiers.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class DutyShift(Base):
    __tablename__ = "duty_shifts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    duty_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_types.id", ondelete="RESTRICT")
    )
    duty_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_locations.id", ondelete="RESTRICT")
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[str] = mapped_column(Text, server_default=text("'00:00'"), default="00:00")  # "HH:MM"
    end_time: Mapped[str] = mapped_column(Text, server_default=text("'23:59'"), default="23:59")    # "HH:MM"
    required_count: Mapped[int] = mapped_column(server_default=text("1"), default=1)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    generated_from_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shift_templates.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    dm_locked: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    reserve_count_override: Mapped[int | None] = mapped_column(
        nullable=True, default=None
    )
    eligible_node_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True, default=None
    )
    status: Mapped[str] = mapped_column(
        String, server_default=text("'active'"), default="active"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class DutyShiftNodeQuota(Base):
    __tablename__ = "duty_shift_node_quotas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    duty_shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_shifts.id", ondelete="CASCADE")
    )
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id", ondelete="RESTRICT")
    )
    count: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        sa.UniqueConstraint("duty_shift_id", "hierarchy_node_id", name="uq_shift_node_quota"),
        sa.CheckConstraint("count >= 1", name="ck_shift_node_quota_count_positive"),
    )


class ShiftTemplate(Base):
    __tablename__ = "shift_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    name: Mapped[str] = mapped_column(Text)
    duty_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_types.id", ondelete="RESTRICT")
    )
    duty_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_locations.id", ondelete="RESTRICT")
    )
    # ISO weekday numbers the shift recurs on: 1=Mon … 7=Sun
    weekdays: Mapped[list[int]] = mapped_column(JSONB, default_factory=list)
    start_time: Mapped[str] = mapped_column(Text, server_default=text("'00:00'"), default="00:00")  # "HH:MM"
    end_time: Mapped[str] = mapped_column(Text, server_default=text("'23:59'"), default="23:59")    # "HH:MM"
    required_count: Mapped[int] = mapped_column(server_default=text("1"), default=1)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    auto_roll: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    auto_roll_until: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    recurrence_type: Mapped[str] = mapped_column(Text, server_default=text("'weekly'"), default="weekly")
    duration_days: Mapped[int] = mapped_column(server_default=text("1"), default=1)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    eligible_node_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True, default=None
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class SwapRequest(Base):
    __tablename__ = "swap_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    # The assignment + specific day being handed off.
    duty_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_assignments.id", ondelete="CASCADE")
    )
    duty_date: Mapped[date] = mapped_column(Date)
    requesting_soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    # True if any eligible soldier may claim this from the open board —
    # independent of whether specific soldiers were also invited (see
    # SwapCandidate for the actual invited/claimed parties).
    open_to_marketplace: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    # open → applied (one candidate finished approval) | rejected | cancelled
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"), default="open")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # Requester's own "I still want this" confirmation — shared across every
    # candidate on this request (there's exactly one requester), auto-set
    # True the first time any candidate is accepted, same as today.
    requester_side_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    resulting_override_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_day_overrides.id", ondelete="SET NULL"), nullable=True, default=None
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    __table_args__ = (
        sa.Index(
            "uq_swap_requests_one_open_per_requester_duty",
            "requesting_soldier_id", "duty_assignment_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )


class SwapCandidate(Base):
    __tablename__ = "swap_candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    swap_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("swap_requests.id", ondelete="CASCADE")
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    # "invited" (added at request-creation time) | "marketplace" (self-claimed
    # from the open board).
    source: Mapped[str] = mapped_column(Text)
    # pending (invited, awaiting response) → declined | accepted → applied | cancelled
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), default="pending")
    offered_assignment_ids: Mapped[list[Any]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default_factory=list
    )
    soldier_side_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    __table_args__ = (
        sa.UniqueConstraint("swap_request_id", "soldier_id", name="uq_swap_candidate_request_soldier"),
    )


class SwapManagerApproval(Base):
    __tablename__ = "swap_manager_approvals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    swap_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("swap_requests.id", ondelete="CASCADE")
    )
    # NULL for side="requester" (shared across every candidate on the
    # request); required for side="covering" (each candidate has their own
    # commander/duty-manager chain, since they're different soldiers).
    swap_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("swap_candidates.id", ondelete="CASCADE"), nullable=True, default=None,
        kw_only=True,
    )
    # "requester" | "covering" -- which side of the swap this approval belongs to.
    side: Mapped[str] = mapped_column(Text)
    # The commander whose chain-of-command approval this row represents.
    commander_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    # Position of this commander within their side's chain, 0 = nearest
    # commander (matches commander_chain_for_soldier's nearest-first order).
    # created_at is NOT usable for this: all rows for a swap's approval chain
    # are inserted in the same session.flush(), so they share one now().
    chain_order: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    approved: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    # May differ from commander_id when an admin/duty-manager approves on the
    # required commander's behalf (broader-scope override).
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    rejected: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    # "commander" | "duty_manager" -- which approval requirement this row satisfies.
    approver_kind: Mapped[str] = mapped_column(Text, server_default=text("'commander'"), default="commander")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    __table_args__ = (
        sa.UniqueConstraint(
            "swap_request_id", "swap_candidate_id", "side", "commander_id", "approver_kind",
            name="uq_swap_manager_approval_request_candidate_side_person_kind",
        ),
    )


class PersonalConstraint(Base):
    __tablename__ = "personal_constraints"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending_commander", default="pending_commander")
    commander_approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class ExemptionRequest(Base):
    __tablename__ = "exemption_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    exemption_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exemption_types.id", ondelete="RESTRICT")
    )
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    enrollment_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soldier_enrollment_requests.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    linked_commander_exemption_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soldier_exemptions.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    status: Mapped[str] = mapped_column(Text, server_default="pending", default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    commander_approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class ExemptionRequestFile(Base):
    __tablename__ = "exemption_request_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    exemption_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exemption_requests.id", ondelete="CASCADE")
    )
    file_name: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    data: Mapped[bytes] = mapped_column(sa.LargeBinary)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class GimelimAttachment(Base):
    __tablename__ = "gimelim_attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    dismissal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_dismissals.id", ondelete="CASCADE")
    )
    file_name: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    data: Mapped[bytes] = mapped_column(sa.LargeBinary)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class ScoreAdjustment(Base):
    __tablename__ = "score_adjustments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    delta: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    reason: Mapped[str] = mapped_column(Text)
    duty_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("duty_types.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soldiers.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class SoldierScoreProjection(Base):
    __tablename__ = "soldier_score_projection"

    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE"), primary_key=True
    )
    projection_version: Mapped[str] = mapped_column(Text)
    duty_score: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    adjustment_score: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    cumulative_score: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    shift_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class SoldierQuarterScoreProjection(Base):
    __tablename__ = "soldier_quarter_score_projection"

    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soldiers.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    quarter_start: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    projection_version: Mapped[str] = mapped_column(Text)
    duty_score: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    adjustment_score: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    total_score: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    source_fingerprint: Mapped[dict[str, Any]] = mapped_column(JSONB)
    shift_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    __table_args__ = (
        sa.Index(
            "ix_soldier_quarter_score_projection_soldier_quarter",
            "soldier_id",
            "quarter_start",
        ),
    )


class ScoreProjectionQuarterTotal(Base):
    __tablename__ = "score_projection_quarter_total"

    quarter_start: Mapped[date] = mapped_column(Date, primary_key=True, index=True)
    projection_version: Mapped[str] = mapped_column(Text)
    duty_score: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    adjustment_score: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    total_score: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class ScoreProjectionState(Base):
    __tablename__ = "score_projection_state"

    canonical_version: Mapped[str] = mapped_column(Text)
    projection_key: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
        server_default=text("'score_projection'"),
        default="score_projection",
    )
    backfill_complete: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    resume_after_soldier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soldiers.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class DutyNoShow(Base):
    __tablename__ = "duty_no_shows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    duty_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_assignments.id", ondelete="CASCADE")
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    note: Mapped[str] = mapped_column(Text)
    marked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    score_adjustment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("score_adjustments.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


RANGE_TYPE_RANK: dict[str, int] = {"laser": 1, "live": 2, "alal": 3}


class RangeEventStatus(str, _enum.Enum):
    planned = "planned"
    completed = "completed"
    cancelled = "cancelled"


class RangeAttendanceStatus(str, _enum.Enum):
    pending = "pending"
    present = "present"
    no_show = "no_show"


class RangeExcusalStatus(str, _enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class RangeLocation(Base):
    __tablename__ = "range_locations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    name: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class RangeEvent(Base):
    __tablename__ = "range_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id", ondelete="RESTRICT")
    )
    range_type: Mapped[str] = mapped_column(Enum(RangeType, name="range_type"))
    date: Mapped[date] = mapped_column(Date)
    range_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("range_locations.id", ondelete="RESTRICT")
    )
    required_count: Mapped[int] = mapped_column(Integer)
    start_time: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    end_time: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    arrival_instructions: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    contact_name: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    contact_phone: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    reserve_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    status: Mapped[str] = mapped_column(
        Enum(RangeEventStatus, name="range_event_status"),
        server_default=text("'planned'"),
        default=RangeEventStatus.planned,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    cancellation_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


class RangeAssignment(Base):
    __tablename__ = "range_assignments"
    __table_args__ = (
        sa.UniqueConstraint("range_event_id", "soldier_id", name="uq_range_assignment_event_soldier"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    range_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("range_events.id", ondelete="CASCADE")
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    is_reserve: Mapped[bool] = mapped_column(Boolean, default=False)
    is_draft: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    attendance_status: Mapped[str] = mapped_column(
        Enum(RangeAttendanceStatus, name="range_attendance_status"),
        server_default=text("'pending'"),
        default=RangeAttendanceStatus.pending,
    )
    marked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    assignment_reason_code: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    assignment_reason_text: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    score_adjustment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("score_adjustments.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class RangeExcusalRequest(Base):
    __tablename__ = "range_excusal_requests"
    __table_args__ = (
        sa.Index(
            "uq_range_excusal_requests_one_pending_per_assignment",
            "range_assignment_id",
            unique=True,
            postgresql_where=sa.text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    # Approved primary and self-service reserve excusals delete the assignment,
    # while this record remains as their audit trail.
    range_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("range_assignments.id", ondelete="SET NULL"), nullable=True
    )
    # Set once at request creation and never cleared — survives range_assignment_id
    # being nulled out when the assignment row is later deleted (approved excusal),
    # so duty-history can still identify which range this request was for.
    range_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("range_events.id", ondelete="SET NULL"), nullable=True, kw_only=True, default=None
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    status: Mapped[RangeExcusalStatus] = mapped_column(
        Enum(RangeExcusalStatus, name="range_excusal_status"),
        server_default=text("'pending'"),
        default=RangeExcusalStatus.pending,
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    promoted_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("range_assignments.id", ondelete="SET NULL"), nullable=True, default=None
    )
class SoldierRangeQualification(Base):
    __tablename__ = "soldier_range_qualifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    range_type: Mapped[str] = mapped_column(Enum(RangeType, name="range_type"))
    valid_until: Mapped[date] = mapped_column(Date)
    source_range_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("range_assignments.id", ondelete="SET NULL"), nullable=True, default=None
    )
    source_range_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("range_events.id", ondelete="SET NULL"), nullable=True, default=None)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class RankAdvancementInterval(Base):
    __tablename__ = "rank_advancement_intervals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    track: Mapped[str] = mapped_column(Text, nullable=False)
    rank: Mapped[str] = mapped_column(Text, nullable=False)
    months_to_next: Mapped[int | None] = mapped_column(Integer, nullable=True)
    advance_on_career_entry: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )

    __table_args__ = (
        sa.UniqueConstraint("track", "rank", name="uq_rank_advancement_interval_track_rank"),
    )


class PotentialModifier(Base):
    __tablename__ = "potential_modifiers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id", ondelete="RESTRICT"), index=True
    )
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True, default=None)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("soldiers.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class AlgorithmJob(Base):
    __tablename__ = "algorithm_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    planning_start: Mapped[date] = mapped_column(Date)
    planning_end: Mapped[date] = mapped_column(Date)
    shift_ids: Mapped[list[Any]] = mapped_column(JSONB)
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    mode: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), default="pending")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    batch_results: Mapped[list[Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )
    result_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )
    solver_input_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )

    @property
    def total_duties(self) -> int:
        return sum(br.get("duty_count", 0) for br in (self.batch_results or []))

    @property
    def assigned_duties(self) -> int:
        return sum(br.get("assigned_count", 0) for br in (self.batch_results or []))


class ImportSession(Base):
    __tablename__ = "import_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    filename: Mapped[str] = mapped_column(Text)
    raw_excel: Mapped[bytes] = mapped_column(sa.LargeBinary)
    status: Mapped[str] = mapped_column(
        Enum("draft", "confirmed", "cancelled", "done", name="import_session_status"),
        server_default="draft", default="draft",
    )
    parsed_state: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"), default_factory=dict)
    user_selections: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"), default_factory=dict)
    created_links: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"), default_factory=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)


class AlgorithmJobSeen(Base):
    __tablename__ = "algorithm_job_seen"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("algorithm_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE"), primary_key=True
    )
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class DutyDismissal(Base):
    __tablename__ = "duty_dismissals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    duty_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_assignments.id", ondelete="CASCADE")
    )
    dismissed_from: Mapped[date] = mapped_column(Date)
    dismissed_to: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    is_gimelim: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class DutyReserveLink(Base):
    __tablename__ = "duty_reserve_links"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    reserve_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_assignments.id", ondelete="CASCADE")
    )
    primary_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_assignments.id", ondelete="CASCADE"), unique=True
    )
    hierarchy_distance: Mapped[int] = mapped_column(server_default=text("0"), default=0)


class AssignmentExplanation(Base):
    __tablename__ = "assignment_explanations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    duty_assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duty_assignments.id", ondelete="CASCADE")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    algorithm_version: Mapped[str] = mapped_column(Text)
    solver_seed: Mapped[str] = mapped_column(Text)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class SoldierFieldUpdate(Base):
    __tablename__ = "soldier_field_updates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    field_name: Mapped[str] = mapped_column(Text)
    new_value: Mapped[str] = mapped_column(Text)
    previous_value: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class NotificationType(str, _enum.Enum):
    swap_offer = "swap_offer"
    swap_accepted = "swap_accepted"
    swap_rejected = "swap_rejected"
    exemption_approved = "exemption_approved"
    exemption_rejected = "exemption_rejected"
    constraint_approved = "constraint_approved"
    constraint_rejected = "constraint_rejected"
    assignment_created = "assignment_created"
    assignment_removed = "assignment_removed"
    score_adjusted = "score_adjusted"
    announcement = "announcement"
    algorithm_job_done = "algorithm_job_done"
    algorithm_job_failed = "algorithm_job_failed"
    enrollment_request_received = "enrollment_request_received"
    enrollment_approved = "enrollment_approved"
    enrollment_rejected = "enrollment_rejected"
    constraint_pending = "constraint_pending"
    exemption_request_pending = "exemption_request_pending"
    swap_offer_incoming = "swap_offer_incoming"
    swap_pending_approval = "swap_pending_approval"
    gimelim_dismissed = "gimelim_dismissed"
    gimelim_reserve_called_up = "gimelim_reserve_called_up"
    gimelim_demoted_to_reserve = "gimelim_demoted_to_reserve"
    gimelim_reassigned = "gimelim_reassigned"
    exemption_revoked = "exemption_revoked"
    transfer_request_pending = "transfer_request_pending"
    transfer_request_rejected = "transfer_request_rejected"
    system_announcement = "system_announcement"
    enrollment_fields_edited = "enrollment_fields_edited"
    no_show_marked = "no_show_marked"
    range_assignment_confirmed = "range_assignment_confirmed"
    range_roster_changed = "range_roster_changed"
    range_cancelled = "range_cancelled"
    range_no_show = "range_no_show"
    range_reminder = "range_reminder"
    range_reminder_shortfall = "range_reminder_shortfall"
    range_excusal_pending = "range_excusal_pending"
    range_excusal_approved = "range_excusal_approved"
    range_excusal_rejected = "range_excusal_rejected"
    range_reserve_promoted = "range_reserve_promoted"
    range_reserve_excused = "range_reserve_excused"
    range_excusal_no_backfill = "range_excusal_no_backfill"
    range_absence_reported_to_commander = "range_absence_reported_to_commander"
    range_attendance_corrected_to_present = "range_attendance_corrected_to_present"
    bug_report_comment = "bug_report_comment"
    weapon_ineligible_detected = "weapon_ineligible_detected"
    range_covers_duty_info = "range_covers_duty_info"
    rank_advanced = "rank_advanced"
    rank_advancement_soon = "rank_advancement_soon"
    mitvahim_expiring_soon = "mitvahim_expiring_soon"
    mitvahim_expired = "mitvahim_expired"
    alal_expiring_soon = "alal_expiring_soon"
    alal_expired = "alal_expired"


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    soldier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[NotificationType] = mapped_column(Enum(NotificationType, name="notification_type"), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    reference_type: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True, default=None)
    is_read: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)


class Announcement(Base):
    __tablename__ = "announcements"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    sender_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_count: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[NotificationType] = mapped_column(Enum(NotificationType, name="notification_type"), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    hierarchy_node_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)


class TelegramLink(Base):
    __tablename__ = "telegram_links"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    soldier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id"), nullable=False, unique=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, default=None)
    telegram_username: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    verification_code: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    is_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    soldier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id"), nullable=False)
    notification_type: Mapped[NotificationType] = mapped_column(Enum(NotificationType, name="notification_type"), nullable=False)
    in_app_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    push_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    __table_args__ = (sa.UniqueConstraint("soldier_id", "notification_type"),)


class CommanderNotificationScope(Base):
    __tablename__ = "commander_notification_scopes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    commander_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("soldiers.id"), nullable=False)
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id"), nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=-1, server_default="-1")


class TelegramOutbox(Base):
    __tablename__ = "telegram_outbox"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    telegram_chat_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    message_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    reply_markup_json: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)


class EmailOutbox(Base):
    __tablename__ = "email_outbox"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False)
    to_address: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    html_body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), init=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)


class TelegramActionToken(Base):
    __tablename__ = "telegram_action_tokens"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    extra_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    awaiting_text_from_chat_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class CommanderNotificationDepth(Base):
    __tablename__ = "commander_notification_depth"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    commander_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False
    )
    notification_type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notification_type"), nullable=False
    )
    max_depth: Mapped[int | None] = mapped_column(sa.Integer, nullable=True, default=2)
    __table_args__ = (sa.UniqueConstraint("commander_id", "notification_type"),)


class DutyManagerScope(Base):
    __tablename__ = "duty_manager_scope"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    duty_manager_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    hierarchy_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id", ondelete="CASCADE")
    )
    __table_args__ = (
        sa.UniqueConstraint("duty_manager_id", "hierarchy_node_id", name="uq_dm_scope"),
    )


class RoleDeputy(Base):
    __tablename__ = "role_deputies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    principal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    deputy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(Enum("commander", "duty_manager", name="deputy_role"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    __table_args__ = (
        sa.UniqueConstraint("principal_id", "deputy_id", "role", name="uq_role_deputy"),
        sa.CheckConstraint("end_date >= start_date", name="ck_role_deputy_date_range"),
    )


class RegistrationInviteCode(Base):
    __tablename__ = "registration_invite_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    code: Mapped[str] = mapped_column(Text, unique=True)
    uses_left: Mapped[int] = mapped_column(server_default=text("1"), default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class SoldierEnrollmentRequest(Base):
    __tablename__ = "soldier_enrollment_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    requested_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hierarchy_nodes.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"), default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    soldier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE"), nullable=False
    )
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class ForcedCallup(Base):
    __tablename__ = "forced_callups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    initiator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    pulled_soldier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    original_assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    pull_date: Mapped[date] = mapped_column(Date)
    replacement_soldier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    replacement_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, default=None
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "rejected", name="forced_callup_status"),
        default="pending",
    )
    approver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, default=None)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    callup_multiplier: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("2.0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class BugReport(Base):
    __tablename__ = "bug_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, kw_only=True, default=None
    )
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(
        Enum("low", "medium", "high", name="bug_report_severity")
    )
    route: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Enum("open", "in_progress", "resolved", "wont_fix", name="bug_report_status"),
        server_default="open", default="open",
    )
    screenshot: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True, default=None)
    nav_history: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True, default=None)
    audit_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True, default=None)
    user_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True, default=None)
    json_file_path: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
    reporter_last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


class BugReportComment(Base):
    __tablename__ = "bug_report_comments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    bug_report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bug_reports.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="CASCADE")
    )
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )


class BugReportCommentAttachment(Base):
    __tablename__ = "bug_report_comment_attachments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"), init=False
    )
    comment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bug_report_comments.id", ondelete="CASCADE"), index=True
    )
    file_name: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(Text)
    data: Mapped[bytes] = mapped_column(sa.LargeBinary)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("soldiers.id", ondelete="SET NULL"), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), init=False
    )
