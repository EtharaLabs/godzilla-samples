// `lini highlight`: the source as HTML spans of token classes.
//
// A small line-oriented state machine (not the real lexer): it never fails, keeps
// every byte of the source (HTML-escaped), and wraps the runs it recognises in
// `<span class="lini-tok-KIND">`. Three modes, all reset at '\n':
// - structural: `name:` declarations (prop / prop-user, unless `name:side`),
//   link operators, classes, vars, hex colours, numbers, bare sides (const);
//   `:` switches to value mode, `|` opens a bar run.
// - value (after `:` until `;` `}` `]` or end of line): numbers may be signed,
//   builder calls (`rgb(`) are type, keywords and colour names.
// - bars (`|…|` on one line): types, `#id`, `::`, classes; no strings/comments.
// The word lists match the compiler's generated grammar tables.

const TYPES: &[&str] = &[
    "BT", "BZ", "C", "D", "F", "FB", "I", "J", "L", "LED", "M", "Q", "R", "SW", "TP", "V", "Y",
    "alt", "appliance", "area", "axis", "badge", "balloon", "band", "bars", "bath", "bed", "block",
    "box", "breakline", "bubble", "caption", "cell", "centerline", "chart", "column", "component",
    "control", "cyl", "datum", "diamond", "dining", "door", "door-leaf", "door-swing", "dots",
    "drawing", "else", "entity", "feature-control", "field", "floorplan", "footer", "footnote",
    "frame", "gnd", "grid", "group", "halo", "header", "hex", "hidden", "hole", "icon", "image",
    "junction", "label", "line", "loop", "magnifier", "mark", "mindmap", "nc", "note", "opamp",
    "opt", "oval", "page", "partition", "path", "pie", "pin", "pitch-circle", "plane", "poly",
    "projection", "rect", "row", "schematic", "sequence", "sheet-caption", "shoulder", "sign",
    "sketch", "slant", "slice", "sofa", "space", "stack", "stair-arrow", "stair-tread", "stairs",
    "surface-finish", "table", "threadline", "tick", "title-block", "topic", "wall", "window",
    "window-sill", "zone",
];

const PROPS: &[&str] = &[
    "activation", "align", "along", "approved", "at", "author", "axis", "bars", "baseline", "break",
    "categories", "cell", "characteristic", "clearance", "color", "columns", "corner-radius",
    "curve", "data", "date", "datums", "density", "department", "direction", "document-type",
    "draw", "drawing-number", "facing", "fill", "fit", "fn", "font-family", "font-size",
    "font-style", "font-weight", "format", "gap", "gap-fill", "gridlines", "height", "hinge",
    "hint", "hole", "href", "justify", "labels", "layer", "layout", "legend", "letter-spacing",
    "line-spacing", "marker", "marker-end", "marker-start", "material", "max-width", "mirror",
    "modifiers", "multiple", "number", "of", "on", "opacity", "padding", "path", "pattern", "pin",
    "pins", "place", "points", "prefix", "project", "radius", "range", "reference", "revision",
    "revolve", "rotate", "routing", "rows", "samples", "scale", "shadow", "shape", "sheet",
    "sheet-number", "side", "skew", "span", "src", "status", "step", "steps", "stroke",
    "stroke-style", "stroke-width", "swing", "symbol", "text-decoration", "text-shadow",
    "text-transform", "text-wrap", "thickness", "thread", "ticks", "title", "tol", "tooltip",
    "translate", "unit", "value", "width", "zone",
];

const KEYWORDS: &[&str] = &[
    "flow", "row", "column", "radial", "bilateral", "start", "center", "end", "stretch", "evenly",
    "origin", "rows", "columns", "none", "auto", "solid", "dashed", "dotted", "wavy", "phantom",
    "log", "linear", "hover", "always", "orthogonal", "natural", "straight", "contain", "cover",
    "x-axis", "y-axis", "px", "mm", "cm", "m", "in", "over", "arrow", "dot", "circle", "diamond",
    "datum", "crow", "many", "one", "exactly-one", "zero-or-one", "one-or-many", "zero-or-many",
    "bottom", "left", "right", "top", "chart", "drawing", "floorplan", "grid", "pie", "schematic",
    "sequence", "stack", "tree",
];

const COLORS: &[&str] = &[
    "white", "black", "red", "green", "blue", "gray", "grey", "crimson", "orange", "yellow", "gold",
    "silver", "navy", "teal", "purple", "pink", "brown", "cyan", "magenta", "lime", "maroon",
    "olive", "cornflowerblue", "currentColor", "transparent",
];

const FUNCS: &[&str] = &[
    "gradient", "hatch", "hsl", "hsla", "linear-gradient", "oklch", "radial-gradient", "repeat",
    "rgb", "rgba",
];

const SIDES: &[&str] = &["left", "right", "top", "bottom"];

#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Comment,
    Str,
    Number,
    Const,
    Keyword,
    Type,
    TypeUser,
    Prop,
    PropUser,
    Var,
    Op,
    Class,
    Punct,
}

impl Kind {
    fn class(self) -> &'static str {
        match self {
            Kind::Comment => "comment",
            Kind::Str => "string",
            Kind::Number => "number",
            Kind::Const => "const",
            Kind::Keyword => "keyword",
            Kind::Type => "type",
            Kind::TypeUser => "type-user",
            Kind::Prop => "prop",
            Kind::PropUser => "prop-user",
            Kind::Var => "var",
            Kind::Op => "op",
            Kind::Class => "class",
            Kind::Punct => "punct",
        }
    }
}

fn is_ident_start(c: u8) -> bool {
    c.is_ascii_alphabetic() || c == b'_'
}

fn is_ident_char(c: u8) -> bool {
    c.is_ascii_alphanumeric() || c == b'_' || c == b'-'
}

struct Out {
    s: String,
}

impl Out {
    fn text(&mut self, t: &str) {
        for c in t.chars() {
            match c {
                '&' => self.s.push_str("&amp;"),
                '<' => self.s.push_str("&lt;"),
                '>' => self.s.push_str("&gt;"),
                '"' => self.s.push_str("&quot;"),
                _ => self.s.push(c),
            }
        }
    }
    fn span(&mut self, k: Kind, t: &str) {
        self.s.push_str("<span class=\"lini-tok-");
        self.s.push_str(k.class());
        self.s.push_str("\">");
        self.text(t);
        self.s.push_str("</span>");
    }
}

struct Scan<'a> {
    src: &'a str,
    b: &'a [u8],
}

impl<'a> Scan<'a> {
    fn at(&self, i: usize) -> u8 {
        if i < self.b.len() {
            self.b[i]
        } else {
            0
        }
    }
    fn ident_end(&self, mut i: usize) -> usize {
        while i < self.b.len() && is_ident_char(self.b[i]) {
            i += 1;
        }
        i
    }
    // end of the (possibly multi-byte) char starting at i
    fn char_end(&self, i: usize) -> usize {
        let mut j = i + 1;
        while j < self.b.len() && !self.src.is_char_boundary(j) {
            j += 1;
        }
        j
    }
    // a number starting at i (optionally signed); returns end
    fn number_at(&self, i: usize, allow_minus: bool) -> Option<usize> {
        let mut j = i;
        let c = self.at(j);
        if c == b'+' || (allow_minus && c == b'-') {
            j += 1;
        }
        let d = self.at(j);
        if d.is_ascii_digit() {
            while self.at(j).is_ascii_digit() {
                j += 1;
            }
            if self.at(j) == b'.' && self.at(j + 1).is_ascii_digit() {
                j += 1;
                while self.at(j).is_ascii_digit() {
                    j += 1;
                }
            }
            Some(j)
        } else if d == b'.' && self.at(j + 1).is_ascii_digit() {
            j += 1;
            while self.at(j).is_ascii_digit() {
                j += 1;
            }
            Some(j)
        } else {
            None
        }
    }
    // `#` + 3/4/6/8 hex digits
    fn hex_at(&self, i: usize) -> Option<usize> {
        let mut j = i + 1;
        while self.at(j).is_ascii_hexdigit() {
            j += 1;
        }
        match j - i - 1 {
            3 | 4 | 6 | 8 => Some(j),
            _ => None,
        }
    }
    // `--` + ident
    fn var_at(&self, i: usize) -> Option<usize> {
        if self.at(i) == b'-' && self.at(i + 1) == b'-' && is_ident_start(self.at(i + 2)) {
            Some(self.ident_end(i + 2))
        } else {
            None
        }
    }
    // link operator: head? body tail?
    fn op_at(&self, i: usize) -> Option<usize> {
        if self.at(i) == b'&' {
            return Some(i + 1);
        }
        let mut j = i;
        // head
        if self.at(j) == b'<' && self.at(j + 1) == b'>' {
            j += 2;
        } else if matches!(self.at(j), b'<' | b'>' | b'*') {
            j += 1;
        }
        // body
        if self.at(j) == b'-' {
            let mut k = 0;
            while self.at(j) == b'-' && k < 3 {
                j += 1;
                k += 1;
            }
        } else if self.at(j) == b'~' {
            j += 1;
        } else {
            return None;
        }
        // tail
        if self.at(j) == b'<' && self.at(j + 1) == b'>' {
            j += 2;
        } else if matches!(self.at(j), b'<' | b'>' | b'*') {
            j += 1;
        }
        Some(j)
    }
    // class: `.` ident (`.` ident)*
    fn class_at(&self, i: usize) -> Option<usize> {
        if self.at(i) != b'.' || !is_ident_start(self.at(i + 1)) {
            return None;
        }
        let mut j = self.ident_end(i + 1);
        while self.at(j) == b'.' && is_ident_start(self.at(j + 1)) {
            j = self.ident_end(j + 1);
        }
        Some(j)
    }
    fn prev_is_ident(&self, i: usize) -> bool {
        i > 0 && is_ident_char(self.b[i - 1])
    }
    // string from i (at '"'): to the closing quote, or to end of line
    fn string_end(&self, i: usize) -> usize {
        let mut j = i + 1;
        while j < self.b.len() {
            match self.b[j] {
                b'"' => return j + 1,
                b'\n' => return j,
                b'\\' => {
                    if j + 1 < self.b.len() && self.b[j + 1] != b'\n' {
                        j += 2;
                    } else {
                        j += 1;
                    }
                }
                _ => j += 1,
            }
        }
        j
    }
    fn line_end(&self, i: usize) -> usize {
        let mut j = i;
        while j < self.b.len() && self.b[j] != b'\n' {
            j += 1;
        }
        j
    }
    // spaces and tabs only (the `name:` lookahead)
    fn skip_blank(&self, mut i: usize) -> usize {
        while matches!(self.at(i), b' ' | b'\t') {
            i += 1;
        }
        i
    }
    // any ASCII whitespace, newlines included (the `builder(` lookahead)
    fn skip_ws(&self, mut i: usize) -> usize {
        while self.at(i).is_ascii_whitespace() {
            i += 1;
        }
        i
    }
    fn s(&self, a: usize, b: usize) -> &'a str {
        &self.src[a..b]
    }
}

pub fn highlight(src: &str) -> String {
    let sc = Scan { src, b: src.as_bytes() };
    let b = sc.b;
    let n = b.len();
    let mut o = Out { s: String::with_capacity(src.len() * 3) };
    let mut i = 0;
    let mut value = false;
    let mut bars = false;
    let mut after_hash = false;
    while i < n {
        let c = b[i];
        if c == b'\n' {
            o.s.push('\n');
            value = false;
            bars = false;
            after_hash = false;
            i += 1;
            continue;
        }
        if bars {
            let was_hash = after_hash;
            after_hash = false;
            if c == b'|' {
                o.span(Kind::Punct, "|");
                bars = false;
                i += 1;
            } else if c == b'#' {
                o.span(Kind::Punct, "#");
                after_hash = true;
                i += 1;
            } else if c == b':' && sc.at(i + 1) == b':' {
                o.span(Kind::Op, "::");
                i += 2;
            } else if let Some(e) = sc.class_at(i) {
                o.span(Kind::Class, sc.s(i, e));
                i = e;
            } else if is_ident_start(c) {
                let e = sc.ident_end(i);
                let w = sc.s(i, e);
                let k = if was_hash || TYPES.contains(&w) { Kind::Type } else { Kind::TypeUser };
                o.span(k, w);
                i = e;
            } else {
                let e = sc.char_end(i);
                o.text(sc.s(i, e));
                i = e;
            }
            continue;
        }
        // comments and strings: both modes
        if c == b'/' && sc.at(i + 1) == b'/' {
            let e = sc.line_end(i);
            o.span(Kind::Comment, sc.s(i, e));
            i = e;
            continue;
        }
        if c == b'"' {
            let e = sc.string_end(i);
            o.span(Kind::Str, sc.s(i, e));
            i = e;
            continue;
        }
        if value {
            match c {
                b';' | b'}' | b']' => {
                    o.span(Kind::Punct, sc.s(i, i + 1));
                    value = false;
                    i += 1;
                    continue;
                }
                b'(' | b')' | b',' => {
                    o.span(Kind::Punct, sc.s(i, i + 1));
                    i += 1;
                    continue;
                }
                _ => {}
            }
            if let Some(e) = sc.var_at(i) {
                o.span(Kind::Var, sc.s(i, e));
                i = e;
                continue;
            }
            if let Some(e) = sc.number_at(i, true) {
                o.span(Kind::Number, sc.s(i, e));
                i = e;
                continue;
            }
            if c == b'#' {
                if let Some(e) = sc.hex_at(i) {
                    o.span(Kind::Const, sc.s(i, e));
                    i = e;
                    continue;
                }
            }
            if is_ident_start(c) {
                let e = sc.ident_end(i);
                let w = sc.s(i, e);
                let k = if FUNCS.contains(&w) && sc.at(sc.skip_ws(e)) == b'(' {
                    Some(Kind::Type)
                } else if COLORS.contains(&w) {
                    Some(Kind::Const)
                } else if KEYWORDS.contains(&w) {
                    Some(Kind::Keyword)
                } else {
                    None
                };
                match k {
                    Some(k) => o.span(k, w),
                    None => o.text(w),
                }
                i = e;
                continue;
            }
            let e = sc.char_end(i);
            o.text(sc.s(i, e));
            i = e;
            continue;
        }
        // normal mode
        match c {
            b'|' => {
                o.span(Kind::Punct, "|");
                bars = true;
                i += 1;
                continue;
            }
            b'{' | b'}' | b'[' | b']' | b'(' | b')' | b';' | b',' => {
                o.span(Kind::Punct, sc.s(i, i + 1));
                i += 1;
                continue;
            }
            b':' => {
                o.span(Kind::Punct, ":");
                value = true;
                i += 1;
                continue;
            }
            _ => {}
        }
        if let Some(e) = sc.var_at(i) {
            o.span(Kind::Var, sc.s(i, e));
            i = e;
            continue;
        }
        if let Some(e) = sc.op_at(i) {
            o.span(Kind::Op, sc.s(i, e));
            i = e;
            continue;
        }
        if let Some(e) = sc.number_at(i, false) {
            o.span(Kind::Number, sc.s(i, e));
            i = e;
            continue;
        }
        if c == b'#' {
            if let Some(e) = sc.hex_at(i) {
                o.span(Kind::Const, sc.s(i, e));
                i = e;
                continue;
            }
        }
        if c == b'.' && !sc.prev_is_ident(i) {
            if let Some(e) = sc.class_at(i) {
                o.span(Kind::Class, sc.s(i, e));
                i = e;
                continue;
            }
        }
        if is_ident_start(c) {
            let e = sc.ident_end(i);
            let w = sc.s(i, e);
            // `name:` (not `::`, not `name:side`) is a declaration
            let k = sc.skip_blank(e);
            let is_prop = sc.at(k) == b':' && sc.at(k + 1) != b':' && {
                let ve = sc.ident_end(k + 1);
                !(is_ident_start(sc.at(k + 1)) && SIDES.contains(&sc.s(k + 1, ve)))
            };
            if is_prop {
                o.span(if PROPS.contains(&w) { Kind::Prop } else { Kind::PropUser }, w);
            } else if SIDES.contains(&w) && !sc.prev_is_ident(i) {
                o.span(Kind::Const, w);
            } else {
                o.text(w);
            }
            i = e;
            continue;
        }
        let e = sc.char_end(i);
        o.text(sc.s(i, e));
        i = e;
    }
    o.s
}
