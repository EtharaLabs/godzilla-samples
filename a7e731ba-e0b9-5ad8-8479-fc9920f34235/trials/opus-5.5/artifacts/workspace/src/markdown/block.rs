// Block-level Markdown parsing into a shallow tree that keeps source lines.

#[derive(Debug, Clone)]
pub enum Block {
    /// A blank line, as written (it may hold spaces).
    Blank(String),
    Para(Vec<String>),
    /// ATX heading; its indentation is kept.
    Atx { level: usize, content: String, indent: usize },
    Setext { para: Vec<String>, heading: String, level: usize },
    Hr,
    Fence { open: String, body: Vec<String>, close: Option<String>, info: String, indent: usize, line: Option<usize> },
    /// Raw lines kept as written (trailing whitespace trimmed).
    Raw(Vec<String>),
    Html(Vec<String>),
    Quote { raw: Vec<String>, inner: Vec<Block>, lazy: bool },
    List(List),
    Table(Vec<String>),
    GridTable(Vec<String>),
    Div { open: String, inner: Vec<Block>, close: Option<String>, raw: Vec<String> },
    Math(Vec<String>),
    Footnote { label: String, first: String, rest: Vec<String>, raw: Vec<String> },
    RefDef(Vec<String>),
    /// Region preserved by a directive (bytes kept).
    Verbatim(Vec<String>),
    Comment(Vec<String>),
    /// Definition list definition (": text").
    Def { marker: char, first: String, rest: Vec<String>, raw: Vec<String> },
}

#[derive(Debug, Clone)]
pub struct List {
    pub raw: Vec<String>,
    pub items: Vec<Item>,
    pub ordered: bool,
}

#[derive(Debug, Clone)]
pub struct Item {
    /// Marker column (relative to container).
    pub col: usize,
    /// Marker text as written.
    pub marker: String,
    pub ordered: bool,
    /// Source content column (relative to container).
    pub content_col: usize,
    /// Child blocks parsed from item lines with `content_col` stripped.
    pub children: Vec<Block>,
    /// Raw item lines.
    pub raw: Vec<String>,
    /// Whether the item had lines less indented than content (lazy continuation).
    pub lazy: bool,
    /// Item text was empty on the marker line.
    pub empty_first: bool,
    /// Columns a task item's continuation lines were shifted to its text column.
    pub task_shift: usize,
    /// A task item's continuation line sits left of the task text.
    pub task_misaligned: bool,
}

pub fn indent_of(s: &str) -> usize {
    let mut n = 0;
    for c in s.chars() {
        match c {
            ' ' => n += 1,
            '\t' => n += 4 - (n % 4),
            _ => break,
        }
    }
    n
}

/// Skip `n` columns of any characters (tabs advance to the next multiple of 4).
pub fn cut_cols(s: &str, n: usize) -> String {
    let mut col = 0;
    for (i, c) in s.char_indices() {
        if col >= n {
            return s[i..].to_string();
        }
        if c == '\t' {
            let w = 4 - (col % 4);
            if col + w > n {
                let rem = col + w - n;
                return format!("{}{}", " ".repeat(rem), &s[i + 1..]);
            }
            col += w;
        } else {
            col += 1;
        }
    }
    String::new()
}

pub fn is_blank(s: &str) -> bool {
    s.trim().is_empty()
}

/// Remove up to `n` columns of leading whitespace.
pub fn strip_cols(s: &str, n: usize) -> String {
    let mut col = 0;
    let mut idx = 0;
    for (i, c) in s.char_indices() {
        if col >= n {
            idx = i;
            break;
        }
        match c {
            ' ' => {
                col += 1;
                idx = i + 1;
            }
            '\t' => {
                let w = 4 - (col % 4);
                if col + w > n {
                    // Partial tab: replace remainder with spaces.
                    let rem = col + w - n;
                    return format!("{}{}", " ".repeat(rem), &s[i + 1..]);
                }
                col += w;
                idx = i + 1;
            }
            _ => {
                idx = i;
                break;
            }
        }
        if col >= n {
            idx = i + c.len_utf8();
            break;
        }
    }
    if col < n && s.chars().all(|c| c == ' ' || c == '\t') {
        return String::new();
    }
    s[idx..].to_string()
}

pub struct FenceOpen {
    pub ch: char,
    pub len: usize,
    pub indent: usize,
    pub info: String,
}

pub fn fence_open(line: &str) -> Option<FenceOpen> {
    let ind = indent_of(line);
    if ind > 3 {
        return None;
    }
    let t = line.trim_start();
    let ch = t.chars().next()?;
    if ch != '`' && ch != '~' {
        return None;
    }
    let len = t.chars().take_while(|&c| c == ch).count();
    if len < 3 {
        return None;
    }
    let info = t[len..].trim().to_string();
    if ch == '`' && info.contains('`') {
        return None;
    }
    Some(FenceOpen { ch, len, indent: ind, info })
}

fn fence_close(line: &str, ch: char, len: usize) -> bool {
    // Inside list items a closing fence may be indented any amount.
    if indent_of(line) > 3 && !IN_ITEM.with(|c| c.get()) {
        return false;
    }
    let t = line.trim();
    let n = t.chars().take_while(|&c| c == ch).count();
    n >= len && t.chars().all(|c| c == ch)
}

pub fn atx_heading(line: &str) -> Option<(usize, String)> {
    let ind = indent_of(line);
    if ind > 3 {
        return None;
    }
    let t = line.trim_start();
    let level = t.chars().take_while(|&c| c == '#').count();
    if level == 0 || level > 6 {
        return None;
    }
    let rest = &t[level..];
    if !rest.is_empty() && !rest.starts_with(' ') && !rest.starts_with('\t') {
        return None;
    }
    let mut content = rest.trim().to_string();
    // Remove closing sequence.
    if content.chars().all(|c| c == '#') {
        content.clear();
    } else {
        let trimmed = content.trim_end_matches('#');
        if trimmed.len() < content.len() && (trimmed.ends_with(' ') || trimmed.ends_with('\t')) {
            content = trimmed.trim_end().to_string();
        }
    }
    Some((level, content))
}

pub fn is_hr(line: &str) -> bool {
    if indent_of(line) > 3 {
        return false;
    }
    let t: String = line.chars().filter(|c| *c != ' ' && *c != '\t').collect();
    if t.len() < 3 {
        return false;
    }
    let c = t.chars().next().unwrap();
    (c == '-' || c == '*' || c == '_') && t.chars().all(|x| x == c)
}

/// A setext underline (any indentation).
fn setext_level(line: &str) -> Option<usize> {
    let t = line.trim();
    if t.is_empty() {
        return None;
    }
    if t.chars().all(|c| c == '=') {
        return Some(1);
    }
    if t.chars().all(|c| c == '-') {
        return Some(2);
    }
    None
}

pub struct ListMarker {
    pub col: usize,
    pub marker: String,
    pub ordered: bool,
    pub content_col: usize,
    pub empty: bool,
}

/// A well-formed roman numeral of at most eight letters (any letter case).
pub fn is_roman(s: &str) -> bool {
    if s.is_empty() || s.len() > 8 {
        return false;
    }
    let l = s.to_ascii_lowercase();
    let mut r = l.trim_start_matches('m');
    // Hundreds, tens and units share one shape: 9, 4, or optional 5 plus up to three 1s.
    for (one, five, ten) in [('c', 'd', 'm'), ('x', 'l', 'c'), ('i', 'v', 'x')] {
        let nine: String = [one, ten].iter().collect();
        let four: String = [one, five].iter().collect();
        if let Some(rest) = r.strip_prefix(nine.as_str()).or_else(|| r.strip_prefix(four.as_str())) {
            r = rest;
            continue;
        }
        r = r.strip_prefix(five).unwrap_or(r);
        let ones = r.chars().take_while(|&c| c == one).count();
        if ones > 3 {
            return false;
        }
        r = &r[ones..];
    }
    r.is_empty()
}

/// Whether `label` can label an ordered list item (`parens` for the `(x)` form).
pub fn is_list_label(label: &str, parens: bool) -> bool {
    if label.is_empty() || !label.chars().all(|c| c.is_ascii_alphanumeric()) {
        return false;
    }
    if label.chars().all(|c| c.is_ascii_digit()) {
        return !parens || label.len() <= 8;
    }
    label.len() == 1 || is_roman(label)
}

pub fn list_marker(line: &str) -> Option<ListMarker> {
    let col = indent_of(line);
    if col > 3 {
        return None;
    }
    let t = line.trim_start();
    let chars: Vec<char> = t.chars().collect();
    if chars.is_empty() {
        return None;
    }
    let (mlen, ordered) = if matches!(chars[0], '-' | '+' | '*') {
        (1, false)
    } else if chars[0] == '(' {
        // (1) (a) (iv)
        let mut j = 1;
        while j < chars.len() && chars[j].is_ascii_alphanumeric() {
            j += 1;
        }
        if j >= chars.len() || chars[j] != ')' || j == 1 {
            return None;
        }
        let label: String = chars[1..j].iter().collect();
        if !is_list_label(&label, true) {
            return None;
        }
        (j + 1, true)
    } else {
        let mut j = 0;
        while j < chars.len() && chars[j].is_ascii_alphanumeric() {
            j += 1;
        }
        if j == 0 || j >= chars.len() || (chars[j] != '.' && chars[j] != ')') {
            return None;
        }
        let label: String = chars[..j].iter().collect();
        if !is_list_label(&label, false) {
            return None;
        }
        (j + 1, true)
    };
    let marker: String = chars[..mlen].iter().collect();
    let rest: String = chars[mlen..].iter().collect();
    if rest.is_empty() {
        return Some(ListMarker { col, marker, ordered, content_col: col + mlen + 1, empty: true });
    }
    if !rest.starts_with(' ') && !rest.starts_with('\t') {
        return None;
    }
    // Alphabetic markers need two spaces after a capital+period (Pandoc), skip that nuance.
    let sp = indent_of(&rest);
    if rest.trim().is_empty() {
        return Some(ListMarker { col, marker, ordered, content_col: col + mlen + 1, empty: true });
    }
    let content_col = if sp >= 5 { col + mlen + 1 } else { col + mlen + sp };
    Some(ListMarker { col, marker, ordered, content_col, empty: false })
}

/// HTML block start (CommonMark types 1-7). Returns the end condition kind.
fn html_block_start(line: &str, can_interrupt: bool) -> Option<u8> {
    if indent_of(line) > 3 {
        return None;
    }
    let t = line.trim_start();
    let lower = t.to_ascii_lowercase();
    for tag in ["<script", "<pre", "<style", "<textarea"] {
        if lower.starts_with(tag) {
            let rest = &lower[tag.len()..];
            if rest.is_empty() || rest.starts_with(' ') || rest.starts_with('>') || rest.starts_with('\t') {
                return Some(1);
            }
        }
    }
    if t.starts_with("<!--") {
        return Some(2);
    }
    if t.starts_with("<?") {
        return Some(3);
    }
    if t.starts_with("<!") && t.len() > 2 && t.as_bytes()[2].is_ascii_alphabetic() {
        return Some(4);
    }
    if t.starts_with("<![CDATA[") {
        return Some(5);
    }
    const BLOCK_TAGS: &[&str] = &[
        "address", "article", "aside", "base", "basefont", "blockquote", "body", "caption", "center", "col", "colgroup", "dd", "details", "dialog", "dir", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "frame", "frameset", "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hr", "html", "iframe", "legend", "li", "link", "main", "menu", "menuitem", "nav", "noframes", "ol", "optgroup", "option", "p", "param", "search", "section", "summary", "table", "tbody", "td", "tfoot", "th", "thead", "title", "tr", "track", "ul",
    ];
    if let Some(rest) = t.strip_prefix('<') {
        let rest = rest.strip_prefix('/').unwrap_or(rest);
        let name: String = rest.chars().take_while(|c| c.is_ascii_alphanumeric()).collect();
        let after = &rest[name.len()..];
        if !name.is_empty() && BLOCK_TAGS.contains(&name.to_ascii_lowercase().as_str()) && (after.is_empty() || after.starts_with(' ') || after.starts_with('>') || after.starts_with("/>") || after.starts_with('\t')) {
            return Some(6);
        }
    }
    if !can_interrupt {
        let chars: Vec<char> = t.trim_end().chars().collect();
        if let Some((e, _, _, _)) = super::inline::html_tag_at(&chars, 0) {
            if e == chars.len() {
                return Some(7);
            }
        }
    }
    None
}

/// Name of a non-void element opened at the start of the line, if any.
fn open_container_tag(line: &str) -> Option<String> {
    let t = line.trim_start();
    let chars: Vec<char> = t.chars().collect();
    let (_, name, close, selfc) = super::inline::html_tag_at(&chars, 0)?;
    if close || selfc {
        return None;
    }
    Some(name)
}

fn html_block_ends(kind: u8, line: &str) -> bool {
    let lower = line.to_ascii_lowercase();
    match kind {
        1 => lower.contains("</script>") || lower.contains("</pre>") || lower.contains("</style>") || lower.contains("</textarea>"),
        2 => line.contains("-->"),
        3 => line.contains("?>"),
        4 => line.contains('>'),
        5 => line.contains("]]>"),
        _ => false,
    }
}

fn is_table_delim(line: &str) -> bool {
    let t = line.trim();
    if !t.starts_with('|') && !t.contains('|') {
        return false;
    }
    let inner = t.trim_start_matches('|').trim_end_matches('|');
    if inner.is_empty() {
        return false;
    }
    inner.split('|').all(|c| {
        let c = c.trim();
        let c = c.strip_prefix(':').unwrap_or(c);
        let c = c.strip_suffix(':').unwrap_or(c);
        !c.is_empty() && c.chars().all(|x| x == '-')
    })
}

fn is_table_start(lines: &[String], i: usize) -> bool {
    if i + 1 >= lines.len() {
        return false;
    }
    let l = lines[i].trim();
    l.starts_with('|') && indent_of(&lines[i]) <= 3 && lines[i + 1].trim().starts_with('|') && is_table_delim(&lines[i + 1])
}

fn ref_def_start(line: &str) -> bool {
    if indent_of(line) > 3 {
        return false;
    }
    let t = line.trim_start();
    if !t.starts_with('[') || t.starts_with("[^") {
        return false;
    }
    match t.find("]:") {
        Some(p) => p > 1 && !t[1..p].contains('[') && !t[1..p].contains(']'),
        None => false,
    }
}

fn footnote_start(line: &str) -> Option<(String, String)> {
    if indent_of(line) > 3 {
        return None;
    }
    let t = line.trim_start();
    if !t.starts_with("[^") {
        return None;
    }
    let p = t.find("]:")?;
    let label = t[2..p].to_string();
    if label.is_empty() || label.contains(char::is_whitespace) {
        return None;
    }
    Some((label, t[p + 2..].trim_start().to_string()))
}

/// A line that is a standalone shortcode token start. Returns the closing delimiter.
fn shortcode_start(line: &str) -> Option<&'static str> {
    let t = line.trim();
    if t.starts_with("{{<") {
        return Some(">}}");
    }
    if t.starts_with("{{%") {
        return Some("%}}");
    }
    None
}

/// Number of lines spanned by a standalone shortcode token at lines[i], if complete and alone.
fn shortcode_span(lines: &[String], i: usize) -> Option<usize> {
    let close = shortcode_start(&lines[i])?;
    let mut j = i;
    while j < lines.len() {
        let t = lines[j].trim_end();
        let from = if j == i { t.find(close.chars().next().map(|_| "").unwrap_or("")).unwrap_or(0) + 3 } else { 0 };
        let seg = if from <= t.len() { &t[from..] } else { "" };
        if let Some(p) = seg.find(close) {
            // Token must end the line.
            if seg[p + close.len()..].trim().is_empty() {
                return Some(j - i + 1);
            }
            return None;
        }
        j += 1;
    }
    None
}

fn def_start(line: &str) -> Option<(char, String)> {
    if indent_of(line) > 3 {
        return None;
    }
    let t = line.trim_start();
    let c = t.chars().next()?;
    if c != ':' && c != '~' {
        return None;
    }
    let rest = &t[1..];
    // A lone `:` opens an empty definition.
    if !rest.starts_with(' ') && !rest.starts_with('\t') && !(c == ':' && rest.is_empty()) {
        return None;
    }
    if c == ':' && t.starts_with(":::") {
        return None;
    }
    // Trailing spaces are kept: they may form a hard break.
    Some((c, rest.trim_start().to_string()))
}

fn div_open(line: &str) -> Option<usize> {
    if indent_of(line) > 3 {
        return None;
    }
    let t = line.trim();
    let n = t.chars().take_while(|&c| c == ':').count();
    if n >= 3 && t.len() > n && !t[n..].trim().is_empty() {
        return Some(n);
    }
    None
}

fn div_close(line: &str) -> bool {
    let t = line.trim();
    t.len() >= 3 && t.chars().all(|c| c == ':')
}

/// A `Table:` caption line outside list items and single-block quotes.
fn table_caption(line: &str) -> bool {
    COLON_RAW.with(|c| c.get()) && indent_of(line) <= 3 && line.trim_start().starts_with("Table:")
}

/// A raw TeX environment starts with `\begin{` on its own line.
fn tex_begin(line: &str) -> bool {
    indent_of(line) <= 3 && line.trim_start().starts_with("\\begin{")
}

fn math_open(line: &str) -> bool {
    indent_of(line) <= 3 && line.trim_start().starts_with("$$")
}

/// Whether a line starts a block that interrupts a paragraph.
fn interrupts_paragraph(lines: &[String], i: usize) -> bool {
    let line = &lines[i];
    if is_blank(line) {
        return true;
    }
    if fence_open(line).is_some() {
        return true;
    }
    if atx_heading(line).is_some() {
        return true;
    }
    if line.trim_start().starts_with('>') && indent_of(line) <= 3 {
        return true;
    }
    if is_hr(line) {
        return true;
    }
    if html_block_start(line, true).is_some() {
        return true;
    }
    // An empty ordered item cannot interrupt a paragraph; an empty bullet item can.
    if let Some(m) = list_marker(line) {
        if !m.empty || !m.ordered {
            return true;
        }
    }
    if is_table_start(lines, i) {
        return true;
    }
    if indent_of(line) >= 4 {
        return true;
    }
    if div_open(line).is_some() || div_close(line) {
        return true;
    }
    if math_open(line) || tex_begin(line) || table_caption(line) {
        return true;
    }
    if footnote_start(line).is_some() {
        return true;
    }
    if def_start(line).is_some() && DEFS.with(|c| c.get()) {
        return true;
    }
    if colon_line(line) {
        return true;
    }
    if indent_of(line) <= 3 && line.trim_start().starts_with('|') {
        return true;
    }
    if shortcode_span(lines, i).is_some() {
        return true;
    }
    false
}

thread_local! {
    /// Whether ':'-prefixed lines stand alone (document-level parsing).
    static COLON_RAW: std::cell::Cell<bool> = const { std::cell::Cell::new(true) };
}

thread_local! {
    /// Whether definition lists are recognized (not inside single-block quotes).
    static DEFS: std::cell::Cell<bool> = const { std::cell::Cell::new(true) };
    /// Whether list item content is being parsed.
    static IN_ITEM: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

fn with_item<T>(f: impl FnOnce() -> T) -> T {
    let prev = IN_ITEM.with(|c| c.replace(true));
    let r = f();
    IN_ITEM.with(|c| c.set(prev));
    r
}

fn with_defs<T>(v: bool, f: impl FnOnce() -> T) -> T {
    let prev = DEFS.with(|c| c.replace(v));
    let r = f();
    DEFS.with(|c| c.set(prev));
    r
}

fn with_colon_raw<T>(v: bool, f: impl FnOnce() -> T) -> T {
    let prev = COLON_RAW.with(|c| c.replace(v));
    let r = f();
    COLON_RAW.with(|c| c.set(prev));
    r
}

/// A line starting with ':' directly followed by other text (e.g. a table delimiter row
/// without leading pipes) stands on its own.
fn colon_line(line: &str) -> bool {
    if !COLON_RAW.with(|c| c.get()) {
        return false;
    }
    if indent_of(line) > 3 {
        return false;
    }
    let t = line.trim_start();
    t.starts_with(':') && !t.starts_with("::") && t.len() > 1 && !t[1..].starts_with(' ') && !t[1..].starts_with('\t')
}

pub fn parse_blocks(lines: &[String]) -> Vec<Block> {
    parse_blocks_at(lines, None)
}

/// Parse blocks; `base` is the absolute line index of `lines[0]` when known.
pub fn parse_blocks_at(lines: &[String], base: Option<usize>) -> Vec<Block> {
    let mut blocks = Vec::new();
    let mut i = 0;
    let n = lines.len();
    while i < n {
        let line = &lines[i];
        if is_blank(line) {
            blocks.push(Block::Blank(line.clone()));
            i += 1;
            continue;
        }
        let ind = indent_of(line);
        if ind >= 4 {
            // Indented code / raw lines until a non-indented, non-blank line.
            let s = i;
            while i < n && (indent_of(&lines[i]) >= 4 || is_blank(&lines[i])) {
                i += 1;
            }
            let mut e = i;
            while e > s && is_blank(&lines[e - 1]) {
                e -= 1;
            }
            blocks.push(Block::Raw(lines[s..e].to_vec()));
            for k in e..i {
                blocks.push(Block::Blank(lines[k].clone()));
            }
            continue;
        }
        if let Some(f) = fence_open(line) {
            let s = i;
            i += 1;
            let mut body = Vec::new();
            let mut close = None;
            while i < n {
                if fence_close(&lines[i], f.ch, f.len) {
                    close = Some(lines[i].clone());
                    i += 1;
                    break;
                }
                body.push(lines[i].clone());
                i += 1;
            }
            blocks.push(Block::Fence { open: lines[s].clone(), body, close, info: f.info, indent: f.indent, line: base.map(|b| b + s) });
            continue;
        }
        if let Some((level, content)) = atx_heading(line) {
            blocks.push(Block::Atx { level, content, indent: ind });
            i += 1;
            continue;
        }
        if line.trim_start().starts_with('>') {
            let s = i;
            let mut inner_lines = Vec::new();
            let lazy = false;
            while i < n {
                let l = &lines[i];
                let t = l.trim_start();
                if t.starts_with('>') && indent_of(l) <= 3 {
                    let rest = &t[1..];
                    let rest = if let Some(r) = rest.strip_prefix(' ') {
                        r.to_string()
                    } else if rest.starts_with('\t') {
                        strip_cols(rest, 1)
                    } else {
                        rest.to_string()
                    };
                    inner_lines.push(rest);
                    i += 1;
                    continue;
                }
                break;
            }
            let single = !inner_lines.iter().any(|l| is_blank(l));
            let inner = with_defs(!single, || with_colon_raw(!single, || parse_blocks(&inner_lines)));
            blocks.push(Block::Quote { raw: lines[s..i].to_vec(), inner, lazy });
            continue;
        }
        if is_hr(line) {
            // A '---' line could be a setext underline only after a paragraph (handled there).
            blocks.push(Block::Hr);
            i += 1;
            continue;
        }
        if let Some(kind) = html_block_start(line, false) {
            let s = i;
            if kind <= 5 {
                while i < n {
                    let done = html_block_ends(kind, &lines[i]);
                    i += 1;
                    if done {
                        break;
                    }
                }
            } else {
                while i < n && !is_blank(&lines[i]) {
                    i += 1;
                }
                // An element left open extends the block to its closing tag.
                if let Some(name) = open_container_tag(&lines[s]) {
                    let close = format!("</{}>", name);
                    let found_in_block = lines[s..i].iter().enumerate().any(|(k, l)| {
                        let lower = l.to_ascii_lowercase();
                        if k == 0 {
                            // Closing tag after the opening tag on the first line.
                            lower.matches(&close).count() > 0
                        } else {
                            lower.contains(&close)
                        }
                    });
                    if !found_in_block {
                        while i < n {
                            let lower = lines[i].to_ascii_lowercase();
                            i += 1;
                            if lower.contains(&close) {
                                break;
                            }
                        }
                    }
                }
            }
            let html = lines[s..i].to_vec();
            if kind == 2 && html.len() == 1 && html[0].trim_start().starts_with("<!--") && html[0].trim_end().ends_with("-->") {
                blocks.push(Block::Comment(html));
            } else {
                blocks.push(Block::Html(html));
            }
            continue;
        }
        if let Some(m) = list_marker(line).filter(|m| !empty_ordered_is_text(lines, i, m)) {
            let (list, next) = parse_list(lines, i, &m);
            blocks.push(Block::List(list));
            i = next;
            continue;
        }
        if line.trim_start().starts_with("+-") && line.trim_end().ends_with('+') && indent_of(line) <= 3 {
            let s = i;
            while i < n && !is_blank(&lines[i]) && (lines[i].trim_start().starts_with('+') || lines[i].trim_start().starts_with('|')) {
                i += 1;
            }
            blocks.push(Block::GridTable(lines[s..i].to_vec()));
            continue;
        }
        if is_table_start(lines, i) {
            let s = i;
            i += 2;
            // Body rows need a pipe somewhere, not necessarily a leading one.
            while i < n && !is_blank(&lines[i]) && lines[i].contains('|') {
                i += 1;
            }
            blocks.push(Block::Table(lines[s..i].to_vec()));
            continue;
        }
        if let Some(colons) = div_open(line) {
            // Find matching close (nesting aware).
            let s = i;
            let mut depth = 1;
            let mut j = i + 1;
            let mut close_idx = None;
            let mut in_fence: Option<(char, usize)> = None;
            while j < n {
                let l = &lines[j];
                if let Some((ch, len)) = in_fence {
                    if fence_close(l, ch, len) {
                        in_fence = None;
                    }
                    j += 1;
                    continue;
                }
                if let Some(f) = fence_open(l) {
                    in_fence = Some((f.ch, f.len));
                    j += 1;
                    continue;
                }
                if div_open(l).is_some() {
                    depth += 1;
                } else if div_close(l) {
                    depth -= 1;
                    if depth == 0 {
                        close_idx = Some(j);
                        break;
                    }
                }
                j += 1;
            }
            let _ = colons;
            match close_idx {
                Some(c) => {
                    let inner = parse_blocks_at(&lines[s + 1..c], base.map(|b| b + s + 1));
                    blocks.push(Block::Div { open: lines[s].clone(), inner, close: Some(lines[c].clone()), raw: lines[s..=c].to_vec() });
                    i = c + 1;
                }
                None => {
                    // An unclosed div is kept as written.
                    blocks.push(Block::Raw(lines[s..].to_vec()));
                    i = n;
                }
            }
            continue;
        }
        if table_caption(line) {
            // A Pandoc table caption stands alone as written.
            blocks.push(Block::Raw(vec![line.clone()]));
            i += 1;
            continue;
        }
        if div_close(line) && indent_of(line) <= 3 {
            // A closing fence without an open div stands alone.
            blocks.push(Block::Raw(vec![line.clone()]));
            i += 1;
            continue;
        }
        if tex_begin(line) {
            // Kept as written through the line starting with `\end{`.
            let s = i;
            i += 1;
            while i < n {
                let done = lines[i].trim_start().starts_with("\\end{");
                i += 1;
                if done {
                    break;
                }
            }
            blocks.push(Block::Raw(lines[s..i].to_vec()));
            continue;
        }
        if math_open(line) {
            let s = i;
            let t = line.trim();
            let single = t.len() > 4 && t[2..].contains("$$");
            i += 1;
            // A multi-line block closes at a line starting with `$$` (an equation label
            // may follow).
            if !single {
                while i < n {
                    let done = lines[i].trim_start().starts_with("$$");
                    i += 1;
                    if done {
                        break;
                    }
                }
            }
            blocks.push(Block::Math(lines[s..i].to_vec()));
            continue;
        }
        if let Some((label, first)) = footnote_start(line) {
            let s = i;
            i += 1;
            let mut rest = Vec::new();
            while i < n {
                let l = &lines[i];
                if is_blank(l) {
                    // Continue only if followed by an indented line.
                    let mut j = i;
                    while j < n && is_blank(&lines[j]) {
                        j += 1;
                    }
                    if j < n && indent_of(&lines[j]) >= 4 {
                        for k in i..j {
                            rest.push(lines[k].clone());
                        }
                        i = j;
                        continue;
                    }
                    break;
                }
                // Continuation lines are indented two or more columns.
                if indent_of(l) >= 2 {
                    rest.push(l.clone());
                    i += 1;
                    continue;
                }
                break;
            }
            blocks.push(Block::Footnote { label, first, rest, raw: lines[s..i].to_vec() });
            continue;
        }
        if def_start(line).is_some() && line.trim_start().starts_with(':') && blocks.iter().rev().find(|b| !matches!(b, Block::Blank(_))).map(|b| matches!(b, Block::Table(_))).unwrap_or(false) {
            // Pandoc table caption.
            let s = i;
            i += 1;
            while i < n && !is_blank(&lines[i]) {
                i += 1;
            }
            blocks.push(Block::Raw(lines[s..i].to_vec()));
            continue;
        }
        // A definition follows its term line directly, or an earlier definition
        // across blank lines and indented continuation blocks.
        let def = def_start(line).filter(|_| {
            DEFS.with(|c| c.get())
                && ((i > 0 && !is_blank(&lines[i - 1]))
                    || blocks
                        .iter()
                        .rev()
                        .find(|b| !matches!(b, Block::Blank(_)) && !matches!(b, Block::Raw(ls) if ls.iter().all(|l| indent_of(l) >= 4)))
                        .map(|b| matches!(b, Block::Def { .. }))
                        .unwrap_or(false))
        });
        if let Some((marker, first)) = def {
            let s = i;
            i += 1;
            let mut rest = Vec::new();
            while i < n {
                let l = &lines[i];
                if is_blank(l) {
                    break;
                }
                if indent_of(l) >= 2 || !interrupts_paragraph(lines, i) {
                    rest.push(l.clone());
                    i += 1;
                    continue;
                }
                break;
            }
            blocks.push(Block::Def { marker, first, rest, raw: lines[s..i].to_vec() });
            continue;
        }
        if ref_def_start(line) {
            let s = i;
            i += 1;
            // Title may continue on following lines; keep consecutive defs together.
            while i < n && !is_blank(&lines[i]) && (ref_def_start(&lines[i]) || indent_of(&lines[i]) > 0) {
                i += 1;
            }
            blocks.push(Block::RefDef(lines[s..i].to_vec()));
            continue;
        }
        if colon_line(line) {
            blocks.push(Block::Raw(vec![line.clone()]));
            i += 1;
            continue;
        }
        if line.trim_start().starts_with('|') {
            // Pandoc line block (or an unrecognized table) kept as written.
            let s = i;
            while i < n && !is_blank(&lines[i]) && lines[i].trim_start().starts_with('|') {
                i += 1;
            }
            blocks.push(Block::Raw(lines[s..i].to_vec()));
            continue;
        }
        if let Some(span) = shortcode_span(lines, i) {
            blocks.push(Block::Raw(lines[i..i + span].to_vec()));
            i += span;
            continue;
        }
        // Paragraph.
        let s = i;
        i += 1;
        let mut setext: Option<usize> = None;
        while i < n {
            if let Some(level) = setext_level(&lines[i]) {
                if level == 1 || lines[i].trim().len() >= 1 {
                    setext = Some(level);
                    break;
                }
            }
            if interrupts_paragraph(lines, i) {
                break;
            }
            i += 1;
        }
        if let Some(level) = setext {
            let para: Vec<String> = lines[s..i - 1].to_vec();
            let heading = lines[i - 1].clone();
            blocks.push(Block::Setext { para, heading, level });
            i += 1;
            continue;
        }
        let mut para = lines[s..i].to_vec();
        if COLON_RAW.with(|c| c.get()) {
            if let Some((m, _)) = def_start(&para[0]) {
                // A stray definition marker: `:` keeps the paragraph as written,
                // `~` is escaped.
                if m == ':' {
                    blocks.push(Block::Raw(para));
                    continue;
                }
                let t = para[0].trim_start();
                para[0] = format!("\\{}", t);
            }
        }
        blocks.push(Block::Para(para));
    }
    blocks
}

/// An ordered marker alone on its line, followed by a line of paragraph text, is
/// itself paragraph text.
fn empty_ordered_is_text(lines: &[String], i: usize, m: &ListMarker) -> bool {
    m.ordered && m.empty && i + 1 < lines.len() && !is_blank(&lines[i + 1]) && indent_of(&lines[i + 1]) < 4 && !interrupts_paragraph(lines, i + 1)
}

/// Number of source lines a block spans.
pub fn line_count(b: &Block) -> usize {
    match b {
        Block::Blank(_) | Block::Atx { .. } | Block::Hr => 1,
        Block::Setext { para, .. } => para.len() + 1,
        Block::Fence { body, close, .. } => 1 + body.len() + usize::from(close.is_some()),
        Block::Para(ls) | Block::Raw(ls) | Block::Html(ls) | Block::Table(ls) | Block::GridTable(ls) | Block::Math(ls) | Block::RefDef(ls) | Block::Verbatim(ls) | Block::Comment(ls) => ls.len(),
        Block::Quote { raw, .. } | Block::Div { raw, .. } | Block::Footnote { raw, .. } | Block::Def { raw, .. } => raw.len(),
        Block::List(l) => l.raw.len(),
    }
}

fn same_list_type(a: &ListMarker, b: &ListMarker) -> bool {
    a.ordered == b.ordered
}

fn parse_list(lines: &[String], start: usize, first: &ListMarker) -> (List, usize) {
    let n = lines.len();
    let mut items = Vec::new();
    let mut i = start;
    let mut cur_marker = ListMarker { col: first.col, marker: first.marker.clone(), ordered: first.ordered, content_col: first.content_col, empty: first.empty };
    loop {
        // Item starting at line i with cur_marker.
        let s = i;
        let w = cur_marker.content_col;
        let mut item_lines: Vec<String> = Vec::new();
        // First line: content after marker.
        let first_line = &lines[i];
        let first_content = if cur_marker.empty { String::new() } else { cut_cols(first_line, w) };
        item_lines.push(first_content);
        i += 1;
        let mut lazy = false;
        let mut last_was_para = !cur_marker.empty;
        let mut in_fence: Option<(char, usize)> = None;
        if let Some(f) = fence_open(&item_lines[0]) {
            in_fence = Some((f.ch, f.len));
        }
        while i < n {
            let l = &lines[i];
            if is_blank(l) {
                // Blank: item continues if a following non-blank line is indented >= w.
                let mut j = i;
                while j < n && is_blank(&lines[j]) {
                    j += 1;
                }
                // Blank lines in a fence stay in the item while the item goes on.
                if in_fence.is_some() && j < n && indent_of(&lines[j]) > cur_marker.col {
                    item_lines.push(String::new());
                    i += 1;
                    continue;
                }
                // An empty ordered item ends at a blank line; an empty bullet item goes on.
                if j < n && indent_of(&lines[j]) >= w && !(cur_marker.empty && cur_marker.ordered && item_lines.len() == 1 && item_lines[0].is_empty()) {
                    for _ in i..j {
                        item_lines.push(String::new());
                    }
                    i = j;
                    last_was_para = false;
                    continue;
                }
                break;
            }
            let ind = indent_of(l);
            if let Some((ch, len)) = in_fence {
                // Fence lines left of the content column but right of the marker stay
                // in the item, which is then kept as written.
                if ind >= w || ind > cur_marker.col {
                    lazy |= ind < w;
                    let sl = strip_cols(l, w.min(ind));
                    if with_item(|| fence_close(&sl, ch, len)) {
                        in_fence = None;
                    }
                    item_lines.push(sl);
                    i += 1;
                    continue;
                }
                break;
            }
            if ind >= w {
                let sl = strip_cols(l, w);
                if let Some(f) = fence_open(&sl) {
                    in_fence = Some((f.ch, f.len));
                    last_was_para = false;
                } else {
                    last_was_para = !(atx_heading(&sl).is_some() || is_hr(&sl));
                }
                item_lines.push(sl);
                i += 1;
                continue;
            }
            // Left of the content column, paragraph text continues the item (lazily left
            // of the column a single space after the marker gives); other blocks right
            // of the marker keep the item as written.
            if list_marker(l).is_none() && ind > cur_marker.col {
                let n_col = cur_marker.col + cur_marker.marker.chars().count() + 1;
                lazy |= ind < n_col || !last_was_para || interrupts_paragraph(lines, i);
                item_lines.push(l.trim_start().to_string());
                i += 1;
                continue;
            }
            break;
        }
        // Task items (`[ ] text`): continuation lines of the first paragraph align
        // with the text after the checkbox.
        let mut task_shift = 0;
        let mut task_misaligned = false;
        if ["[ ] ", "[x] ", "[X] "].iter().any(|t| item_lines[0].starts_with(t)) {
            task_shift = 4;
            let mut k = 1;
            while k < item_lines.len() && !is_blank(&item_lines[k]) {
                let t = item_lines[k].trim_start();
                if list_marker(t).is_some() || t.starts_with('>') || fence_open(t).is_some() || atx_heading(t).is_some() {
                    break;
                }
                let ind = indent_of(&item_lines[k]);
                if ind < 4 {
                    task_misaligned = true;
                    break;
                }
                if ind < 8 {
                    item_lines[k] = strip_cols(&item_lines[k], 4);
                }
                k += 1;
            }
        }
        let mut children = with_defs(true, || with_colon_raw(false, || with_item(|| parse_blocks(&item_lines))));
        // A lone list marker on the item's first line is plain text of the item.
        if let Some(Block::List(sub)) = children.first() {
            if sub.items.len() == 1 && !cur_marker.empty {
                let n = sub.raw.len();
                let mut para: Vec<String> = sub.raw.iter().filter(|l| !is_blank(l)).cloned().collect();
                let trailing_blanks = sub.raw.iter().rev().take_while(|l| is_blank(l)).count();
                if para.len() + trailing_blanks == n {
                    para.truncate(n - trailing_blanks);
                    let mut rest = vec![Block::Para(para)];
                    rest.extend(sub.raw[n - trailing_blanks..].iter().map(|l| Block::Blank(l.clone())));
                    rest.extend(children.drain(1..));
                    children = rest;
                }
            }
        }
        items.push(Item {
            col: cur_marker.col,
            marker: cur_marker.marker.clone(),
            ordered: cur_marker.ordered,
            content_col: w,
            children,
            raw: lines[s..i].to_vec(),
            lazy,
            empty_first: cur_marker.empty,
            task_shift,
            task_misaligned,
        });
        // Trailing blank lines between items belong to the list if another item follows.
        let mut j = i;
        while j < n && is_blank(&lines[j]) {
            j += 1;
        }
        // After a blank line a thematic break ends the list.
        if j < n && !(j > i && is_hr(&lines[j])) {
            if let Some(m) = list_marker(&lines[j]).filter(|m| !empty_ordered_is_text(lines, j, m)) {
                // A marker left of the previous item's content starts a sibling item; a
                // marker of another list type joins too when not left of the list and
                // not after a blank line.
                let joins = if same_list_type(&m, first) {
                    m.col < cur_marker.content_col.max(first.col + 2) && (m.col + 2 > first.col || m.col == first.col)
                } else {
                    j == i && m.col >= first.col && m.col < cur_marker.content_col
                };
                if joins {
                    // Blank lines become part of the previous item.
                    if j > i {
                        let last = items.last_mut().unwrap();
                        for k in i..j {
                            last.raw.push(lines[k].clone());
                            last.children.push(Block::Blank(lines[k].clone()));
                        }
                    }
                    i = j;
                    cur_marker = m;
                    continue;
                }
            }
        }
        break;
    }
    let raw = lines[start..i].to_vec();
    (List { raw, items, ordered: first.ordered }, i)
}
