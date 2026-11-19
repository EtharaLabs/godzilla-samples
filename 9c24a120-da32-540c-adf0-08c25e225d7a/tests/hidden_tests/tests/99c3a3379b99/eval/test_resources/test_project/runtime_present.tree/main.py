import geometry
from _pyfun_rt import Ok, Error
def _pf_result_with_default(d, r):
    if isinstance(r, Ok):
        return r._0
    return d
x = Ok(geometry.area(2, 3))
print(_pf_result_with_default(0, x))
