package yaml

import (
	"errors"
	"fmt"
)

// Parse parses the first document of data into a node tree, as
// yaml.Unmarshal(data, &node) does with gopkg.in/yaml.v3. It returns the
// document node, or nil if data holds no document (it is empty or holds only
// comments). On malformed input it returns the error yaml.v3 returns, such
// as "yaml: line 2: found character that cannot start any token".
//
// Anything after the first document is ignored, except that the scanner
// reads a few tokens ahead and reports an error it finds there.
func Parse(data []byte) (doc *Node, err error) {
	defer handleErr(&err)
	if len(data) == 0 {
		data = []byte{'\n'}
	}
	c := &composer{p: newParser(data), anchors: make(map[string]*Node)}
	c.expect(streamStartEvent)
	return c.parse(), nil
}

// syntaxError carries a parse error up to Parse.
type syntaxError struct{ err error }

func failf(format string, args ...any) {
	panic(syntaxError{fmt.Errorf("yaml: "+format, args...)})
}

func handleErr(err *error) {
	if v := recover(); v != nil {
		e, ok := v.(syntaxError)
		if !ok {
			panic(v)
		}
		*err = e.err
	}
}

// composer builds nodes from parser events, following yaml.v3.
type composer struct {
	p       *parser
	event   event // The event peeked at but not consumed yet, if any.
	anchors map[string]*Node
}

func (c *composer) fail() {
	panic(syntaxError{errors.New(c.p.errorMessage())})
}

// peek returns the type of the next event without consuming it.
func (c *composer) peek() eventType {
	if c.event.typ != noEvent {
		return c.event.typ
	}
	if !c.p.parse(&c.event) || c.p.err != noError {
		c.fail()
	}
	return c.event.typ
}

// expect consumes the next event, which must be of type t.
func (c *composer) expect(t eventType) {
	if c.event.typ == noEvent && !c.p.parse(&c.event) {
		c.fail()
	}
	if c.event.typ == streamEndEvent {
		failf("attempted to go past the end of stream; corrupted value?")
	}
	if c.event.typ != t {
		c.p.problem = fmt.Sprintf("expected %s event but got %s", t, c.event.typ)
		c.fail()
	}
	c.event = event{}
}

func (c *composer) parse() *Node {
	switch c.peek() {
	case scalarEvent:
		return c.scalar()
	case aliasEvent:
		return c.alias()
	case mappingStartEvent:
		return c.mapping()
	case sequenceStartEvent:
		return c.sequence()
	case documentStartEvent:
		return c.document()
	case streamEndEvent:
		return nil
	}
	panic("yaml: internal error: unexpected " + c.event.typ.String() + " event")
}

// node creates a node for the current event. An explicit tag other than
// the non-specific "!" wins; otherwise collections and quoted scalars get
// defaultTag and plain scalars a tag resolved from their value.
func (c *composer) node(kind Kind, defaultTag, tag, value string) *Node {
	var style Style
	switch {
	case tag != "" && tag != "!":
		tag = shortTag(tag)
		style = TaggedStyle
	case defaultTag != "":
		tag = defaultTag
	case kind == ScalarNode:
		tag = resolveTag(value)
	}
	return &Node{
		Kind:   kind,
		Style:  style,
		Tag:    tag,
		Value:  value,
		Line:   c.event.start.line + 1,
		Column: c.event.start.column + 1,
	}
}

func (c *composer) anchor(n *Node, anchor []byte) {
	if anchor != nil {
		n.Anchor = string(anchor)
		c.anchors[n.Anchor] = n
	}
}

func (c *composer) document() *Node {
	n := c.node(DocumentNode, "", "", "")
	c.expect(documentStartEvent)
	n.Content = append(n.Content, c.parse())
	c.peek()
	c.expect(documentEndEvent)
	return n
}

func (c *composer) alias() *Node {
	n := c.node(AliasNode, "", "", string(c.event.anchor))
	n.Alias = c.anchors[n.Value]
	if n.Alias == nil {
		failf("unknown anchor '%s' referenced", n.Value)
	}
	c.expect(aliasEvent)
	return n
}

func (c *composer) scalar() *Node {
	var style Style
	switch c.event.style {
	case doubleQuotedScalarStyle:
		style = DoubleQuotedStyle
	case singleQuotedScalarStyle:
		style = SingleQuotedStyle
	case literalScalarStyle:
		style = LiteralStyle
	case foldedScalarStyle:
		style = FoldedStyle
	}
	value := string(c.event.value)
	var defaultTag string
	if style != 0 {
		defaultTag = strTag
	} else if value == "<<" {
		defaultTag = mergeTag
	}
	n := c.node(ScalarNode, defaultTag, string(c.event.tag), value)
	n.Style |= style
	c.anchor(n, c.event.anchor)
	c.expect(scalarEvent)
	return n
}

func (c *composer) sequence() *Node {
	n := c.node(SequenceNode, seqTag, string(c.event.tag), "")
	if c.event.flow {
		n.Style |= FlowStyle
	}
	c.anchor(n, c.event.anchor)
	c.expect(sequenceStartEvent)
	for c.peek() != sequenceEndEvent {
		n.Content = append(n.Content, c.parse())
	}
	c.expect(sequenceEndEvent)
	return n
}

func (c *composer) mapping() *Node {
	n := c.node(MappingNode, mapTag, string(c.event.tag), "")
	if c.event.flow {
		n.Style |= FlowStyle
	}
	c.anchor(n, c.event.anchor)
	c.expect(mappingStartEvent)
	for c.peek() != mappingEndEvent {
		k := c.parse()
		v := c.parse()
		n.Content = append(n.Content, k, v)
	}
	c.expect(mappingEndEvent)
	return n
}
