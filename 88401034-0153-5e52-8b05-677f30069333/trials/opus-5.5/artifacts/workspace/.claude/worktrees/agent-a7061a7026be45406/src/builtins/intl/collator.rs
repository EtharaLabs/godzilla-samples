//! Intl.Collator (stub -- to be implemented).

use super::*;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    define_class(
        vm,
        intl,
        "Collator",
        0,
        not_implemented,
        &[Member::Method("resolvedOptions", 0, not_implemented), Member::Getter("compare", not_implemented)],
        true,
    );
}
