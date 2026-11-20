//! Intl.ListFormat (stub -- to be implemented).

use super::*;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    define_class(
        vm,
        intl,
        "ListFormat",
        0,
        not_implemented,
        &[
            Member::Method("format", 1, not_implemented),
            Member::Method("formatToParts", 1, not_implemented),
            Member::Method("resolvedOptions", 0, not_implemented),
        ],
        true,
    );
}
