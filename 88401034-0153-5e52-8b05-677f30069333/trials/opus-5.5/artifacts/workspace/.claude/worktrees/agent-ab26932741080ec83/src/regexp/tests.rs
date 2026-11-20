//! Unit tests for the regexp engine.

use super::*;

fn u(s: &str) -> Vec<u16> {
    s.encode_utf16().collect()
}

fn flags(f: &str) -> RegexFlags {
    parse_flags(&u(f)).unwrap()
}

fn exec(p: &str, f: &str, s: &str) -> Option<Vec<Option<(usize, usize)>>> {
    let re = compile(&u(p), flags(f)).unwrap();
    re.exec(&u(s), 0)
}

fn err(p: &str, f: &str) -> String {
    compile(&u(p), flags(f)).unwrap_err()
}

#[test]
fn basic_matching() {
    assert_eq!(exec("a(b)c", "", "xabc"), Some(vec![Some((1, 4)), Some((2, 3))]));
    assert_eq!(exec("a|ab", "", "ab"), Some(vec![Some((0, 1))]));
    assert_eq!(exec("(a)|b", "", "b"), Some(vec![Some((0, 1)), None]));
    let m = exec("(z)((a+)?(b+)?(c))*", "", "zaacbbbcac").unwrap();
    assert_eq!((m[3], m[4]), (Some((8, 9)), None));
    assert_eq!(exec("(?<=\\$)\\d+", "", "cost: $42"), Some(vec![Some((7, 9))]));
    assert_eq!(exec("(?<!a)b", "", "ab cb"), Some(vec![Some((4, 5))]));
    assert_eq!(exec("(a)\\1", "i", "aA"), Some(vec![Some((0, 2)), Some((0, 1))]));
    assert_eq!(exec("^.$", "u", "\u{1F600}"), Some(vec![Some((0, 2))]));
    assert_eq!(exec("^.$", "", "\u{1F600}"), None);
    assert_eq!(exec("[\\q{abc|ab}]", "v", "abc"), Some(vec![Some((0, 3))]));
    assert_eq!(exec("(?i:a)b", "", "Ab"), Some(vec![Some((0, 2))]));
    assert_eq!(exec("(?i:a)b", "", "AB"), None);
}

#[test]
fn sticky_and_last_index() {
    let re = compile(&u("a"), flags("y")).unwrap();
    assert_eq!(re.exec(&u("ba"), 0), None);
    assert_eq!(re.exec(&u("ba"), 1), Some(vec![Some((1, 2))]));
    let re = compile(&u("."), flags("gu")).unwrap();
    // lastIndex inside a surrogate pair: the attempt starts at the pair
    assert_eq!(re.exec(&u("\u{1F600}"), 1), Some(vec![Some((0, 2))]));
    assert_eq!(re.exec(&u("abc"), 4), None);
}

#[test]
fn named_groups() {
    let re = compile(&u("(?<a>x)|(?<a>y)(?<b>z)"), flags("")).unwrap();
    assert_eq!(re.group_names(), vec![(u("a"), vec![1, 2]), (u("b"), vec![3])]);
    assert_eq!(re.capture_count(), 3);
}

#[test]
fn error_messages() {
    assert_eq!(err("[", ""), "unterminated character class");
    assert_eq!(err("(", ""), "expected ')' in pattern");
    assert_eq!(err("a**", ""), "nothing to repeat");
    assert_eq!(err("a{2,1}", ""), "numbers out of order in {} quantifier");
    assert_eq!(err("\\k<x>", "u"), "invalid named back reference <x>");
    assert_eq!(err("(?<a>.)(?<a>.)", ""), "duplicate group name a");
    assert_eq!(err("\\p{Foo}", "u"), "invalid unicode property Foo");
    assert_eq!(err("(a)\\2", "u"), "back reference \\2 exceeds the number of capture groups");
    assert_eq!(err("[^\\q{ab}]", "v"), "cannot negate a class set containing strings");
    assert_eq!(err("(?:a){1001}", ""), "repetition count too large");
    assert_eq!(parse_flags(&u("gg")).unwrap_err(), "duplicate regular expression flag g");
    assert_eq!(parse_flags(&u("x")).unwrap_err(), "invalid regular expression flag x");
    assert_eq!(parse_flags(&u("uv")).unwrap_err(), "the u and v regular expression flags are mutually exclusive");
}

#[test]
fn source_escaping() {
    let e = |s: &str| String::from_utf16(&escape_source(&u(s))).unwrap();
    assert_eq!(e(""), "(?:)");
    assert_eq!(e("a/b"), "a\\/b");
    assert_eq!(e("[/]"), "[/]");
    assert_eq!(e("\\/"), "\\/");
    assert_eq!(e("\n"), "\\n");
    assert_eq!(e("\\\n"), "\\n");
    assert_eq!(e("\u{2028}"), "\\u2028");
}

#[test]
fn original_runtime_limits() {
    // greedy loops stop at the original's recursion depth limit
    let s: String = "ab".repeat(2000);
    let m = exec("(?:a|b)*", "", &s).unwrap();
    assert_eq!(m[0], Some((0, 999)));
    // captures leak out of positive lookaheads on backtracking
    assert_eq!(exec("(?=(a))b|a", "", "a"), Some(vec![Some((0, 1)), Some((0, 1))]));
}

#[test]
fn large_inputs_do_not_crash() {
    let s: String = "ab".repeat(200_000);
    assert_eq!(exec("(a|b)*c", "", &s), None);
    let s: String = "a".repeat(1 << 20);
    assert_eq!(exec(".*x", "", &s), None);
    let s: String = " ".repeat(100_000) + "a";
    assert_eq!(exec("\\s+$", "", &s), None);
    let s: String = "a".repeat(30);
    assert_eq!(exec("^(a+)+$", "", &(s + "!")), None);
}

#[test]
fn deep_nesting_small_stack() {
    let h = std::thread::Builder::new()
        .stack_size(1 << 21)
        .spawn(|| {
            for n in [1000usize, 3000] {
                let p = "(?:".repeat(n) + "a" + &")".repeat(n);
                assert!(exec(&p, "", "a").is_some());
                let p = "(".repeat(n) + "a" + &")".repeat(n);
                let _ = exec(&p, "", "a");
                let p = "[".repeat(n.min(1000)) + "a" + &"]".repeat(n.min(1000));
                let _ = compile(&u(&p), flags("v"));
            }
        })
        .unwrap();
    h.join().unwrap();
}

#[test]
#[ignore]
fn deep_nesting_probe() {
    for (stack, label) in [(1usize << 21, "2MB"), (1 << 23, "8MB")] {
        for n in [3000usize, 5000, 8000, 12000, 20000, 50000] {
            let ok = std::thread::Builder::new()
                .stack_size(stack)
                .spawn(move || {
                    let p = "(".repeat(n) + "a" + &")*".repeat(n);
                    let _ = exec(&p, "", "aa");
                    let p = "(?:a|".repeat(n) + "b" + &")".repeat(n);
                    let _ = exec(&p, "", "b");
                    let p = "(?=".repeat(n) + "a" + &")".repeat(n);
                    let _ = exec(&p, "", "a");
                })
                .unwrap()
                .join()
                .is_ok();
            eprintln!("{} n={} ok={}", label, n, ok);
            if !ok {
                break;
            }
        }
    }
}
