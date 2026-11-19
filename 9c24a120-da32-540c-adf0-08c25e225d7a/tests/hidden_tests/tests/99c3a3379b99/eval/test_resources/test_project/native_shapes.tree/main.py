import shape
from _pyfun_rt import Some, None_, _None_
def _pf_iter(f, xs):
    for x in xs:
        f(x)
    return None
def _pf_head(xs):
    return Some(xs[0]) if xs else _None_
def _pf_option_map(f, o):
    if isinstance(o, Some):
        return Some(f(o._0))
    return _None_
def area(s) -> int:
    if isinstance(s, shape.Circle):
        r = s._0
        return r * r
    else:
        w = s._0
        h = s._1
        return w * h
shapes = [shape.Circle(3), shape.Rect(4, 5)]
_pf_iter(lambda s: print(f"{shape.describe(s)} has area {area(s)}"), shapes)
print(_pf_option_map(area, _pf_head(shapes)))
