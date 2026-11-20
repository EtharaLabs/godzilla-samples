// Own-property orders of builtin objects (matching the reference engine's enumeration order).

use crate::object::*;
use crate::realm::Intrinsics;
use crate::value::*;
use crate::vm::Vm;

enum Target {
    Glob(&'static str),
    Proto(&'static str),
    TaCtor,
    Intr(fn(&Intrinsics) -> Obj),
    Global,
}

const ORDERS: &[(Target, &[&str])] = &[
    (Target::Glob("Object"), &["length", "name", "prototype", "hasOwn", "groupBy", "keys", "getOwnPropertyNames", "getOwnPropertySymbols", "getPrototypeOf", "setPrototypeOf", "create", "defineProperty", "getOwnPropertyDescriptor", "getOwnPropertyDescriptors", "freeze", "preventExtensions", "isExtensible", "assign", "is", "values", "entries", "fromEntries", "defineProperties", "seal", "isSealed", "isFrozen"]),
    (Target::Proto("Object"), &["hasOwnProperty", "__defineGetter__", "__defineSetter__", "__lookupGetter__", "__lookupSetter__", "isPrototypeOf", "propertyIsEnumerable", "toString", "valueOf", "toLocaleString", "__proto__", "constructor"]),
    (Target::Glob("Function"), &["length", "name", "prototype"]),
    (Target::Proto("Function"), &["length", "name", "call", "apply", "bind", "toString", "caller", "arguments", "constructor", "@Symbol.hasInstance"]),
    (Target::Glob("Array"), &["length", "name", "prototype", "isArray", "of", "from", "fromAsync", "@Symbol.species"]),
    (Target::Proto("Array"), &["length", "push", "pop", "shift", "unshift", "slice", "indexOf", "includes", "join", "concat", "forEach", "map", "filter", "reduce", "reverse", "toString", "toLocaleString", "at", "find", "findIndex", "findLast", "findLastIndex", "some", "every", "fill", "lastIndexOf", "flat", "flatMap", "splice", "sort", "toReversed", "toSorted", "with", "toSpliced", "reduceRight", "copyWithin", "values", "keys", "entries", "constructor", "@Symbol.unscopables", "@Symbol.iterator"]),
    (Target::Glob("String"), &["length", "name", "prototype", "fromCharCode", "raw", "fromCodePoint"]),
    (Target::Proto("String"), &["toString", "valueOf", "charAt", "charCodeAt", "indexOf", "lastIndexOf", "toLocaleLowerCase", "toLocaleUpperCase", "normalize", "includes", "startsWith", "endsWith", "slice", "substring", "substr", "anchor", "link", "fontcolor", "fontsize", "big", "blink", "bold", "fixed", "italics", "small", "strike", "sub", "sup", "toUpperCase", "toLowerCase", "isWellFormed", "toWellFormed", "trim", "localeCompare", "toLocaleString", "concat", "repeat", "split", "at", "codePointAt", "trimStart", "trimEnd", "trimLeft", "trimRight", "padStart", "padEnd", "match", "search", "matchAll", "replace", "replaceAll", "constructor", "@Symbol.iterator"]),
    (Target::Glob("Number"), &["length", "name", "prototype", "MAX_SAFE_INTEGER", "MIN_SAFE_INTEGER", "MAX_VALUE", "MIN_VALUE", "POSITIVE_INFINITY", "NEGATIVE_INFINITY", "NaN", "EPSILON", "isNaN", "isFinite", "isSafeInteger", "isInteger", "parseInt", "parseFloat"]),
    (Target::Proto("Number"), &["toLocaleString", "toString", "valueOf", "toExponential", "toPrecision", "toFixed", "constructor"]),
    (Target::Glob("Boolean"), &["length", "name", "prototype"]),
    (Target::Proto("Boolean"), &["toString", "valueOf", "constructor"]),
    (Target::Glob("Symbol"), &["length", "name", "prototype", "iterator", "asyncIterator", "hasInstance", "isConcatSpreadable", "match", "matchAll", "replace", "search", "species", "split", "toPrimitive", "toStringTag", "unscopables", "dispose", "asyncDispose", "metadata", "for", "keyFor"]),
    (Target::Proto("Symbol"), &["toString", "valueOf", "description", "constructor", "@Symbol.toPrimitive", "@Symbol.toStringTag"]),
    (Target::Glob("BigInt"), &["length", "name", "prototype", "asIntN", "asUintN"]),
    (Target::Proto("BigInt"), &["toString", "valueOf", "toLocaleString", "constructor", "@Symbol.toStringTag"]),
    (Target::Glob("Math"), &["E", "LN10", "LN2", "LOG10E", "LOG2E", "PI", "SQRT1_2", "SQRT2", "abs", "floor", "ceil", "round", "trunc", "sqrt", "cbrt", "sign", "expm1", "log1p", "sinh", "cosh", "tanh", "asinh", "acosh", "atanh", "fround", "f16round", "clz32", "sumPrecise", "hypot", "imul", "random", "log", "log2", "log10", "exp", "sin", "cos", "tan", "atan", "asin", "acos", "pow", "atan2", "max", "min", "@Symbol.toStringTag"]),
    (Target::Glob("JSON"), &["stringify", "parse", "rawJSON", "isRawJSON", "@Symbol.toStringTag"]),
    (Target::Glob("Reflect"), &["get", "set", "has", "getOwnPropertyDescriptor", "deleteProperty", "ownKeys", "getPrototypeOf", "setPrototypeOf", "defineProperty", "apply", "construct", "isExtensible", "preventExtensions", "@Symbol.toStringTag"]),
    (Target::Glob("Promise"), &["length", "name", "prototype", "withResolvers", "resolve", "reject", "all", "race", "allSettled", "any", "allKeyed", "allSettledKeyed", "try", "@Symbol.species"]),
    (Target::Proto("Promise"), &["then", "catch", "finally", "constructor", "@Symbol.toStringTag"]),
    (Target::Glob("Map"), &["length", "name", "prototype", "groupBy", "@Symbol.species"]),
    (Target::Proto("Map"), &["set", "get", "has", "delete", "clear", "forEach", "values", "entries", "keys", "size", "constructor", "getOrInsert", "getOrInsertComputed", "@Symbol.iterator", "@Symbol.toStringTag"]),
    (Target::Glob("Set"), &["length", "name", "prototype", "@Symbol.species"]),
    (Target::Proto("Set"), &["add", "has", "delete", "clear", "forEach", "values", "entries", "keys", "size", "constructor", "union", "intersection", "difference", "symmetricDifference", "isSubsetOf", "isSupersetOf", "isDisjointFrom", "@Symbol.iterator", "@Symbol.toStringTag"]),
    (Target::Glob("WeakMap"), &["length", "name", "prototype"]),
    (Target::Proto("WeakMap"), &["set", "get", "getOrInsert", "getOrInsertComputed", "has", "delete", "constructor", "@Symbol.toStringTag"]),
    (Target::Glob("WeakSet"), &["length", "name", "prototype"]),
    (Target::Proto("WeakSet"), &["add", "has", "delete", "constructor", "@Symbol.toStringTag"]),
    (Target::Glob("WeakRef"), &["length", "name", "prototype"]),
    (Target::Proto("WeakRef"), &["deref", "constructor", "@Symbol.toStringTag"]),
    (Target::Glob("FinalizationRegistry"), &["length", "name", "prototype"]),
    (Target::Proto("FinalizationRegistry"), &["register", "unregister", "constructor", "@Symbol.toStringTag"]),
    (Target::Glob("Date"), &["length", "name", "prototype", "now", "parse", "UTC"]),
    (Target::Proto("Date"), &["getTime", "valueOf", "setTime", "getTimezoneOffset", "toTemporalInstant", "getFullYear", "getUTCFullYear", "getMonth", "getUTCMonth", "getDate", "getUTCDate", "getDay", "getUTCDay", "getHours", "getUTCHours", "getMinutes", "getUTCMinutes", "getSeconds", "getUTCSeconds", "getMilliseconds", "getUTCMilliseconds", "setFullYear", "getYear", "setYear", "setMonth", "setDate", "setHours", "setMinutes", "setSeconds", "setMilliseconds", "setUTCFullYear", "setUTCMonth", "setUTCDate", "setUTCHours", "setUTCMinutes", "setUTCSeconds", "setUTCMilliseconds", "toISOString", "toJSON", "toString", "toDateString", "toTimeString", "toUTCString", "toGMTString", "toLocaleString", "toLocaleDateString", "toLocaleTimeString", "constructor", "@Symbol.toPrimitive"]),
    (Target::Glob("RegExp"), &["length", "name", "input", "$_", "lastMatch", "$&", "lastParen", "$+", "leftContext", "$`", "rightContext", "$'", "$1", "$2", "$3", "$4", "$5", "$6", "$7", "$8", "$9", "prototype", "escape", "@Symbol.species"]),
    (Target::Proto("RegExp"), &["source", "flags", "global", "ignoreCase", "multiline", "dotAll", "sticky", "unicode", "hasIndices", "unicodeSets", "compile", "exec", "test", "toString", "constructor", "@Symbol.match", "@Symbol.replace", "@Symbol.search", "@Symbol.split", "@Symbol.matchAll"]),
    (Target::Glob("Error"), &["length", "name", "isError", "prototype", "stackTraceLimit", "captureStackTrace"]),
    (Target::Proto("Error"), &["name", "message", "toString", "stack", "constructor"]),
    (Target::Glob("TypeError"), &["length", "name", "prototype"]),
    (Target::Proto("TypeError"), &["name", "message", "constructor"]),
    (Target::Glob("RangeError"), &["length", "name", "prototype"]),
    (Target::Proto("RangeError"), &["name", "message", "constructor"]),
    (Target::Glob("SyntaxError"), &["length", "name", "prototype"]),
    (Target::Proto("SyntaxError"), &["name", "message", "constructor"]),
    (Target::Glob("ReferenceError"), &["length", "name", "prototype"]),
    (Target::Proto("ReferenceError"), &["name", "message", "constructor"]),
    (Target::Glob("EvalError"), &["length", "name", "prototype"]),
    (Target::Proto("EvalError"), &["name", "message", "constructor"]),
    (Target::Glob("URIError"), &["length", "name", "prototype"]),
    (Target::Proto("URIError"), &["name", "message", "constructor"]),
    (Target::Glob("AggregateError"), &["length", "name", "prototype"]),
    (Target::Proto("AggregateError"), &["name", "message", "constructor"]),
    (Target::Glob("SuppressedError"), &["length", "name", "prototype"]),
    (Target::Proto("SuppressedError"), &["name", "message", "constructor"]),
    (Target::Glob("ArrayBuffer"), &["length", "name", "prototype", "isView", "@Symbol.species"]),
    (Target::Proto("ArrayBuffer"), &["byteLength", "maxByteLength", "resizable", "detached", "immutable", "slice", "resize", "transfer", "transferToFixedLength", "transferToImmutable", "sliceToImmutable", "constructor", "@Symbol.toStringTag"]),
    (Target::Glob("SharedArrayBuffer"), &["length", "name", "prototype", "@Symbol.species"]),
    (Target::Proto("SharedArrayBuffer"), &["byteLength", "maxByteLength", "growable", "grow", "slice", "constructor", "@Symbol.toStringTag"]),
    (Target::Glob("DataView"), &["length", "name", "prototype"]),
    (Target::Proto("DataView"), &["buffer", "byteLength", "byteOffset", "getInt8", "setInt8", "getUint8", "setUint8", "getInt16", "setInt16", "getUint16", "setUint16", "getInt32", "setInt32", "getUint32", "setUint32", "getFloat16", "setFloat16", "getFloat32", "setFloat32", "getFloat64", "setFloat64", "getBigInt64", "getBigUint64", "setBigInt64", "setBigUint64", "constructor", "@Symbol.toStringTag"]),
    (Target::Glob("Atomics"), &["add", "sub", "and", "or", "xor", "exchange", "load", "store", "compareExchange", "isLockFree", "wait", "notify", "waitAsync", "pause", "@Symbol.toStringTag"]),
    (Target::Glob("Proxy"), &["length", "name", "revocable"]),
    (Target::Glob("Iterator"), &["length", "name", "from", "zip", "zipKeyed", "concat", "prototype"]),
    (Target::Proto("Iterator"), &["map", "filter", "take", "drop", "flatMap", "toArray", "forEach", "reduce", "some", "every", "find", "constructor", "@Symbol.iterator", "@Symbol.dispose", "@Symbol.toStringTag"]),
    (Target::Glob("Uint8Array"), &["length", "name", "prototype", "BYTES_PER_ELEMENT", "fromHex", "fromBase64"]),
    (Target::Proto("Uint8Array"), &["BYTES_PER_ELEMENT", "constructor", "toHex", "toBase64", "setFromHex", "setFromBase64"]),
    (Target::Glob("Int16Array"), &["length", "name", "prototype", "BYTES_PER_ELEMENT"]),
    (Target::Proto("Int16Array"), &["BYTES_PER_ELEMENT", "constructor"]),
    (Target::Glob("Float64Array"), &["length", "name", "prototype", "BYTES_PER_ELEMENT"]),
    (Target::Proto("Float64Array"), &["BYTES_PER_ELEMENT", "constructor"]),
    (Target::Glob("BigInt64Array"), &["length", "name", "prototype", "BYTES_PER_ELEMENT"]),
    (Target::Proto("BigInt64Array"), &["BYTES_PER_ELEMENT", "constructor"]),
    (Target::Proto("Int8Array"), &["BYTES_PER_ELEMENT", "constructor"]),
    (Target::Proto("Uint8ClampedArray"), &["BYTES_PER_ELEMENT", "constructor"]),
    (Target::Proto("Uint16Array"), &["BYTES_PER_ELEMENT", "constructor"]),
    (Target::Proto("Int32Array"), &["BYTES_PER_ELEMENT", "constructor"]),
    (Target::Proto("Uint32Array"), &["BYTES_PER_ELEMENT", "constructor"]),
    (Target::Proto("Float16Array"), &["BYTES_PER_ELEMENT", "constructor"]),
    (Target::Proto("Float32Array"), &["BYTES_PER_ELEMENT", "constructor"]),
    (Target::Proto("BigUint64Array"), &["BYTES_PER_ELEMENT", "constructor"]),
    (Target::Glob("DisposableStack"), &["length", "name", "prototype"]),
    (Target::Proto("DisposableStack"), &["use", "adopt", "defer", "dispose", "move", "disposed", "constructor", "@Symbol.toStringTag", "@Symbol.dispose"]),
    (Target::Glob("AsyncDisposableStack"), &["length", "name", "prototype"]),
    (Target::Proto("AsyncDisposableStack"), &["use", "adopt", "defer", "disposeAsync", "move", "disposed", "constructor", "@Symbol.toStringTag", "@Symbol.asyncDispose"]),
    (Target::TaCtor, &["length", "name", "prototype", "of", "from", "@Symbol.species"]),
    (Target::Intr(|i| i.typed_array_proto.clone()), &["forEach", "map", "filter", "reduce", "reduceRight", "some", "every", "find", "findIndex", "findLast", "findLastIndex", "indexOf", "lastIndexOf", "includes", "join", "fill", "reverse", "sort", "slice", "at", "keys", "values", "entries", "copyWithin", "toReversed", "toSorted", "with", "toString", "set", "subarray", "toLocaleString", "length", "byteLength", "byteOffset", "buffer", "constructor", "@Symbol.iterator", "@Symbol.toStringTag"]),
    (Target::Intr(|i| i.array_iterator_proto.clone()), &["next", "@Symbol.toStringTag"]),
    (Target::Intr(|i| i.map_iterator_proto.clone()), &["next", "@Symbol.toStringTag"]),
    (Target::Intr(|i| i.set_iterator_proto.clone()), &["next", "@Symbol.toStringTag"]),
    (Target::Intr(|i| i.string_iterator_proto.clone()), &["next", "@Symbol.toStringTag"]),
    (Target::Intr(|i| i.regexp_string_iterator_proto.clone()), &["next", "@Symbol.toStringTag"]),
    (Target::Intr(|i| i.iterator_helper_proto.clone()), &["next", "return", "@Symbol.toStringTag"]),
    (Target::Intr(|i| i.wrap_iterator_proto.clone()), &["next", "return"]),
    (Target::Intr(|i| i.generator_proto.clone()), &["next", "return", "throw", "constructor", "@Symbol.toStringTag"]),
    (Target::Intr(|i| i.generator_function_proto.clone()), &["constructor", "prototype", "@Symbol.toStringTag"]),
    (Target::Intr(|i| i.async_generator_proto.clone()), &["next", "return", "throw", "constructor", "@Symbol.toStringTag"]),
    (Target::Intr(|i| i.async_generator_function_proto.clone()), &["constructor", "prototype", "@Symbol.toStringTag"]),
    (Target::Intr(|i| i.async_function_proto.clone()), &["constructor", "@Symbol.toStringTag"]),
    (Target::Intr(|i| i.async_iterator_proto.clone()), &["@Symbol.asyncIterator", "@Symbol.asyncDispose"]),
];

fn key_matches(k: &PropKey, spec: &str) -> bool {
    match spec.strip_prefix('@') {
        Some(d) => matches!(k, PropKey::Sym(s) if s.0.description.as_ref().map_or(false, |x| x.eq_str(d))),
        None => k.eq_str(spec),
    }
}

/// Rebuild `o`'s property map so the listed keys come first, in order.
pub fn reorder_props(o: &Obj, order: &[&str]) {
    let mut b = o.borrow_mut();
    let keys: Vec<PropKey> = b.props.keys().to_vec();
    let mut entries: Vec<(PropKey, Prop)> = keys.iter().map(|k| (k.clone(), b.props.get(k).unwrap().clone())).collect();
    let mut out: Vec<(PropKey, Prop)> = Vec::with_capacity(entries.len());
    for spec in order {
        if let Some(pos) = entries.iter().position(|(k, _)| key_matches(k, spec)) {
            out.push(entries.remove(pos));
        }
    }
    out.extend(entries);
    b.props.clear();
    for (k, p) in out {
        b.props.insert(k, p);
    }
}

fn global_obj(vm: &Vm, name: &str) -> Option<Obj> {
    match vm.global.get_own_data(&PropKey::from_str(name)) {
        Some(Value::Obj(o)) => Some(o),
        _ => None,
    }
}

pub fn apply_orders(vm: &mut Vm) {
    for (t, order) in ORDERS {
        let o = match t {
            Target::Glob(n) => global_obj(vm, n),
            Target::Proto(n) => global_obj(vm, n).and_then(|c| match c.get_own_data(&PropKey::from_str("prototype")) {
                Some(Value::Obj(p)) => Some(p),
                _ => None,
            }),
            Target::TaCtor => Some(vm.intr.typed_array_ctor.clone()),
            Target::Intr(f) => Some(f(&vm.intr)),
            Target::Global => None,
        };
        if let Some(o) = o {
            reorder_props(&o, order);
        }
    }
}

/// Global object property order (applied once the runtime globals exist).
const GLOBAL_ORDER: &[&str] = &["undefined", "NaN", "Infinity", "globalThis", "Function", "Object", "Symbol", "Iterator", "Array", "String", "Number", "Boolean", "BigInt", "Math", "Error", "TypeError", "RangeError", "ReferenceError", "SyntaxError", "EvalError", "URIError", "AggregateError", "SuppressedError", "Reflect", "Proxy", "Promise", "JSON", "Map", "Set", "WeakMap", "WeakSet", "Date", "ArrayBuffer", "Int8Array", "Uint8Array", "Uint8ClampedArray", "Int16Array", "Uint16Array", "Int32Array", "Uint32Array", "Float16Array", "Float32Array", "Float64Array", "BigInt64Array", "BigUint64Array", "DataView", "SharedArrayBuffer", "RegExp", "print", "parseInt", "parseFloat", "isNaN", "isFinite", "escape", "unescape", "encodeURIComponent", "encodeURI", "decodeURIComponent", "decodeURI", "eval", "console", "$262", "Atomics", "WeakRef", "FinalizationRegistry", "DisposableStack", "AsyncDisposableStack", "ShadowRealm", "Temporal", "Intl", "setTimeout", "setInterval", "clearTimeout", "clearInterval", "setImmediate", "process", "fs", "__fs_native", "__http_server", "DOMException", "Event", "CustomEvent", "EventTarget", "AbortSignal", "AbortController", "MessageEvent", "CloseEvent", "ErrorEvent", "PromiseRejectionEvent", "MessagePort", "MessageChannel", "BroadcastChannel", "TextEncoder", "TextDecoder", "btoa", "atob", "structuredClone", "__serializeForClone", "__deserializeClone", "URLSearchParams", "URL", "URLPattern", "ReadableStream", "ReadableStreamDefaultReader", "ReadableStreamDefaultController", "ReadableStreamBYOBReader", "ReadableByteStreamController", "ReadableStreamBYOBRequest", "WritableStream", "WritableStreamDefaultWriter", "WritableStreamDefaultController", "TransformStream", "TransformStreamDefaultController", "ByteLengthQueuingStrategy", "CountQueuingStrategy", "TextEncoderStream", "TextDecoderStream", "CompressionStream", "DecompressionStream", "Blob", "File", "FormData", "Headers", "Request", "Response", "fetch", "WebSocket", "EventSource", "Lumen", "Crypto", "SubtleCrypto", "crypto", "CryptoKey", "navigator", "self", "Performance", "performance", "WebAssembly", "__net", "__udp", "__tls", "__sqlite", "__dns", "global", "Buffer", "__lumenHpackHuffman", "__lumenHttp2Codec", "__lumenInitWorkerThread", "__lumenPostgres", "__lumenMySQL", "__lumenSQL", "__lumenRedisClient", "__lumenBunCookies", "__lumenFileSystemRouter", "__lumenS3", "__lumenGenerateHeapSnapshot", "Bun", "__lumenStripTypeScriptTypes", "require", "__runMain", "__esmBuiltin", "__esmBuiltinSources", "__builtinNames", "__lumenWorkerOps", "Worker", "queueMicrotask", "onerror", "onunhandledrejection", "reportError"];

pub fn apply_global_order(vm: &mut Vm) {
    let g = vm.global.clone();
    reorder_props(&g, GLOBAL_ORDER);
}
