from _pyfun_rt import Some, None_, _None_
def lookup(key: int) -> Some | None_:
    if key == 1:
        return Some(100)
    elif key == 2:
        return Some(200)
    else:
        return _None_
