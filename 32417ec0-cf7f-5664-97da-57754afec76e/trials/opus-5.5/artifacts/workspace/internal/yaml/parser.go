package yaml

import (
	"bytes"
	"strconv"
)

// The parser turns tokens into events. It is a port of the libyaml parser as
// found in yaml.v3, and shares its state with the reader and the scanner.

type errorType int

const (
	noError errorType = iota
	readerError
	scannerError
	parserError
)

type parserState int

const (
	stateStreamStart parserState = iota
	stateImplicitDocumentStart
	stateDocumentStart
	stateDocumentContent
	stateDocumentEnd
	stateBlockNode
	stateBlockSequenceFirstEntry
	stateBlockSequenceEntry
	stateIndentlessSequenceEntry
	stateBlockMappingFirstKey
	stateBlockMappingKey
	stateBlockMappingValue
	stateFlowSequenceFirstEntry
	stateFlowSequenceEntry
	stateFlowSequenceEntryMappingKey
	stateFlowSequenceEntryMappingValue
	stateFlowSequenceEntryMappingEnd
	stateFlowMappingFirstKey
	stateFlowMappingKey
	stateFlowMappingValue
	stateFlowMappingEmptyValue
	stateEnd
)

type eventType int

const (
	noEvent eventType = iota
	streamStartEvent
	streamEndEvent
	documentStartEvent
	documentEndEvent
	aliasEvent
	scalarEvent
	sequenceStartEvent
	sequenceEndEvent
	mappingStartEvent
	mappingEndEvent
)

var eventNames = [...]string{
	noEvent:            "none",
	streamStartEvent:   "stream start",
	streamEndEvent:     "stream end",
	documentStartEvent: "document start",
	documentEndEvent:   "document end",
	aliasEvent:         "alias",
	scalarEvent:        "scalar",
	sequenceStartEvent: "sequence start",
	sequenceEndEvent:   "sequence end",
	mappingStartEvent:  "mapping start",
	mappingEndEvent:    "mapping end",
}

func (e eventType) String() string {
	if e >= 0 && int(e) < len(eventNames) {
		return eventNames[e]
	}
	return "unknown event " + strconv.Itoa(int(e))
}

type event struct {
	typ        eventType
	start, end mark

	anchor []byte // Anchor of a node; name referred to by an alias.
	tag    []byte
	value  []byte
	style  scalarStyle // Scalar style.
	flow   bool        // Whether a collection is in the flow style.
}

type tagDirective struct {
	handle, prefix []byte
}

var defaultTagDirectives = []tagDirective{
	{[]byte("!"), []byte("!")},
	{[]byte("!!"), []byte("tag:yaml.org,2002:")},
}

type parser struct {
	// Error state.
	err         errorType
	problem     string
	context     string
	contextMark mark
	problemMark mark

	// Reader state.
	input     []byte
	inputPos  int
	raw       []byte // Raw input waiting to be decoded.
	rawPos    int
	eof       bool
	encoding  encoding
	buffer    []byte // Decoded characters, in UTF-8.
	bufferPos int
	unread    int // Number of characters decoded but not consumed.

	// Scanner state.
	mark                mark
	newlines            int // Line breaks since the last non-blank character.
	streamStartProduced bool
	streamEndProduced   bool
	flowLevel           int
	tokens              []token
	tokensHead          int
	tokensParsed        int // Number of tokens consumed by the parser.
	tokenAvailable      bool
	indent              int
	indents             []int
	simpleKeyAllowed    bool
	simpleKeys          []simpleKey // One potential simple key per flow level.
	simpleKeysByTok     map[int]int // Token number to index in simpleKeys.

	// Comment state, see comments.go.
	comments     []comment
	commentsHead int
	headComment  []byte
	lineComment  []byte
	footComment  []byte
	stemComment  []byte

	// Parser state.
	state         parserState
	states        []parserState
	marks         []mark
	tagDirectives []tagDirective
}

func newParser(input []byte) *parser {
	return &parser{
		input:  input,
		raw:    make([]byte, 0, rawBufferSize),
		buffer: make([]byte, 0, rawBufferSize*3),
	}
}

func (p *parser) setParserError(problem string, problemMark mark) bool {
	p.err = parserError
	p.problem = problem
	p.problemMark = problemMark
	return false
}

func (p *parser) setParserErrorContext(context string, contextMark mark, problem string, problemMark mark) bool {
	p.err = parserError
	p.context = context
	p.contextMark = contextMark
	p.problem = problem
	p.problemMark = problemMark
	return false
}

// errorMessage formats the current error as yaml.v3 does. The line is the
// zero-based line of the context mark, or else of the problem mark, plus one
// for scanner errors only; it is left out when it comes out as zero.
func (p *parser) errorMessage() string {
	line := 0
	if p.contextMark.line != 0 {
		line = p.contextMark.line
	} else if p.problemMark.line != 0 {
		line = p.problemMark.line
	}
	if line != 0 && p.err == scannerError {
		line++
	}
	where := ""
	if line != 0 {
		where = "line " + strconv.Itoa(line) + ": "
	}
	problem := p.problem
	if problem == "" {
		problem = "unknown problem parsing YAML content"
	}
	return "yaml: " + where + problem
}

func (p *parser) peekToken() *token {
	if p.tokenAvailable || p.fetchMoreTokens() {
		t := &p.tokens[p.tokensHead]
		p.unfoldComments(t)
		return t
	}
	return nil
}

func (p *parser) skipToken() {
	p.tokenAvailable = false
	p.tokensParsed++
	p.streamEndProduced = p.tokens[p.tokensHead].typ == tokStreamEnd
	p.tokensHead++
}

func (p *parser) popState() parserState {
	s := p.states[len(p.states)-1]
	p.states = p.states[:len(p.states)-1]
	return s
}

func (p *parser) popMark() mark {
	m := p.marks[len(p.marks)-1]
	p.marks = p.marks[:len(p.marks)-1]
	return m
}

// parse produces the next event. After an error, or once the stream has
// ended, it produces no event and reports success.
func (p *parser) parse(e *event) bool {
	*e = event{}
	if p.streamEndProduced || p.err != noError || p.state == stateEnd {
		return true
	}
	switch p.state {
	case stateStreamStart:
		return p.parseStreamStart(e)
	case stateImplicitDocumentStart:
		return p.parseDocumentStart(e, true)
	case stateDocumentStart:
		return p.parseDocumentStart(e, false)
	case stateDocumentContent:
		return p.parseDocumentContent(e)
	case stateDocumentEnd:
		return p.parseDocumentEnd(e)
	case stateBlockNode:
		return p.parseNode(e, true, false)
	case stateBlockSequenceFirstEntry:
		return p.parseBlockSequenceEntry(e, true)
	case stateBlockSequenceEntry:
		return p.parseBlockSequenceEntry(e, false)
	case stateIndentlessSequenceEntry:
		return p.parseIndentlessSequenceEntry(e)
	case stateBlockMappingFirstKey:
		return p.parseBlockMappingKey(e, true)
	case stateBlockMappingKey:
		return p.parseBlockMappingKey(e, false)
	case stateBlockMappingValue:
		return p.parseBlockMappingValue(e)
	case stateFlowSequenceFirstEntry:
		return p.parseFlowSequenceEntry(e, true)
	case stateFlowSequenceEntry:
		return p.parseFlowSequenceEntry(e, false)
	case stateFlowSequenceEntryMappingKey:
		return p.parseFlowSequenceEntryMappingKey(e)
	case stateFlowSequenceEntryMappingValue:
		return p.parseFlowSequenceEntryMappingValue(e)
	case stateFlowSequenceEntryMappingEnd:
		return p.parseFlowSequenceEntryMappingEnd(e)
	case stateFlowMappingFirstKey:
		return p.parseFlowMappingKey(e, true)
	case stateFlowMappingKey:
		return p.parseFlowMappingKey(e, false)
	case stateFlowMappingValue:
		return p.parseFlowMappingValue(e, false)
	case stateFlowMappingEmptyValue:
		return p.parseFlowMappingValue(e, true)
	}
	panic("yaml: invalid parser state")
}

// stream ::= STREAM-START implicit_document? explicit_document* STREAM-END
func (p *parser) parseStreamStart(e *event) bool {
	t := p.peekToken()
	if t == nil {
		return false
	}
	if t.typ != tokStreamStart {
		return p.setParserError("did not find expected <stream-start>", t.start)
	}
	p.state = stateImplicitDocumentStart
	*e = event{typ: streamStartEvent, start: t.start, end: t.end}
	p.skipToken()
	return true
}

// implicit_document ::= block_node DOCUMENT-END*
// explicit_document ::= DIRECTIVE* DOCUMENT-START block_node? DOCUMENT-END*
func (p *parser) parseDocumentStart(e *event, implicit bool) bool {
	t := p.peekToken()
	if t == nil {
		return false
	}

	// Skip extra document end indicators.
	if !implicit {
		for t.typ == tokDocumentEnd {
			p.skipToken()
			if t = p.peekToken(); t == nil {
				return false
			}
		}
	}

	switch {
	case implicit && t.typ != tokVersionDirective && t.typ != tokTagDirective &&
		t.typ != tokDocumentStart && t.typ != tokStreamEnd:
		// An implicit document.
		if !p.processDirectives() {
			return false
		}
		p.states = append(p.states, stateDocumentEnd)
		p.state = stateBlockNode
		p.splitDocumentComment()
		*e = event{typ: documentStartEvent, start: t.start, end: t.end}

	case t.typ != tokStreamEnd:
		// An explicit document.
		start := t.start
		if !p.processDirectives() {
			return false
		}
		if t = p.peekToken(); t == nil {
			return false
		}
		if t.typ != tokDocumentStart {
			return p.setParserError("did not find expected <document start>", t.start)
		}
		p.states = append(p.states, stateDocumentEnd)
		p.state = stateDocumentContent
		*e = event{typ: documentStartEvent, start: start, end: t.end}
		p.skipToken()

	default:
		p.state = stateEnd
		*e = event{typ: streamEndEvent, start: t.start, end: t.end}
		p.skipToken()
	}
	return true
}

func (p *parser) parseDocumentContent(e *event) bool {
	t := p.peekToken()
	if t == nil {
		return false
	}
	switch t.typ {
	case tokVersionDirective, tokTagDirective, tokDocumentStart, tokDocumentEnd, tokStreamEnd:
		p.state = p.popState()
		return p.processEmptyScalar(e, t.start)
	}
	return p.parseNode(e, true, false)
}

func (p *parser) parseDocumentEnd(e *event) bool {
	t := p.peekToken()
	if t == nil {
		return false
	}
	start, end := t.start, t.start
	if t.typ == tokDocumentEnd {
		end = t.end
		p.skipToken()
	}
	p.tagDirectives = p.tagDirectives[:0]
	p.state = stateDocumentStart
	*e = event{typ: documentEndEvent, start: start, end: end}
	p.takeComments()
	return true
}

// processDirectives handles the %YAML and %TAG directives of a document.
func (p *parser) processDirectives() bool {
	t := p.peekToken()
	if t == nil {
		return false
	}
	haveVersion := false
	for t.typ == tokVersionDirective || t.typ == tokTagDirective {
		if t.typ == tokVersionDirective {
			if haveVersion {
				return p.setParserError("found duplicate %YAML directive", t.start)
			}
			if t.major != 1 || t.minor != 1 {
				return p.setParserError("found incompatible YAML document", t.start)
			}
			haveVersion = true
		} else {
			d := tagDirective{handle: t.value, prefix: t.prefix}
			if !p.appendTagDirective(d, false, t.start) {
				return false
			}
		}
		p.skipToken()
		if t = p.peekToken(); t == nil {
			return false
		}
	}
	for _, d := range defaultTagDirectives {
		if !p.appendTagDirective(d, true, t.start) {
			return false
		}
	}
	return true
}

func (p *parser) appendTagDirective(d tagDirective, allowDuplicates bool, m mark) bool {
	for _, have := range p.tagDirectives {
		if bytes.Equal(d.handle, have.handle) {
			if allowDuplicates {
				return true
			}
			return p.setParserError("found duplicate %TAG directive", m)
		}
	}
	p.tagDirectives = append(p.tagDirectives, tagDirective{
		handle: append([]byte(nil), d.handle...),
		prefix: append([]byte(nil), d.prefix...),
	})
	return true
}

// parseNode parses a node: an alias, or properties (anchor and tag)
// followed by a scalar, a collection, or nothing.
func (p *parser) parseNode(e *event, block, indentlessSequence bool) bool {
	t := p.peekToken()
	if t == nil {
		return false
	}

	if t.typ == tokAlias {
		p.state = p.popState()
		*e = event{typ: aliasEvent, start: t.start, end: t.end, anchor: t.value}
		p.takeComments()
		p.skipToken()
		return true
	}

	start, end := t.start, t.start
	var tagMark mark
	var anchor, tagHandle, tagSuffix []byte
	hasTag := false
	switch t.typ {
	case tokAnchor:
		anchor = t.value
		start, end = t.start, t.end
		p.skipToken()
		if t = p.peekToken(); t == nil {
			return false
		}
		if t.typ == tokTag {
			hasTag = true
			tagHandle, tagSuffix = t.value, t.suffix
			tagMark, end = t.start, t.end
			p.skipToken()
			if t = p.peekToken(); t == nil {
				return false
			}
		}
	case tokTag:
		hasTag = true
		tagHandle, tagSuffix = t.value, t.suffix
		start, tagMark, end = t.start, t.start, t.end
		p.skipToken()
		if t = p.peekToken(); t == nil {
			return false
		}
		if t.typ == tokAnchor {
			anchor = t.value
			end = t.end
			p.skipToken()
			if t = p.peekToken(); t == nil {
				return false
			}
		}
	}

	var tag []byte
	if hasTag {
		if len(tagHandle) == 0 {
			tag = tagSuffix
		} else {
			for _, d := range p.tagDirectives {
				if bytes.Equal(d.handle, tagHandle) {
					tag = append(append([]byte(nil), d.prefix...), tagSuffix...)
					break
				}
			}
			if len(tag) == 0 {
				return p.setParserErrorContext("while parsing a node", start, "found undefined tag handle", tagMark)
			}
		}
	}

	if indentlessSequence && t.typ == tokBlockEntry {
		p.state = stateIndentlessSequenceEntry
		*e = event{typ: sequenceStartEvent, start: start, end: t.end, anchor: anchor, tag: tag}
		return true
	}
	switch {
	case t.typ == tokScalar:
		p.state = p.popState()
		*e = event{typ: scalarEvent, start: start, end: t.end, anchor: anchor, tag: tag, value: t.value, style: t.style}
		p.takeComments()
		p.skipToken()
		return true
	case t.typ == tokFlowSequenceStart:
		p.state = stateFlowSequenceFirstEntry
		*e = event{typ: sequenceStartEvent, start: start, end: t.end, anchor: anchor, tag: tag, flow: true}
		p.takeComments()
		return true
	case t.typ == tokFlowMappingStart:
		p.state = stateFlowMappingFirstKey
		*e = event{typ: mappingStartEvent, start: start, end: t.end, anchor: anchor, tag: tag, flow: true}
		p.takeComments()
		return true
	case block && t.typ == tokBlockSequenceStart:
		p.state = stateBlockSequenceFirstEntry
		*e = event{typ: sequenceStartEvent, start: start, end: t.end, anchor: anchor, tag: tag}
		p.stemComment = nil
		return true
	case block && t.typ == tokBlockMappingStart:
		p.state = stateBlockMappingFirstKey
		*e = event{typ: mappingStartEvent, start: start, end: t.end, anchor: anchor, tag: tag}
		p.stemComment = nil
		return true
	case len(anchor) > 0 || len(tag) > 0:
		// Properties without content: an empty scalar.
		p.state = p.popState()
		*e = event{typ: scalarEvent, start: start, end: end, anchor: anchor, tag: tag, style: plainScalarStyle}
		return true
	}
	context := "while parsing a flow node"
	if block {
		context = "while parsing a block node"
	}
	return p.setParserErrorContext(context, start, "did not find expected node content", t.start)
}

// block_sequence ::= BLOCK-SEQUENCE-START (BLOCK-ENTRY block_node?)* BLOCK-END
func (p *parser) parseBlockSequenceEntry(e *event, first bool) bool {
	if first {
		t := p.peekToken()
		if t == nil {
			return false
		}
		p.marks = append(p.marks, t.start)
		p.skipToken()
	}
	t := p.peekToken()
	if t == nil {
		return false
	}
	switch t.typ {
	case tokBlockEntry:
		m := t.end
		priorHeadLen := len(p.headComment)
		p.skipToken()
		p.splitStemComment(priorHeadLen)
		if t = p.peekToken(); t == nil {
			return false
		}
		if t.typ != tokBlockEntry && t.typ != tokBlockEnd {
			p.states = append(p.states, stateBlockSequenceEntry)
			return p.parseNode(e, true, false)
		}
		p.state = stateBlockSequenceEntry
		return p.processEmptyScalar(e, m)
	case tokBlockEnd:
		p.state = p.popState()
		p.popMark()
		*e = event{typ: sequenceEndEvent, start: t.start, end: t.end}
		p.skipToken()
		return true
	}
	return p.setParserErrorContext("while parsing a block collection", p.popMark(),
		"did not find expected '-' indicator", t.start)
}

// indentless_sequence ::= (BLOCK-ENTRY block_node?)+
func (p *parser) parseIndentlessSequenceEntry(e *event) bool {
	t := p.peekToken()
	if t == nil {
		return false
	}
	if t.typ == tokBlockEntry {
		m := t.end
		priorHeadLen := len(p.headComment)
		p.skipToken()
		p.splitStemComment(priorHeadLen)
		if t = p.peekToken(); t == nil {
			return false
		}
		if t.typ != tokBlockEntry && t.typ != tokKey && t.typ != tokValue && t.typ != tokBlockEnd {
			p.states = append(p.states, stateIndentlessSequenceEntry)
			return p.parseNode(e, true, false)
		}
		p.state = stateIndentlessSequenceEntry
		return p.processEmptyScalar(e, m)
	}
	p.state = p.popState()
	*e = event{typ: sequenceEndEvent, start: t.start, end: t.start}
	return true
}

// block_mapping ::= BLOCK-MAPPING-START
//
//	((KEY block_node_or_indentless_sequence?)?
//	(VALUE block_node_or_indentless_sequence?)?)*
//	BLOCK-END
func (p *parser) parseBlockMappingKey(e *event, first bool) bool {
	if first {
		t := p.peekToken()
		if t == nil {
			return false
		}
		p.marks = append(p.marks, t.start)
		p.skipToken()
	}
	t := p.peekToken()
	if t == nil {
		return false
	}
	switch t.typ {
	case tokKey:
		m := t.end
		p.skipToken()
		if t = p.peekToken(); t == nil {
			return false
		}
		if t.typ != tokKey && t.typ != tokValue && t.typ != tokBlockEnd {
			p.states = append(p.states, stateBlockMappingValue)
			return p.parseNode(e, true, true)
		}
		p.state = stateBlockMappingValue
		return p.processEmptyScalar(e, m)
	case tokBlockEnd:
		p.state = p.popState()
		p.popMark()
		*e = event{typ: mappingEndEvent, start: t.start, end: t.end}
		p.takeComments()
		p.skipToken()
		return true
	}
	return p.setParserErrorContext("while parsing a block mapping", p.popMark(),
		"did not find expected key", t.start)
}

func (p *parser) parseBlockMappingValue(e *event) bool {
	t := p.peekToken()
	if t == nil {
		return false
	}
	if t.typ == tokValue {
		m := t.end
		p.skipToken()
		if t = p.peekToken(); t == nil {
			return false
		}
		if t.typ != tokKey && t.typ != tokValue && t.typ != tokBlockEnd {
			p.states = append(p.states, stateBlockMappingKey)
			return p.parseNode(e, true, true)
		}
		p.state = stateBlockMappingKey
		return p.processEmptyScalar(e, m)
	}
	p.state = stateBlockMappingKey
	return p.processEmptyScalar(e, t.start)
}

// flow_sequence ::= FLOW-SEQUENCE-START
//
//	(flow_sequence_entry FLOW-ENTRY)* flow_sequence_entry?
//	FLOW-SEQUENCE-END
func (p *parser) parseFlowSequenceEntry(e *event, first bool) bool {
	if first {
		t := p.peekToken()
		if t == nil {
			return false
		}
		p.marks = append(p.marks, t.start)
		p.skipToken()
	}
	t := p.peekToken()
	if t == nil {
		return false
	}
	if t.typ != tokFlowSequenceEnd {
		if !first {
			if t.typ != tokFlowEntry {
				return p.setParserErrorContext("while parsing a flow sequence", p.popMark(),
					"did not find expected ',' or ']'", t.start)
			}
			p.skipToken()
			if t = p.peekToken(); t == nil {
				return false
			}
		}
		if t.typ == tokKey {
			// A single-pair mapping: [ key: value ].
			p.state = stateFlowSequenceEntryMappingKey
			*e = event{typ: mappingStartEvent, start: t.start, end: t.end, flow: true}
			p.skipToken()
			return true
		}
		if t.typ != tokFlowSequenceEnd {
			p.states = append(p.states, stateFlowSequenceEntry)
			return p.parseNode(e, false, false)
		}
	}
	p.state = p.popState()
	p.popMark()
	*e = event{typ: sequenceEndEvent, start: t.start, end: t.end}
	p.takeComments()
	p.skipToken()
	return true
}

func (p *parser) parseFlowSequenceEntryMappingKey(e *event) bool {
	t := p.peekToken()
	if t == nil {
		return false
	}
	if t.typ != tokValue && t.typ != tokFlowEntry && t.typ != tokFlowSequenceEnd {
		p.states = append(p.states, stateFlowSequenceEntryMappingValue)
		return p.parseNode(e, false, false)
	}
	// Like yaml.v3, this consumes the token after an empty key, even a ':'.
	m := t.end
	p.skipToken()
	p.state = stateFlowSequenceEntryMappingValue
	return p.processEmptyScalar(e, m)
}

func (p *parser) parseFlowSequenceEntryMappingValue(e *event) bool {
	t := p.peekToken()
	if t == nil {
		return false
	}
	if t.typ == tokValue {
		p.skipToken()
		if t = p.peekToken(); t == nil {
			return false
		}
		if t.typ != tokFlowEntry && t.typ != tokFlowSequenceEnd {
			p.states = append(p.states, stateFlowSequenceEntryMappingEnd)
			return p.parseNode(e, false, false)
		}
	}
	p.state = stateFlowSequenceEntryMappingEnd
	return p.processEmptyScalar(e, t.start)
}

func (p *parser) parseFlowSequenceEntryMappingEnd(e *event) bool {
	t := p.peekToken()
	if t == nil {
		return false
	}
	p.state = stateFlowSequenceEntry
	*e = event{typ: mappingEndEvent, start: t.start, end: t.start}
	return true
}

// flow_mapping ::= FLOW-MAPPING-START
//
//	(flow_mapping_entry FLOW-ENTRY)* flow_mapping_entry?
//	FLOW-MAPPING-END
func (p *parser) parseFlowMappingKey(e *event, first bool) bool {
	if first {
		t := p.peekToken()
		if t == nil {
			return false
		}
		p.marks = append(p.marks, t.start)
		p.skipToken()
	}
	t := p.peekToken()
	if t == nil {
		return false
	}
	if t.typ != tokFlowMappingEnd {
		if !first {
			if t.typ != tokFlowEntry {
				return p.setParserErrorContext("while parsing a flow mapping", p.popMark(),
					"did not find expected ',' or '}'", t.start)
			}
			p.skipToken()
			if t = p.peekToken(); t == nil {
				return false
			}
		}
		if t.typ == tokKey {
			p.skipToken()
			if t = p.peekToken(); t == nil {
				return false
			}
			if t.typ != tokValue && t.typ != tokFlowEntry && t.typ != tokFlowMappingEnd {
				p.states = append(p.states, stateFlowMappingValue)
				return p.parseNode(e, false, false)
			}
			p.state = stateFlowMappingValue
			return p.processEmptyScalar(e, t.start)
		}
		if t.typ != tokFlowMappingEnd {
			p.states = append(p.states, stateFlowMappingEmptyValue)
			return p.parseNode(e, false, false)
		}
	}
	p.state = p.popState()
	p.popMark()
	*e = event{typ: mappingEndEvent, start: t.start, end: t.end}
	p.takeComments()
	p.skipToken()
	return true
}

func (p *parser) parseFlowMappingValue(e *event, empty bool) bool {
	t := p.peekToken()
	if t == nil {
		return false
	}
	if empty {
		p.state = stateFlowMappingKey
		return p.processEmptyScalar(e, t.start)
	}
	if t.typ == tokValue {
		p.skipToken()
		if t = p.peekToken(); t == nil {
			return false
		}
		if t.typ != tokFlowEntry && t.typ != tokFlowMappingEnd {
			p.states = append(p.states, stateFlowMappingKey)
			return p.parseNode(e, false, false)
		}
	}
	p.state = stateFlowMappingKey
	return p.processEmptyScalar(e, t.start)
}

func (p *parser) processEmptyScalar(e *event, m mark) bool {
	*e = event{typ: scalarEvent, start: m, end: m, style: plainScalarStyle}
	return true
}
