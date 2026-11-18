package yaml

import (
	"fmt"
	"strings"
)

// The scanner turns the character buffer into tokens. It is a port of the
// libyaml scanner with the changes yaml.v3 made to it; those changes are
// visible in error messages, so they are kept, quirks included:
//
//   - The token queue is filled with two tokens of lookahead beyond the
//     one the parser asks for, so a scanner error up to two tokens ahead
//     wins over a parser error at the current token.
//   - A comment after a token on the same line is consumed right after
//     the token, tabs before it included; a run of comment lines is
//     consumed as a whole, again tabs included (see comments.go).
//   - Potential simple keys are only invalidated lazily, when a ':' or
//     another key needs them, not every time a token is fetched; and
//     closing an empty flow collection forgets that the collection itself
//     may be a simple key.
//   - A byte order mark at the start of a line is detected by looking at
//     the start of the buffer rather than at the current position.

// mark is a position in the input. All fields are zero-based and count
// characters, not bytes.
type mark struct {
	index, line, column int
}

type tokenType int

const (
	tokStreamStart tokenType = iota + 1
	tokStreamEnd
	tokVersionDirective
	tokTagDirective
	tokDocumentStart
	tokDocumentEnd
	tokBlockSequenceStart
	tokBlockMappingStart
	tokBlockEnd
	tokFlowSequenceStart
	tokFlowSequenceEnd
	tokFlowMappingStart
	tokFlowMappingEnd
	tokBlockEntry
	tokFlowEntry
	tokKey
	tokValue
	tokAlias
	tokAnchor
	tokTag
	tokScalar
)

type scalarStyle int

const (
	plainScalarStyle scalarStyle = iota + 1
	singleQuotedScalarStyle
	doubleQuotedScalarStyle
	literalScalarStyle
	foldedScalarStyle
)

type token struct {
	typ        tokenType
	start, end mark

	value        []byte // Scalar value, anchor or alias name, tag or %TAG handle.
	suffix       []byte // Tag suffix.
	prefix       []byte // %TAG prefix.
	style        scalarStyle
	major, minor int8 // %YAML version.
}

// simpleKey records where a key without '?' may start. Whether it really is
// a key is only known once a ':' follows on the same line.
type simpleKey struct {
	possible    bool
	required    bool
	tokenNumber int
	mark        mark
}

const (
	maxFlowLevel = 10000
	maxIndents   = 10000
)

// Character classes. The helpers on the parser look at the byte k positions
// after the current one; past the end of the buffer they see NUL.

func (p *parser) at(k int) byte {
	if i := p.bufferPos + k; i < len(p.buffer) {
		return p.buffer[i]
	}
	return 0
}

func (p *parser) isBlank(k int) bool { c := p.at(k); return c == ' ' || c == '\t' }
func (p *parser) isZ(k int) bool     { return p.at(k) == 0 }
func (p *parser) isCRLF(k int) bool  { return p.at(k) == '\r' && p.at(k+1) == '\n' }

// bufferStartsWithBOM reports whether the buffer, not the current position,
// starts with a byte order mark. yaml.v3 checks this to skip a BOM at the
// start of a line, so after an input that starts with two BOMs it skips the
// first character of later lines too, until the buffer is refilled.
func (p *parser) bufferStartsWithBOM() bool {
	return len(p.buffer) >= 3 && p.buffer[0] == 0xEF && p.buffer[1] == 0xBB && p.buffer[2] == 0xBF
}

// isBreak reports a line break: CR, LF, NEL, LS or PS.
func (p *parser) isBreak(k int) bool {
	switch p.at(k) {
	case '\r', '\n':
		return true
	case 0xC2:
		return p.at(k+1) == 0x85
	case 0xE2:
		return p.at(k+1) == 0x80 && (p.at(k+2) == 0xA8 || p.at(k+2) == 0xA9)
	}
	return false
}

func (p *parser) isBreakz(k int) bool { return p.isZ(k) || p.isBreak(k) }
func (p *parser) isBlankz(k int) bool { return p.isBlank(k) || p.isBreakz(k) }

// isAlpha reports the characters allowed in anchors, tag handles and
// directive names.
func isAlpha(c byte) bool {
	return c >= '0' && c <= '9' || c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z' || c == '_' || c == '-'
}

func isDigit(c byte) bool { return c >= '0' && c <= '9' }

func isHex(c byte) bool {
	return c >= '0' && c <= '9' || c >= 'A' && c <= 'F' || c >= 'a' && c <= 'f'
}

func asHex(c byte) int {
	switch {
	case c >= 'A' && c <= 'F':
		return int(c-'A') + 10
	case c >= 'a' && c <= 'f':
		return int(c-'a') + 10
	}
	return int(c - '0')
}

// width returns the length of the UTF-8 sequence starting with c.
func width(c byte) int {
	switch {
	case c&0x80 == 0x00:
		return 1
	case c&0xE0 == 0xC0:
		return 2
	case c&0xF0 == 0xE0:
		return 3
	case c&0xF8 == 0xF0:
		return 4
	}
	return 0
}

// Moving through the buffer.

// skip moves past the current character.
func (p *parser) skip() {
	if !p.isBlank(0) {
		p.newlines = 0
	}
	p.mark.index++
	p.mark.column++
	p.unread--
	p.bufferPos += width(p.at(0))
}

// skipLine moves past the line break at the current position, if any.
func (p *parser) skipLine() {
	if p.isCRLF(0) {
		p.mark.index += 2
		p.mark.column = 0
		p.mark.line++
		p.unread -= 2
		p.bufferPos += 2
		p.newlines++
	} else if p.isBreak(0) {
		p.mark.index++
		p.mark.column = 0
		p.mark.line++
		p.unread--
		p.bufferPos += width(p.at(0))
		p.newlines++
	}
}

// read appends the current character to s and moves past it.
func (p *parser) read(s []byte) []byte {
	if !p.isBlank(0) {
		p.newlines = 0
	}
	w := width(p.at(0))
	end := p.bufferPos + w
	if end > len(p.buffer) {
		end = len(p.buffer)
	}
	s = append(s, p.buffer[p.bufferPos:end]...)
	p.bufferPos += w
	p.mark.index++
	p.mark.column++
	p.unread--
	return s
}

// readLine appends the line break at the current position to s, normalized
// to LF except for LS and PS, and moves past it.
func (p *parser) readLine(s []byte) []byte {
	switch {
	case p.at(0) == '\r' && p.at(1) == '\n':
		s = append(s, '\n')
		p.bufferPos += 2
		p.mark.index++
		p.unread--
	case p.at(0) == '\r' || p.at(0) == '\n':
		s = append(s, '\n')
		p.bufferPos++
	case p.at(0) == 0xC2 && p.at(1) == 0x85:
		s = append(s, '\n')
		p.bufferPos += 2
	case p.at(0) == 0xE2 && p.at(1) == 0x80 && (p.at(2) == 0xA8 || p.at(2) == 0xA9):
		s = append(s, p.buffer[p.bufferPos:p.bufferPos+3]...)
		p.bufferPos += 3
	default:
		return s
	}
	p.mark.index++
	p.mark.column = 0
	p.mark.line++
	p.unread--
	p.newlines++
	return s
}

func (p *parser) setScannerError(context string, contextMark mark, problem string) bool {
	p.err = scannerError
	p.context = context
	p.contextMark = contextMark
	p.problem = problem
	p.problemMark = p.mark
	return false
}

func (p *parser) setScannerTagError(directive bool, contextMark mark, problem string) bool {
	context := "while parsing a tag"
	if directive {
		context = "while parsing a %TAG directive"
	}
	return p.setScannerError(context, contextMark, problem)
}

// The token queue.

// insertToken inserts t at position pos of the queue, counted from its head,
// or appends it when pos is negative. Consumed tokens are kept, as the
// comment scanner looks back at the last tokens queued.
func (p *parser) insertToken(pos int, t token) {
	p.tokens = append(p.tokens, t)
	if pos < 0 {
		return
	}
	copy(p.tokens[p.tokensHead+pos+1:], p.tokens[p.tokensHead+pos:])
	p.tokens[p.tokensHead+pos] = t
}

// fetchMoreTokens makes sure the queue holds a token the parser may consume:
// at least three tokens, and more while the head token may still turn out
// to be a simple key.
func (p *parser) fetchMoreTokens() bool {
	for {
		if p.tokensHead < len(p.tokens)-2 {
			i, ok := p.simpleKeysByTok[p.tokensParsed]
			if !ok || i >= len(p.simpleKeys) {
				break
			}
			valid, ok := p.simpleKeyIsValid(&p.simpleKeys[i])
			if !ok {
				return false
			}
			if !valid {
				break
			}
		}
		if !p.fetchNextToken() {
			return false
		}
	}
	p.tokenAvailable = true
	return true
}

// fetchNextToken scans the next token and queues it, along with any
// BLOCK-END, KEY and BLOCK-*-START tokens it implies.
func (p *parser) fetchNextToken() (ok bool) {
	if p.unread < 1 && !p.updateBuffer(1) {
		return false
	}
	if !p.streamStartProduced {
		return p.fetchStreamStart()
	}
	if !p.scanToNextToken() {
		return false
	}
	if !p.unrollIndent(p.mark.column) {
		return false
	}
	// The longest indicators, "--- " and "... ", take four characters.
	if p.unread < 4 && !p.updateBuffer(4) {
		return false
	}
	if p.isZ(0) {
		return p.fetchStreamEnd()
	}
	if p.mark.column == 0 && p.at(0) == '%' {
		return p.fetchDirective()
	}
	if p.mark.column == 0 && p.at(0) == '-' && p.at(1) == '-' && p.at(2) == '-' && p.isBlankz(3) {
		return p.fetchDocumentIndicator(tokDocumentStart)
	}
	if p.mark.column == 0 && p.at(0) == '.' && p.at(1) == '.' && p.at(2) == '.' && p.isBlankz(3) {
		return p.fetchDocumentIndicator(tokDocumentEnd)
	}

	// Consume a comment on the rest of the line as a line comment, except
	// after a sequence entry indicator. After a ':' (or a ',' in a flow) it
	// belongs to the token before.
	c := p.at(0)
	commentMark := p.mark
	if len(p.tokens) > 0 && (p.flowLevel == 0 && c == ':' || p.flowLevel > 0 && c == ',') {
		commentMark = p.tokens[len(p.tokens)-1].start
	}
	defer func() {
		if ok && p.tokens[len(p.tokens)-1].typ != tokBlockEntry {
			ok = p.scanLineComment(commentMark)
		}
	}()

	switch c {
	case '[':
		return p.fetchFlowCollectionStart(tokFlowSequenceStart)
	case '{':
		return p.fetchFlowCollectionStart(tokFlowMappingStart)
	case ']':
		return p.fetchFlowCollectionEnd(tokFlowSequenceEnd)
	case '}':
		return p.fetchFlowCollectionEnd(tokFlowMappingEnd)
	case ',':
		return p.fetchFlowEntry()
	}
	if c == '-' && p.isBlankz(1) {
		return p.fetchBlockEntry()
	}
	if c == '?' && (p.flowLevel > 0 || p.isBlankz(1)) {
		return p.fetchKey()
	}
	if c == ':' && (p.flowLevel > 0 || p.isBlankz(1)) {
		return p.fetchValue()
	}
	switch c {
	case '*':
		return p.fetchAnchor(tokAlias)
	case '&':
		return p.fetchAnchor(tokAnchor)
	case '!':
		return p.fetchTag()
	case '|':
		if p.flowLevel == 0 {
			return p.fetchBlockScalar(true)
		}
	case '>':
		if p.flowLevel == 0 {
			return p.fetchBlockScalar(false)
		}
	case '\'':
		return p.fetchFlowScalar(true)
	case '"':
		return p.fetchFlowScalar(false)
	}

	// A plain scalar may not start with an indicator, except for '-', and
	// for '?' and ':' in the block context, when followed by a non-space.
	if !(p.isBlankz(0) || strings.IndexByte("-?:,[]{}#&*!|>'\"%@`", c) >= 0) ||
		c == '-' && !p.isBlank(1) ||
		p.flowLevel == 0 && (c == '?' || c == ':') && !p.isBlankz(1) {
		return p.fetchPlainScalar()
	}
	return p.setScannerError("while scanning for the next token", p.mark,
		"found character that cannot start any token")
}

// Simple keys.

// simpleKeyIsValid reports whether a potential simple key may still be one:
// a key must end on its line and within 1024 characters.
func (p *parser) simpleKeyIsValid(k *simpleKey) (valid, ok bool) {
	if !k.possible {
		return false, true
	}
	if k.mark.line < p.mark.line || k.mark.index+1024 < p.mark.index {
		if k.required {
			return false, p.setScannerError("while scanning a simple key", k.mark,
				"could not find expected ':'")
		}
		k.possible = false
		return false, true
	}
	return true, true
}

// saveSimpleKey records that a simple key may start at the current position.
func (p *parser) saveSimpleKey() bool {
	// A simple key is required where a block collection expects its next
	// key: in the block context, at the indentation column.
	required := p.flowLevel == 0 && p.indent == p.mark.column
	if p.simpleKeyAllowed {
		k := simpleKey{
			possible:    true,
			required:    required,
			tokenNumber: p.tokensParsed + len(p.tokens) - p.tokensHead,
			mark:        p.mark,
		}
		if !p.removeSimpleKey() {
			return false
		}
		p.simpleKeys[len(p.simpleKeys)-1] = k
		p.simpleKeysByTok[k.tokenNumber] = len(p.simpleKeys) - 1
	}
	return true
}

// removeSimpleKey drops the potential simple key of the current flow level,
// failing if it was required.
func (p *parser) removeSimpleKey() bool {
	i := len(p.simpleKeys) - 1
	if p.simpleKeys[i].possible {
		if p.simpleKeys[i].required {
			return p.setScannerError("while scanning a simple key", p.simpleKeys[i].mark,
				"could not find expected ':'")
		}
		p.simpleKeys[i].possible = false
		delete(p.simpleKeysByTok, p.simpleKeys[i].tokenNumber)
	}
	return true
}

func (p *parser) increaseFlowLevel() bool {
	// As in yaml.v3, the new level's empty key slot carries the number of
	// the token being scanned. Closing an empty collection then forgets
	// that the collection itself may be a simple key, which lets the parser
	// consume it before a ':' that follows further on the line is seen.
	p.simpleKeys = append(p.simpleKeys, simpleKey{
		tokenNumber: p.tokensParsed + len(p.tokens) - p.tokensHead,
		mark:        p.mark,
	})
	p.flowLevel++
	if p.flowLevel > maxFlowLevel {
		return p.setScannerError("while increasing flow level", p.simpleKeys[len(p.simpleKeys)-1].mark,
			fmt.Sprintf("exceeded max depth of %d", maxFlowLevel))
	}
	return true
}

func (p *parser) decreaseFlowLevel() bool {
	if p.flowLevel > 0 {
		p.flowLevel--
		last := len(p.simpleKeys) - 1
		delete(p.simpleKeysByTok, p.simpleKeys[last].tokenNumber)
		p.simpleKeys = p.simpleKeys[:last]
	}
	return true
}

// Indentation.

// rollIndent opens a block collection when column is deeper than the current
// indentation, queueing its start token at position number (an absolute
// token number), or at the end if number is -1.
func (p *parser) rollIndent(column, number int, typ tokenType, m mark) bool {
	if p.flowLevel > 0 {
		return true
	}
	if p.indent < column {
		p.indents = append(p.indents, p.indent)
		p.indent = column
		if len(p.indents) > maxIndents {
			return p.setScannerError("while increasing indent level", p.simpleKeys[len(p.simpleKeys)-1].mark,
				fmt.Sprintf("exceeded max depth of %d", maxIndents))
		}
		if number > -1 {
			number -= p.tokensParsed
		}
		p.insertToken(number, token{typ: typ, start: m, end: m})
	}
	return true
}

// unrollIndent closes the block collections deeper than column.
func (p *parser) unrollIndent(column int) bool {
	if p.flowLevel > 0 {
		return true
	}
	for p.indent > column {
		p.insertToken(-1, token{typ: tokBlockEnd, start: p.mark, end: p.mark})
		p.indent = p.indents[len(p.indents)-1]
		p.indents = p.indents[:len(p.indents)-1]
	}
	return true
}

// Fetching tokens.

func (p *parser) fetchStreamStart() bool {
	p.indent = -1
	p.simpleKeys = append(p.simpleKeys, simpleKey{})
	p.simpleKeysByTok = make(map[int]int)
	p.simpleKeyAllowed = true
	p.streamStartProduced = true
	p.insertToken(-1, token{typ: tokStreamStart, start: p.mark, end: p.mark})
	return true
}

func (p *parser) fetchStreamEnd() bool {
	// Force a new line.
	if p.mark.column != 0 {
		p.mark.column = 0
		p.mark.line++
	}
	if !p.unrollIndent(-1) || !p.removeSimpleKey() {
		return false
	}
	p.simpleKeyAllowed = false
	p.insertToken(-1, token{typ: tokStreamEnd, start: p.mark, end: p.mark})
	return true
}

func (p *parser) fetchDirective() bool {
	if !p.unrollIndent(-1) || !p.removeSimpleKey() {
		return false
	}
	p.simpleKeyAllowed = false
	var t token
	if !p.scanDirective(&t) {
		return false
	}
	p.insertToken(-1, t)
	return true
}

func (p *parser) fetchDocumentIndicator(typ tokenType) bool {
	if !p.unrollIndent(-1) || !p.removeSimpleKey() {
		return false
	}
	p.simpleKeyAllowed = false
	start := p.mark
	p.skip()
	p.skip()
	p.skip()
	p.insertToken(-1, token{typ: typ, start: start, end: p.mark})
	return true
}

func (p *parser) fetchFlowCollectionStart(typ tokenType) bool {
	// '[' and '{' may start a simple key.
	if !p.saveSimpleKey() || !p.increaseFlowLevel() {
		return false
	}
	p.simpleKeyAllowed = true
	start := p.mark
	p.skip()
	p.insertToken(-1, token{typ: typ, start: start, end: p.mark})
	return true
}

func (p *parser) fetchFlowCollectionEnd(typ tokenType) bool {
	if !p.removeSimpleKey() || !p.decreaseFlowLevel() {
		return false
	}
	p.simpleKeyAllowed = false
	start := p.mark
	p.skip()
	p.insertToken(-1, token{typ: typ, start: start, end: p.mark})
	return true
}

func (p *parser) fetchFlowEntry() bool {
	if !p.removeSimpleKey() {
		return false
	}
	p.simpleKeyAllowed = true
	start := p.mark
	p.skip()
	p.insertToken(-1, token{typ: tokFlowEntry, start: start, end: p.mark})
	return true
}

func (p *parser) fetchBlockEntry() bool {
	if p.flowLevel == 0 {
		if !p.simpleKeyAllowed {
			return p.setScannerError("", p.mark, "block sequence entries are not allowed in this context")
		}
		if !p.rollIndent(p.mark.column, -1, tokBlockSequenceStart, p.mark) {
			return false
		}
	}
	// In the flow context a '-' entry is an error the parser reports.
	if !p.removeSimpleKey() {
		return false
	}
	p.simpleKeyAllowed = true
	start := p.mark
	p.skip()
	p.insertToken(-1, token{typ: tokBlockEntry, start: start, end: p.mark})
	return true
}

func (p *parser) fetchKey() bool {
	if p.flowLevel == 0 {
		if !p.simpleKeyAllowed {
			return p.setScannerError("", p.mark, "mapping keys are not allowed in this context")
		}
		if !p.rollIndent(p.mark.column, -1, tokBlockMappingStart, p.mark) {
			return false
		}
	}
	if !p.removeSimpleKey() {
		return false
	}
	p.simpleKeyAllowed = p.flowLevel == 0
	start := p.mark
	p.skip()
	p.insertToken(-1, token{typ: tokKey, start: start, end: p.mark})
	return true
}

func (p *parser) fetchValue() bool {
	k := &p.simpleKeys[len(p.simpleKeys)-1]
	valid, ok := p.simpleKeyIsValid(k)
	if !ok {
		return false
	}
	if valid {
		// The simple key turned out to be a key: queue KEY before it, and
		// BLOCK-MAPPING-START too if it opens a mapping.
		p.insertToken(k.tokenNumber-p.tokensParsed, token{typ: tokKey, start: k.mark, end: k.mark})
		if !p.rollIndent(k.mark.column, k.tokenNumber, tokBlockMappingStart, k.mark) {
			return false
		}
		k.possible = false
		delete(p.simpleKeysByTok, k.tokenNumber)
		// A simple key cannot follow another simple key.
		p.simpleKeyAllowed = false
	} else {
		// The ':' follows a complex key, or no key at all.
		if p.flowLevel == 0 {
			if !p.simpleKeyAllowed {
				return p.setScannerError("", p.mark, "mapping values are not allowed in this context")
			}
			if !p.rollIndent(p.mark.column, -1, tokBlockMappingStart, p.mark) {
				return false
			}
		}
		p.simpleKeyAllowed = p.flowLevel == 0
	}
	start := p.mark
	p.skip()
	p.insertToken(-1, token{typ: tokValue, start: start, end: p.mark})
	return true
}

func (p *parser) fetchAnchor(typ tokenType) bool {
	// An anchor or an alias may start a simple key.
	if !p.saveSimpleKey() {
		return false
	}
	p.simpleKeyAllowed = false
	var t token
	if !p.scanAnchor(&t, typ) {
		return false
	}
	p.insertToken(-1, t)
	return true
}

func (p *parser) fetchTag() bool {
	// A tag may start a simple key.
	if !p.saveSimpleKey() {
		return false
	}
	p.simpleKeyAllowed = false
	var t token
	if !p.scanTag(&t) {
		return false
	}
	p.insertToken(-1, t)
	return true
}

func (p *parser) fetchBlockScalar(literal bool) bool {
	if !p.removeSimpleKey() {
		return false
	}
	// A simple key may follow a block scalar.
	p.simpleKeyAllowed = true
	var t token
	if !p.scanBlockScalar(&t, literal) {
		return false
	}
	p.insertToken(-1, t)
	return true
}

func (p *parser) fetchFlowScalar(single bool) bool {
	if !p.saveSimpleKey() {
		return false
	}
	p.simpleKeyAllowed = false
	var t token
	if !p.scanFlowScalar(&t, single) {
		return false
	}
	p.insertToken(-1, t)
	return true
}

func (p *parser) fetchPlainScalar() bool {
	if !p.saveSimpleKey() {
		return false
	}
	p.simpleKeyAllowed = false
	var t token
	if !p.scanPlainScalar(&t) {
		return false
	}
	p.insertToken(-1, t)
	return true
}

// Whitespace and comments.

// scanToNextToken skips whitespace, comments and line breaks.
func (p *parser) scanToNextToken() bool {
	scanMark := p.mark
	for {
		// Allow a byte order mark at the start of a line.
		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
		if p.mark.column == 0 && p.bufferStartsWithBOM() {
			p.skip()
		}

		// Tabs are allowed in the flow context, and in the block context
		// where no simple key may start: not at the start of a line nor
		// after '-', '?' or a complex ':'.
		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
		for p.at(0) == ' ' || (p.flowLevel > 0 || !p.simpleKeyAllowed) && p.at(0) == '\t' {
			p.skip()
			if p.unread < 1 && !p.updateBuffer(1) {
				return false
			}
		}

		p.repositionEntryComment()

		if p.at(0) == '#' && !p.scanComments(scanMark) {
			return false
		}

		if !p.isBreak(0) {
			return true
		}
		if p.unread < 2 && !p.updateBuffer(2) {
			return false
		}
		p.skipLine()
		if p.flowLevel == 0 {
			p.simpleKeyAllowed = true
		}
	}
}

// Directives.

func (p *parser) scanDirective(t *token) bool {
	start := p.mark
	p.skip() // '%'

	var name []byte
	if !p.scanDirectiveName(start, &name) {
		return false
	}
	switch string(name) {
	case "YAML":
		var major, minor int8
		if !p.scanVersionDirectiveValue(start, &major, &minor) {
			return false
		}
		*t = token{typ: tokVersionDirective, start: start, end: p.mark, major: major, minor: minor}
	case "TAG":
		var handle, prefix []byte
		if !p.scanTagDirectiveValue(start, &handle, &prefix) {
			return false
		}
		*t = token{typ: tokTagDirective, start: start, end: p.mark, value: handle, prefix: prefix}
	default:
		return p.setScannerError("while scanning a directive", start, "found unknown directive name")
	}

	// Eat the rest of the line, including any comment.
	if p.unread < 1 && !p.updateBuffer(1) {
		return false
	}
	for p.isBlank(0) {
		p.skip()
		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
	}
	if p.at(0) == '#' {
		for !p.isBreakz(0) {
			p.skip()
			if p.unread < 1 && !p.updateBuffer(1) {
				return false
			}
		}
	}
	if !p.isBreakz(0) {
		return p.setScannerError("while scanning a directive", start, "did not find expected comment or line break")
	}
	if p.isBreak(0) {
		if p.unread < 2 && !p.updateBuffer(2) {
			return false
		}
		p.skipLine()
	}
	return true
}

func (p *parser) scanDirectiveName(start mark, name *[]byte) bool {
	if p.unread < 1 && !p.updateBuffer(1) {
		return false
	}
	var s []byte
	for isAlpha(p.at(0)) {
		s = p.read(s)
		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
	}
	if len(s) == 0 {
		return p.setScannerError("while scanning a directive", start, "could not find expected directive name")
	}
	if !p.isBlankz(0) {
		return p.setScannerError("while scanning a directive", start, "found unexpected non-alphabetical character")
	}
	*name = s
	return true
}

func (p *parser) scanVersionDirectiveValue(start mark, major, minor *int8) bool {
	if p.unread < 1 && !p.updateBuffer(1) {
		return false
	}
	for p.isBlank(0) {
		p.skip()
		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
	}
	if !p.scanVersionDirectiveNumber(start, major) {
		return false
	}
	if p.at(0) != '.' {
		return p.setScannerError("while scanning a %YAML directive", start, "did not find expected digit or '.' character")
	}
	p.skip()
	return p.scanVersionDirectiveNumber(start, minor)
}

func (p *parser) scanVersionDirectiveNumber(start mark, number *int8) bool {
	const maxNumberLength = 2
	if p.unread < 1 && !p.updateBuffer(1) {
		return false
	}
	var value, length int8
	for isDigit(p.at(0)) {
		length++
		if length > maxNumberLength {
			return p.setScannerError("while scanning a %YAML directive", start, "found extremely long version number")
		}
		value = value*10 + int8(p.at(0)-'0')
		p.skip()
		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
	}
	if length == 0 {
		return p.setScannerError("while scanning a %YAML directive", start, "did not find expected version number")
	}
	*number = value
	return true
}

func (p *parser) scanTagDirectiveValue(start mark, handle, prefix *[]byte) bool {
	if p.unread < 1 && !p.updateBuffer(1) {
		return false
	}
	for p.isBlank(0) {
		p.skip()
		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
	}
	var handleValue, prefixValue []byte
	if !p.scanTagHandle(true, start, &handleValue) {
		return false
	}
	if p.unread < 1 && !p.updateBuffer(1) {
		return false
	}
	if !p.isBlank(0) {
		return p.setScannerError("while scanning a %TAG directive", start, "did not find expected whitespace")
	}
	for p.isBlank(0) {
		p.skip()
		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
	}
	if !p.scanTagURI(true, nil, start, &prefixValue) {
		return false
	}
	if p.unread < 1 && !p.updateBuffer(1) {
		return false
	}
	if !p.isBlankz(0) {
		return p.setScannerError("while scanning a %TAG directive", start, "did not find expected whitespace or line break")
	}
	*handle = handleValue
	*prefix = prefixValue
	return true
}

// Anchors, aliases and tags.

func (p *parser) scanAnchor(t *token, typ tokenType) bool {
	start := p.mark
	p.skip() // '&' or '*'

	if p.unread < 1 && !p.updateBuffer(1) {
		return false
	}
	var s []byte
	for isAlpha(p.at(0)) {
		s = p.read(s)
		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
	}
	end := p.mark

	// The name must be followed by a blank or one of the indicators
	// '?', ':', ',', ']', '}', '%', '@' and '`'.
	if len(s) == 0 || !(p.isBlankz(0) || strings.IndexByte("?:,]}%@`", p.at(0)) >= 0) {
		context := "while scanning an alias"
		if typ == tokAnchor {
			context = "while scanning an anchor"
		}
		return p.setScannerError(context, start, "did not find expected alphabetic or numeric character")
	}
	*t = token{typ: typ, start: start, end: end, value: s}
	return true
}

func (p *parser) scanTag(t *token) bool {
	start := p.mark
	var handle, suffix []byte

	if p.unread < 2 && !p.updateBuffer(2) {
		return false
	}
	if p.at(1) == '<' {
		// A verbatim tag, !<...>: the handle stays empty.
		p.skip()
		p.skip()
		if !p.scanTagURI(false, nil, start, &suffix) {
			return false
		}
		if p.at(0) != '>' {
			return p.setScannerError("while scanning a tag", start, "did not find the expected '>'")
		}
		p.skip()
	} else {
		// The tag is either !suffix or !handle!suffix.
		if !p.scanTagHandle(false, start, &handle) {
			return false
		}
		if handle[0] == '!' && len(handle) > 1 && handle[len(handle)-1] == '!' {
			if !p.scanTagURI(false, nil, start, &suffix) {
				return false
			}
		} else {
			// It was not a handle after all: it starts the suffix.
			if !p.scanTagURI(false, handle, start, &suffix) {
				return false
			}
			handle = []byte{'!'}
			// The non-specific tag "!" alone gets an empty handle.
			if len(suffix) == 0 {
				handle, suffix = suffix, handle
			}
		}
	}

	if p.unread < 1 && !p.updateBuffer(1) {
		return false
	}
	if !p.isBlankz(0) {
		if p.flowLevel == 0 || p.at(0) != ',' {
			return p.setScannerError("while scanning a tag", start, "did not find expected whitespace or line break")
		}
	}
	*t = token{typ: tokTag, start: start, end: p.mark, value: handle, suffix: suffix}
	return true
}

func (p *parser) scanTagHandle(directive bool, start mark, handle *[]byte) bool {
	if p.unread < 1 && !p.updateBuffer(1) {
		return false
	}
	if p.at(0) != '!' {
		return p.setScannerTagError(directive, start, "did not find expected '!'")
	}
	s := p.read(nil)
	if p.unread < 1 && !p.updateBuffer(1) {
		return false
	}
	for isAlpha(p.at(0)) {
		s = p.read(s)
		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
	}
	if p.at(0) == '!' {
		s = p.read(s)
	} else if directive && string(s) != "!" {
		// A %TAG handle must end with '!'; in a tag token this is the
		// start of the suffix instead.
		return p.setScannerTagError(directive, start, "did not find expected '!'")
	}
	*handle = s
	return true
}

// scanTagURI scans a tag suffix or %TAG prefix. head holds the characters
// already scanned as a would-be handle, its leading '!' excluded. As in
// yaml.v3, the URI characters include ',', '[' and ']' even in the flow
// context.
func (p *parser) scanTagURI(directive bool, head []byte, start mark, uri *[]byte) bool {
	var s []byte
	hasTag := len(head) > 0
	if len(head) > 1 {
		s = append(s, head[1:]...)
	}
	if p.unread < 1 && !p.updateBuffer(1) {
		return false
	}
	for {
		c := p.at(0)
		if !(isAlpha(c) || c != 0 && strings.IndexByte(";/?:@&=+$,.!~*'()[]%", c) >= 0) {
			break
		}
		if c == '%' {
			if !p.scanURIEscapes(directive, start, &s) {
				return false
			}
		} else {
			s = p.read(s)
		}
		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
		hasTag = true
	}
	if !hasTag {
		return p.setScannerTagError(directive, start, "did not find expected tag URI")
	}
	*uri = s
	return true
}

// scanURIEscapes decodes a %-escaped UTF-8 sequence.
func (p *parser) scanURIEscapes(directive bool, start mark, s *[]byte) bool {
	w := 1024
	for w > 0 {
		if p.unread < 3 && !p.updateBuffer(3) {
			return false
		}
		if !(p.at(0) == '%' && isHex(p.at(1)) && isHex(p.at(2))) {
			return p.setScannerTagError(directive, start, "did not find URI escaped octet")
		}
		octet := byte(asHex(p.at(1))<<4 + asHex(p.at(2)))
		if w == 1024 {
			w = width(octet)
			if w == 0 {
				return p.setScannerTagError(directive, start, "found an incorrect leading UTF-8 octet")
			}
		} else if octet&0xC0 != 0x80 {
			return p.setScannerTagError(directive, start, "found an incorrect trailing UTF-8 octet")
		}
		*s = append(*s, octet)
		p.skip()
		p.skip()
		p.skip()
		w--
	}
	return true
}

// Scalars.

func (p *parser) scanBlockScalar(t *token, literal bool) bool {
	start := p.mark
	p.skip() // '|' or '>'

	// The header: chomping and indentation indicators, in either order.
	if p.unread < 1 && !p.updateBuffer(1) {
		return false
	}
	var chomping, increment int
	if c := p.at(0); c == '+' || c == '-' {
		chomping = +1
		if c == '-' {
			chomping = -1
		}
		p.skip()
		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
		if c := p.at(0); isDigit(c) {
			if c == '0' {
				return p.setScannerError("while scanning a block scalar", start, "found an indentation indicator equal to 0")
			}
			increment = int(c - '0')
			p.skip()
		}
	} else if isDigit(c) {
		if c == '0' {
			return p.setScannerError("while scanning a block scalar", start, "found an indentation indicator equal to 0")
		}
		increment = int(c - '0')
		p.skip()
		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
		if c := p.at(0); c == '+' || c == '-' {
			chomping = +1
			if c == '-' {
				chomping = -1
			}
			p.skip()
		}
	}

	// Eat whitespace and a comment to the end of the line.
	if p.unread < 1 && !p.updateBuffer(1) {
		return false
	}
	for p.isBlank(0) {
		p.skip()
		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
	}
	if p.at(0) == '#' {
		if !p.scanLineComment(start) {
			return false
		}
		for !p.isBreakz(0) {
			p.skip()
			if p.unread < 1 && !p.updateBuffer(1) {
				return false
			}
		}
	}
	if !p.isBreakz(0) {
		return p.setScannerError("while scanning a block scalar", start, "did not find expected comment or line break")
	}
	if p.isBreak(0) {
		if p.unread < 2 && !p.updateBuffer(2) {
			return false
		}
		p.skipLine()
	}
	end := p.mark

	indent := 0
	if increment > 0 {
		if p.indent >= 0 {
			indent = p.indent + increment
		} else {
			indent = increment
		}
	}

	// Scan the leading empty lines, and find the indentation if needed.
	var s, leadingBreak, trailingBreaks []byte
	if !p.scanBlockScalarBreaks(&indent, &trailingBreaks, start, &end) {
		return false
	}

	if p.unread < 1 && !p.updateBuffer(1) {
		return false
	}
	var leadingBlank, trailingBlank bool
	for p.mark.column == indent && !p.isZ(0) {
		// At the start of a non-empty line.
		trailingBlank = p.isBlank(0)

		// Fold the line break unless a line starts with a blank.
		if !literal && !leadingBlank && !trailingBlank && len(leadingBreak) > 0 && leadingBreak[0] == '\n' {
			if len(trailingBreaks) == 0 {
				s = append(s, ' ')
			}
		} else {
			s = append(s, leadingBreak...)
		}
		leadingBreak = leadingBreak[:0]
		s = append(s, trailingBreaks...)
		trailingBreaks = trailingBreaks[:0]

		leadingBlank = p.isBlank(0)

		for !p.isBreakz(0) {
			s = p.read(s)
			if p.unread < 1 && !p.updateBuffer(1) {
				return false
			}
		}
		if p.unread < 2 && !p.updateBuffer(2) {
			return false
		}
		leadingBreak = p.readLine(leadingBreak)

		if !p.scanBlockScalarBreaks(&indent, &trailingBreaks, start, &end) {
			return false
		}
	}

	// Chomp the tail.
	if chomping != -1 {
		s = append(s, leadingBreak...)
	}
	if chomping == 1 {
		s = append(s, trailingBreaks...)
	}

	style := literalScalarStyle
	if !literal {
		style = foldedScalarStyle
	}
	*t = token{typ: tokScalar, start: start, end: end, value: s, style: style}
	return true
}

// scanBlockScalarBreaks eats indentation and empty lines inside a block
// scalar, determining the indentation from the first non-empty line when it
// is not known yet.
func (p *parser) scanBlockScalarBreaks(indent *int, breaks *[]byte, start mark, end *mark) bool {
	*end = p.mark
	maxIndent := 0
	for {
		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
		for (*indent == 0 || p.mark.column < *indent) && p.at(0) == ' ' {
			p.skip()
			if p.unread < 1 && !p.updateBuffer(1) {
				return false
			}
		}
		if p.mark.column > maxIndent {
			maxIndent = p.mark.column
		}
		if (*indent == 0 || p.mark.column < *indent) && p.at(0) == '\t' {
			return p.setScannerError("while scanning a block scalar", start,
				"found a tab character where an indentation space is expected")
		}
		if !p.isBreak(0) {
			break
		}
		if p.unread < 2 && !p.updateBuffer(2) {
			return false
		}
		*breaks = p.readLine(*breaks)
		*end = p.mark
	}
	if *indent == 0 {
		*indent = maxIndent
		if *indent < p.indent+1 {
			*indent = p.indent + 1
		}
		if *indent < 1 {
			*indent = 1
		}
	}
	return true
}

// scanFlowScalar scans a single- or double-quoted scalar.
func (p *parser) scanFlowScalar(t *token, single bool) bool {
	start := p.mark
	p.skip() // The opening quote.

	var s, leadingBreak, trailingBreaks, whitespaces []byte
	for {
		// A document indicator may not occur inside the scalar.
		if p.unread < 4 && !p.updateBuffer(4) {
			return false
		}
		if p.mark.column == 0 &&
			(p.at(0) == '-' && p.at(1) == '-' && p.at(2) == '-' ||
				p.at(0) == '.' && p.at(1) == '.' && p.at(2) == '.') &&
			p.isBlankz(3) {
			return p.setScannerError("while scanning a quoted scalar", start, "found unexpected document indicator")
		}
		if p.isZ(0) {
			return p.setScannerError("while scanning a quoted scalar", start, "found unexpected end of stream")
		}

		// Consume non-blank characters.
		leadingBlanks := false
		for !p.isBlankz(0) {
			c := p.at(0)
			if single && c == '\'' && p.at(1) == '\'' {
				// An escaped single quote.
				s = append(s, '\'')
				p.skip()
				p.skip()
			} else if single && c == '\'' || !single && c == '"' {
				break // The closing quote.
			} else if !single && c == '\\' && p.isBreak(1) {
				// An escaped line break.
				if p.unread < 3 && !p.updateBuffer(3) {
					return false
				}
				p.skip()
				p.skipLine()
				leadingBlanks = true
				break
			} else if !single && c == '\\' {
				codeLength := 0
				switch p.at(1) {
				case '0':
					s = append(s, 0)
				case 'a':
					s = append(s, '\x07')
				case 'b':
					s = append(s, '\x08')
				case 't', '\t':
					s = append(s, '\x09')
				case 'n':
					s = append(s, '\x0A')
				case 'v':
					s = append(s, '\x0B')
				case 'f':
					s = append(s, '\x0C')
				case 'r':
					s = append(s, '\x0D')
				case 'e':
					s = append(s, '\x1B')
				case ' ':
					s = append(s, '\x20')
				case '"':
					s = append(s, '"')
				case '\'':
					s = append(s, '\'')
				case '\\':
					s = append(s, '\\')
				case 'N': // NEL (#x85)
					s = append(s, "\u0085"...)
				case '_': // #xA0
					s = append(s, "\u00a0"...)
				case 'L': // LS (#x2028)
					s = append(s, "\u2028"...)
				case 'P': // PS (#x2029)
					s = append(s, "\u2029"...)
				case 'x':
					codeLength = 2
				case 'u':
					codeLength = 4
				case 'U':
					codeLength = 8
				default:
					return p.setScannerError("while parsing a quoted scalar", start, "found unknown escape character")
				}
				p.skip()
				p.skip()

				if codeLength > 0 {
					if p.unread < codeLength && !p.updateBuffer(codeLength) {
						return false
					}
					value := 0
					for k := 0; k < codeLength; k++ {
						if !isHex(p.at(k)) {
							return p.setScannerError("while parsing a quoted scalar", start, "did not find expected hexdecimal number")
						}
						value = value<<4 + asHex(p.at(k))
					}
					if value >= 0xD800 && value <= 0xDFFF || value > 0x10FFFF {
						return p.setScannerError("while parsing a quoted scalar", start, "found invalid Unicode character escape code")
					}
					s = appendCodePoint(s, value)
					for k := 0; k < codeLength; k++ {
						p.skip()
					}
				}
			} else {
				s = p.read(s)
			}
			if p.unread < 2 && !p.updateBuffer(2) {
				return false
			}
		}

		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
		if single && p.at(0) == '\'' || !single && p.at(0) == '"' {
			break
		}

		// Consume blanks and line breaks.
		for p.isBlank(0) || p.isBreak(0) {
			if p.isBlank(0) {
				if !leadingBlanks {
					whitespaces = p.read(whitespaces)
				} else {
					p.skip()
				}
			} else {
				if p.unread < 2 && !p.updateBuffer(2) {
					return false
				}
				if !leadingBlanks {
					whitespaces = whitespaces[:0]
					leadingBreak = p.readLine(leadingBreak)
					leadingBlanks = true
				} else {
					trailingBreaks = p.readLine(trailingBreaks)
				}
			}
			if p.unread < 1 && !p.updateBuffer(1) {
				return false
			}
		}

		// Join the whitespace or fold the line breaks.
		if leadingBlanks {
			if len(leadingBreak) > 0 && leadingBreak[0] == '\n' {
				if len(trailingBreaks) == 0 {
					s = append(s, ' ')
				} else {
					s = append(s, trailingBreaks...)
				}
			} else {
				s = append(s, leadingBreak...)
				s = append(s, trailingBreaks...)
			}
			trailingBreaks = trailingBreaks[:0]
			leadingBreak = leadingBreak[:0]
		} else {
			s = append(s, whitespaces...)
			whitespaces = whitespaces[:0]
		}
	}

	p.skip() // The closing quote.
	style := doubleQuotedScalarStyle
	if single {
		style = singleQuotedScalarStyle
	}
	*t = token{typ: tokScalar, start: start, end: p.mark, value: s, style: style}
	return true
}

// appendCodePoint appends the UTF-8 encoding of an escaped code point.
func appendCodePoint(s []byte, v int) []byte {
	switch {
	case v <= 0x7F:
		return append(s, byte(v))
	case v <= 0x7FF:
		return append(s, byte(0xC0+v>>6), byte(0x80+v&0x3F))
	case v <= 0xFFFF:
		return append(s, byte(0xE0+v>>12), byte(0x80+(v>>6)&0x3F), byte(0x80+v&0x3F))
	}
	return append(s, byte(0xF0+v>>18), byte(0x80+(v>>12)&0x3F), byte(0x80+(v>>6)&0x3F), byte(0x80+v&0x3F))
}

func (p *parser) scanPlainScalar(t *token) bool {
	var s, leadingBreak, trailingBreaks, whitespaces []byte
	leadingBlanks := false
	indent := p.indent + 1
	start := p.mark
	end := p.mark

	for {
		// A document indicator ends the scalar.
		if p.unread < 4 && !p.updateBuffer(4) {
			return false
		}
		if p.mark.column == 0 &&
			(p.at(0) == '-' && p.at(1) == '-' && p.at(2) == '-' ||
				p.at(0) == '.' && p.at(1) == '.' && p.at(2) == '.') &&
			p.isBlankz(3) {
			break
		}
		if p.at(0) == '#' {
			break
		}

		// Consume non-blank characters.
		for !p.isBlankz(0) {
			c := p.at(0)
			if c == ':' && p.isBlankz(1) ||
				p.flowLevel > 0 && (c == ',' || c == '?' || c == '[' || c == ']' || c == '{' || c == '}') {
				break
			}

			// Join the preceding whitespace or line breaks.
			if leadingBlanks || len(whitespaces) > 0 {
				if leadingBlanks {
					if leadingBreak[0] == '\n' {
						if len(trailingBreaks) == 0 {
							s = append(s, ' ')
						} else {
							s = append(s, trailingBreaks...)
						}
					} else {
						s = append(s, leadingBreak...)
						s = append(s, trailingBreaks...)
					}
					trailingBreaks = trailingBreaks[:0]
					leadingBreak = leadingBreak[:0]
					leadingBlanks = false
				} else {
					s = append(s, whitespaces...)
					whitespaces = whitespaces[:0]
				}
			}

			s = p.read(s)
			end = p.mark
			if p.unread < 2 && !p.updateBuffer(2) {
				return false
			}
		}

		if !(p.isBlank(0) || p.isBreak(0)) {
			break
		}

		// Consume blanks and line breaks.
		if p.unread < 1 && !p.updateBuffer(1) {
			return false
		}
		for p.isBlank(0) || p.isBreak(0) {
			if p.isBlank(0) {
				if leadingBlanks && p.mark.column < indent && p.at(0) == '\t' {
					return p.setScannerError("while scanning a plain scalar", start,
						"found a tab character that violates indentation")
				}
				if !leadingBlanks {
					whitespaces = p.read(whitespaces)
				} else {
					p.skip()
				}
			} else {
				if p.unread < 2 && !p.updateBuffer(2) {
					return false
				}
				if !leadingBlanks {
					whitespaces = whitespaces[:0]
					leadingBreak = p.readLine(leadingBreak)
					leadingBlanks = true
				} else {
					trailingBreaks = p.readLine(trailingBreaks)
				}
			}
			if p.unread < 1 && !p.updateBuffer(1) {
				return false
			}
		}

		// In the block context a line less indented than the scalar ends it.
		if p.flowLevel == 0 && p.mark.column < indent {
			break
		}
	}

	*t = token{typ: tokScalar, start: start, end: end, value: s, style: plainScalarStyle}
	// A simple key may start after a line break.
	if leadingBlanks {
		p.simpleKeyAllowed = true
	}
	return true
}
