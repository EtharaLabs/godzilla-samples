import mathx
def _pf_map(f, xs):
    return list(map(f, xs))
r = mathx.fabs(-8.0)
print(r)
print(_pf_map(mathx.fabs, [-1.5, 2.0]))
