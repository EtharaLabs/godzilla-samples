// A position-preserving YAML parser producing a lossless-enough tree for formatting.

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScalarStyle {
    Plain,
    Single,
    Double,
    Literal,
    Folded,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Chomp {
    Clip,
    Strip,
    Keep,
}

thread_local! {
    /// First line of the last parse that needed structural recovery (a line
    /// without a key among entries, or a sequence left of its siblings).
    static STRUCT_RECOVERY: std::cell::Cell<Option<usize>> = const { std::cell::Cell::new(None) };
}

fn note_struct_recovery(line: usize) {
    STRUCT_RECOVERY.with(|r| r.set(Some(r.get().map_or(line, |l| l.min(line)))));
}

/// The first structurally recovered line of the last parse.
pub fn last_struct_recovery() -> Option<usize> {
    STRUCT_RECOVERY.with(|r| r.get())
}

#[derive(Debug, Clone)]
pub struct BlockHeader {
    pub indicator: Option<usize>,
    pub chomp: Chomp,
    /// Raw header text after the style character (e.g. "-", "2+").
    pub raw: String,
    pub comment: Option<String>,
    /// Absolute column of the content lines.
    pub content_indent: usize,
    /// Content lines (without indentation), as raw lines; may contain more-indented text.
    pub lines: Vec<String>,
    /// Line index of the first content line.
    pub first_line: usize,
    /// Number of source lines spanned by content (including trailing blank lines consumed).
    pub line_count: usize,
    /// Raw source lines of the content area (including trailing blank lines).
    pub raw_lines: Vec<String>,
    /// Content includes lines indented less than the content indentation.
    pub irregular: bool,
}

#[derive(Debug, Clone)]
pub struct Scalar {
    pub style: ScalarStyle,
    /// Byte span of the scalar text (excluding properties).
    pub start: usize,
    pub end: usize,
    pub value: String,
    pub multiline: bool,
    pub block: Option<BlockHeader>,
    /// Kept exactly as written (a double-quoted scalar with an unknown escape).
    pub verbatim: bool,
}

#[derive(Debug, Clone)]
pub struct Props {
    pub anchor: Option<String>,
    pub tag: Option<String>,
    pub start: usize,
    pub end: usize,
    /// Properties are followed by a line break before the node content.
    pub newline_after: bool,
}

#[derive(Debug, Clone)]
pub enum Kind {
    Null,
    Scalar(Scalar),
    Alias(String),
    Map(Vec<Entry>),
    Seq(Vec<Item>),
    FlowMap(Vec<FlowEntry>),
    FlowSeq(Vec<FlowEntry>),
}

#[derive(Debug, Clone)]
pub struct Node {
    pub start: usize,
    pub end: usize,
    pub line: usize,
    pub col: usize,
    pub props: Option<Props>,
    pub kind: Kind,
    /// Trailing comment on the node's last line (scalars, aliases, flow collections).
    pub comment: Option<String>,
    /// For flow collections: comments inside.
    pub flow_has_comment: bool,
    /// Source line range of node content.
    pub end_line: usize,
}

#[derive(Debug, Clone)]
pub struct Entry {
    pub line: usize,
    pub col: usize,
    pub start: usize,
    /// 0: normal; 1: kept verbatim (unparseable key line and its block); 2: emitted as a quoted line.
    pub quirk: u8,
    pub explicit: bool,
    pub key: Node,
    /// Byte span of the key text (from key start to before ':').
    pub key_end: usize,
    pub colon: usize,
    /// Comment after "key:" when the value is not on the same line.
    pub colon_comment: Option<String>,
    pub value: Node,
    pub value_same_line: bool,
    /// Trivia lines between key line and value start.
    pub trivia_before_value: bool,
    pub end: usize,
    pub end_line: usize,
    /// More-indented blocks after a finished value, kept at their own indentation.
    pub orphans: Vec<Node>,
}

#[derive(Debug, Clone)]
pub struct Item {
    pub line: usize,
    pub col: usize,
    pub start: usize,
    /// The item's line is kept as written (a trailing comment confused the key scan).
    pub verbatim_line: bool,
    pub dash_comment: Option<String>,
    pub value: Node,
    pub value_same_line: bool,
    pub trivia_before_value: bool,
    pub end: usize,
    pub end_line: usize,
    pub orphans: Vec<Node>,
}

#[derive(Debug, Clone)]
pub struct FlowEntry {
    pub key: Option<Node>,
    pub value: Option<Node>,
    /// Pair written with explicit '?' or as `key: value` inside a sequence.
    pub is_pair: bool,
    pub explicit: bool,
}

#[derive(Debug, Clone)]
pub struct Document {
    /// Line index of the '---' marker, if any.
    pub start_marker: Option<usize>,
    /// Byte offset just after '---' and following spaces when content is on the marker line.
    pub marker_content_start: Option<usize>,
    pub root: Option<Node>,
    /// Further top-level nodes after the root, formatted where they are written.
    pub extra: Vec<Node>,
    pub end_marker: Option<usize>,
    pub first_line: usize,
    pub last_line: usize,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LineKind {
    Content,
    Blank,
    Comment,
    Directive,
    DocStart,
    DocEnd,
}

#[derive(Debug)]
pub struct Stream {
    pub docs: Vec<Document>,
    pub line_kinds: Vec<LineKind>,
}

#[derive(Debug)]
pub struct ParseError {
    pub pos: usize,
    pub msg: String,
}

pub struct Parser<'a> {
    pub src: &'a str,
    b: &'a [u8],
    pos: usize,
    in_flow: bool,
    last_root_quirk_end: Option<usize>,
    pub line_starts: Vec<usize>,
    pub line_kinds: Vec<LineKind>,
}

type PResult<T> = Result<T, ParseError>;

fn is_ws(c: u8) -> bool {
    c == b' ' || c == b'\t'
}

fn is_flow_ind(c: u8) -> bool {
    matches!(c, b',' | b'[' | b']' | b'{' | b'}')
}

impl<'a> Parser<'a> {
    pub fn new(src: &'a str) -> Self {
        let b = src.as_bytes();
        let mut line_starts = vec![0];
        for (i, &c) in b.iter().enumerate() {
            if c == b'\n' && i + 1 <= b.len() {
                line_starts.push(i + 1);
            }
        }
        // A final empty line after a trailing newline is not a real line.
        if line_starts.len() > 1 && *line_starts.last().unwrap() == b.len() {
            line_starts.pop();
        }
        let n = line_starts.len();
        Parser { src, b, pos: 0, in_flow: false, last_root_quirk_end: None, line_starts, line_kinds: vec![LineKind::Content; n] }
    }

    fn err<T>(&self, msg: &str) -> PResult<T> {
        Err(ParseError { pos: self.pos, msg: msg.to_string() })
    }

    pub fn line_of(&self, pos: usize) -> usize {
        match self.line_starts.binary_search(&pos) {
            Ok(i) => i,
            Err(i) => i - 1,
        }
    }

    pub fn col_of(&self, pos: usize) -> usize {
        let l = self.line_of(pos);
        self.src[self.line_starts[l]..pos].chars().count()
    }

    fn peek(&self) -> u8 {
        if self.pos < self.b.len() {
            self.b[self.pos]
        } else {
            0
        }
    }

    fn peek_at(&self, off: usize) -> u8 {
        if self.pos + off < self.b.len() {
            self.b[self.pos + off]
        } else {
            0
        }
    }

    fn at_eof(&self) -> bool {
        self.pos >= self.b.len()
    }

    fn line_end(&self, pos: usize) -> usize {
        match self.src[pos..].find('\n') {
            Some(p) => pos + p,
            None => self.b.len(),
        }
    }

    fn skip_inline_ws(&mut self) {
        while self.pos < self.b.len() && is_ws(self.b[self.pos]) {
            self.pos += 1;
        }
    }

    /// True if at a break (newline or EOF) possibly after spaces.
    fn at_break(&self) -> bool {
        self.pos >= self.b.len() || self.b[self.pos] == b'\n'
    }

    /// Consume an optional trailing comment and the line break. Returns comment text.
    fn eat_line_rest(&mut self) -> PResult<Option<String>> {
        let save = self.pos;
        self.skip_inline_ws();
        let mut comment = None;
        if self.peek() == b'#' {
            if self.pos > save || self.pos == 0 || self.b[self.pos - 1] == b'\n' {
                let e = self.line_end(self.pos);
                comment = Some(self.src[self.pos..e].trim_end().to_string());
                self.pos = e;
            } else {
                return self.err("comment without preceding space");
            }
        }
        if self.at_eof() {
            return Ok(comment);
        }
        if self.peek() != b'\n' {
            return self.err("unexpected content at end of line");
        }
        self.pos += 1;
        Ok(comment)
    }

    fn is_doc_marker_at(&self, pos: usize) -> bool {
        let l = self.line_of(pos);
        if self.line_starts[l] != pos {
            return false;
        }
        let rest = &self.b[pos..];
        if rest.len() >= 3 && (&rest[..3] == b"---" || &rest[..3] == b"...") {
            return rest.len() == 3 || matches!(rest[3], b' ' | b'\t' | b'\n');
        }
        false
    }

    /// Skip blank and comment lines starting at a line start, recording them as trivia.
    /// Returns number of trivia lines skipped. Position must be at a line start.
    fn skip_trivia_lines(&mut self) -> usize {
        let mut count = 0;
        loop {
            if self.at_eof() {
                break;
            }
            let ls = self.pos;
            let le = self.line_end(ls);
            let line = &self.src[ls..le];
            let t = line.trim_start_matches([' ', '\t']);
            if t.is_empty() {
                let l = self.line_of(ls);
                self.line_kinds[l] = LineKind::Blank;
            } else if t.starts_with('#') || is_template_line(t) {
                // Lines holding only a template expression are trivia like comments.
                let l = self.line_of(ls);
                self.line_kinds[l] = LineKind::Comment;
            } else {
                break;
            }
            count += 1;
            self.pos = if le < self.b.len() { le + 1 } else { le };
        }
        count
    }

    /// Column of the first non-space character of the current line (pos at line start).
    fn line_indent(&self, ls: usize) -> usize {
        let mut i = ls;
        while i < self.b.len() && self.b[i] == b' ' {
            i += 1;
        }
        i - ls
    }

    pub fn parse_stream(mut self) -> PResult<Stream> {
        STRUCT_RECOVERY.with(|r| r.set(None));
        let mut docs = Vec::new();
        loop {
            self.skip_trivia_lines();
            // Directives.
            let mut saw_directive = false;
            while !self.at_eof() && self.peek() == b'%' {
                let l = self.line_of(self.pos);
                self.line_kinds[l] = LineKind::Directive;
                let e = self.line_end(self.pos);
                self.pos = if e < self.b.len() { e + 1 } else { e };
                saw_directive = true;
                self.skip_trivia_lines();
            }
            if self.at_eof() {
                if saw_directive {
                    return self.err("directive without document");
                }
                break;
            }
            let first_line = self.line_of(self.pos);
            let mut doc = Document {
                start_marker: None,
                marker_content_start: None,
                root: None,
                extra: Vec::new(),
                end_marker: None,
                first_line,
                last_line: first_line,
            };
            if self.is_doc_marker_at(self.pos) && self.b[self.pos] == b'-' {
                let l = self.line_of(self.pos);
                self.line_kinds[l] = LineKind::DocStart;
                doc.start_marker = Some(l);
                self.pos += 3;
                let save = self.pos;
                self.skip_inline_ws();
                if self.at_break() || (self.peek() == b'#' && self.pos > save) {
                    self.pos = save;
                    let _ = self.eat_line_rest()?;
                } else {
                    // Content on the marker line.
                    doc.marker_content_start = Some(self.pos);
                    let node = self.parse_marker_node()?;
                    doc.root = Some(node);
                }
            } else if saw_directive {
                return self.err("directive without document start");
            }
            if doc.root.is_none() {
                self.skip_trivia_lines();
                if !self.at_eof() && !self.is_doc_marker_at(self.pos) {
                    let node = self.parse_block_node(-1, Ctx::BlockOut)?;
                    doc.root = Some(node);
                }
            }
            self.skip_trivia_lines();
            while doc.root.is_some() && !self.at_eof() && !self.is_doc_marker_at(self.pos) {
                let ls = self.pos;
                let node = self.parse_block_node(-1, Ctx::BlockOut)?;
                if self.pos == ls {
                    return self.err("unexpected content after document");
                }
                doc.extra.push(node);
                self.skip_trivia_lines();
            }
            if !self.at_eof() {
                if self.is_doc_marker_at(self.pos) {
                    if self.b[self.pos] == b'.' {
                        let l = self.line_of(self.pos);
                        self.line_kinds[l] = LineKind::DocEnd;
                        doc.end_marker = Some(l);
                        let e = self.line_end(self.pos);
                        self.pos = if e < self.b.len() { e + 1 } else { e };
                    }
                } else {
                    return self.err("unexpected content after document");
                }
            }
            doc.last_line = if self.pos > 0 { self.line_of(self.pos.saturating_sub(1)) } else { 0 };
            docs.push(doc);
            if self.at_eof() {
                break;
            }
        }
        Ok(Stream { docs, line_kinds: self.line_kinds })
    }

    /// A node that begins on the `---` line.
    fn parse_marker_node(&mut self) -> PResult<Node> {
        let start = self.pos;
        let line = self.line_of(start);
        let col = self.col_of(start);
        let props = self.parse_props()?;
        if let Some(p) = &props {
            if p.newline_after {
                // Block collection below.
                let mut node = self.parse_block_node(-1, Ctx::BlockOut)?;
                node.start = start;
                node.line = line;
                node.col = col;
                node.props = props;
                return Ok(node);
            }
        }
        let c = self.peek();
        let mut node = if c == b'|' || c == b'>' {
            self.parse_block_scalar(-1)?
        } else if c == b'[' || c == b'{' {
            let n = self.parse_flow_collection()?;
            let comment = self.eat_line_rest()?;
            let mut n = n;
            n.comment = comment;
            n
        } else {
            let n = self.parse_inline_scalar_or_alias(-1, false)?;
            let comment = self.eat_line_rest()?;
            let mut n = n;
            n.comment = comment;
            n
        };
        node.start = start;
        node.line = line;
        node.col = col;
        node.props = props;
        Ok(node)
    }

    /// Parse optional properties (anchor/tag) at current position.
    fn parse_props(&mut self) -> PResult<Option<Props>> {
        let start = self.pos;
        let mut anchor = None;
        let mut tag = None;
        let mut end = self.pos;
        loop {
            let c = self.peek();
            if c == b'&' && anchor.is_none() {
                let s = self.pos + 1;
                let mut i = s;
                while i < self.b.len() && !matches!(self.b[i], b' ' | b'\t' | b'\n') && !is_flow_ind(self.b[i]) {
                    i += 1;
                }
                if i == s {
                    return self.err("empty anchor");
                }
                anchor = Some(self.src[s..i].to_string());
                self.pos = i;
                end = i;
            } else if c == b'!' && tag.is_none() {
                let s = self.pos;
                let mut i = s + 1;
                if i < self.b.len() && self.b[i] == b'<' {
                    while i < self.b.len() && self.b[i] != b'>' && self.b[i] != b'\n' {
                        i += 1;
                    }
                    if i >= self.b.len() || self.b[i] != b'>' {
                        return self.err("bad verbatim tag");
                    }
                    i += 1;
                } else {
                    while i < self.b.len() && !matches!(self.b[i], b' ' | b'\t' | b'\n') && !is_flow_ind(self.b[i]) {
                        i += 1;
                    }
                }
                tag = Some(self.src[s..i].to_string());
                self.pos = i;
                end = i;
            } else {
                break;
            }
            let save = self.pos;
            self.skip_inline_ws();
            if self.peek() != b'&' && self.peek() != b'!' {
                self.pos = save;
                break;
            }
            if self.pos == save {
                return self.err("properties need separation");
            }
        }
        if anchor.is_none() && tag.is_none() {
            return Ok(None);
        }
        // Determine whether a line break follows.
        let save = self.pos;
        self.skip_inline_ws();
        let mut newline_after = false;
        if self.at_break() || (self.peek() == b'#' && self.pos > save) {
            newline_after = true;
            self.pos = save;
        } else if self.pos == save && !is_flow_ind(self.peek()) && self.peek() != b':' {
            return self.err("properties need separation");
        }
        Ok(Some(Props { anchor, tag, start, end, newline_after }))
    }

    /// Parse a block node whose parent is at indentation `parent`.
    /// Position: either mid-line after an indicator (e.g. after "key:" or "- "), or at a line start.
    fn parse_block_node(&mut self, parent: isize, ctx: Ctx) -> PResult<Node> {
        // Determine where content starts.
        let save = self.pos;
        self.skip_inline_ws();
        let at_line_start_content;
        if self.at_break() || self.peek() == b'#' {
            // Content (if any) is on following lines.
            self.pos = save;
            let comment = self.eat_line_rest()?;
            let _ = comment;
            self.skip_trivia_lines();
            at_line_start_content = true;
        } else {
            at_line_start_content = false;
        }
        if self.at_eof() {
            return Ok(self.null_node());
        }
        if at_line_start_content {
            let ls = self.pos;
            let ind = self.line_indent(ls) as isize;
            if self.is_doc_marker_at(ls) {
                return Ok(self.null_node());
            }
            self.pos = ls + ind as usize;
            if self.peek() == b'\t' {
                return self.err("tab indentation");
            }
            let c = self.peek();
            let is_seq = c == b'-' && matches!(self.peek_at(1), b' ' | b'\t' | b'\n' | 0);
            // A block sequence as a mapping value may sit at the parent's column.
            let ok = ind > parent || (ctx == Ctx::MapValue && is_seq && ind == parent);
            if !ok {
                self.pos = ls;
                return Ok(self.null_node());
            }
        }
        let start = self.pos;
        let line = self.line_of(start);
        let col = self.col_of(start);
        let props = self.parse_props()?;
        if let Some(p) = &props {
            let ls = self.line_starts[self.line_of(start)];
            let first_on_line = self.src[ls..start].trim().is_empty();
            if p.newline_after && (at_line_start_content || first_on_line) && parent >= 0 {
                return self.err("properties on their own line");
            }
            if p.newline_after {
                // Comment/newline after props; the content follows on next lines.
                let pend = self.pos;
                let _ = self.eat_line_rest()?;
                let n_trivia = self.skip_trivia_lines();
                let _ = n_trivia;
                if self.at_eof() || self.is_doc_marker_at(self.pos) {
                    let mut n = self.null_node();
                    n.start = start;
                    n.end = pend;
                    n.line = line;
                    n.col = col;
                    n.end_line = line;
                    n.props = props;
                    return Ok(n);
                }
                let ls = self.pos;
                let ind = self.line_indent(ls) as isize;
                self.pos = ls + ind as usize;
                let c = self.peek();
                let is_seq = c == b'-' && matches!(self.peek_at(1), b' ' | b'\t' | b'\n' | 0);
                let ok = ind > parent || (ctx == Ctx::MapValue && is_seq && ind == parent);
                if !ok {
                    self.pos = ls;
                    let mut n = self.null_node();
                    n.start = start;
                    n.end = pend;
                    n.line = line;
                    n.col = col;
                    n.end_line = line;
                    n.props = props;
                    return Ok(n);
                }
                let mut node = self.parse_block_content(parent, ctx)?;
                node.start = start;
                node.line = line;
                node.col = col;
                node.props = props;
                return Ok(node);
            }
        }
        let mut node = self.parse_block_content(parent, ctx)?;
        if props.is_some() {
            node.start = start;
            node.line = line;
            node.col = col;
            node.props = props;
        }
        Ok(node)
    }

    fn null_node(&self) -> Node {
        Node {
            start: self.pos,
            end: self.pos,
            line: self.line_of(self.pos.min(self.b.len().saturating_sub(1)).max(0)),
            col: 0,
            props: None,
            kind: Kind::Null,
            comment: None,
            flow_has_comment: false,
            end_line: 0,
        }
    }

    /// Parse block content at the current position (content start, after properties).
    fn parse_block_content(&mut self, parent: isize, ctx: Ctx) -> PResult<Node> {
        let start = self.pos;
        let col = self.col_of(start);
        let c = self.peek();
        let ls = self.line_starts[self.line_of(start)];
        let inline_value = ctx == Ctx::MapValue && self.src[ls..start].contains(':') && !self.src[ls..start].trim().is_empty() && self.inline_after_key(start);
        if inline_value {
            // A value on the key's line cannot start a block collection.
            if c == b'-' && matches!(self.peek_at(1), b' ' | b'\t' | b'\n' | 0) {
                return self.err("block sequence on key line");
            }
            if !matches!(c, b'[' | b'{' | b'|' | b'>' | b'"' | b'\'' | b'*' | b'&' | b'!') {
                let mut n = self.parse_plain_block_opts(parent, true)?;
                n.comment = self.eat_line_rest()?;
                return Ok(n);
            }
        }
        if c == b'-' && matches!(self.peek_at(1), b' ' | b'\t' | b'\n' | 0) {
            return self.parse_block_seq(col);
        }
        if !matches!(c, b'[' | b'{' | b'|' | b'>' | b'"' | b'\'' | b'*' | b'&' | b'!' | b'?') {
            match self.colon_key_quirk() {
                Some(true) if parent >= 0 => {
                    let mut n = self.parse_plain_block_opts(parent, true)?;
                    n.comment = self.eat_line_rest()?;
                    return Ok(n);
                }
                Some(true) => return self.parse_block_map(col, parent),
                Some(_) => return self.err("plain key containing colon"),
                None => {}
            }
        }
        if c == b'?' && matches!(self.peek_at(1), b' ' | b'\t' | b'\n' | 0) {
            return self.parse_block_map(col, parent);
        }
        if c == b'|' || c == b'>' {
            return self.parse_block_scalar(parent);
        }
        // Possibly an implicit key: look ahead for "key:" on this line.
        if self.implicit_key_ahead() {
            return self.parse_block_map(col, parent);
        }
        if c == b'[' || c == b'{' {
            let mut n = self.parse_flow_collection()?;
            n.comment = self.eat_line_rest()?;
            return Ok(n);
        }
        let _ = ctx;
        let mut n = self.parse_inline_scalar_or_alias(parent, true)?;
        n.comment = self.eat_line_rest()?;
        Ok(n)
    }

    /// A root-level line whose key contains ':' : either kept verbatim with its
    /// indented block, or (with a flow tail) rendered as a quoted line.
    fn root_quirk_entry(&mut self, col: usize, estart: usize) -> PResult<Option<Entry>> {
        let le = self.line_end(estart);
        let line = &self.src[estart..le];
        let t = line.trim_end();
        let (rest_is_flow, rest_empty) = match self.colon_key_quirk() {
            Some(true) => {
                let tail = t.rsplit_once(": ").map(|x| x.1.trim()).unwrap_or("");
                (!t.ends_with(':') && (tail.starts_with('[') || tail.starts_with('{')), t.ends_with(':'))
            }
            _ => return Ok(None),
        };
        let eline = self.line_of(estart);
        let mut end_line = eline;
        let quirk;
        if rest_empty {
            // The region runs over blank, more-indented and quirk lines, ending before a
            // comment line or an ordinary key line. Blank lines inside, trailing comments,
            // or a terminating comment keep it verbatim; otherwise it reads as one plain scalar.
            let mut l = eline + 1;
            let mut has_comment = self.src[estart..le].contains(" #");
            let mut ended_by_comment = false;
            let mut pending_blank = false;
            while l < self.line_starts.len() {
                let ls = self.line_starts[l];
                let lt = &self.src[ls..self.line_end(ls)];
                if lt.trim().is_empty() {
                    pending_blank = true;
                    l += 1;
                    continue;
                }
                if lt.trim_start().starts_with('#') {
                    ended_by_comment = !pending_blank;
                    break;
                }
                pending_blank = false;
                let ind = self.line_indent(ls);
                if ind > col || self.is_quirk_line(ls + ind) {
                    if lt.contains(" #") {
                        has_comment = true;
                    }
                    end_line = l;
                    l += 1;
                    continue;
                }
                break;
            }
            let has_blank = (eline..=end_line).any(|k| self.src[self.line_starts[k]..self.line_end(self.line_starts[k])].trim().is_empty());
            quirk = if has_comment || ended_by_comment || has_blank { 1 } else { 3 };
            self.last_root_quirk_end = Some(end_line);
        } else if rest_is_flow {
            quirk = 2;
        } else {
            return Ok(None);
        }
        let end = self.line_end(self.line_starts[end_line]);
        self.pos = if end < self.b.len() { end + 1 } else { end };
        let key = Node {
            start: estart,
            end: le,
            line: eline,
            col,
            props: None,
            kind: Kind::Null,
            comment: None,
            flow_has_comment: false,
            end_line: eline,
        };
        let value = Node { start: end, end, line: end_line, col: 0, props: None, kind: Kind::Null, comment: None, flow_has_comment: false, end_line };
        Ok(Some(Entry {
            line: eline,
            col,
            start: estart,
            quirk,
            explicit: false,
            key,
            key_end: le,
            colon: le,
            colon_comment: None,
            value,
            value_same_line: true,
            trivia_before_value: false,
            end,
            end_line,
            orphans: Vec::new(),
        }))
    }

    /// Whether the line content at `pos` is a key line whose plain key contains ':'.
    fn is_quirk_line(&self, pos: usize) -> bool {
        if pos >= self.b.len() || matches!(self.b[pos], b'[' | b'{' | b'"' | b'\'' | b'*' | b'&' | b'!' | b'#' | b'-') {
            return false;
        }
        let le = self.line_end(pos);
        let line = &self.src[pos..le];
        let lb = line.as_bytes();
        for i in 0..lb.len() {
            if lb[i] == b'#' && i > 0 && is_ws(lb[i - 1]) {
                return false;
            }
            if lb[i] == b':' && (i + 1 >= lb.len() || is_ws(lb[i + 1])) {
                return key_has_bare_colon(&line[..i]);
            }
        }
        false
    }

    /// Whether `pos` is directly after a "key:" on the same line (not after "- ").
    fn inline_after_key(&self, pos: usize) -> bool {
        let ls = self.line_starts[self.line_of(pos)];
        let before = self.src[ls..pos].trim_end();
        before.ends_with(':')
    }

    /// Lines whose plain key contains ':' are not keys. Returns Some(true) when the line
    /// ends in a complete flow collection after ": " (read as one plain scalar).
    fn colon_key_quirk(&self) -> Option<bool> {
        let le = self.line_end(self.pos);
        let line = &self.src[self.pos..le];
        let lb = line.as_bytes();
        let mut i = 0;
        let mut found = None;
        while i < lb.len() {
            if lb[i] == b'#' && i > 0 && is_ws(lb[i - 1]) {
                break;
            }
            if lb[i] == b':' && (i + 1 >= lb.len() || is_ws(lb[i + 1])) {
                found = Some(i);
                break;
            }
            i += 1;
        }
        let i = found?;
        let key = &line[..i];
        if !key_has_bare_colon(key) {
            return None;
        }
        let rest = line[i + 1..].trim();
        if rest.is_empty() || (rest.starts_with('[') && rest.ends_with(']')) || (rest.starts_with('{') && rest.ends_with('}')) {
            return Some(true);
        }
        Some(false)
    }

    /// Check whether the current line holds an implicit mapping key at the current position.
    fn implicit_key_ahead(&mut self) -> bool {
        let save = self.pos;
        let r = self.try_scan_implicit_key();
        self.pos = save;
        r
    }

    fn try_scan_implicit_key(&mut self) -> bool {
        let c = self.peek();
        let ok = if c == b'[' || c == b'{' {
            self.skip_flow_raw().is_ok()
        } else if c == b'"' || c == b'\'' {
            match self.scan_quoted_end() {
                Some(e) => {
                    // Implicit keys must be single-line.
                    if self.src[self.pos..e].contains('\n') {
                        return false;
                    }
                    self.pos = e;
                    true
                }
                None => false,
            }
        } else if c == b'*' {
            while self.pos < self.b.len() && !matches!(self.b[self.pos], b' ' | b'\t' | b'\n') && !is_flow_ind(self.b[self.pos]) {
                self.pos += 1;
            }
            true
        } else if c == b'&' || c == b'!' {
            // Properties before a key.
            if self.parse_props().ok().flatten().map(|p| p.newline_after).unwrap_or(true) {
                return false;
            }
            self.skip_inline_ws();
            return self.try_scan_implicit_key();
        } else {
            // Plain scalar on one line: find ": " or ":" EOL.
            let le = self.line_end(self.pos);
            let mut i = self.pos;
            let mut prev_space = false;
            while i < le {
                let ch = self.b[i];
                if ch == b':' && (i + 1 >= le || matches!(self.b[i + 1], b' ' | b'\t')) {
                    self.pos = i;
                    break;
                }
                if ch == b'#' && prev_space {
                    return false;
                }
                prev_space = is_ws(ch);
                i += 1;
            }
            if i >= le {
                return false;
            }
            let start = self.line_starts[self.line_of(i)];
            let _ = start;
            true
        };
        if !ok {
            return false;
        }
        self.skip_inline_ws();
        self.peek() == b':' && matches!(self.peek_at(1), b' ' | b'\t' | b'\n' | 0)
    }

    fn scan_quoted_end(&self) -> Option<usize> {
        let q = self.b[self.pos];
        let mut i = self.pos + 1;
        while i < self.b.len() {
            let c = self.b[i];
            if q == b'\'' {
                if c == b'\'' {
                    if i + 1 < self.b.len() && self.b[i + 1] == b'\'' {
                        i += 2;
                        continue;
                    }
                    return Some(i + 1);
                }
            } else {
                if c == b'\\' {
                    i += 2;
                    continue;
                }
                if c == b'"' {
                    return Some(i + 1);
                }
            }
            i += 1;
        }
        None
    }

    fn skip_flow_raw(&mut self) -> PResult<()> {
        let mut depth = 0i32;
        loop {
            if self.at_eof() {
                return self.err("unterminated flow");
            }
            let c = self.peek();
            match c {
                b'[' | b'{' => {
                    depth += 1;
                    self.pos += 1;
                }
                b']' | b'}' => {
                    depth -= 1;
                    self.pos += 1;
                    if depth == 0 {
                        return Ok(());
                    }
                }
                b'"' | b'\'' => match self.scan_quoted_end() {
                    Some(e) => self.pos = e,
                    None => return self.err("unterminated quote"),
                },
                b'#' => {
                    if self.pos > 0 && matches!(self.b[self.pos - 1], b' ' | b'\t' | b'\n') {
                        self.pos = self.line_end(self.pos);
                    } else {
                        self.pos += 1;
                    }
                }
                _ => self.pos += 1,
            }
        }
    }

    fn parse_block_seq(&mut self, col: usize) -> PResult<Node> {
        let start = self.pos;
        let line = self.line_of(start);
        let mut items = Vec::new();
        loop {
            // At '-'
            let istart = self.pos;
            let iline = self.line_of(istart);
            self.pos += 1;
            let save = self.pos;
            self.skip_inline_ws();
            let mut dash_comment = None;
            let value_same_line;
            let mut trivia_before_value = false;
            if self.at_break() || self.peek() == b'#' {
                self.pos = save;
                dash_comment = self.eat_line_rest()?;
                let n = self.skip_trivia_lines();
                trivia_before_value = n > 0;
                value_same_line = false;
            } else {
                value_same_line = true;
            }
            let mut verbatim_line = false;
            if value_same_line {
                // A ": " that only appears inside a trailing comment confuses the key scan.
                let cs = self.pos;
                let c0 = self.peek();
                if !matches!(c0, b'"' | b'\'' | b'[' | b'{' | b'*' | b'&' | b'!' | b'|' | b'>' | b'-' | b'?') {
                    let le = self.line_end(cs);
                    let line = &self.src[cs..le];
                    let lb = line.as_bytes();
                    let mut comment_at = None;
                    for k in 1..lb.len() {
                        if lb[k] == b'#' && is_ws(lb[k - 1]) {
                            comment_at = Some(k);
                            break;
                        }
                    }
                    if let Some(ca) = comment_at {
                        let before = &line[..ca];
                        let after = &line[ca..];
                        let colon_in = |t: &str| t.contains(": ") || t.contains(":\t") || t.trim_end().ends_with(':');
                        if !colon_in(before) && colon_in(after) {
                            if before.contains(':') {
                                return self.err("colon in item comment");
                            }
                            verbatim_line = true;
                        }
                    }
                }
            }
            let value = if value_same_line {
                self.parse_block_node(col as isize, Ctx::SeqItem)?
            } else {
                // Content on next lines must be indented more than the dash.
                if self.at_eof() || self.is_doc_marker_at(self.pos) {
                    self.null_node()
                } else {
                    let ls = self.pos;
                    let ind = self.line_indent(ls);
                    if ind > col {
                        self.parse_block_node(col as isize, Ctx::SeqItem)?
                    } else {
                        self.null_node()
                    }
                }
            };
            let iend = if matches!(value.kind, Kind::Null) && value.props.is_none() {
                istart + 1
            } else {
                value.end
            };
            let mut end_line = self.line_of(iend.saturating_sub(1).max(istart));
            if !matches!(value.kind, Kind::Null) {
                end_line = end_line.max(value.end_line);
            }
            items.push(Item {
                line: iline,
                col,
                start: istart,
                verbatim_line,
                dash_comment,
                value,
                value_same_line,
                trivia_before_value,
                end: iend,
                end_line,
                orphans: Vec::new(),
            });
            // Next item? Blocks indented under a finished value stay at their own indentation.
            let ind = loop {
                self.skip_trivia_lines();
                if self.at_eof() || self.is_doc_marker_at(self.pos) {
                    break None;
                }
                let ls = self.pos;
                let ind = self.line_indent(ls);
                if ind <= col {
                    break Some(ind);
                }
                self.pos = ls + ind;
                let orphan = self.parse_block_node(ind as isize - 1, Ctx::BlockOut)?;
                if self.pos == ls + ind {
                    return self.err("bad indentation in sequence");
                }
                let last = items.last_mut().unwrap();
                last.end = orphan.end;
                last.end_line = last.end_line.max(orphan.end_line);
                last.orphans.push(orphan);
            };
            let Some(ind) = ind else { break };
            let ls = self.pos;
            if ind == col && self.b.get(ls + ind) == Some(&b'-') && matches!(self.b.get(ls + ind + 1), Some(b' ') | Some(b'\t') | Some(b'\n') | None) {
                self.pos = ls + ind;
                continue;
            }
            break;
        }
        let end = items.last().map(|i| i.end).unwrap_or(start);
        let end_line = items.last().map(|i| i.end_line).unwrap_or(line);
        Ok(Node {
            start,
            end,
            line,
            col,
            props: None,
            kind: Kind::Seq(items),
            comment: None,
            flow_has_comment: false,
            end_line,
        })
    }

    /// After a mapping entry: attach blocks indented under it, then report whether
    /// another entry follows at `col` (positioned at its content).
    fn map_entry_tail(&mut self, col: usize, entries: &mut [Entry]) -> PResult<bool> {
        // Blocks indented under a finished value, and sequences at the mapping's
        // column, stay where they are written.
        loop {
            self.skip_trivia_lines();
            if self.at_eof() || self.is_doc_marker_at(self.pos) {
                return Ok(false);
            }
            let ls = self.pos;
            let ind = self.line_indent(ls);
            if ind < col {
                return Ok(false);
            }
            self.pos = ls + ind;
            let orphan = if ind == col {
                let c = self.peek();
                if c == b'\t' {
                    return self.err("tab");
                }
                if !(c == b'-' && matches!(self.peek_at(1), b' ' | b'\t' | b'\n' | 0)) {
                    return Ok(true);
                }
                self.parse_block_seq(col)?
            } else {
                let n = self.parse_block_node(ind as isize - 1, Ctx::BlockOut)?;
                if self.pos == ls + ind {
                    return self.err("bad indentation in mapping");
                }
                n
            };
            if matches!(orphan.kind, Kind::Seq(_)) {
                note_struct_recovery(orphan.line);
            }
            let last = entries.last_mut().unwrap();
            last.end = orphan.end;
            last.end_line = last.end_line.max(orphan.end_line);
            last.orphans.push(orphan);
        }
    }

    fn parse_block_map(&mut self, col: usize, parent: isize) -> PResult<Node> {
        let _ = parent;
        let start = self.pos;
        let line = self.line_of(start);
        let mut entries = Vec::new();
        loop {
            let estart = self.pos;
            let eline = self.line_of(estart);
            let explicit = self.peek() == b'?' && matches!(self.peek_at(1), b' ' | b'\t' | b'\n' | 0);
            let key;
            let key_end;
            if explicit {
                self.pos += 1;
                key = self.parse_block_node(col as isize, Ctx::SeqItem)?;
                key_end = key.end.max(estart + 1);
                // Expect ':' at column col on a following line (or none).
                self.skip_trivia_lines();
                let ls = self.pos;
                let ind = if self.at_eof() { 0 } else { self.line_indent(ls) };
                if !self.at_eof() && ind == col && self.b.get(ls + ind) == Some(&b':') && matches!(self.b.get(ls + ind + 1), Some(b' ') | Some(b'\t') | Some(b'\n') | None) {
                    self.pos = ls + ind;
                } else {
                    // No value.
                    let end = key_end;
                    let end_line = self.line_of(end.saturating_sub(1).max(estart));
                    let value = self.null_node();
                    entries.push(Entry {
                        line: eline,
                        col,
                        start: estart,
                        quirk: 0,
                        explicit: true,
                        key,
                        key_end,
                        colon: end,
                        colon_comment: None,
                        value,
                        value_same_line: false,
                        trivia_before_value: false,
                        end,
                        end_line,
                        orphans: Vec::new(),
                    });
                    if self.at_eof() || self.is_doc_marker_at(ls) {
                        break;
                    }
                    if ind == col {
                        self.pos = ls + ind;
                        continue;
                    }
                    if ind > col {
                        return self.err("bad indentation in mapping");
                    }
                    break;
                }
            } else {
                if !matches!(self.peek(), b'[' | b'{' | b'"' | b'\'' | b'*' | b'&' | b'!') && self.colon_key_quirk().is_some() {
                    if parent < 0 {
                        if let Some(e) = self.root_quirk_entry(col, estart)? {
                            entries.push(e);
                            self.skip_trivia_lines();
                            if self.at_eof() {
                                break;
                            }
                            let ls = self.pos;
                            if self.is_doc_marker_at(ls) {
                                break;
                            }
                            let ind = self.line_indent(ls);
                            if ind == col {
                                self.pos = ls + ind;
                                continue;
                            }
                            if ind > col {
                                return self.err("bad indentation in mapping");
                            }
                            break;
                        }
                    }
                    return self.err("plain key containing colon");
                }
                key = self.parse_implicit_key()?;
                key_end = key.end;
                self.skip_inline_ws();
                if self.peek() != b':' {
                    // A plain line without a key after the first entry is kept as written.
                    let plain = key.props.is_none() && matches!(&key.kind, Kind::Scalar(sc) if sc.style == ScalarStyle::Plain);
                    if entries.is_empty() || !plain {
                        return self.err("expected ':'");
                    }
                    self.pos = estart;
                    note_struct_recovery(eline);
                    // Following lines at the same column continue it.
                    let mut node = self.parse_plain_block(col as isize - 1, false)?;
                    node.comment = self.eat_line_rest()?;
                    let (end, end_line) = (node.end, node.end_line);
                    let value = self.null_node();
                    entries.push(Entry {
                        line: eline,
                        col,
                        start: estart,
                        quirk: 4,
                        explicit: false,
                        key: node,
                        key_end: end,
                        colon: end,
                        colon_comment: None,
                        value,
                        value_same_line: true,
                        trivia_before_value: false,
                        end,
                        end_line,
                        orphans: Vec::new(),
                    });
                    if !self.map_entry_tail(col, &mut entries)? {
                        break;
                    }
                    continue;
                }
            }
            let colon = self.pos;
            self.pos += 1;
            // Value.
            let save = self.pos;
            self.skip_inline_ws();
            let mut colon_comment = None;
            let mut value_same_line = true;
            let mut trivia_before_value = false;
            if self.at_break() || self.peek() == b'#' {
                self.pos = save;
                colon_comment = self.eat_line_rest()?;
                value_same_line = false;
                let n = self.skip_trivia_lines();
                trivia_before_value = n > 0;
            } else if self.pos == save {
                return self.err("missing space after colon");
            }
            let value = if value_same_line {
                self.parse_block_node(col as isize, Ctx::MapValue)?
            } else if self.at_eof() || self.is_doc_marker_at(self.pos) {
                self.null_node()
            } else {
                let ls = self.pos;
                let ind = self.line_indent(ls);
                let is_seq = self.b.get(ls + ind) == Some(&b'-') && matches!(self.b.get(ls + ind + 1), Some(b' ') | Some(b'\t') | Some(b'\n') | None);
                if ind > col || (ind == col && is_seq) {
                    self.parse_block_node(col as isize, Ctx::MapValue)?
                } else {
                    self.null_node()
                }
            };
            let end = if matches!(value.kind, Kind::Null) && value.props.is_none() {
                colon + 1
            } else {
                value.end
            };
            let mut end_line = self.line_of(end.saturating_sub(1).max(estart));
            if !matches!(value.kind, Kind::Null) {
                end_line = end_line.max(value.end_line);
            }
            entries.push(Entry {
                line: eline,
                col,
                start: estart,
                quirk: 0,
                explicit,
                key,
                key_end,
                colon,
                colon_comment,
                value,
                value_same_line,
                trivia_before_value,
                end,
                end_line,
                orphans: Vec::new(),
            });
            if !self.map_entry_tail(col, &mut entries)? {
                break;
            }
        }
        let end = entries.last().map(|e| e.end).unwrap_or(start);
        let end_line = entries.last().map(|e| e.end_line).unwrap_or(line);
        Ok(Node {
            start,
            end,
            line,
            col,
            props: None,
            kind: Kind::Map(entries),
            comment: None,
            flow_has_comment: false,
            end_line,
        })
    }

    fn parse_implicit_key(&mut self) -> PResult<Node> {
        let start = self.pos;
        let line = self.line_of(start);
        let col = self.col_of(start);
        let props = self.parse_props()?;
        if let Some(p) = &props {
            if p.newline_after {
                return self.err("props before key newline");
            }
            self.skip_inline_ws();
        }
        let c = self.peek();
        let mut node = if c == b'[' || c == b'{' {
            self.parse_flow_collection()?
        } else if c == b'"' || c == b'\'' {
            self.parse_quoted(-1)?
        } else if c == b'*' {
            self.parse_alias()?
        } else {
            // Plain key up to ':'.
            let le = self.line_end(self.pos);
            let mut i = self.pos;
            while i < le {
                if self.b[i] == b':' && (i + 1 >= le || matches!(self.b[i + 1], b' ' | b'\t')) {
                    break;
                }
                i += 1;
            }
            let mut e = i;
            while e > self.pos && is_ws(self.b[e - 1]) {
                e -= 1;
            }
            let text = self.src[self.pos..e].to_string();
            if i < le && has_unclosed_opener(&text) {
                return self.err("unclosed bracket or quote in key");
            }
            let s = self.pos;
            self.pos = e;
            Node {
                start: s,
                end: e,
                line,
                col: self.col_of(s),
                props: None,
                kind: Kind::Scalar(Scalar {
                    style: ScalarStyle::Plain,
                    start: s,
                    end: e,
                    value: text,
                    multiline: false,
                    verbatim: false,
                    block: None,
                }),
                comment: None,
                flow_has_comment: false,
                end_line: line,
            }
        };
        if props.is_some() {
            node.start = start;
            node.col = col;
            node.props = props;
        }
        Ok(node)
    }

    fn parse_alias(&mut self) -> PResult<Node> {
        let s = self.pos;
        self.pos += 1;
        while self.pos < self.b.len() && !matches!(self.b[self.pos], b' ' | b'\t' | b'\n') && !is_flow_ind(self.b[self.pos]) {
            self.pos += 1;
        }
        if self.pos == s + 1 {
            return self.err("empty alias");
        }
        let line = self.line_of(s);
        Ok(Node {
            start: s,
            end: self.pos,
            line,
            col: self.col_of(s),
            props: None,
            kind: Kind::Alias(self.src[s + 1..self.pos].to_string()),
            comment: None,
            flow_has_comment: false,
            end_line: line,
        })
    }

    /// Parse a plain/quoted scalar or alias in block context (value position).
    fn parse_inline_scalar_or_alias(&mut self, parent: isize, block: bool) -> PResult<Node> {
        let c = self.peek();
        if c == b'*' {
            return self.parse_alias();
        }
        if c == b'"' || c == b'\'' {
            return self.parse_quoted(parent);
        }
        self.parse_plain_block(parent, block)
    }

    fn parse_quoted(&mut self, parent: isize) -> PResult<Node> {
        let s = self.pos;
        let line = self.line_of(s);
        let e = match self.scan_quoted_end() {
            Some(e) => e,
            None => return self.err("unterminated quoted scalar"),
        };
        let raw = &self.src[s..e];
        // Continuation lines must be indented more than the parent.
        if raw.contains('\n') {
            for (i, l) in raw.split('\n').enumerate() {
                if i == 0 {
                    continue;
                }
                let ind = l.len() - l.trim_start_matches(' ').len();
                let t = l.trim_start_matches([' ', '\t']);
                if !t.is_empty() && (ind as isize) <= parent {
                    return self.err("bad quoted indentation");
                }
                if i > 0 && (l.starts_with("---") || l.starts_with("...")) && (l.len() == 3 || matches!(l.as_bytes()[3], b' ' | b'\t')) {
                    return self.err("document marker in quoted scalar");
                }
            }
        }
        let style = if self.b[s] == b'"' { ScalarStyle::Double } else { ScalarStyle::Single };
        // An unknown escape keeps the scalar as written.
        let mut verbatim = false;
        let value = match style {
            ScalarStyle::Double => match decode_double(&raw[1..raw.len() - 1]) {
                Some(v) => v,
                None => {
                    verbatim = true;
                    raw[1..raw.len() - 1].to_string()
                }
            },
            _ => decode_single(&raw[1..raw.len() - 1]),
        };
        self.pos = e;
        let end_line = self.line_of(e - 1);
        Ok(Node {
            start: s,
            end: e,
            line,
            col: self.col_of(s),
            props: None,
            kind: Kind::Scalar(Scalar {
                style,
                start: s,
                end: e,
                value,
                multiline: end_line > line,
                verbatim,
                block: None,
            }),
            comment: None,
            flow_has_comment: false,
            end_line,
        })
    }

    /// Plain scalar in block context, possibly multi-line.
    fn parse_plain_block(&mut self, parent: isize, _block: bool) -> PResult<Node> {
        self.parse_plain_block_opts(parent, false)
    }

    fn parse_plain_block_opts(&mut self, parent: isize, allow_colon: bool) -> PResult<Node> {
        let s = self.pos;
        let line = self.line_of(s);
        let c = self.peek();
        // Indicators that cannot start a plain scalar.
        // The reserved indicators `@` and backtick are accepted.
        if matches!(c, b'#' | b'&' | b'*' | b'!' | b'|' | b'>' | b'\'' | b'"' | b'%' | b'[' | b']' | b'{' | b'}' | b',') {
            return self.err("invalid plain scalar start");
        }
        if matches!(c, b'-' | b'?' | b':') && matches!(self.peek_at(1), b' ' | b'\t' | b'\n' | 0) {
            return self.err("invalid plain scalar start");
        }
        let mut end = if allow_colon { self.scan_plain_line_colon(self.pos) } else { self.scan_plain_line(self.pos)? };
        let mut lines: Vec<(usize, usize)> = vec![(s, end)];
        let first_indent = self.line_indent(self.line_starts[line]);
        // Continuation lines.
        let mut p = end;
        loop {
            // Move to next line.
            let mut q = p;
            while q < self.b.len() && is_ws(self.b[q]) {
                q += 1;
            }
            if q < self.b.len() && self.b[q] == b'#' {
                break;
            }
            if q >= self.b.len() || self.b[q] != b'\n' {
                break;
            }
            // Skip blank lines.
            let mut ls = q + 1;
            let mut blank_lines = 0;
            loop {
                if ls >= self.b.len() {
                    break;
                }
                let le = self.line_end(ls);
                if self.src[ls..le].trim_matches([' ', '\t']).is_empty() {
                    blank_lines += 1;
                    ls = if le < self.b.len() { le + 1 } else { le };
                } else {
                    break;
                }
            }
            if ls >= self.b.len() {
                break;
            }
            let ind = self.line_indent(ls) as isize;
            if ind <= parent {
                break;
            }
            if self.is_doc_marker_at(ls) {
                break;
            }
            let cs = ls + ind as usize;
            let mut cs2 = cs;
            while cs2 < self.b.len() && is_ws(self.b[cs2]) {
                cs2 += 1;
            }
            if self.b[cs2] == b'#' {
                break;
            }
            let starts_line = self.src[self.line_starts[line]..s].trim().is_empty();
            if allow_colon && starts_line && (ind as usize) <= self.col_of(s) {
                // A `key: value` line not indented past a quirk scalar that starts its
                // line ends it with an error; a bare `key:` line continues it.
                let text = &self.src[cs2..self.line_end(cs2)];
                let text = text.split(" #").next().unwrap_or(text).trim_end();
                if text.find(": ").map(|p| !text[p + 2..].trim().is_empty()).unwrap_or(false) {
                    return self.err("key-like continuation");
                }
            }
            // A sequence entry not indented past the scalar's first line ends it.
            if !allow_colon && (ind as usize) <= first_indent && self.b[cs2] == b'-' && matches!(self.b.get(cs2 + 1), Some(b' ') | Some(b'\t') | Some(b'\n') | None) {
                break;
            }
            let le = if allow_colon {
                self.scan_plain_line_colon(cs2)
            } else {
                match self.scan_plain_line(cs2) {
                    Ok(e) => e,
                    // A continuation line that looks like a mapping entry is still part
                    // of the scalar when indented past the scalar's first line.
                    Err(_) if (ind as usize) > first_indent => self.scan_plain_line_colon(cs2),
                    Err(_) => break,
                }
            };
            let _ = blank_lines;
            lines.push((cs2, le));
            end = le;
            p = le;
        }
        // Check the first line isn't followed by ':' (would be a key).
        let mut value = String::new();
        let mut pending_newlines = 0;
        for (i, (a, b)) in lines.iter().enumerate() {
            let t = &self.src[*a..*b];
            if i > 0 {
                // Count blank lines between previous line and this one.
                let prev_end = lines[i - 1].1;
                let between = &self.src[prev_end..*a];
                let nl = between.matches('\n').count();
                pending_newlines = nl;
                if pending_newlines <= 1 {
                    value.push(' ');
                } else {
                    for _ in 0..pending_newlines - 1 {
                        value.push('\n');
                    }
                }
            }
            value.push_str(t);
        }
        let _ = pending_newlines;
        self.pos = end;
        let end_line = self.line_of(end.saturating_sub(1).max(s));
        Ok(Node {
            start: s,
            end,
            line,
            col: self.col_of(s),
            props: None,
            kind: Kind::Scalar(Scalar {
                style: ScalarStyle::Plain,
                start: s,
                end,
                value,
                multiline: lines.len() > 1,
                verbatim: false,
                block: None,
            }),
            comment: None,
            flow_has_comment: false,
            end_line,
        })
    }

    /// Like `scan_plain_line` but ": " does not end the scalar.
    fn scan_plain_line_colon(&self, start: usize) -> usize {
        let le = self.line_end(start);
        let mut i = start;
        let mut last_non_ws = start;
        while i < le {
            let c = self.b[i];
            if c == b'#' && i > start && is_ws(self.b[i - 1]) {
                break;
            }
            if !is_ws(c) {
                last_non_ws = i + 1;
            }
            i += 1;
        }
        last_non_ws
    }

    /// Scan a plain scalar on one line from `start`; returns end (trailing spaces trimmed).
    fn scan_plain_line(&self, start: usize) -> PResult<usize> {
        let le = self.line_end(start);
        let mut i = start;
        let mut last_non_ws = start;
        while i < le {
            let c = self.b[i];
            if c == b':' && (i + 1 >= le || matches!(self.b[i + 1], b' ' | b'\t')) {
                break;
            }
            if c == b'#' && i > start && is_ws(self.b[i - 1]) {
                break;
            }
            if !is_ws(c) {
                last_non_ws = i + 1;
            }
            i += 1;
        }
        if i < le && self.b[i] == b':' {
            // "key: value" inside a value position.
            return Err(ParseError { pos: i, msg: "unexpected mapping value".into() });
        }
        Ok(last_non_ws)
    }

    fn parse_block_scalar(&mut self, parent: isize) -> PResult<Node> {
        let s = self.pos;
        let line = self.line_of(s);
        let style = if self.b[s] == b'|' { ScalarStyle::Literal } else { ScalarStyle::Folded };
        self.pos += 1;
        let hs = self.pos;
        let mut indicator = None;
        let mut chomp = Chomp::Clip;
        for _ in 0..2 {
            let c = self.peek();
            if c.is_ascii_digit() && c != b'0' && indicator.is_none() {
                indicator = Some((c - b'0') as usize);
                self.pos += 1;
            } else if c == b'-' && chomp == Chomp::Clip {
                chomp = Chomp::Strip;
                self.pos += 1;
            } else if c == b'+' && chomp == Chomp::Clip {
                chomp = Chomp::Keep;
                self.pos += 1;
            }
        }
        let raw = self.src[hs..self.pos].to_string();
        let save = self.pos;
        self.skip_inline_ws();
        if !self.at_break() && !(self.peek() == b'#' && self.pos > save) {
            return self.err("bad block scalar header");
        }
        self.pos = save;
        let comment = self.eat_line_rest()?;
        // Content lines.
        let base = if parent < 0 { 0 } else { parent as usize };
        let mut content_indent: Option<usize> = indicator.map(|i| if parent < 0 { i } else { base + i });
        let first_line = if self.at_eof() { self.line_starts.len() } else { self.line_of(self.pos) };
        let mut lines: Vec<String> = Vec::new();
        let mut consumed_end = self.pos;
        let mut max_leading_blank_indent = 0usize;
        let mut li = first_line;
        let mut line_count = 0;
        let mut irregular = false;
        while li < self.line_starts.len() {
            let ls = self.line_starts[li];
            let le = self.line_end(ls);
            let text = &self.src[ls..le];
            let ind = text.len() - text.trim_start_matches(' ').len();
            let is_blank = text.trim_start_matches(' ').is_empty();
            if content_indent.is_none() {
                if is_blank {
                    max_leading_blank_indent = max_leading_blank_indent.max(ind);
                    lines.push(String::new());
                    li += 1;
                    line_count += 1;
                    consumed_end = if le < self.b.len() { le + 1 } else { le };
                    continue;
                }
                if (ind as isize) <= parent || (parent < 0 && false) {
                    break;
                }
                if self.is_doc_marker_at(ls) {
                    break;
                }
                if ind < max_leading_blank_indent {
                    return self.err("leading blank lines more indented");
                }
                content_indent = Some(ind);
            }
            let ci = content_indent.unwrap();
            if is_blank {
                if ind > ci {
                    lines.push(text[ci..].to_string());
                } else {
                    lines.push(String::new());
                }
                li += 1;
                line_count += 1;
                consumed_end = if le < self.b.len() { le + 1 } else { le };
                continue;
            }
            if self.is_doc_marker_at(ls) {
                break;
            }
            if ind < ci {
                // Lines still indented past the parent stay in the scalar.
                if (ind as isize) <= parent {
                    break;
                }
                irregular = true;
                lines.push(text[ind..].to_string());
                li += 1;
                line_count += 1;
                consumed_end = if le < self.b.len() { le + 1 } else { le };
                continue;
            }
            lines.push(text[ci..].to_string());
            li += 1;
            line_count += 1;
            consumed_end = if le < self.b.len() { le + 1 } else { le };
        }
        // Trailing blank lines are part of the block scalar.
        let value = block_scalar_value(style, &lines, chomp);
        let total = lines.len();
        let raw_lines: Vec<String> = (first_line..first_line + total)
            .map(|l| {
                let ls = self.line_starts[l];
                self.src[ls..self.line_end(ls)].to_string()
            })
            .collect();
        let end = if total == 0 { self.line_end(s) } else { self.line_end(self.line_starts[first_line + total - 1]) };
        self.pos = consumed_end.max(self.pos);
        let _ = line_count;
        let end_line = self.line_of(end.saturating_sub(1).max(s));
        let end_line = if total == 0 { line } else { end_line.max(first_line + total - 1) };
        let ci = content_indent.unwrap_or(base + 1);
        Ok(Node {
            start: s,
            end,
            line,
            col: self.col_of(s),
            props: None,
            kind: Kind::Scalar(Scalar {
                style,
                start: s,
                end,
                value,
                multiline: true,
                verbatim: false,
                block: Some(BlockHeader {
                    indicator,
                    chomp,
                    raw,
                    comment,
                    content_indent: ci,
                    lines: lines.clone(),
                    first_line,
                    line_count: total,
                    raw_lines,
                    irregular,
                }),
            }),
            comment: None,
            flow_has_comment: false,
            end_line,
        })
    }

    // ---------------- Flow collections ----------------

    fn skip_flow_ws(&mut self, has_comment: &mut bool) -> PResult<()> {
        loop {
            if self.at_eof() {
                return Ok(());
            }
            let c = self.peek();
            if c == b' ' || c == b'\t' || c == b'\n' {
                self.pos += 1;
            } else if c == b'#' && self.pos > 0 && matches!(self.b[self.pos - 1], b' ' | b'\t' | b'\n') {
                *has_comment = true;
                self.pos = self.line_end(self.pos);
            } else {
                return Ok(());
            }
        }
    }

    /// Outermost flow sequences spanning lines reject continuation lines that open
    /// with a brace (mirrors the reference formatter's line scanner).
    fn check_flow_continuations(&self, n: &Node) -> PResult<()> {
        if !matches!(n.kind, Kind::FlowSeq(_)) || n.end_line == n.line {
            return Ok(());
        }
        for l in n.line + 1..=n.end_line {
            let ls = self.line_starts[l];
            let le = self.line_end(ls);
            let t = self.src[ls..le].trim_start();
            if t.starts_with('{') || t.starts_with("\"{") || t.starts_with("'{") {
                return Err(ParseError { pos: ls, msg: "brace on flow continuation line".into() });
            }
        }
        Ok(())
    }

    fn parse_flow_collection(&mut self) -> PResult<Node> {
        let outer = !self.in_flow;
        self.in_flow = true;
        let r = self.parse_flow_collection_inner();
        if outer {
            self.in_flow = false;
            if let Ok(n) = &r {
                self.check_flow_continuations(n)?;
            }
        }
        r
    }

    fn parse_flow_collection_inner(&mut self) -> PResult<Node> {
        let s = self.pos;
        let line = self.line_of(s);
        let open = self.b[s];
        let close = if open == b'[' { b']' } else { b'}' };
        self.pos += 1;
        let mut has_comment = false;
        let mut entries = Vec::new();
        loop {
            self.skip_flow_ws(&mut has_comment)?;
            if self.at_eof() {
                return self.err("unterminated flow collection");
            }
            if self.peek() == close {
                self.pos += 1;
                break;
            }
            let entry = self.parse_flow_entry(open == b'{', &mut has_comment)?;
            entries.push(entry);
            self.skip_flow_ws(&mut has_comment)?;
            if self.peek() == b',' {
                self.pos += 1;
                continue;
            }
            if self.peek() == close {
                self.pos += 1;
                break;
            }
            return self.err("expected ',' or end of flow collection");
        }
        let end = self.pos;
        let end_line = self.line_of(end - 1);
        if has_comment {
            return Err(ParseError { pos: s, msg: "comment inside flow collection".into() });
        }
        // Document markers inside flow collections are invalid.
        Ok(Node {
            start: s,
            end,
            line,
            col: self.col_of(s),
            props: None,
            kind: if open == b'[' { Kind::FlowSeq(entries) } else { Kind::FlowMap(entries) },
            comment: None,
            flow_has_comment: has_comment,
            end_line,
        })
    }

    fn parse_flow_entry(&mut self, in_map: bool, has_comment: &mut bool) -> PResult<FlowEntry> {
        let mut explicit = false;
        if self.peek() == b'?' && matches!(self.peek_at(1), b' ' | b'\t' | b'\n') {
            explicit = true;
            self.pos += 1;
            self.skip_flow_ws(has_comment)?;
        }
        // Key or value node.
        let first = if self.peek() == b':' && matches!(self.peek_at(1), b' ' | b'\t' | b'\n' | b',' | b']' | b'}') {
            None
        } else {
            Some(self.parse_flow_node(has_comment)?)
        };
        let save = self.pos;
        let mut tmp = false;
        self.skip_flow_ws(&mut tmp)?;
        let is_json_like = first.as_ref().map(|n| matches!(n.kind, Kind::FlowMap(_) | Kind::FlowSeq(_)) || matches!(&n.kind, Kind::Scalar(sc) if sc.style == ScalarStyle::Double || sc.style == ScalarStyle::Single)).unwrap_or(false);
        let colon_ok = self.peek() == b':' && (is_json_like || matches!(self.peek_at(1), b' ' | b'\t' | b'\n' | b',' | b']' | b'}' | 0));
        if colon_ok {
            *has_comment |= tmp;
            self.pos += 1;
            self.skip_flow_ws(has_comment)?;
            let value = if matches!(self.peek(), b',' | b']' | b'}') {
                None
            } else {
                Some(self.parse_flow_node(has_comment)?)
            };
            return Ok(FlowEntry { key: first, value, is_pair: true, explicit });
        }
        self.pos = save;
        if in_map || explicit {
            return Ok(FlowEntry { key: first, value: None, is_pair: in_map || explicit, explicit });
        }
        Ok(FlowEntry { key: None, value: first, is_pair: false, explicit })
    }

    fn parse_flow_node(&mut self, has_comment: &mut bool) -> PResult<Node> {
        let start = self.pos;
        let line = self.line_of(start);
        let col = self.col_of(start);
        let props = self.parse_props_flow()?;
        if props.is_some() {
            self.skip_flow_ws(has_comment)?;
        }
        let c = self.peek();
        let mut node = if c == b'[' || c == b'{' {
            self.parse_flow_collection()?
        } else if c == b'"' || c == b'\'' {
            self.parse_quoted(-1)?
        } else if c == b'*' {
            self.parse_alias()?
        } else if matches!(c, b',' | b']' | b'}') && props.is_some() {
            let mut n = self.null_node();
            n.line = line;
            n.end_line = line;
            n
        } else {
            self.parse_plain_flow()?
        };
        if props.is_some() {
            node.start = start;
            node.line = line;
            node.col = col;
            node.props = props;
        }
        Ok(node)
    }

    fn parse_props_flow(&mut self) -> PResult<Option<Props>> {
        if self.peek() != b'&' && self.peek() != b'!' {
            return Ok(None);
        }
        let start = self.pos;
        let mut anchor = None;
        let mut tag = None;
        let mut end = self.pos;
        loop {
            let c = self.peek();
            if c == b'&' && anchor.is_none() {
                let s = self.pos + 1;
                let mut i = s;
                while i < self.b.len() && !matches!(self.b[i], b' ' | b'\t' | b'\n') && !is_flow_ind(self.b[i]) {
                    i += 1;
                }
                anchor = Some(self.src[s..i].to_string());
                self.pos = i;
                end = i;
            } else if c == b'!' && tag.is_none() {
                let s = self.pos;
                let mut i = s + 1;
                if i < self.b.len() && self.b[i] == b'<' {
                    while i < self.b.len() && self.b[i] != b'>' {
                        i += 1;
                    }
                    i += 1;
                } else {
                    while i < self.b.len() && !matches!(self.b[i], b' ' | b'\t' | b'\n') && !is_flow_ind(self.b[i]) {
                        i += 1;
                    }
                }
                tag = Some(self.src[s..i.min(self.b.len())].to_string());
                self.pos = i.min(self.b.len());
                end = self.pos;
            } else {
                break;
            }
            let save = self.pos;
            self.skip_inline_ws();
            if self.peek() != b'&' && self.peek() != b'!' {
                self.pos = save;
                break;
            }
        }
        Ok(Some(Props { anchor, tag, start, end, newline_after: false }))
    }

    fn parse_plain_flow(&mut self) -> PResult<Node> {
        let s = self.pos;
        let line = self.line_of(s);
        let c = self.peek();
        if matches!(c, b'#' | b'&' | b'*' | b'!' | b'|' | b'>' | b'\'' | b'"' | b'%' | b'@' | b'`' | b'[' | b']' | b'{' | b'}' | b',') {
            return self.err("invalid plain scalar start in flow");
        }
        if matches!(c, b'-' | b'?' | b':') && matches!(self.peek_at(1), b' ' | b'\t' | b'\n' | 0 | b',' | b'[' | b']' | b'{' | b'}') {
            return self.err("invalid plain scalar start in flow");
        }
        let mut segs: Vec<(usize, usize)> = Vec::new();
        let mut i = s;
        let mut seg_start = s;
        let mut last_non_ws = s;
        loop {
            if i >= self.b.len() {
                break;
            }
            let ch = self.b[i];
            if ch == b'\n' {
                segs.push((seg_start, last_non_ws));
                // continuation
                let mut j = i + 1;
                while j < self.b.len() && matches!(self.b[j], b' ' | b'\t' | b'\n') {
                    j += 1;
                }
                if j >= self.b.len() {
                    break;
                }
                let cj = self.b[j];
                if cj == b'#' || is_flow_ind(cj) || (cj == b':' && matches!(self.b.get(j + 1), Some(b' ') | Some(b'\t') | Some(b'\n') | Some(b',') | Some(b']') | Some(b'}') | None)) {
                    break;
                }
                if self.is_doc_marker_at(self.line_starts[self.line_of(j)]) && self.line_starts[self.line_of(j)] == j {
                    return self.err("doc marker in flow");
                }
                seg_start = j;
                last_non_ws = j;
                i = j;
                continue;
            }
            if is_flow_ind(ch) {
                break;
            }
            if ch == b':' && matches!(self.b.get(i + 1), Some(b' ') | Some(b'\t') | Some(b'\n') | Some(b',') | Some(b']') | Some(b'}') | None) {
                break;
            }
            if ch == b'#' && i > s && is_ws(self.b[i - 1]) {
                break;
            }
            if !is_ws(ch) {
                last_non_ws = i + 1;
            }
            i += 1;
        }
        if segs.last().map(|x| x.0) != Some(seg_start) || segs.is_empty() {
            if last_non_ws > seg_start || segs.is_empty() {
                segs.push((seg_start, last_non_ws));
            }
        }
        let end = segs.last().map(|x| x.1).unwrap_or(s);
        let mut value = String::new();
        for (k, (a, b)) in segs.iter().enumerate() {
            if k > 0 {
                let between = &self.src[segs[k - 1].1..*a];
                let nl = between.matches('\n').count();
                if nl <= 1 {
                    value.push(' ');
                } else {
                    for _ in 0..nl - 1 {
                        value.push('\n');
                    }
                }
            }
            value.push_str(&self.src[*a..*b]);
        }
        self.pos = end;
        let end_line = self.line_of(end.saturating_sub(1).max(s));
        Ok(Node {
            start: s,
            end,
            line,
            col: self.col_of(s),
            props: None,
            kind: Kind::Scalar(Scalar {
                style: ScalarStyle::Plain,
                start: s,
                end,
                value,
                multiline: end_line > line,
                verbatim: false,
                block: None,
            }),
            comment: None,
            flow_has_comment: false,
            end_line,
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Ctx {
    BlockOut,
    MapValue,
    SeqItem,
}

pub fn decode_single(raw: &str) -> String {
    // Fold line breaks, unescape ''.
    let folded = fold_quoted_lines(raw);
    folded.replace("''", "'")
}

/// Apply flow-scalar line folding to raw quoted content (without quotes).
fn fold_quoted_lines(raw: &str) -> String {
    if !raw.contains('\n') {
        return raw.to_string();
    }
    let lines: Vec<&str> = raw.split('\n').collect();
    let mut out = String::new();
    let n = lines.len();
    let mut i = 0;
    while i < n {
        let mut l = lines[i];
        if i > 0 {
            l = l.trim_start_matches([' ', '\t']);
        }
        if i < n - 1 {
            l = l.trim_end_matches([' ', '\t']);
        }
        out.push_str(l);
        if i < n - 1 {
            // Count following empty lines.
            let mut j = i + 1;
            let mut empties = 0;
            while j < n - 1 && lines[j].trim_matches([' ', '\t']).is_empty() {
                empties += 1;
                j += 1;
            }
            if empties == 0 {
                out.push(' ');
            } else {
                for _ in 0..empties {
                    out.push('\n');
                }
            }
            i = j;
            continue;
        }
        i += 1;
    }
    out
}

pub fn decode_double(raw: &str) -> Option<String> {
    // Handle escaped line breaks first: a backslash at end of line joins without space.
    let mut out = String::new();
    let lines: Vec<&str> = raw.split('\n').collect();
    let n = lines.len();
    let mut i = 0;
    let mut pending_join_escape = false;
    while i < n {
        let mut l = lines[i];
        if i > 0 {
            l = l.trim_start_matches([' ', '\t']);
        }
        let mut escaped_break = false;
        if i < n - 1 {
            // Check for escaped line break (odd number of trailing backslashes).
            let trimmed = l.trim_end_matches([' ', '\t']);
            let bs = trimmed.len() - trimmed.trim_end_matches('\\').len();
            if bs % 2 == 1 {
                escaped_break = true;
                l = &l[..trimmed.len() - 1];
                // Keep trailing whitespace before the backslash.
                let _ = trimmed;
            } else {
                l = trimmed;
            }
        }
        let _ = pending_join_escape;
        out.push_str(&unescape_double(l)?);
        if i < n - 1 {
            if escaped_break {
                pending_join_escape = true;
                i += 1;
                continue;
            }
            let mut j = i + 1;
            let mut empties = 0;
            while j < n - 1 && lines[j].trim_matches([' ', '\t']).is_empty() {
                empties += 1;
                j += 1;
            }
            if empties == 0 {
                out.push(' ');
            } else {
                for _ in 0..empties {
                    out.push('\n');
                }
            }
            i = j;
            continue;
        }
        i += 1;
    }
    Some(out)
}

fn unescape_double(s: &str) -> Option<String> {
    let mut out = String::new();
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        if c != '\\' {
            out.push(c);
            continue;
        }
        let e = chars.next()?;
        match e {
            '0' => out.push('\0'),
            'a' => out.push('\x07'),
            'b' => out.push('\x08'),
            't' | '\t' => out.push('\t'),
            'n' => out.push('\n'),
            'v' => out.push('\x0b'),
            'f' => out.push('\x0c'),
            'r' => out.push('\r'),
            'e' => out.push('\x1b'),
            ' ' => out.push(' '),
            '"' => out.push('"'),
            '/' => out.push('/'),
            '\\' => out.push('\\'),
            'N' => out.push('\u{85}'),
            '_' => out.push('\u{a0}'),
            'L' => out.push('\u{2028}'),
            'P' => out.push('\u{2029}'),
            'x' | 'u' | 'U' => {
                let n = match e {
                    'x' => 2,
                    'u' => 4,
                    _ => 8,
                };
                let mut v = 0u32;
                for _ in 0..n {
                    let d = chars.next()?.to_digit(16)?;
                    v = v * 16 + d;
                }
                out.push(char::from_u32(v)?);
            }
            _ => return None,
        }
    }
    Some(out)
}

fn block_scalar_value(style: ScalarStyle, lines: &[String], chomp: Chomp) -> String {
    // lines: content with indentation removed; empty strings for blank lines.
    let mut content: Vec<&str> = lines.iter().map(|s| s.as_str()).collect();
    let mut trailing = 0;
    while let Some(l) = content.last() {
        if l.is_empty() {
            content.pop();
            trailing += 1;
        } else {
            break;
        }
    }
    let mut body = String::new();
    if style == ScalarStyle::Literal {
        for (i, l) in content.iter().enumerate() {
            if i > 0 {
                body.push('\n');
            }
            body.push_str(l);
        }
    } else {
        // Folded: join lines; more-indented lines and blank lines preserve breaks.
        let mut prev_more = false;
        let mut i = 0;
        let mut first = true;
        while i < content.len() {
            let l = content[i];
            if l.is_empty() {
                // count consecutive blanks
                let mut j = i;
                while j < content.len() && content[j].is_empty() {
                    j += 1;
                }
                let blanks = j - i;
                let next_more = j < content.len() && (content[j].starts_with(' ') || content[j].starts_with('\t'));
                if first {
                    for _ in 0..blanks {
                        body.push('\n');
                    }
                } else if prev_more || next_more {
                    for _ in 0..blanks + 1 {
                        body.push('\n');
                    }
                } else {
                    for _ in 0..blanks {
                        body.push('\n');
                    }
                }
                i = j;
                if j < content.len() {
                    body.push_str(content[j]);
                    prev_more = content[j].starts_with(' ') || content[j].starts_with('\t');
                    first = false;
                    i = j + 1;
                }
                continue;
            }
            let more = l.starts_with(' ') || l.starts_with('\t');
            if !first {
                if more || prev_more {
                    body.push('\n');
                } else {
                    body.push(' ');
                }
            }
            body.push_str(l);
            prev_more = more;
            first = false;
            i += 1;
        }
    }
    match chomp {
        Chomp::Strip => body,
        Chomp::Clip => {
            if content.is_empty() {
                body
            } else {
                body.push('\n');
                body
            }
        }
        Chomp::Keep => {
            if !content.is_empty() {
                body.push('\n');
            }
            for _ in 0..trailing {
                body.push('\n');
            }
            body
        }
    }
}

/// Whether a plain key contains ':' outside closed bracket, brace and quote pairs.
fn key_has_bare_colon(key: &str) -> bool {
    let c: Vec<char> = key.chars().collect();
    let mut i = 0;
    while i < c.len() {
        let close = match c[i] {
            '"' | '\'' => c[i + 1..].iter().position(|&x| x == c[i]).map(|p| i + 1 + p),
            '[' | '{' => {
                let mut depth = 0;
                let mut end = None;
                for (k, &x) in c.iter().enumerate().skip(i) {
                    if x == '[' || x == '{' {
                        depth += 1;
                    } else if x == ']' || x == '}' {
                        depth -= 1;
                        if depth == 0 {
                            end = Some(k);
                            break;
                        }
                    }
                }
                end
            }
            ':' => return true,
            _ => None,
        };
        i = close.map(|e| e + 1).unwrap_or(i + 1);
    }
    false
}

/// Whether a plain key leaves a bracket, brace or quote open.
fn has_unclosed_opener(key: &str) -> bool {
    let c: Vec<char> = key.chars().collect();
    let mut i = 0;
    while i < c.len() {
        match c[i] {
            '"' | '\'' => match c[i + 1..].iter().position(|&x| x == c[i]) {
                Some(p) => i += p + 2,
                None => return true,
            },
            '[' | '{' => {
                let mut depth = 0;
                let mut end = None;
                for (k, &x) in c.iter().enumerate().skip(i) {
                    if x == '[' || x == '{' {
                        depth += 1;
                    } else if x == ']' || x == '}' {
                        depth -= 1;
                        if depth == 0 {
                            end = Some(k);
                            break;
                        }
                    }
                }
                match end {
                    Some(e) => i = e + 1,
                    None => return true,
                }
            }
            _ => i += 1,
        }
    }
    false
}

/// Whether a line holds only template expressions (`{{ ... }}`, `{% ... %}`, ...).
pub fn is_template_line(t: &str) -> bool {
    let t = t.trim();
    [("{{", "}}"), ("{%", "%}"), ("{#", "#}"), ("<%", "%>")].iter().any(|(o, c)| t.starts_with(o) && t.ends_with(c) && t.len() >= o.len() + c.len())
}
