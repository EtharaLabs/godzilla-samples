//! Intl.PluralRules (stub -- to be implemented).

use super::*;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    define_class(
        vm,
        intl,
        "PluralRules",
        0,
        not_implemented,
        &[
            Member::Method("select", 1, not_implemented),
            Member::Method("selectRange", 2, not_implemented),
            Member::Method("resolvedOptions", 0, not_implemented),
        ],
        true,
    );
}
