//! Intl.Segmenter (stub -- to be implemented).

use super::*;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    define_class(
        vm,
        intl,
        "Segmenter",
        0,
        not_implemented,
        &[Member::Method("segment", 1, not_implemented), Member::Method("resolvedOptions", 0, not_implemented)],
        true,
    );
}
