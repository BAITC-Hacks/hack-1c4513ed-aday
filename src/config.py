from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Config:
    as_of: date = date(2026, 9, 22)
    outlier_k: float = 5.0
    outlier_m: float = 10.0
    min_outlier_qty: float = 10.0
    review_days: int = 30
    default_lead_days: int = 30
    service_z: dict = field(default_factory=lambda: {"A": 1.65, "B": 1.28, "C": 1.04})


DEFAULT = Config()
