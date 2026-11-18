// Template expression recognition.

use crate::options::TemplateDelims;

/// Whether any single line of `s` contains a complete template expression.
pub fn contains_template(s: &str, delims: &TemplateDelims) -> bool {
    for line in s.split('\n') {
        for (open, close) in &delims.pairs {
            let mut from = 0;
            while let Some(p) = line[from..].find(open.as_str()) {
                let after = from + p + open.len();
                if line[after..].contains(close.as_str()) {
                    return true;
                }
                from = from + p + 1;
                if from >= line.len() {
                    break;
                }
            }
        }
    }
    false
}
