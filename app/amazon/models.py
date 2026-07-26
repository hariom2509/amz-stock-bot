"""
Amazon product state models returned by the parser.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class StockStatus(str, Enum):
    """Stock status as determined by the parser."""
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


@dataclass
class ProductState:
    """
    Result of parsing an Amazon product page.

    Includes confidence scoring and evidence list so the caller
    can decide whether to trust the result.
    """
    status: StockStatus
    confidence: float  # 0.0 – 1.0
    title: Optional[str] = None
    price: Optional[str] = None
    currency: str = "INR"
    evidence: List[str] = field(default_factory=list)
    raw_availability_text: Optional[str] = None
    error_message: Optional[str] = None

    @property
    def is_confident_in_stock(self) -> bool:
        """True if we're confident enough to send an alert."""
        return self.status == StockStatus.IN_STOCK and self.confidence >= 0.6

    @property
    def is_blocked(self) -> bool:
        return self.status == StockStatus.BLOCKED
