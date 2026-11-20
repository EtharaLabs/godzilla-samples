//! Intl.Locale (stub -- to be implemented).

use super::*;

pub fn setup(vm: &mut Vm, intl: &Obj) {
    let mut members = Vec::new();
    for g in [
        "baseName", "language", "script", "region", "variants", "calendar", "collation", "hourCycle", "caseFirst",
        "firstDayOfWeek", "numberingSystem", "numeric",
    ] {
        members.push(Member::Getter(g, not_implemented));
    }
    for m in [
        "toString", "maximize", "minimize", "getCalendars", "getCollations", "getHourCycles", "getNumberingSystems",
        "getTimeZones", "getTextInfo", "getWeekInfo",
    ] {
        members.push(Member::Method(m, 0, not_implemented));
    }
    define_class(vm, intl, "Locale", 1, not_implemented, &members, false);
}
