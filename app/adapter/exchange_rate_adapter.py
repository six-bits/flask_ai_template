"""Adapter managing currency exchange rates matrix (simulating external FX feed)."""

from typing import Dict, Optional, Tuple


class ExchangeRateAdapter:
    """In-memory exchange rates provider."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Initialize standard FX rate matrix."""
        self._rates: Dict[Tuple[str, str], str] = {
            ("USD", "EUR"): "0.9200",
            ("EUR", "USD"): "1.0870",
            ("USD", "GBP"): "0.7900",
            ("GBP", "USD"): "1.2660",
            ("EUR", "GBP"): "0.8600",
            ("GBP", "EUR"): "1.1630",
        }

    def get_rate(self, from_curr: str, to_curr: str) -> Optional[str]:
        """Lookup exchange rate between two currencies."""
        if from_curr == to_curr:
            return "1.0000"
        return self._rates.get((from_curr, to_curr))

    def set_rate(self, from_curr: str, to_curr: str, rate: str) -> None:
        """Override or add exchange rate."""
        self._rates[(from_curr, to_curr)] = rate


# Default singleton instance
exchange_rate_adapter = ExchangeRateAdapter()
