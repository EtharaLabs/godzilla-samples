// Runtime helper snippets emitted on demand, with their dependencies.
// group: 1 list, 2 modules, 3 prelude, 4 decoders, 5 async, 6 codecs

pub struct Helper {
    pub name: &'static str,
    pub group: u8,
    pub deps: &'static [&'static str],
    pub text: &'static str,
}

pub const HELPERS: &[Helper] = &[
    Helper { name: "_pf_Async", group: 5, deps: &[], text: "class _pf_Async:
    __slots__ = (\"fn\", \"args\")
    def __init__(self, fn, *args):
        self.fn = fn
        self.args = args
    def __await__(self):
        return self.fn(*self.args).__await__()
    async def __call__(self):
        return await self
    def __repr__(self):
        return \"<Async>\"" },
    Helper { name: "_pf_async_catch", group: 5, deps: &["#result", "#exception", "_pf_Async", "@asyncio"], text: "def _pf_async_catch(c):
    async def run():
        try:
            return Ok(await c)
        except Exception as e:
            return Error(_Exception(type(e).__name__, str(e)))
    return _pf_Async(run)" },
    Helper { name: "_pf_async_parallel", group: 5, deps: &["@asyncio", "_pf_Async", "_pf_run"], text: "def _pf_async_parallel(xs):
    async def run():
        return list(await asyncio.gather(*map(_pf_run, xs)))
    return _pf_Async(run)" },
    Helper { name: "_pf_async_race", group: 5, deps: &["@asyncio", "_pf_Async", "_pf_run"], text: "def _pf_async_race(xs):
    async def run():
        if not xs:
            raise ValueError(\"Async.race needs at least one value\")
        tasks = list(map(asyncio.ensure_future, map(_pf_run, xs)))
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        return next(iter(done)).result()
    return _pf_Async(run)" },
    Helper { name: "_pf_async_sleep", group: 5, deps: &["@asyncio", "_pf_Async"], text: "def _pf_async_sleep(secs):
    return _pf_Async(asyncio.sleep, secs)" },
    Helper { name: "_pf_async_timeout", group: 5, deps: &["#option", "@asyncio", "_pf_Async", "_pf_run"], text: "def _pf_async_timeout(secs, c):
    async def run():
        try:
            return Some(await asyncio.wait_for(_pf_run(c), secs))
        except TimeoutError:
            return _None_
    return _pf_Async(run)" },
    Helper { name: "_pf_async_to_thread", group: 5, deps: &["@asyncio", "_pf_Async"], text: "def _pf_async_to_thread(f):
    return _pf_Async(asyncio.to_thread, f, None)" },
    Helper { name: "_pf_average", group: 2, deps: &["#option"], text: "def _pf_average(xs):
    return Some(sum(xs) / len(xs)) if xs else _None_" },
    Helper { name: "_pf_choose", group: 2, deps: &["#option"], text: "def _pf_choose(f, xs):
    out = []
    for x in xs:
        y = f(x)
        if isinstance(y, Some):
            out.append(y._0)
    return out" },
    Helper { name: "_pf_chunk", group: 1, deps: &[], text: "def _pf_chunk(n, xs):
    if n <= 0:
        return []
    out = []
    for i in range(0, len(xs), n):
        out.append(xs[i:i + n])
    return out" },
    Helper { name: "_pf_collect", group: 1, deps: &[], text: "def _pf_collect(f, xs):
    out = []
    for x in xs:
        out.extend(f(x))
    return out" },
    Helper { name: "_pf_concat", group: 1, deps: &[], text: "def _pf_concat(xs, ys):
    return xs + ys" },
    Helper { name: "_pf_const", group: 3, deps: &[], text: "def _pf_const(x, y):
    return x" },
    Helper { name: "_pf_count_by", group: 1, deps: &[], text: "def _pf_count_by(f, xs):
    counts = dict()
    for x in xs:
        k = f(x)
        counts[k] = counts.get(k, 0) + 1
    return list(counts.items())" },
    Helper { name: "_pf_dec_and_then", group: 4, deps: &[], text: "def _pf_dec_and_then(f, dec):
    def go(v):
        return f(dec(v))(v)
    return go" },
    Helper { name: "_pf_dec_auto", group: 6, deps: &["_pf_dec_auto_value"], text: "def _pf_dec_auto(d):
    return lambda v: _pf_dec_auto_value(d, v)" },
    Helper { name: "_pf_dec_auto_value", group: 6, deps: &["#option"], text: "def _pf_dec_auto_value(d, v):
    k = d[0]
    if k == \"ref\":
        return _pf_dec_auto_value(_pf_codecs[d[1]], v)
    if k == \"int\":
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(\"expected an int, got \" + type(v).__name__)
        return v
    if k == \"float\":
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(\"expected a float, got \" + type(v).__name__)
        return float(v)
    if k == \"bool\":
        if not isinstance(v, bool):
            raise ValueError(\"expected a bool, got \" + type(v).__name__)
        return v
    if k == \"str\":
        if not isinstance(v, str):
            raise ValueError(\"expected a string, got \" + type(v).__name__)
        return v
    if k == \"unit\":
        if not v is None:
            raise ValueError(\"expected null, got \" + type(v).__name__)
        return None
    if k == \"option\":
        if v is None:
            return _None_
        return Some(_pf_dec_auto_value(d[1], v))
    if k == \"list\" or k == \"set\":
        if not isinstance(v, list):
            raise ValueError(\"expected a list, got \" + type(v).__name__)
        out = []
        for x in v:
            out.append(_pf_dec_auto_value(d[1], x))
        return out if k == \"list\" else set(out)
    if k == \"tuple\":
        if not isinstance(v, list) or len(v) != len(d[1]):
            raise ValueError(\"expected a list of \" + str(len(d[1])) + \" items\")
        return tuple(map(_pf_dec_auto_value, d[1], v))
    if k == \"map\":
        out = {}
        if d[1][0] == \"str\":
            if not isinstance(v, dict):
                raise ValueError(\"expected an object, got \" + type(v).__name__)
            for key in v:
                out[key] = _pf_dec_auto_value(d[2], v[key])
            return out
        if not isinstance(v, list):
            raise ValueError(\"expected a list of pairs, got \" + type(v).__name__)
        for pair in v:
            out[_pf_dec_auto_value(d[1], pair[0])] = _pf_dec_auto_value(d[2], pair[1])
        return out
    if k == \"record\":
        if not isinstance(v, dict):
            raise ValueError(\"expected an object, got \" + type(v).__name__)
        args = []
        for field in d[2]:
            args.append(_pf_dec_auto_value(field[1], v[field[0]]))
        return d[1](*args)
    if k == \"adt\":
        if not isinstance(v, dict):
            raise ValueError(\"expected an object, got \" + type(v).__name__)
        tag = v[\"type\"]
        if not tag in d[1]:
            raise ValueError(\"unknown case \" + str(tag))
        ctor, descs = d[1][tag]
        fields = v.get(\"fields\", [])
        if len(fields) != len(descs):
            raise ValueError(\"case \" + tag + (\" takes \" + (str(len(descs)) + \" fields\")))
        if not descs:
            return ctor
        return ctor(*map(_pf_dec_auto_value, descs, fields))
    raise ValueError(\"unknown codec \" + str(k))" },
    Helper { name: "_pf_dec_bool", group: 4, deps: &[], text: "def _pf_dec_bool(v):
    if isinstance(v, bool):
        return v
    raise ValueError(\"expected a bool, got \" + type(v).__name__)" },
    Helper { name: "_pf_dec_decode_string", group: 4, deps: &["#result", "#exception", "@json"], text: "def _pf_dec_decode_string(dec, s):
    try:
        return Ok(dec(json.loads(s)))
    except Exception as e:
        return Error(_Exception(type(e).__name__, str(e)))" },
    Helper { name: "_pf_dec_fail", group: 4, deps: &[], text: "def _pf_dec_fail(msg):
    def go(v):
        raise ValueError(msg)
    return go" },
    Helper { name: "_pf_dec_field", group: 4, deps: &[], text: "def _pf_dec_field(name, dec):
    def go(v):
        if not isinstance(v, dict):
            raise ValueError(\"expected a JSON object\")
        return dec(v[name])
    return go" },
    Helper { name: "_pf_dec_float", group: 4, deps: &[], text: "def _pf_dec_float(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    raise ValueError(\"expected a float, got \" + type(v).__name__)" },
    Helper { name: "_pf_dec_int", group: 4, deps: &[], text: "def _pf_dec_int(v):
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    raise ValueError(\"expected an int, got \" + type(v).__name__)" },
    Helper { name: "_pf_dec_list", group: 4, deps: &[], text: "def _pf_dec_list(dec):
    def go(v):
        if not isinstance(v, list):
            raise ValueError(\"expected a JSON array\")
        return list(map(dec, v))
    return go" },
    Helper { name: "_pf_dec_map", group: 4, deps: &[], text: "def _pf_dec_map(f, dec):
    def go(v):
        return f(dec(v))
    return go" },
    Helper { name: "_pf_dec_map2", group: 4, deps: &[], text: "def _pf_dec_map2(f, da, db):
    def go(v):
        return f(da(v), db(v))
    return go" },
    Helper { name: "_pf_dec_map3", group: 4, deps: &[], text: "def _pf_dec_map3(f, da, db, dc):
    def go(v):
        return f(da(v), db(v), dc(v))
    return go" },
    Helper { name: "_pf_dec_map4", group: 4, deps: &[], text: "def _pf_dec_map4(f, da, db, dc, dd):
    def go(v):
        return f(da(v), db(v), dc(v), dd(v))
    return go" },
    Helper { name: "_pf_dec_nullable", group: 4, deps: &["#option"], text: "def _pf_dec_nullable(dec):
    def go(v):
        return None_() if v is None else Some(dec(v))
    return go" },
    Helper { name: "_pf_dec_one_of", group: 4, deps: &[], text: "def _pf_dec_one_of(decs):
    def go(v):
        def _try(i):
            if i >= len(decs):
                raise ValueError(\"Decode.oneOf: no decoder matched\")
            try:
                return decs[i](v)
            except Exception:
                return _try(i + 1)
        return _try(0)
    return go" },
    Helper { name: "_pf_dec_string", group: 4, deps: &[], text: "def _pf_dec_string(v):
    if isinstance(v, str):
        return v
    raise ValueError(\"expected a string, got \" + type(v).__name__)" },
    Helper { name: "_pf_dec_succeed", group: 4, deps: &[], text: "def _pf_dec_succeed(x):
    def go(v):
        return x
    return go" },
    Helper { name: "_pf_distinct", group: 1, deps: &[], text: "def _pf_distinct(xs):
    return list(dict.fromkeys(xs))" },
    Helper { name: "_pf_distinct_by", group: 1, deps: &[], text: "def _pf_distinct_by(f, xs):
    seen = set()
    out = []
    for x in xs:
        k = f(x)
        if not k in seen:
            seen.add(k)
            out.append(x)
    return out" },
    Helper { name: "_pf_drop", group: 1, deps: &[], text: "def _pf_drop(n, xs):
    return xs[max(n, 0):len(xs)]" },
    Helper { name: "_pf_drop_while", group: 1, deps: &["@itertools"], text: "def _pf_drop_while(f, xs):
    return list(itertools.dropwhile(f, xs))" },
    Helper { name: "_pf_enc_auto", group: 6, deps: &["@json", "_pf_enc_value"], text: "def _pf_enc_auto(v):
    return json.dumps(_pf_enc_value(v))" },
    Helper { name: "_pf_enc_value", group: 6, deps: &["#option", "@dataclasses", "@keyword"], text: "def _pf_enc_value(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (list, tuple, set, frozenset)):
        return list(map(_pf_enc_value, v))
    if isinstance(v, dict):
        pairs = []
        strings = True
        for key in v:
            if not isinstance(key, str):
                strings = False
            pairs.append([_pf_enc_value(key), _pf_enc_value(v[key])])
        return dict(pairs) if strings else pairs
    if isinstance(v, Some):
        return _pf_enc_value(v._0)
    if isinstance(v, None_):
        return None
    names = []
    for f in dataclasses.fields(v):
        names.append(f.name)
    positional = True
    for n in names:
        if not n.startswith(\"_\"):
            positional = False
    if positional:
        out = {\"type\": type(v).__name__}
        if names:
            out[\"fields\"] = []
            for n in names:
                out[\"fields\"].append(_pf_enc_value(getattr(v, n)))
        return out
    out = {}
    for n in names:
        key = n[0:-1] if n.endswith(\"_\") and keyword.iskeyword(n[0:-1]) else n
        out[key] = _pf_enc_value(getattr(v, n))
    return out" },
    Helper { name: "_pf_exists", group: 1, deps: &[], text: "def _pf_exists(f, xs):
    return any(map(f, xs))" },
    Helper { name: "_pf_filter", group: 1, deps: &[], text: "def _pf_filter(f, xs):
    return list(filter(f, xs))" },
    Helper { name: "_pf_find_index", group: 2, deps: &["#option"], text: "def _pf_find_index(f, xs):
    for p in enumerate(xs):
        if f(p[1]):
            return Some(p[0])
    return _None_" },
    Helper { name: "_pf_flatten", group: 1, deps: &[], text: "def _pf_flatten(xs):
    out = []
    for x in xs:
        out.extend(x)
    return out" },
    Helper { name: "_pf_flip", group: 3, deps: &[], text: "def _pf_flip(f, x, y):
    return f(y, x)" },
    Helper { name: "_pf_fmt_currency", group: 2, deps: &[], text: "def _pf_fmt_currency(sym, n, x):
    return sym + format(x, f\",.{n}f\")" },
    Helper { name: "_pf_fmt_fixed", group: 2, deps: &[], text: "def _pf_fmt_fixed(n, x):
    return format(x, f\".{n}f\")" },
    Helper { name: "_pf_fmt_grouped", group: 2, deps: &[], text: "def _pf_fmt_grouped(x):
    return format(x, \",\")" },
    Helper { name: "_pf_fmt_pad_left", group: 2, deps: &[], text: "def _pf_fmt_pad_left(w, fill, s):
    return s.rjust(w, fill)" },
    Helper { name: "_pf_fmt_pad_right", group: 2, deps: &[], text: "def _pf_fmt_pad_right(w, fill, s):
    return s.ljust(w, fill)" },
    Helper { name: "_pf_fmt_percent", group: 2, deps: &[], text: "def _pf_fmt_percent(n, x):
    return format(x, f\".{n}%\")" },
    Helper { name: "_pf_fmt_thousands", group: 2, deps: &[], text: "def _pf_fmt_thousands(n, x):
    return format(x, f\",.{n}f\")" },
    Helper { name: "_pf_fold", group: 1, deps: &["@functools"], text: "def _pf_fold(f, acc, xs):
    return functools.reduce(f, xs, acc)" },
    Helper { name: "_pf_forall", group: 1, deps: &[], text: "def _pf_forall(f, xs):
    return all(map(f, xs))" },
    Helper { name: "_pf_fst", group: 3, deps: &[], text: "def _pf_fst(p):
    return p[0]" },
    Helper { name: "_pf_group_by", group: 1, deps: &[], text: "def _pf_group_by(f, xs):
    groups = dict()
    for x in xs:
        groups.setdefault(f(x), []).append(x)
    return list(groups.items())" },
    Helper { name: "_pf_head", group: 2, deps: &["#option"], text: "def _pf_head(xs):
    return Some(xs[0]) if xs else _None_" },
    Helper { name: "_pf_id", group: 3, deps: &[], text: "def _pf_id(x):
    return x" },
    Helper { name: "_pf_ignore", group: 3, deps: &[], text: "def _pf_ignore(x):
    return None" },
    Helper { name: "_pf_indexed", group: 1, deps: &[], text: "def _pf_indexed(xs):
    return list(enumerate(xs))" },
    Helper { name: "_pf_init", group: 1, deps: &[], text: "def _pf_init(n, f):
    out = []
    for i in range(max(n, 0)):
        out.append(f(i))
    return out" },
    Helper { name: "_pf_insert_at", group: 1, deps: &[], text: "def _pf_insert_at(i, v, xs):
    out = list(xs)
    out.insert(max(i, 0), v)
    return out" },
    Helper { name: "_pf_is_empty", group: 1, deps: &[], text: "def _pf_is_empty(xs):
    return len(xs) == 0" },
    Helper { name: "_pf_iter", group: 1, deps: &[], text: "def _pf_iter(f, xs):
    for x in xs:
        f(x)
    return None" },
    Helper { name: "_pf_last", group: 2, deps: &["#option"], text: "def _pf_last(xs):
    return Some(xs[-1]) if xs else _None_" },
    Helper { name: "_pf_list_contains", group: 1, deps: &[], text: "def _pf_list_contains(x, xs):
    return x in xs" },
    Helper { name: "_pf_list_find", group: 2, deps: &["#option"], text: "def _pf_list_find(f, xs):
    return next(map(Some, filter(f, xs)), _None_)" },
    Helper { name: "_pf_list_get", group: 2, deps: &["#option"], text: "def _pf_list_get(i, xs):
    return Some(xs[i]) if 0 <= i < len(xs) else _None_" },
    Helper { name: "_pf_map", group: 1, deps: &[], text: "def _pf_map(f, xs):
    return list(map(f, xs))" },
    Helper { name: "_pf_map2", group: 1, deps: &[], text: "def _pf_map2(f, xs, ys):
    out = []
    for p in zip(xs, ys):
        out.append(f(p[0], p[1]))
    return out" },
    Helper { name: "_pf_map_add", group: 2, deps: &[], text: "def _pf_map_add(k, v, m):
    return dict(list(m.items()) + [[k, v]])" },
    Helper { name: "_pf_map_contains", group: 2, deps: &[], text: "def _pf_map_contains(k, m):
    return k in m" },
    Helper { name: "_pf_map_exists", group: 2, deps: &[], text: "def _pf_map_exists(f, m):
    for kv in m.items():
        if f(kv[0], kv[1]):
            return True
    return False" },
    Helper { name: "_pf_map_filter", group: 2, deps: &[], text: "def _pf_map_filter(f, m):
    out = dict()
    for kv in m.items():
        if f(kv[0], kv[1]):
            out[kv[0]] = kv[1]
    return out" },
    Helper { name: "_pf_map_find_or", group: 2, deps: &[], text: "def _pf_map_find_or(k, default, m):
    return m.get(k, default)" },
    Helper { name: "_pf_map_fold", group: 2, deps: &[], text: "def _pf_map_fold(f, acc, m):
    for kv in m.items():
        acc = f(acc, kv[0], kv[1])
    return acc" },
    Helper { name: "_pf_map_forall", group: 2, deps: &[], text: "def _pf_map_forall(f, m):
    for kv in m.items():
        if not f(kv[0], kv[1]):
            return False
    return True" },
    Helper { name: "_pf_map_is_empty", group: 2, deps: &[], text: "def _pf_map_is_empty(m):
    return not m" },
    Helper { name: "_pf_map_iter", group: 2, deps: &[], text: "def _pf_map_iter(f, m):
    for kv in m.items():
        f(kv[0], kv[1])
    return None" },
    Helper { name: "_pf_map_keys", group: 2, deps: &[], text: "def _pf_map_keys(m):
    return list(m.keys())" },
    Helper { name: "_pf_map_map", group: 2, deps: &[], text: "def _pf_map_map(f, m):
    out = dict()
    for kv in m.items():
        out[kv[0]] = f(kv[0], kv[1])
    return out" },
    Helper { name: "_pf_map_partition", group: 2, deps: &[], text: "def _pf_map_partition(f, m):
    yes = dict()
    no = dict()
    for kv in m.items():
        if f(kv[0], kv[1]):
            yes[kv[0]] = kv[1]
        else:
            no[kv[0]] = kv[1]
    return (yes, no)" },
    Helper { name: "_pf_map_remove", group: 2, deps: &[], text: "def _pf_map_remove(k, m):
    r = dict(m)
    r.pop(k, None)
    return r" },
    Helper { name: "_pf_map_to_list", group: 2, deps: &[], text: "def _pf_map_to_list(m):
    return list(m.items())" },
    Helper { name: "_pf_map_try_find", group: 2, deps: &["#option"], text: "def _pf_map_try_find(k, m):
    if k in m:
        return Some(m.get(k))
    return _None_" },
    Helper { name: "_pf_map_union", group: 2, deps: &[], text: "def _pf_map_union(a, b):
    out = dict(a)
    out.update(b)
    return out" },
    Helper { name: "_pf_map_values", group: 2, deps: &[], text: "def _pf_map_values(m):
    return list(m.values())" },
    Helper { name: "_pf_max", group: 2, deps: &["#option"], text: "def _pf_max(xs):
    return Some(max(xs)) if xs else _None_" },
    Helper { name: "_pf_max_by", group: 2, deps: &["#option"], text: "def _pf_max_by(f, xs):
    return Some(max(xs, key=f)) if xs else _None_" },
    Helper { name: "_pf_min", group: 2, deps: &["#option"], text: "def _pf_min(xs):
    return Some(min(xs)) if xs else _None_" },
    Helper { name: "_pf_min_by", group: 2, deps: &["#option"], text: "def _pf_min_by(f, xs):
    return Some(min(xs, key=f)) if xs else _None_" },
    Helper { name: "_pf_opt_contains", group: 2, deps: &["#option"], text: "def _pf_opt_contains(x, o):
    return isinstance(o, Some) and o._0 == x" },
    Helper { name: "_pf_opt_exists", group: 2, deps: &["#option"], text: "def _pf_opt_exists(f, o):
    return isinstance(o, Some) and f(o._0)" },
    Helper { name: "_pf_opt_flatten", group: 2, deps: &["#option"], text: "def _pf_opt_flatten(o):
    return o._0 if isinstance(o, Some) else _None_" },
    Helper { name: "_pf_opt_forall", group: 2, deps: &["#option"], text: "def _pf_opt_forall(f, o):
    return not isinstance(o, Some) or f(o._0)" },
    Helper { name: "_pf_opt_iter", group: 2, deps: &["#option"], text: "def _pf_opt_iter(f, o):
    if isinstance(o, Some):
        f(o._0)
    return None" },
    Helper { name: "_pf_opt_map2", group: 2, deps: &["#option"], text: "def _pf_opt_map2(f, a, b):
    if isinstance(a, Some) and isinstance(b, Some):
        return Some(f(a._0, b._0))
    return _None_" },
    Helper { name: "_pf_opt_or_else", group: 2, deps: &["#option"], text: "def _pf_opt_or_else(fallback, o):
    return o if isinstance(o, Some) else fallback" },
    Helper { name: "_pf_opt_to_list", group: 2, deps: &["#option"], text: "def _pf_opt_to_list(o):
    return [o._0] if isinstance(o, Some) else []" },
    Helper { name: "_pf_option_bind", group: 2, deps: &["#option"], text: "def _pf_option_bind(f, o):
    if isinstance(o, Some):
        return f(o._0)
    return _None_" },
    Helper { name: "_pf_option_filter", group: 2, deps: &["#option"], text: "def _pf_option_filter(f, o):
    return o if isinstance(o, Some) and f(o._0) else _None_" },
    Helper { name: "_pf_option_is_none", group: 2, deps: &["#option"], text: "def _pf_option_is_none(o):
    return not isinstance(o, Some)" },
    Helper { name: "_pf_option_is_some", group: 2, deps: &["#option"], text: "def _pf_option_is_some(o):
    return isinstance(o, Some)" },
    Helper { name: "_pf_option_map", group: 2, deps: &["#option"], text: "def _pf_option_map(f, o):
    if isinstance(o, Some):
        return Some(f(o._0))
    return _None_" },
    Helper { name: "_pf_option_to_result", group: 2, deps: &["#option", "#result"], text: "def _pf_option_to_result(err, o):
    if isinstance(o, Some):
        return Ok(o._0)
    return Error(err)" },
    Helper { name: "_pf_option_with_default", group: 2, deps: &["#option"], text: "def _pf_option_with_default(d, o):
    if isinstance(o, Some):
        return o._0
    return d" },
    Helper { name: "_pf_pairwise", group: 1, deps: &[], text: "def _pf_pairwise(xs):
    return list(zip(xs, xs[1:len(xs)]))" },
    Helper { name: "_pf_partition", group: 1, deps: &[], text: "def _pf_partition(f, xs):
    yes = []
    no = []
    for x in xs:
        if f(x):
            yes.append(x)
        else:
            no.append(x)
    return (yes, no)" },
    Helper { name: "_pf_range", group: 1, deps: &[], text: "def _pf_range(lo, hi):
    return list(range(lo, hi))" },
    Helper { name: "_pf_reduce", group: 2, deps: &["#option", "@functools"], text: "def _pf_reduce(f, xs):
    return Some(functools.reduce(f, xs)) if xs else _None_" },
    Helper { name: "_pf_remove_at", group: 1, deps: &[], text: "def _pf_remove_at(i, xs):
    out = list(xs)
    if 0 <= i < len(out):
        out.pop(i)
    return out" },
    Helper { name: "_pf_replicate", group: 1, deps: &[], text: "def _pf_replicate(n, x):
    return [x] * max(n, 0)" },
    Helper { name: "_pf_res_contains", group: 2, deps: &["#result"], text: "def _pf_res_contains(x, r):
    return isinstance(r, Ok) and r._0 == x" },
    Helper { name: "_pf_res_exists", group: 2, deps: &["#result"], text: "def _pf_res_exists(f, r):
    return isinstance(r, Ok) and f(r._0)" },
    Helper { name: "_pf_res_forall", group: 2, deps: &["#result"], text: "def _pf_res_forall(f, r):
    return not isinstance(r, Ok) or f(r._0)" },
    Helper { name: "_pf_res_iter", group: 2, deps: &["#result"], text: "def _pf_res_iter(f, r):
    if isinstance(r, Ok):
        f(r._0)
    return None" },
    Helper { name: "_pf_res_map2", group: 2, deps: &["#result"], text: "def _pf_res_map2(f, a, b):
    if isinstance(a, Error):
        return a
    if isinstance(b, Error):
        return b
    return Ok(f(a._0, b._0))" },
    Helper { name: "_pf_res_or_else", group: 2, deps: &["#result"], text: "def _pf_res_or_else(fallback, r):
    return r if isinstance(r, Ok) else fallback" },
    Helper { name: "_pf_res_to_list", group: 2, deps: &["#result"], text: "def _pf_res_to_list(r):
    return [r._0] if isinstance(r, Ok) else []" },
    Helper { name: "_pf_result_bind", group: 2, deps: &["#result"], text: "def _pf_result_bind(f, r):
    if isinstance(r, Ok):
        return f(r._0)
    return r" },
    Helper { name: "_pf_result_is_error", group: 2, deps: &["#result"], text: "def _pf_result_is_error(r):
    return isinstance(r, Error)" },
    Helper { name: "_pf_result_is_ok", group: 2, deps: &["#result"], text: "def _pf_result_is_ok(r):
    return isinstance(r, Ok)" },
    Helper { name: "_pf_result_map", group: 2, deps: &["#result"], text: "def _pf_result_map(f, r):
    if isinstance(r, Ok):
        return Ok(f(r._0))
    return r" },
    Helper { name: "_pf_result_map_error", group: 2, deps: &["#result"], text: "def _pf_result_map_error(f, r):
    if isinstance(r, Error):
        return Error(f(r._0))
    return r" },
    Helper { name: "_pf_result_to_option", group: 2, deps: &["#option", "#result"], text: "def _pf_result_to_option(r):
    if isinstance(r, Ok):
        return Some(r._0)
    return _None_" },
    Helper { name: "_pf_result_with_default", group: 2, deps: &["#result"], text: "def _pf_result_with_default(d, r):
    if isinstance(r, Ok):
        return r._0
    return d" },
    Helper { name: "_pf_rev", group: 1, deps: &[], text: "def _pf_rev(xs):
    return list(reversed(xs))" },
    Helper { name: "_pf_run", group: 5, deps: &[], text: "async def _pf_run(a):
    return await a" },
    Helper { name: "_pf_seq_collect", group: 2, deps: &["@itertools"], text: "def _pf_seq_collect(f, xs):
    return itertools.chain.from_iterable(map(f, xs))" },
    Helper { name: "_pf_seq_concat", group: 2, deps: &["@itertools"], text: "def _pf_seq_concat(xs, ys):
    return itertools.chain(xs, ys)" },
    Helper { name: "_pf_seq_contains", group: 2, deps: &[], text: "def _pf_seq_contains(x, xs):
    return x in xs" },
    Helper { name: "_pf_seq_distinct", group: 2, deps: &[], text: "def _pf_seq_distinct(xs):
    seen = set()
    for x in xs:
        if not x in seen:
            seen.add(x)
            yield x" },
    Helper { name: "_pf_seq_distinct_by", group: 2, deps: &[], text: "def _pf_seq_distinct_by(f, xs):
    seen = set()
    for x in xs:
        k = f(x)
        if not k in seen:
            seen.add(k)
            yield x" },
    Helper { name: "_pf_seq_drop", group: 2, deps: &["@itertools"], text: "def _pf_seq_drop(n, xs):
    return itertools.islice(xs, max(n, 0), None)" },
    Helper { name: "_pf_seq_drop_while", group: 2, deps: &["@itertools"], text: "def _pf_seq_drop_while(f, xs):
    return itertools.dropwhile(f, xs)" },
    Helper { name: "_pf_seq_exists", group: 2, deps: &[], text: "def _pf_seq_exists(f, xs):
    return any(map(f, xs))" },
    Helper { name: "_pf_seq_find", group: 2, deps: &["#option"], text: "def _pf_seq_find(f, xs):
    return next(map(Some, filter(f, xs)), _None_)" },
    Helper { name: "_pf_seq_flatten", group: 2, deps: &["@itertools"], text: "def _pf_seq_flatten(xs):
    return itertools.chain.from_iterable(xs)" },
    Helper { name: "_pf_seq_forall", group: 2, deps: &[], text: "def _pf_seq_forall(f, xs):
    return all(map(f, xs))" },
    Helper { name: "_pf_seq_get", group: 2, deps: &["#option", "@itertools"], text: "def _pf_seq_get(i, xs):
    return next(map(Some, itertools.islice(xs, max(i, 0), None)), _None_)" },
    Helper { name: "_pf_seq_head", group: 2, deps: &["#option"], text: "def _pf_seq_head(xs):
    return next(map(Some, xs), _None_)" },
    Helper { name: "_pf_seq_init", group: 2, deps: &[], text: "def _pf_seq_init(n, f):
    return map(f, range(max(n, 0)))" },
    Helper { name: "_pf_seq_init_inf", group: 2, deps: &["@itertools"], text: "def _pf_seq_init_inf(f):
    return map(f, itertools.count())" },
    Helper { name: "_pf_seq_is_empty", group: 2, deps: &["#option"], text: "def _pf_seq_is_empty(xs):
    return not isinstance(next(map(Some, xs), _None_), Some)" },
    Helper { name: "_pf_seq_iter", group: 2, deps: &[], text: "def _pf_seq_iter(f, xs):
    for x in xs:
        f(x)
    return None" },
    Helper { name: "_pf_seq_last", group: 2, deps: &["#option"], text: "def _pf_seq_last(xs):
    out = _None_
    for x in xs:
        out = Some(x)
    return out" },
    Helper { name: "_pf_seq_len", group: 2, deps: &[], text: "def _pf_seq_len(xs):
    return len(list(xs))" },
    Helper { name: "_pf_seq_max", group: 2, deps: &["#option"], text: "def _pf_seq_max(xs):
    items = list(xs)
    return Some(max(items)) if items else _None_" },
    Helper { name: "_pf_seq_min", group: 2, deps: &["#option"], text: "def _pf_seq_min(xs):
    items = list(xs)
    return Some(min(items)) if items else _None_" },
    Helper { name: "_pf_seq_pairwise", group: 2, deps: &["@itertools"], text: "def _pf_seq_pairwise(xs):
    return itertools.pairwise(xs)" },
    Helper { name: "_pf_seq_reduce", group: 2, deps: &["#option", "@functools"], text: "def _pf_seq_reduce(f, xs):
    items = list(xs)
    return Some(functools.reduce(f, items)) if items else _None_" },
    Helper { name: "_pf_seq_replicate", group: 2, deps: &["@itertools"], text: "def _pf_seq_replicate(n, x):
    return itertools.repeat(x, max(n, 0))" },
    Helper { name: "_pf_seq_sum_by", group: 2, deps: &[], text: "def _pf_seq_sum_by(f, xs):
    return sum(map(f, xs))" },
    Helper { name: "_pf_seq_take", group: 2, deps: &["@itertools"], text: "def _pf_seq_take(n, xs):
    return itertools.islice(xs, n)" },
    Helper { name: "_pf_seq_take_while", group: 2, deps: &["@itertools"], text: "def _pf_seq_take_while(f, xs):
    return itertools.takewhile(f, xs)" },
    Helper { name: "_pf_seq_unfold", group: 2, deps: &["#option"], text: "def _pf_seq_unfold(f, state):
    while True:
        step = f(state)
        if not isinstance(step, Some):
            return None
        pair = step._0
        yield pair[0]
        state = pair[1]" },
    Helper { name: "_pf_set_add", group: 2, deps: &[], text: "def _pf_set_add(x, s):
    return s.union([x])" },
    Helper { name: "_pf_set_contains", group: 2, deps: &[], text: "def _pf_set_contains(x, s):
    return x in s" },
    Helper { name: "_pf_set_difference", group: 2, deps: &[], text: "def _pf_set_difference(a, b):
    return a.difference(b)" },
    Helper { name: "_pf_set_exists", group: 2, deps: &[], text: "def _pf_set_exists(f, s):
    return any(map(f, s))" },
    Helper { name: "_pf_set_filter", group: 2, deps: &[], text: "def _pf_set_filter(f, s):
    return set(filter(f, s))" },
    Helper { name: "_pf_set_forall", group: 2, deps: &[], text: "def _pf_set_forall(f, s):
    return all(map(f, s))" },
    Helper { name: "_pf_set_intersect", group: 2, deps: &[], text: "def _pf_set_intersect(a, b):
    return a.intersection(b)" },
    Helper { name: "_pf_set_is_empty", group: 2, deps: &[], text: "def _pf_set_is_empty(s):
    return not s" },
    Helper { name: "_pf_set_is_subset", group: 2, deps: &[], text: "def _pf_set_is_subset(a, b):
    return a.issubset(b)" },
    Helper { name: "_pf_set_is_superset", group: 2, deps: &[], text: "def _pf_set_is_superset(a, b):
    return a.issuperset(b)" },
    Helper { name: "_pf_set_iter", group: 2, deps: &[], text: "def _pf_set_iter(f, s):
    for x in s:
        f(x)
    return None" },
    Helper { name: "_pf_set_map", group: 2, deps: &[], text: "def _pf_set_map(f, s):
    return set(map(f, s))" },
    Helper { name: "_pf_set_max", group: 2, deps: &["#option"], text: "def _pf_set_max(s):
    return Some(max(s)) if s else _None_" },
    Helper { name: "_pf_set_min", group: 2, deps: &["#option"], text: "def _pf_set_min(s):
    return Some(min(s)) if s else _None_" },
    Helper { name: "_pf_set_partition", group: 2, deps: &[], text: "def _pf_set_partition(f, s):
    yes = set()
    no = set()
    for x in s:
        if f(x):
            yes.add(x)
        else:
            no.add(x)
    return (yes, no)" },
    Helper { name: "_pf_set_remove", group: 2, deps: &[], text: "def _pf_set_remove(x, s):
    return s.difference([x])" },
    Helper { name: "_pf_set_union", group: 2, deps: &[], text: "def _pf_set_union(a, b):
    return a.union(b)" },
    Helper { name: "_pf_sign", group: 3, deps: &[], text: "def _pf_sign(x):
    return (x > 0) - (x < 0)" },
    Helper { name: "_pf_snd", group: 3, deps: &[], text: "def _pf_snd(p):
    return p[1]" },
    Helper { name: "_pf_sort", group: 1, deps: &[], text: "def _pf_sort(xs):
    return sorted(xs)" },
    Helper { name: "_pf_sort_by", group: 1, deps: &[], text: "def _pf_sort_by(f, xs):
    return sorted(xs, key=f)" },
    Helper { name: "_pf_sort_by_desc", group: 1, deps: &[], text: "def _pf_sort_by_desc(f, xs):
    return sorted(xs, key=f, reverse=True)" },
    Helper { name: "_pf_sort_desc", group: 1, deps: &[], text: "def _pf_sort_desc(xs):
    return sorted(xs, reverse=True)" },
    Helper { name: "_pf_split_at", group: 1, deps: &[], text: "def _pf_split_at(n, xs):
    m = max(n, 0)
    return (xs[0:m], xs[m:len(xs)])" },
    Helper { name: "_pf_str_concat", group: 2, deps: &[], text: "def _pf_str_concat(a, b):
    return a + b" },
    Helper { name: "_pf_str_contains", group: 2, deps: &[], text: "def _pf_str_contains(sub, s):
    return sub in s" },
    Helper { name: "_pf_str_ends_with", group: 2, deps: &[], text: "def _pf_str_ends_with(suf, s):
    return s.endswith(suf)" },
    Helper { name: "_pf_str_get", group: 2, deps: &["#option"], text: "def _pf_str_get(i, s):
    return Some(s[i]) if 0 <= i < len(s) else _None_" },
    Helper { name: "_pf_str_index_of", group: 2, deps: &["#option"], text: "def _pf_str_index_of(sub, s):
    i = s.find(sub)
    return Some(i) if i >= 0 else _None_" },
    Helper { name: "_pf_str_is_empty", group: 2, deps: &[], text: "def _pf_str_is_empty(s):
    return not s" },
    Helper { name: "_pf_str_join", group: 2, deps: &[], text: "def _pf_str_join(sep, xs):
    return sep.join(xs)" },
    Helper { name: "_pf_str_lower", group: 2, deps: &[], text: "def _pf_str_lower(s):
    return s.lower()" },
    Helper { name: "_pf_str_of_list", group: 2, deps: &[], text: "def _pf_str_of_list(xs):
    return \"\".join(xs)" },
    Helper { name: "_pf_str_repeat", group: 2, deps: &[], text: "def _pf_str_repeat(n, s):
    return s * max(n, 0)" },
    Helper { name: "_pf_str_replace", group: 2, deps: &[], text: "def _pf_str_replace(old, new, s):
    return s.replace(old, new)" },
    Helper { name: "_pf_str_rev", group: 2, deps: &[], text: "def _pf_str_rev(s):
    return \"\".join(reversed(s))" },
    Helper { name: "_pf_str_slice", group: 2, deps: &[], text: "def _pf_str_slice(start, end, s):
    return s[start:end]" },
    Helper { name: "_pf_str_split", group: 2, deps: &[], text: "def _pf_str_split(sep, s):
    return s.split(sep)" },
    Helper { name: "_pf_str_split_lines", group: 2, deps: &[], text: "def _pf_str_split_lines(s):
    return s.splitlines()" },
    Helper { name: "_pf_str_starts_with", group: 2, deps: &[], text: "def _pf_str_starts_with(pre, s):
    return s.startswith(pre)" },
    Helper { name: "_pf_str_strip", group: 2, deps: &[], text: "def _pf_str_strip(s):
    return s.strip()" },
    Helper { name: "_pf_str_to_float", group: 2, deps: &["#option"], text: "def _pf_str_to_float(s):
    try:
        return Some(float(s))
    except ValueError:
        return _None_" },
    Helper { name: "_pf_str_to_int", group: 2, deps: &["#option"], text: "def _pf_str_to_int(s):
    try:
        return Some(int(s))
    except ValueError:
        return _None_" },
    Helper { name: "_pf_str_trim_end", group: 2, deps: &[], text: "def _pf_str_trim_end(s):
    return s.rstrip()" },
    Helper { name: "_pf_str_trim_start", group: 2, deps: &[], text: "def _pf_str_trim_start(s):
    return s.lstrip()" },
    Helper { name: "_pf_str_upper", group: 2, deps: &[], text: "def _pf_str_upper(s):
    return s.upper()" },
    Helper { name: "_pf_sum_by", group: 1, deps: &[], text: "def _pf_sum_by(f, xs):
    return sum(map(f, xs))" },
    Helper { name: "_pf_tail", group: 2, deps: &["#option"], text: "def _pf_tail(xs):
    return Some(xs[1:len(xs)]) if xs else _None_" },
    Helper { name: "_pf_take", group: 1, deps: &[], text: "def _pf_take(n, xs):
    return xs[0:max(n, 0)]" },
    Helper { name: "_pf_take_while", group: 1, deps: &["@itertools"], text: "def _pf_take_while(f, xs):
    return list(itertools.takewhile(f, xs))" },
    Helper { name: "_pf_task_scope", group: 5, deps: &["@asyncio", "_pf_Async", "_pf_scope"], text: "def _pf_task_scope(body):
    async def run():
        async def scoped():
            async with asyncio.TaskGroup() as tg:
                _pf_scope.set(tg)
                return await body
        return await asyncio.create_task(scoped())
    return _pf_Async(run)" },
    Helper { name: "_pf_task_start", group: 5, deps: &["_pf_run", "_pf_scope", "_pf_Async", "@asyncio"], text: "def _pf_task_start(c):
    _pf_scope.get().create_task(_pf_run(c))
    return None" },
    Helper { name: "_pf_unzip", group: 1, deps: &[], text: "def _pf_unzip(xs):
    a = []
    b = []
    for p in xs:
        a.append(p[0])
        b.append(p[1])
    return (a, b)" },
    Helper { name: "_pf_update_at", group: 1, deps: &[], text: "def _pf_update_at(i, v, xs):
    out = list(xs)
    if 0 <= i < len(out):
        out[i] = v
    return out" },
    Helper { name: "_pf_windowed", group: 1, deps: &[], text: "def _pf_windowed(n, xs):
    if n <= 0:
        return []
    out = []
    for i in range(len(xs) - n + 1):
        out.append(xs[i:i + n])
    return out" },
    Helper { name: "_pf_zip", group: 1, deps: &[], text: "def _pf_zip(xs, ys):
    return list(zip(xs, ys))" },
    Helper { name: "_pf_scope", group: 5, deps: &["@contextvars"], text: "_pf_scope = contextvars.ContextVar(\"_pf_scope\")" },
];
