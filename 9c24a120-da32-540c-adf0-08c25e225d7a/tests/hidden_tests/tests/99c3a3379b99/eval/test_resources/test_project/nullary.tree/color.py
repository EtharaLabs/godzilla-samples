from dataclasses import dataclass
from functools import total_ordering
@total_ordering
@dataclass(frozen=True, slots=True, repr=False)
class Red:
    def __repr__(self):
        return "Red"
    def __lt__(self, other):
        return self._pf_order_key() < other._pf_order_key()
    def _pf_order_key(self):
        return (0,)
_Red = Red()
@total_ordering
@dataclass(frozen=True, slots=True, repr=False)
class Green:
    def __repr__(self):
        return "Green"
    def __lt__(self, other):
        return self._pf_order_key() < other._pf_order_key()
    def _pf_order_key(self):
        return (1,)
_Green = Green()
@total_ordering
@dataclass(frozen=True, slots=True, repr=False)
class Blue:
    def __repr__(self):
        return "Blue"
    def __lt__(self, other):
        return self._pf_order_key() < other._pf_order_key()
    def _pf_order_key(self):
        return (2,)
_Blue = Blue()
