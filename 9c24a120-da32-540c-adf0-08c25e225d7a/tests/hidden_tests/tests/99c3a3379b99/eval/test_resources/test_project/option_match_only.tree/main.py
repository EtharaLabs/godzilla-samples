import helper
from _pyfun_rt import Some, None_, _None_
def probe(xs):
    _pf_t0 = helper.firstOf(xs)
    if isinstance(_pf_t0, None_):
        return "none"
    else:
        k = _pf_t0._0
        return k
print(probe(["A", "B"]))
print(probe([]))
