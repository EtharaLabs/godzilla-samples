//! Intl.RelativeTimeFormat (stub -- to be implemented).

use super::*;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    define_class(
        vm,
        intl,
        "RelativeTimeFormat",
        0,
        not_implemented,
        &[
            Member::Method("format", 2, not_implemented),
            Member::Method("formatToParts", 2, not_implemented),
            Member::Method("resolvedOptions", 0, not_implemented),
        ],
        true,
    );
}
