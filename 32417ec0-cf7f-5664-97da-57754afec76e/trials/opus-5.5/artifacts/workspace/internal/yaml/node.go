// Package yaml parses YAML into a tree of nodes.
//
// It reproduces gopkg.in/yaml.v3, which is itself a port of libyaml: the
// scanner, the parser and the node builder follow the same algorithms, so
// documents produce the same nodes, positions and resolved tags, and
// malformed input produces the same error messages.
package yaml

import (
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Kind identifies the kind of a node.
type Kind uint32

const (
	DocumentNode Kind = 1 << iota
	SequenceNode
	MappingNode
	ScalarNode
	AliasNode
)

// Style holds the presentation style of a node.
type Style uint32

const (
	TaggedStyle Style = 1 << iota
	DoubleQuotedStyle
	SingleQuotedStyle
	LiteralStyle
	FoldedStyle
	FlowStyle
)

// Node is a node of a YAML document tree.
type Node struct {
	Kind  Kind
	Style Style

	// Tag is stored as yaml.v3 stores it: the short form of an explicit
	// tag, or else the tag resolved from the content ("!!str", "!!int",
	// "!!map", ...). Document and alias nodes have no tag.
	Tag string

	// Value is the scalar value after unescaping and folding. For an alias
	// it is the name of the anchor referred to.
	Value string

	// Anchor is the name of the anchor defined on the node, if any.
	Anchor string

	// Alias is the node an alias refers to.
	Alias *Node

	// Content holds the child of a document, the items of a sequence, or
	// the keys and values of a mapping, alternating.
	Content []*Node

	// Line and Column give the 1-based position where the node starts:
	// its anchor or tag if it has one, else its first token.
	Line, Column int
}

const (
	nullTag      = "!!null"
	boolTag      = "!!bool"
	strTag       = "!!str"
	intTag       = "!!int"
	floatTag     = "!!float"
	timestampTag = "!!timestamp"
	seqTag       = "!!seq"
	mapTag       = "!!map"
	binaryTag    = "!!binary"
	mergeTag     = "!!merge"
)

const longTagPrefix = "tag:yaml.org,2002:"

// shortTag abbreviates tags of the YAML namespace: tag:yaml.org,2002:str
// becomes !!str. Other tags are returned unchanged.
func shortTag(tag string) string {
	if strings.HasPrefix(tag, longTagPrefix) {
		return "!!" + tag[len(longTagPrefix):]
	}
	return tag
}

// ShortTag returns the short form of the node's tag, resolving it from the
// content when the node has none.
func (n *Node) ShortTag() string {
	if n.indicatedString() {
		return strTag
	}
	if n.Tag == "" || n.Tag == "!" {
		switch n.Kind {
		case MappingNode:
			return mapTag
		case SequenceNode:
			return seqTag
		case AliasNode:
			if n.Alias != nil {
				return n.Alias.ShortTag()
			}
		case ScalarNode:
			return resolveTag(n.Value)
		case 0:
			if n.isZero() {
				return nullTag
			}
		}
		return ""
	}
	return shortTag(n.Tag)
}

// indicatedString reports whether the node is a scalar whose tag or quoting
// makes it a string.
func (n *Node) indicatedString() bool {
	return n.Kind == ScalarNode &&
		(shortTag(n.Tag) == strTag ||
			(n.Tag == "" || n.Tag == "!") && n.Style&(SingleQuotedStyle|DoubleQuotedStyle|LiteralStyle|FoldedStyle) != 0)
}

func (n *Node) isZero() bool {
	return n.Kind == 0 && n.Style == 0 && n.Tag == "" && n.Value == "" && n.Anchor == "" &&
		n.Alias == nil && n.Content == nil && n.Line == 0 && n.Column == 0
}

// resolveTable classifies the first byte of a plain scalar: 'D' digit,
// 'S' sign, 'M' possibly a keyword of resolveMap, '.' possibly a float.
var resolveTable = func() (t [256]byte) {
	t['+'] = 'S'
	t['-'] = 'S'
	for _, c := range "0123456789" {
		t[c] = 'D'
	}
	for _, c := range "yYnNtTfFoO~" {
		t[c] = 'M'
	}
	t['.'] = '.'
	return t
}()

var resolveMap = func() map[string]string {
	m := make(map[string]string)
	add := func(tag string, values ...string) {
		for _, v := range values {
			m[v] = tag
		}
	}
	add(boolTag, "true", "True", "TRUE", "false", "False", "FALSE")
	add(nullTag, "", "~", "null", "Null", "NULL")
	add(floatTag, ".nan", ".NaN", ".NAN",
		".inf", ".Inf", ".INF", "+.inf", "+.Inf", "+.INF", "-.inf", "-.Inf", "-.INF")
	add(mergeTag, "<<")
	return m
}()

var yamlStyleFloat = regexp.MustCompile(`^[-+]?(\.[0-9]+|[0-9]+(\.[0-9]*)?)([eE][-+]?[0-9]+)?$`)

// resolveTag returns the tag yaml.v3 resolves for an untagged plain scalar.
func resolveTag(in string) string {
	hint := byte('N')
	if in != "" {
		hint = resolveTable[in[0]]
	}
	if hint == 0 {
		return strTag
	}
	if tag, ok := resolveMap[in]; ok {
		return tag
	}
	switch hint {
	case '.':
		if _, err := strconv.ParseFloat(in, 64); err == nil {
			return floatTag
		}
	case 'D', 'S':
		if _, ok := parseTimestamp(in); ok {
			return timestampTag
		}
		plain := strings.ReplaceAll(in, "_", "")
		if _, err := strconv.ParseInt(plain, 0, 64); err == nil {
			return intTag
		}
		if _, err := strconv.ParseUint(plain, 0, 64); err == nil {
			return intTag
		}
		if yamlStyleFloat.MatchString(plain) {
			if _, err := strconv.ParseFloat(plain, 64); err == nil {
				return floatTag
			}
		}
		switch {
		case strings.HasPrefix(plain, "0b"):
			if _, err := strconv.ParseInt(plain[2:], 2, 64); err == nil {
				return intTag
			}
			if _, err := strconv.ParseUint(plain[2:], 2, 64); err == nil {
				return intTag
			}
		case strings.HasPrefix(plain, "-0b"):
			if _, err := strconv.ParseInt("-"+plain[3:], 2, 64); err == nil {
				return intTag
			}
		}
		switch {
		case strings.HasPrefix(plain, "0o"):
			if _, err := strconv.ParseInt(plain[2:], 8, 64); err == nil {
				return intTag
			}
			if _, err := strconv.ParseUint(plain[2:], 8, 64); err == nil {
				return intTag
			}
		case strings.HasPrefix(plain, "-0o"):
			if _, err := strconv.ParseInt("-"+plain[3:], 8, 64); err == nil {
				return intTag
			}
		}
	}
	return strTag
}

// allowedTimestampFormats is the subset of the formats of
// https://yaml.org/type/timestamp.html that yaml.v3 recognizes.
var allowedTimestampFormats = []string{
	"2006-1-2T15:4:5.999999999Z07:00", // RFC3339Nano with short date fields.
	"2006-1-2t15:4:5.999999999Z07:00", // RFC3339Nano with short date fields and lower-case "t".
	"2006-1-2 15:4:5.999999999",       // space separated with no time zone
	"2006-1-2",                        // date only
}

// parseTimestamp parses s as a timestamp and reports whether it succeeded.
func parseTimestamp(s string) (time.Time, bool) {
	// Quick check: all date formats start with YYYY-.
	i := 0
	for ; i < len(s); i++ {
		if c := s[i]; c < '0' || c > '9' {
			break
		}
	}
	if i != 4 || i == len(s) || s[i] != '-' {
		return time.Time{}, false
	}
	for _, format := range allowedTimestampFormats {
		if t, err := time.Parse(format, s); err == nil {
			return t, true
		}
	}
	return time.Time{}, false
}
