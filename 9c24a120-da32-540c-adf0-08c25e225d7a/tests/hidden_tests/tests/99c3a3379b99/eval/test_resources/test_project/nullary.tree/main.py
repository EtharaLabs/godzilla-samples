import color
from _pyfun_rt import Some, None_, _None_
def _pf_last(xs):
    return Some(xs[-1]) if xs else _None_
def name(k):
    match k:
        case color.Red():
            return "r"
        case color.Green():
            return "g"
        case color.Blue():
            return "b"
        case _:
            raise RuntimeError("non-exhaustive match")
def last(xs):
    _pf_t0 = _pf_last(xs)
    if isinstance(_pf_t0, Some):
        c = _pf_t0._0
        return name(c)
    else:
        return "-"
print(last([color._Green, color._Red]))
print(last([]))
print(color._Red == color._Red)
print(len(set([color._Red, color._Red, color._Blue])))
