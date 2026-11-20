// The Math object.

use crate::object::*;
use crate::value::*;
use crate::vm::{JsResult, Vm};

pub fn setup(vm: &mut Vm) {
    let m = vm.new_object();
    for (n, v) in [
        ("E", std::f64::consts::E),
        ("LN10", std::f64::consts::LN_10),
        ("LN2", std::f64::consts::LN_2),
        ("LOG10E", std::f64::consts::LOG10_E),
        ("LOG2E", std::f64::consts::LOG2_E),
        ("PI", std::f64::consts::PI),
        ("SQRT1_2", std::f64::consts::FRAC_1_SQRT_2),
        ("SQRT2", std::f64::consts::SQRT_2),
    ] {
        m.set_prop(PropKey::from_str(n), Value::Num(v), 0);
    }
    let fns: &[(&str, u32, NativeFn)] = &[
        ("abs", 1, |vm, a| unary(vm, a, f64::abs)),
        ("floor", 1, |vm, a| unary(vm, a, f64::floor)),
        ("ceil", 1, |vm, a| unary(vm, a, f64::ceil)),
        ("round", 1, |vm, a| unary(vm, a, js_round)),
        ("trunc", 1, |vm, a| unary(vm, a, f64::trunc)),
        ("sqrt", 1, |vm, a| unary(vm, a, f64::sqrt)),
        ("cbrt", 1, |vm, a| unary(vm, a, f64::cbrt)),
        ("sign", 1, |vm, a| unary(vm, a, js_sign)),
        ("expm1", 1, |vm, a| unary(vm, a, f64::exp_m1)),
        ("log1p", 1, |vm, a| unary(vm, a, f64::ln_1p)),
        ("sinh", 1, |vm, a| unary(vm, a, f64::sinh)),
        ("cosh", 1, |vm, a| unary(vm, a, f64::cosh)),
        ("tanh", 1, |vm, a| unary(vm, a, f64::tanh)),
        ("asinh", 1, |vm, a| unary(vm, a, js_asinh)),
        ("acosh", 1, |vm, a| unary(vm, a, f64::acosh)),
        ("atanh", 1, |vm, a| unary(vm, a, f64::atanh)),
        ("fround", 1, |vm, a| unary(vm, a, |x| x as f32 as f64)),
        ("f16round", 1, |vm, a| unary(vm, a, crate::builtins::typedarray::f16_round)),
        ("clz32", 1, clz32),
        ("sumPrecise", 1, sum_precise),
        ("hypot", 2, hypot),
        ("imul", 2, imul),
        ("random", 0, random),
        ("log", 1, |vm, a| unary(vm, a, f64::ln)),
        ("log2", 1, |vm, a| unary(vm, a, f64::log2)),
        ("log10", 1, |vm, a| unary(vm, a, f64::log10)),
        ("exp", 1, |vm, a| unary(vm, a, f64::exp)),
        ("sin", 1, |vm, a| unary(vm, a, f64::sin)),
        ("cos", 1, |vm, a| unary(vm, a, f64::cos)),
        ("tan", 1, |vm, a| unary(vm, a, f64::tan)),
        ("atan", 1, |vm, a| unary(vm, a, f64::atan)),
        ("asin", 1, |vm, a| unary(vm, a, f64::asin)),
        ("acos", 1, |vm, a| unary(vm, a, f64::acos)),
        ("pow", 2, pow),
        ("atan2", 2, atan2),
        ("max", 2, max),
        ("min", 2, min),
    ];
    for (n, l, f) in fns {
        vm.def_method(&m, n, *l, *f);
    }
    vm.set_tag(&m, "Math");
    vm.def_global("Math", Value::Obj(m));
}

fn js_round(x: f64) -> f64 {
    if !x.is_finite() || x == 0.0 {
        return x;
    }
    if x > 0.0 && x < 0.5 {
        return 0.0;
    }
    if x < 0.0 && x >= -0.5 {
        return -0.0;
    }
    let f = x.floor();
    if x - f >= 0.5 {
        f + 1.0
    } else {
        f
    }
}

fn js_sign(x: f64) -> f64 {
    if x.is_nan() || x == 0.0 {
        x
    } else if x > 0.0 {
        1.0
    } else {
        -1.0
    }
}

fn js_asinh(x: f64) -> f64 {
    if x == 0.0 || !x.is_finite() {
        return x;
    }
    x.asinh()
}

fn unary(vm: &mut Vm, a: &Args, f: fn(f64) -> f64) -> JsResult<Value> {
    let x = match a.args.first() {
        Some(Value::Num(n)) => *n,
        _ => vm.to_number(&a.arg(0))?,
    };
    Ok(Value::Num(f(x)))
}

fn clz32(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let n = vm.to_uint32(&a.arg(0))?;
    Ok(Value::Num(n.leading_zeros() as f64))
}

fn imul(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let x = vm.to_int32(&a.arg(0))?;
    let y = vm.to_int32(&a.arg(1))?;
    Ok(Value::Num(x.wrapping_mul(y) as f64))
}

fn pow(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let x = vm.to_number(&a.arg(0))?;
    let y = vm.to_number(&a.arg(1))?;
    Ok(Value::Num(crate::vm::js_pow(x, y)))
}

fn atan2(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let y = vm.to_number(&a.arg(0))?;
    let x = vm.to_number(&a.arg(1))?;
    Ok(Value::Num(y.atan2(x)))
}

fn max(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut r = f64::NEG_INFINITY;
    let mut nan = false;
    for v in a.args {
        let n = match v {
            Value::Num(n) => *n,
            _ => vm.to_number(v)?,
        };
        if n.is_nan() {
            nan = true;
        } else if n > r || (n == 0.0 && r == 0.0 && !n.is_sign_negative()) {
            r = n;
        }
    }
    Ok(Value::Num(if nan { f64::NAN } else { r }))
}

fn min(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut r = f64::INFINITY;
    let mut nan = false;
    for v in a.args {
        let n = match v {
            Value::Num(n) => *n,
            _ => vm.to_number(v)?,
        };
        if n.is_nan() {
            nan = true;
        } else if n < r || (n == 0.0 && r == 0.0 && n.is_sign_negative()) {
            r = n;
        }
    }
    Ok(Value::Num(if nan { f64::NAN } else { r }))
}

fn hypot(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let mut nums = Vec::new();
    for v in a.args {
        nums.push(vm.to_number(v)?);
    }
    if nums.iter().any(|n| n.is_infinite()) {
        return Ok(Value::Num(f64::INFINITY));
    }
    if nums.iter().any(|n| n.is_nan()) {
        return Ok(Value::Num(f64::NAN));
    }
    // plain sum of squares (no scaling), like the reference engine
    let mut sum = 0.0f64;
    for n in &nums {
        sum += n * n;
    }
    Ok(Value::Num(sum.sqrt()))
}

thread_local! {
    static RNG: std::cell::Cell<u64> = std::cell::Cell::new(0);
}

pub fn random_u64() -> u64 {
    RNG.with(|r| {
        let mut s = r.get();
        if s == 0 {
            let mut buf = [0u8; 8];
            if let Ok(mut f) = std::fs::File::open("/dev/urandom") {
                use std::io::Read;
                let _ = f.read_exact(&mut buf);
            }
            s = u64::from_le_bytes(buf) | 1;
        }
        // xorshift64*
        s ^= s >> 12;
        s ^= s << 25;
        s ^= s >> 27;
        r.set(s);
        s.wrapping_mul(0x2545F4914F6CDD1D)
    })
}

fn random(_vm: &mut Vm, _a: &Args) -> JsResult<Value> {
    let x = (random_u64() >> 11) as f64 / (1u64 << 53) as f64;
    Ok(Value::Num(x))
}

fn sum_precise(vm: &mut Vm, a: &Args) -> JsResult<Value> {
    let items = a.arg(0);
    if !items.is_object() {
        return vm.throw_type("Math.sumPrecise requires an iterable");
    }
    let vals = vm.iterate_to_vec(&items)?;
    let mut nums = Vec::new();
    for v in vals {
        match v {
            Value::Num(n) => nums.push(n),
            _ => return vm.throw_type("Math.sumPrecise: value is not a number"),
        }
    }
    if nums.is_empty() {
        return Ok(Value::Num(-0.0));
    }
    if nums.iter().any(|n| n.is_nan()) {
        return Ok(Value::Num(f64::NAN));
    }
    let pinf = nums.iter().any(|n| *n == f64::INFINITY);
    let ninf = nums.iter().any(|n| *n == f64::NEG_INFINITY);
    if pinf && ninf {
        return Ok(Value::Num(f64::NAN));
    }
    if pinf {
        return Ok(Value::Num(f64::INFINITY));
    }
    if ninf {
        return Ok(Value::Num(f64::NEG_INFINITY));
    }
    if nums.iter().all(|n| *n == 0.0 && n.is_sign_negative()) {
        return Ok(Value::Num(-0.0));
    }
    // Shewchuk's algorithm (exact partials)
    let mut partials: Vec<f64> = Vec::new();
    for mut x in nums {
        let mut i = 0;
        for j in 0..partials.len() {
            let mut y = partials[j];
            if x.abs() < y.abs() {
                std::mem::swap(&mut x, &mut y);
            }
            let hi = x + y;
            let lo = y - (hi - x);
            if lo != 0.0 {
                partials[i] = lo;
                i += 1;
            }
            x = hi;
        }
        partials.truncate(i);
        partials.push(x);
    }
    let mut hi = 0.0;
    while let Some(x) = partials.pop() {
        let y = hi;
        hi = x + y;
        let lo = y - (hi - x);
        if lo != 0.0 {
            if let Some(p) = partials.last() {
                if (lo < 0.0) == (*p < 0.0) {
                    let y2 = lo * 2.0;
                    let x2 = hi + y2;
                    if y2 == x2 - hi {
                        hi = x2;
                    }
                }
            }
            break;
        }
    }
    Ok(Value::Num(hi))
}
