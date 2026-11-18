from _pyfun_rt import Some, None_, _None_
def lookup(key):
    match key:
        case 1:
            return Some(100)
        case 2:
            return Some(200)
        case _:
            return _None_
