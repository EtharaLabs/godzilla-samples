from dataclasses import dataclass
@dataclass(frozen=True, slots=True, repr=False)
class Circle:
    _0: int
    def __repr__(self):
        return f"Circle({self._0!r})"
    def __eq__(self, other):
        return type(other) is Circle and self._pf_order_key() == other._pf_order_key()
    def __lt__(self, other):
        return self._pf_order_key() < other._pf_order_key()
    def __le__(self, other):
        return self._pf_order_key() <= other._pf_order_key()
    def __gt__(self, other):
        return self._pf_order_key() > other._pf_order_key()
    def __ge__(self, other):
        return self._pf_order_key() >= other._pf_order_key()
    def _pf_order_key(self):
        return (0, self._0)
@dataclass(frozen=True, slots=True, repr=False)
class Rect:
    _0: int
    _1: int
    def __repr__(self):
        return f"Rect({self._0!r}, {self._1!r})"
    def __eq__(self, other):
        return type(other) is Rect and self._pf_order_key() == other._pf_order_key()
    def __lt__(self, other):
        return self._pf_order_key() < other._pf_order_key()
    def __le__(self, other):
        return self._pf_order_key() <= other._pf_order_key()
    def __gt__(self, other):
        return self._pf_order_key() > other._pf_order_key()
    def __ge__(self, other):
        return self._pf_order_key() >= other._pf_order_key()
    def _pf_order_key(self):
        return (1, self._0, self._1)
Shape = Circle | Rect
def describe(s: Shape) -> str:
    if isinstance(s, Circle):
        r = s._0
        return f"circle {r}"
    else:
        w = s._0
        h = s._1
        return f"rect {w}x{h}"
