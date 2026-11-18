from _pyfun_rt import Some, None_, _None_
def _pf_list_get(i, xs):
    return Some(xs[i]) if 0 <= i < len(xs) else _None_
def firstOf(xs):
    return _pf_list_get(0, xs)
