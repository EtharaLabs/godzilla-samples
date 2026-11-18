//! A room's kind as its name says it, in Portuguese or English: the name lower-cased, its accents
//! taken off, then searched for the words of each kind, a service area's first, then a
//! bathroom's, a kitchen's, a veranda's and a dry room's.

/// The name as the words are looked for in it: lower case, without accents.
pub fn fold(name: &str) -> String {
    let mut out = String::with_capacity(name.len());
    for c in name.chars() {
        for l in c.to_lowercase() {
            out.push(match l {
                'á' | 'à' | 'â' | 'ã' | 'ä' => 'a',
                'é' | 'è' | 'ê' | 'ë' => 'e',
                'í' | 'ì' | 'î' | 'ï' => 'i',
                'ó' | 'ò' | 'ô' | 'õ' | 'ö' => 'o',
                'ú' | 'ù' | 'û' | 'ü' => 'u',
                'ç' => 'c',
                x => x,
            });
        }
    }
    out
}

/// Each kind with the words found anywhere in a name and the words that must stand alone.
const KINDS: &[(&str, &[&str], &[&str])] = &[
    ("service", &["servico", "lavanderia", "laundry", "utility"], &[]),
    ("bath", &["banheiro", "lavabo", "sanitario", "toilet", "bathroom", "restroom"], &["wc", "bwc", "bath"]),
    ("kitchen", &["cozinha", "copa", "kitchen", "pantry"], &[]),
    ("veranda", &["varanda", "sacada", "balcony", "veranda"], &[]),
    ("dry", &["sala", "quarto", "dormitorio", "suite", "bedroom", "living"], &[]),
];

/// The kind a name says, if it says one.
pub fn kind_of(name: &str) -> Option<&'static str> {
    let f = fold(name);
    let words: Vec<&str> = f.split(|c: char| !c.is_alphanumeric()).filter(|w| !w.is_empty()).collect();
    for (kind, parts, whole) in KINDS {
        if parts.iter().any(|p| f.contains(p)) || words.iter().any(|w| whole.contains(w)) {
            return Some(kind);
        }
    }
    None
}

/// Whether a name says a kitchen or a pantry, which has the outlets over the sink's counter.
pub fn has_counter(name: &str) -> bool {
    let f = fold(name);
    ["cozinha", "copa", "kitchen"].iter().any(|p| f.contains(p))
}
