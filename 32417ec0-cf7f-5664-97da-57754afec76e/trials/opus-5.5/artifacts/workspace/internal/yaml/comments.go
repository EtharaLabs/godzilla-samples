package yaml

// Comments are not part of the node tree, but yaml.v3 tracks them as it
// scans and parses, and that bookkeeping changes which error some malformed
// documents report: when the parser moves past a '-' entry with a head
// comment pending, it peeks at the next token to split the comment and
// ignores a scanner error that peek runs into. Scanning then resumes after
// the failed token, and a later parser error replaces the scanner error.
//
// This file keeps the comment state needed to reproduce that: comments are
// collected as head, line or foot comments while scanning, attached to the
// parser when it reaches the token they precede, and dropped when an event
// takes them.

type comment struct {
	tokenMark mark // Tokens from this position on take the comment.
	startMark mark // Position of the '#'.

	head, line, foot []byte
}

// scanComments consumes the comment at the current position, along with
// any following lines that hold only blanks and comments, and records them.
// A comment right below content is a foot comment of that content, unless
// an empty line follows it; the others are head comments of what follows.
func (p *parser) scanComments(scanMark mark) bool {
	last := p.tokens[len(p.tokens)-1]
	if last.typ == tokFlowEntry && len(p.tokens) > 1 {
		last = p.tokens[len(p.tokens)-2]
	}
	tokenMark := last.start
	var startMark mark
	nextIndent := max(p.indent, 0)
	recentEmpty := false
	firstEmpty := p.newlines <= 1
	line, column := p.mark.line, p.mark.column
	var text []byte

	// A comment starting on the foot line is still a foot of the prior
	// content. If the current line has content, that is the line below it.
	footLine := -1
	if scanMark.line > 0 {
		footLine = p.mark.line - p.newlines + 1
		if p.newlines == 0 && p.mark.column > 1 {
			footLine++
		}
	}

	// addFoot records the comment so far as a foot comment; what follows
	// is taken by the tokens from end on.
	addFoot := func(end mark) {
		p.comments = append(p.comments, comment{tokenMark: tokenMark, startMark: startMark, foot: text})
		tokenMark, text = end, nil
	}

	peek := 0
	for ; peek < 512; peek++ {
		if p.unread < peek+1 && !p.updateBuffer(peek+1) {
			break
		}
		column++
		if p.isBlank(peek) {
			continue
		}
		c := p.at(peek)
		closeFlow := p.flowLevel > 0 && (c == ']' || c == '}')
		if closeFlow || p.isBreakz(peek) {
			// A line break or the end of a flow collection.
			if closeFlow || !recentEmpty {
				if closeFlow || firstEmpty && (startMark.line == footLine && last.typ != tokValue || startMark.column-1 < nextIndent) {
					// The comment so far is a foot of the prior content.
					if len(text) > 0 {
						if startMark.column-1 < nextIndent {
							// Dedented, it is unrelated to the prior token.
							tokenMark = startMark
						}
						addFoot(mark{p.mark.index + peek, line, column})
					}
				} else if len(text) > 0 && p.at(peek) != 0 {
					text = append(text, '\n')
				}
			}
			if !p.isBreak(peek) {
				break
			}
			firstEmpty = false
			recentEmpty = true
			column = 0
			line++
			continue
		}

		if len(text) > 0 && column-1 < nextIndent && column != startMark.column {
			// A comment at a different indentation is a foot of the
			// preceding content rather than a head of what follows.
			addFoot(mark{p.mark.index + peek, line, column})
		}

		if c != '#' {
			break
		}
		if len(text) == 0 {
			startMark = mark{p.mark.index + peek, line, column}
		} else {
			text = append(text, '\n')
		}
		recentEmpty = false

		// Consume up to the end of this comment line.
		seen := p.mark.index + peek
		for {
			if p.unread < 1 && !p.updateBuffer(1) {
				return false
			}
			if p.isBreakz(0) {
				if p.mark.index >= seen {
					break
				}
				if p.unread < 2 && !p.updateBuffer(2) {
					return false
				}
				p.skipLine()
			} else if p.mark.index >= seen {
				text = p.read(text)
			} else {
				p.skip()
			}
		}

		// The next round starts past the line break ending the comment.
		peek = 0
		column = 0
		line = p.mark.line
		nextIndent = max(p.indent, 0)
	}

	if len(text) > 0 {
		p.comments = append(p.comments, comment{tokenMark: startMark, startMark: startMark, head: text})
	}
	return true
}

// scanLineComment consumes a comment that follows a token on its line and
// records it as a line comment taken by the tokens from tokenMark on.
// Unlike the whitespace skipping between tokens, it skips tabs too.
func (p *parser) scanLineComment(tokenMark mark) bool {
	if p.newlines > 0 {
		return true
	}
	var startMark mark
	var text []byte
	for peek := 0; peek < 512; peek++ {
		if p.unread < peek+1 && !p.updateBuffer(peek+1) {
			break
		}
		if p.isBlank(peek) {
			continue
		}
		if p.at(peek) == '#' {
			seen := p.mark.index + peek
			for {
				if p.unread < 1 && !p.updateBuffer(1) {
					return false
				}
				if p.isBreakz(0) {
					if p.mark.index >= seen {
						break
					}
					if p.unread < 2 && !p.updateBuffer(2) {
						return false
					}
					p.skipLine()
				} else if p.mark.index >= seen {
					if len(text) == 0 {
						startMark = p.mark
					}
					text = p.read(text)
				} else {
					p.skip()
				}
			}
		}
		break
	}
	if len(text) > 0 {
		p.comments = append(p.comments, comment{tokenMark: tokenMark, startMark: startMark, line: text})
	}
	return true
}

// repositionEntryComment handles a line comment followed by a sequence
// entry, as in
//
//	key: # comment
//	  - item
//
// where yaml.v3 turns the line comment into a head comment of the item.
func (p *parser) repositionEntryComment() {
	if len(p.comments) == 0 || len(p.tokens) < 2 {
		return
	}
	a, b := p.tokens[len(p.tokens)-2], p.tokens[len(p.tokens)-1]
	c := &p.comments[len(p.comments)-1]
	if a.typ == tokBlockSequenceStart && b.typ == tokBlockEntry && len(c.line) > 0 && !p.isBreak(0) {
		c.head, c.line = c.line, nil
		if c.startMark.line == p.mark.line-1 {
			c.tokenMark = p.mark
		}
	}
}

// unfoldComments attaches to the parser the comments taken by t. Head
// comments wait for a token other than BLOCK-END.
func (p *parser) unfoldComments(t *token) {
	for p.commentsHead < len(p.comments) && t.start.index >= p.comments[p.commentsHead].tokenMark.index {
		c := &p.comments[p.commentsHead]
		if len(c.head) > 0 {
			if t.typ == tokBlockEnd {
				break
			}
			p.headComment = appendComment(p.headComment, c.head)
		}
		if len(c.foot) > 0 {
			p.footComment = appendComment(p.footComment, c.foot)
		}
		if len(c.line) > 0 {
			p.lineComment = appendComment(p.lineComment, c.line)
		}
		*c = comment{}
		p.commentsHead++
	}
}

func appendComment(to, text []byte) []byte {
	if len(to) > 0 {
		to = append(to, '\n')
	}
	return append(to, text...)
}

// takeComments drops the pending comments, which an event takes.
func (p *parser) takeComments() {
	p.headComment = nil
	p.lineComment = nil
	p.footComment = nil
	p.stemComment = nil
}

// splitStemComment moves the head comment pending before a '-' entry aside
// when the entry holds a block collection. Like yaml.v3 it peeks at the
// next token and ignores a failure to scan it.
func (p *parser) splitStemComment(stemLen int) {
	if stemLen == 0 {
		return
	}
	t := p.peekToken()
	if t == nil || t.typ != tokBlockSequenceStart && t.typ != tokBlockMappingStart {
		return
	}
	p.stemComment = p.headComment[:stemLen]
	if len(p.headComment) == stemLen {
		p.headComment = nil
	} else {
		p.headComment = append([]byte(nil), p.headComment[stemLen+1:]...)
	}
}

// splitDocumentComment gives an implicit document the part of the pending
// head comment that ends with an empty line.
func (p *parser) splitDocumentComment() {
	h := p.headComment
	for i := len(h) - 1; i > 0; i-- {
		if h[i] != '\n' {
			continue
		}
		if i == len(h)-1 || h[i-1] == '\n' {
			p.headComment = h[i+1:]
			return
		}
	}
}
