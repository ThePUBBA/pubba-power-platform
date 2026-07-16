"""Phase 2 domain vocabulary shared by APIs, services, and persistence code.

These enums are intentionally string-valued so they can be used directly in
Pydantic schemas and PostgreSQL check constraints without translation.
"""

from enum import Enum


METRIC_VERSION = "1.0"


class AssetStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    UNAVAILABLE = "unavailable"
    MAINTENANCE = "maintenance"
    RETIRED = "retired"


class DispatchStatus(str, Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    CHARGING = "charging"
    HOLDING = "holding"
    DISCHARGING = "discharging"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class SettlementStatus(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    UNSETTLED = "unsettled"
    ESTIMATED = "estimated"
    SETTLED = "settled"
    DISPUTED = "disputed"


class DispatchSource(str, Enum):
    SIMULATION = "simulation"
    MANUAL = "manual"
    EXTERNAL = "external"
    AUTOMATED = "automated"


class UtilizationMethod(str, Enum):
    DISPATCH_WINDOW_PROXY = "dispatch_window_proxy"
    AVAILABLE_HOURS = "available_hours"

