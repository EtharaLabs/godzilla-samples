// performance (Performance + user timing marks/measures), navigator, self.

use super::*;
use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};
use std::cell::RefCell;

thread_local! {
    static START: std::cell::Cell<Option<std::time::Instant>> = std::cell::Cell::new(None);
    static TIME_ORIGIN: RefCell<f64> = RefCell::new(0.0);
    /// the performance entry buffer (shared by mark/measure/getEntries*)
    static BUFFER: RefCell<Option<Obj>> = RefCell::new(None);
}

/// Milliseconds since the performance time origin (set when the runtime finishes setting up).
pub fn perf_now() -> f64 {
    match START.with(|s| s.get()) {
        Some(t) => t.elapsed().as_secs_f64() * 1000.0,
        None => 0.0,
    }
}

fn now(_vm: &Vm) -> f64 {
    perf_now()
}

pub fn setup(vm: &mut Vm) {
    // navigator / self come before Performance in the reference's global order
    let nav = vm.new_object();
    nav.set_prop(key("userAgent"), Value::str("lumen"), ENUMERABLE | CONFIGURABLE);
    set_global(vm, "navigator", Value::Obj(nav));
    let g = vm.global.clone();
    set_global(vm, "self", Value::Obj(g));

    // time origin: wall clock at process start
    START.with(|s| s.set(Some(std::time::Instant::now())));
    let origin = crate::datetime::now_ms();
    TIME_ORIGIN.with(|t| *t.borrow_mut() = origin);

    let (c, p) = make_class(vm, "Performance", "Performance.prototype", 0, performance_ctor, None);
    method(vm, &p, "now", 0, perf_now_native);
    getter(vm, &p, "timeOrigin", perf_time_origin);
    method(vm, &p, "toJSON", 0, perf_to_json);
    set_global(vm, "Performance", Value::Obj(c));

    // PerformanceEntry / PerformanceMark / PerformanceMeasure (not globals)
    let (_c, ep) = make_class(vm, "PerformanceEntry", "PerformanceEntry.prototype", 4, perf_entry_ctor, None);
    method(vm, &ep, "toJSON", 0, perf_entry_to_json);
    make_class(vm, "PerformanceMark", "PerformanceMark.prototype", 2, perf_mark_ctor, Some("PerformanceEntry"));
    make_class(vm, "PerformanceMeasure", "PerformanceMeasure.prototype", 4, perf_measure_ctor, Some("PerformanceEntry"));

    let buf = vm.new_array(Vec::new());
    BUFFER.with(|b| *b.borrow_mut() = Some(buf));

    let perf = Obj::new(Some(p), ObjKind::Ordinary);
    let f = plain_fn(vm, "mark", 2, perf_mark);
    perf.set_prop(key("mark"), Value::Obj(f), WEC);
    let f = plain_fn(vm, "measure", 3, perf_measure);
    perf.set_prop(key("measure"), Value::Obj(f), WEC);
    let f = plain_fn(vm, "clearMarks", 1, perf_clear_marks);
    perf.set_prop(key("clearMarks"), Value::Obj(f), WEC);
    let f = plain_fn(vm, "clearMeasures", 1, perf_clear_measures);
    perf.set_prop(key("clearMeasures"), Value::Obj(f), WEC);
    let f = vm.native_fn("", 0, perf_get_entries);
    perf.set_prop(key("getEntries"), Value::Obj(f), WEC);
    let f = vm.native_fn("", 2, perf_get_entries_by_name);
    perf.set_prop(key("getEntriesByName"), Value::Obj(f), WEC);
    let f = vm.native_fn("", 1, perf_get_entries_by_type);
    perf.set_prop(key("getEntriesByType"), Value::Obj(f), WEC);
    let f = vm.native_fn("", 0, perf_clear_resource_timings);
    perf.set_prop(key("clearResourceTimings"), Value::Obj(f), WEC);
    set_global(vm, "performance", Value::Obj(perf));
}

fn performance_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    Ok(Value::Obj(new_this(vm, a, "Performance.prototype")?))
}

fn perf_now_native(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Num(now(vm)))
}

fn perf_time_origin(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    Ok(Value::Num(TIME_ORIGIN.with(|t| *t.borrow())))
}

fn perf_to_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let t = get(vm, &a.this, "timeOrigin")?;
    Ok(Value::Obj(plain(vm, vec![("timeOrigin", t)])))
}

fn entry_init(vm: &mut Vm, this: &Value, name: Value, ty: Value, start: Value, dur: Value) -> JsResult<()> {
    set(vm, this, "name", name)?;
    set(vm, this, "entryType", ty)?;
    set(vm, this, "startTime", start)?;
    set(vm, this, "duration", dur)?;
    Ok(())
}

fn perf_entry_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ov = Value::Obj(new_this(vm, a, "PerformanceEntry.prototype")?);
    entry_init(vm, &ov, a.arg(0), a.arg(1), a.arg(2), a.arg(3))?;
    Ok(ov)
}

fn perf_entry_to_json(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let n = get(vm, &a.this, "name")?;
    let t = get(vm, &a.this, "entryType")?;
    let s = get(vm, &a.this, "startTime")?;
    let d = get(vm, &a.this, "duration")?;
    Ok(Value::Obj(plain(vm, vec![("name", n), ("entryType", t), ("startTime", s), ("duration", d)])))
}

fn mark_init(vm: &mut Vm, this: &Value, name: Value, options: &Value) -> JsResult<()> {
    let start = if options.truthy() {
        let st = get(vm, options, "startTime")?;
        if st.is_undefined() {
            Value::Num(now(vm))
        } else {
            get(vm, options, "startTime")?
        }
    } else {
        Value::Num(now(vm))
    };
    entry_init(vm, this, name, Value::str("mark"), start, Value::Num(0.0))?;
    let detail = if options.truthy() { get(vm, options, "detail")? } else { options.clone() };
    let detail = if detail.is_nullish() { Value::Null } else { detail };
    set(vm, this, "detail", detail)?;
    Ok(())
}

fn perf_mark_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ov = Value::Obj(new_this(vm, a, "PerformanceMark.prototype")?);
    mark_init(vm, &ov, a.arg(0), &a.arg(1))?;
    Ok(ov)
}

fn measure_init(vm: &mut Vm, this: &Value, name: Value, start: Value, dur: Value, detail: Value) -> JsResult<()> {
    entry_init(vm, this, name, Value::str("measure"), start, dur)?;
    let detail = if detail.is_nullish() { Value::Null } else { detail };
    set(vm, this, "detail", detail)?;
    Ok(())
}

fn perf_measure_ctor(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ov = Value::Obj(new_this(vm, a, "PerformanceMeasure.prototype")?);
    measure_init(vm, &ov, a.arg(0), a.arg(1), a.arg(2), a.arg(3))?;
    Ok(ov)
}

fn buffer(vm: &mut Vm) -> Obj {
    BUFFER.with(|b| b.borrow().clone()).unwrap_or_else(|| vm.new_array(Vec::new()))
}

fn record(vm: &mut Vm, entry: Value) -> JsResult<Value> {
    let b = Value::Obj(buffer(vm));
    arr_push(vm, &b, entry.clone())?;
    Ok(entry)
}

fn perf_mark(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let p = reg(vm, "PerformanceMark.prototype");
    let ov = Value::Obj(Obj::new(Some(p), ObjKind::Ordinary));
    mark_init(vm, &ov, a.arg(0), &a.arg(1))?;
    record(vm, ov)
}

/// resolveMark: numbers pass through, names resolve to the latest mark's startTime.
fn resolve_mark(vm: &mut Vm, v: &Value) -> JsResult<Value> {
    if let Value::Num(_) = v {
        return Ok(v.clone());
    }
    with_frame(vm, "resolveMark", |vm| resolve_mark_by_name(vm, v))
}

fn resolve_mark_by_name(vm: &mut Vm, v: &Value) -> JsResult<Value> {
    let b = Value::Obj(buffer(vm));
    let items = list_items(vm, &b)?;
    for e in items.iter().rev() {
        let t = get(vm, e, "entryType")?;
        if !Value::strict_eq(&t, &Value::str("mark")) {
            continue;
        }
        let n = get(vm, e, "name")?;
        if Value::strict_eq(&n, v) {
            return get(vm, e, "startTime");
        }
    }
    let shown = js_string(vm, v)?;
    vm.throw_error("Error", format!("The \"{}\" performance mark has not been set", shown))
}

fn perf_measure(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let name = a.arg(0);
    let so = a.arg(1);
    let end_mark = a.arg(2);
    let p = reg(vm, "PerformanceMeasure.prototype");
    let ov = Value::Obj(Obj::new(Some(p), ObjKind::Ordinary));
    if so.truthy() && is_object_type(&so) {
        let sv = get(vm, &so, "start")?;
        let mut start = resolve_mark(vm, &sv)?;
        let ev = get(vm, &so, "end")?;
        let mut end = if !ev.is_undefined() {
            let ev2 = get(vm, &so, "end")?;
            resolve_mark(vm, &ev2)?
        } else {
            Value::Num(now(vm))
        };
        let dur = get(vm, &so, "duration")?;
        if !dur.is_undefined() {
            let st = get(vm, &so, "start")?;
            if !st.is_undefined() {
                let d = get(vm, &so, "duration")?;
                end = vm.op_add(&start, &d)?;
            }
        }
        let d = vm.op_arith(crate::bytecode::Op::Sub, &end, &start)?;
        let detail = get(vm, &so, "detail")?;
        start = start.clone();
        measure_init(vm, &ov, name, start, d, detail)?;
        return record(vm, ov);
    }
    let start = if !so.is_undefined() { resolve_mark(vm, &so)? } else { Value::Num(0.0) };
    let end = if !end_mark.is_undefined() { resolve_mark(vm, &end_mark)? } else { Value::Num(now(vm)) };
    let d = vm.op_arith(crate::bytecode::Op::Sub, &end, &start)?;
    measure_init(vm, &ov, name, start, d, Value::Undefined)?;
    record(vm, ov)
}

fn clear_type(vm: &mut Vm, ty: &str, name: &Value) -> JsResult<()> {
    let b = Value::Obj(buffer(vm));
    let items = list_items(vm, &b)?;
    for i in (0..items.len()).rev() {
        let t = get(vm, &items[i], "entryType")?;
        if !Value::strict_eq(&t, &Value::str(ty)) {
            continue;
        }
        let matches = if name.is_undefined() {
            true
        } else {
            let n = get(vm, &items[i], "name")?;
            Value::strict_eq(&n, name)
        };
        if matches {
            invoke(vm, &b, "splice", &[Value::Num(i as f64), Value::Num(1.0)])?;
        }
    }
    Ok(())
}

fn perf_clear_marks(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    clear_type(vm, "mark", &a.arg(0))?;
    Ok(Value::Undefined)
}

fn perf_clear_measures(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    clear_type(vm, "measure", &a.arg(0))?;
    Ok(Value::Undefined)
}

fn perf_clear_resource_timings(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    clear_type(vm, "resource", &Value::Undefined)?;
    Ok(Value::Undefined)
}

fn perf_get_entries(vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let b = Value::Obj(buffer(vm));
    let items = list_items(vm, &b)?;
    Ok(array(vm, items))
}

fn perf_get_entries_by_name(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let name = a.arg(0);
    let ty = a.arg(1);
    let b = Value::Obj(buffer(vm));
    let mut out = Vec::new();
    for e in list_items(vm, &b)? {
        let n = get(vm, &e, "name")?;
        if !Value::strict_eq(&n, &name) {
            continue;
        }
        if !ty.is_undefined() {
            let t = get(vm, &e, "entryType")?;
            if !Value::strict_eq(&t, &ty) {
                continue;
            }
        }
        out.push(e);
    }
    Ok(array(vm, out))
}

fn perf_get_entries_by_type(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let ty = a.arg(0);
    let b = Value::Obj(buffer(vm));
    let mut out = Vec::new();
    for e in list_items(vm, &b)? {
        let t = get(vm, &e, "entryType")?;
        if Value::strict_eq(&t, &ty) {
            out.push(e);
        }
    }
    Ok(array(vm, out))
}
