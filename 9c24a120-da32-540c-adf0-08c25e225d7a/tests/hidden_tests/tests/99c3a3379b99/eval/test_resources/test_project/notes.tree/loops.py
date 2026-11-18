def _pf_map(f, xs):
    return list(map(f, xs))
def go(n, acc):
    match n:
        case 0:
            return acc
        case _:
            return go(n - 1, _pf_map(lambda x: x + n, acc))
