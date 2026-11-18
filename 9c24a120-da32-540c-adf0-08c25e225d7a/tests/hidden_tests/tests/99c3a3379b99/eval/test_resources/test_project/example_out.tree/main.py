import functools
import geometry
import store
from _pyfun_rt import Some, None_, _None_
def _pf_option_with_default(d, o):
    if isinstance(o, Some):
        return o._0
    return d
floor = geometry.area(4, 5)
nine = geometry.square(3)
widen = functools.partial(geometry.area, 10)
strip = widen(2)
hit = _pf_option_with_default(0, store.lookup(1))
miss = _pf_option_with_default(0, store.lookup(9))
print(floor)
print(nine)
print(strip)
print(hit)
print(miss)
