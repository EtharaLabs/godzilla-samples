//! Reading small structures from a command's parameters with serde's words for what is wrong:
//! a work plane's `surface` {point, normal} and a 3D dimension's reference {at, edge?}.
//!
//! As serde reads them from a `serde_json::Value`: an object's keys in sorted order (an unknown one
//! refused as it is met), the fields it lacks after (in declaration order); a list as the fields in
//! order; a fixed array of three numbers, too short or too long.

use crate::json::Value;

pub type R<T> = Result<T, String>;

/// A number (serde's f64).
pub fn f64_of(v: &Value) -> R<f64> {
    match v {
        Value::Num(n) => Ok(n.as_f64()),
        _ => Err(format!("invalid type: {}, expected f64", v.kind_name())),
    }
}

/// `[f64; 3]`.
pub fn arr3(v: &Value) -> R<[f64; 3]> {
    let Value::Arr(a) = v else {
        return Err(format!("invalid type: {}, expected an array of length 3", v.kind_name()));
    };
    let mut out = [0.0; 3];
    for i in 0..3 {
        match a.get(i) {
            Some(x) => out[i] = f64_of(x)?,
            None => return Err(format!("invalid length {}, expected an array of length 3", i)),
        }
    }
    if a.len() > 3 {
        return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
    }
    Ok(out)
}

/// `[[f64; 3]; 2]`.
pub fn arr3x2(v: &Value) -> R<[[f64; 3]; 2]> {
    let Value::Arr(a) = v else {
        return Err(format!("invalid type: {}, expected an array of length 2", v.kind_name()));
    };
    let mut out = [[0.0; 3]; 2];
    for i in 0..2 {
        match a.get(i) {
            Some(x) => out[i] = arr3(x)?,
            None => return Err(format!("invalid length {}, expected an array of length 2", i)),
        }
    }
    if a.len() > 2 {
        return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
    }
    Ok(out)
}

/// serde's list of the fields a struct has: `a`, `a` or `b`, one of `a`, `b`, `c`.
fn expected(fields: &[&str]) -> String {
    match fields.len() {
        0 => "there are no fields".to_string(),
        1 => format!("`{}`", fields[0]),
        2 => format!("`{}` or `{}`", fields[0], fields[1]),
        _ => format!("one of {}", fields.iter().map(|f| format!("`{}`", f)).collect::<Vec<_>>().join(", ")),
    }
}

/// A struct's fields, by name, as serde would deserialize them: `required` say which must be
/// there (the rest default). Each is read by `read(field index, value)`.
fn read_struct(
    v: &Value,
    name: &str,
    fields: &[&str],
    required: &[bool],
    read: &mut dyn FnMut(usize, &Value) -> R<()>,
) -> R<()> {
    match v {
        Value::Obj(m) => {
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort();
            keys.dedup();
            let mut got = vec![false; fields.len()];
            for k in keys {
                let Some(i) = fields.iter().position(|f| f == k) else {
                    return Err(format!("unknown field `{}`, expected {}", k, expected(fields)));
                };
                read(i, m.get(k).unwrap())?;
                got[i] = true;
            }
            for i in 0..fields.len() {
                if !got[i] && required[i] {
                    return Err(format!("missing field `{}`", fields[i]));
                }
            }
            Ok(())
        }
        Value::Arr(a) => {
            for i in 0..fields.len() {
                match a.get(i) {
                    Some(x) => read(i, x)?,
                    None => {
                        if required[i] {
                            return Err(format!(
                                "invalid length {}, expected struct {} with {} elements",
                                i,
                                name,
                                fields.len()
                            ));
                        }
                    }
                }
            }
            if a.len() > fields.len() {
                return Err(format!("invalid length {}, expected fewer elements in array", a.len()));
            }
            Ok(())
        }
        _ => Err(format!("invalid type: {}, expected struct {}", v.kind_name(), name)),
    }
}

/// A work plane's `surface`: {point: [x, y, z], normal: [x, y, z]}.
pub fn surface(v: &Value) -> R<([f64; 3], [f64; 3])> {
    let mut point = [0.0; 3];
    let mut normal = [0.0; 3];
    read_struct(v, "Surface", &["point", "normal"], &[true, true], &mut |i, x| {
        let q = arr3(x)?;
        if i == 0 {
            point = q;
        } else {
            normal = q;
        }
        Ok(())
    })?;
    Ok((point, normal))
}

/// A 3D dimension's reference: {at: [x, y, z], edge?: [[x, y, z], [x, y, z]]}.
pub fn ref3(v: &Value) -> R<([f64; 3], Option<[[f64; 3]; 2]>)> {
    let mut at = [0.0; 3];
    let mut edge = None;
    read_struct(v, "Ref3", &["at", "edge"], &[true, false], &mut |i, x| {
        if i == 0 {
            at = arr3(x)?;
        } else if !x.is_null() {
            edge = Some(arr3x2(x)?);
        } else {
            edge = None;
        }
        Ok(())
    })?;
    Ok((at, edge))
}
