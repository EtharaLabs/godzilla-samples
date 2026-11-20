//! Intl.DisplayNames (stub -- to be implemented).

use super::*;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    define_class(
        vm,
        intl,
        "DisplayNames",
        2,
        not_implemented,
        &[Member::Method("of", 1, not_implemented), Member::Method("resolvedOptions", 0, not_implemented)],
        true,
    );
}
