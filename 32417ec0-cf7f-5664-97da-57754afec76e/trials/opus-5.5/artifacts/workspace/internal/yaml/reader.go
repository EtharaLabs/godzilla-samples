package yaml

import "unicode/utf8"

// The reader decodes the input into p.buffer, a UTF-8 byte buffer the
// scanner reads characters from. Like libyaml it decodes the input in
// 512-byte chunks, only when the scanner asks for more characters than are
// buffered, and it validates every character it decodes. An invalid byte is
// therefore only reported once the scanner reads near it, which decides
// whether a reader or a scanner error wins on larger inputs.

const rawBufferSize = 512

type encoding int

const (
	anyEncoding encoding = iota
	utf8Encoding
	utf16LEEncoding
	utf16BEEncoding
)

func (p *parser) setReaderError(problem string) bool {
	p.err = readerError
	p.problem = problem
	return false
}

// updateRawBuffer moves the next chunk of the input into the raw buffer.
func (p *parser) updateRawBuffer() bool {
	if p.rawPos == 0 && len(p.raw) == cap(p.raw) {
		return true // The raw buffer is full.
	}
	if p.eof {
		return true
	}
	if p.rawPos > 0 && p.rawPos < len(p.raw) {
		copy(p.raw, p.raw[p.rawPos:])
	}
	p.raw = p.raw[:len(p.raw)-p.rawPos]
	p.rawPos = 0
	if p.inputPos == len(p.input) {
		p.eof = true
		return true
	}
	n := copy(p.raw[len(p.raw):cap(p.raw)], p.input[p.inputPos:])
	p.inputPos += n
	p.raw = p.raw[:len(p.raw)+n]
	return true
}

// determineEncoding detects the encoding from a byte order mark, which it
// consumes, and defaults to UTF-8.
func (p *parser) determineEncoding() bool {
	for !p.eof && len(p.raw)-p.rawPos < 3 {
		if !p.updateRawBuffer() {
			return false
		}
	}
	buf := p.raw[p.rawPos:]
	switch {
	case len(buf) >= 2 && buf[0] == 0xFF && buf[1] == 0xFE:
		p.encoding = utf16LEEncoding
		p.rawPos += 2
	case len(buf) >= 2 && buf[0] == 0xFE && buf[1] == 0xFF:
		p.encoding = utf16BEEncoding
		p.rawPos += 2
	case len(buf) >= 3 && buf[0] == 0xEF && buf[1] == 0xBB && buf[2] == 0xBF:
		p.encoding = utf8Encoding
		p.rawPos += 3
	default:
		p.encoding = utf8Encoding
	}
	return true
}

// updateBuffer makes sure at least length characters are buffered. At the
// end of the input the buffer is padded with NUL characters, which the
// scanner treats as the end of the stream.
func (p *parser) updateBuffer(length int) bool {
	if p.unread >= length {
		return true
	}
	if p.encoding == anyEncoding && !p.determineEncoding() {
		return false
	}

	// Move the unread characters to the beginning of the buffer.
	if p.bufferPos > 0 {
		n := 0
		if p.bufferPos < len(p.buffer) {
			n = copy(p.buffer, p.buffer[p.bufferPos:])
		}
		p.buffer = p.buffer[:n]
		p.bufferPos = 0
	}

	for first := true; p.unread < length; first = false {
		if !first || p.rawPos == len(p.raw) {
			if !p.updateRawBuffer() {
				return false
			}
		}
		if !p.decodeRaw() {
			return false
		}
		if p.eof {
			p.buffer = append(p.buffer, 0)
			p.unread++
			break
		}
	}
	for len(p.buffer) < length {
		p.buffer = append(p.buffer, 0)
	}
	return true
}

// decodeRaw decodes the complete characters of the raw buffer into the
// buffer, checking that each is a valid, printable character.
func (p *parser) decodeRaw() bool {
	for p.rawPos != len(p.raw) {
		var value rune
		var width int
		rawUnread := len(p.raw) - p.rawPos

		switch p.encoding {
		case utf8Encoding:
			octet := p.raw[p.rawPos]
			switch {
			case octet&0x80 == 0x00:
				width, value = 1, rune(octet&0x7F)
			case octet&0xE0 == 0xC0:
				width, value = 2, rune(octet&0x1F)
			case octet&0xF0 == 0xE0:
				width, value = 3, rune(octet&0x0F)
			case octet&0xF8 == 0xF0:
				width, value = 4, rune(octet&0x07)
			default:
				return p.setReaderError("invalid leading UTF-8 octet")
			}
			if width > rawUnread {
				if p.eof {
					return p.setReaderError("incomplete UTF-8 octet sequence")
				}
				return true // Wait for the rest of the character.
			}
			for k := 1; k < width; k++ {
				octet = p.raw[p.rawPos+k]
				if octet&0xC0 != 0x80 {
					return p.setReaderError("invalid trailing UTF-8 octet")
				}
				value = value<<6 + rune(octet&0x3F)
			}
			switch {
			case width == 1:
			case width == 2 && value >= 0x80:
			case width == 3 && value >= 0x800:
			case width == 4 && value >= 0x10000:
			default:
				return p.setReaderError("invalid length of a UTF-8 sequence")
			}
			if value >= 0xD800 && value <= 0xDFFF || value > 0x10FFFF {
				return p.setReaderError("invalid Unicode character")
			}

		case utf16LEEncoding, utf16BEEncoding:
			low, high := 0, 1
			if p.encoding == utf16BEEncoding {
				low, high = 1, 0
			}
			if rawUnread < 2 {
				if p.eof {
					return p.setReaderError("incomplete UTF-16 character")
				}
				return true
			}
			value = rune(p.raw[p.rawPos+low]) + rune(p.raw[p.rawPos+high])<<8
			if value&0xFC00 == 0xDC00 {
				return p.setReaderError("unexpected low surrogate area")
			}
			width = 2
			if value&0xFC00 == 0xD800 {
				width = 4
				if rawUnread < 4 {
					if p.eof {
						return p.setReaderError("incomplete UTF-16 surrogate pair")
					}
					return true
				}
				value2 := rune(p.raw[p.rawPos+low+2]) + rune(p.raw[p.rawPos+high+2])<<8
				if value2&0xFC00 != 0xDC00 {
					return p.setReaderError("expected low surrogate area")
				}
				value = 0x10000 + (value&0x3FF)<<10 + value2&0x3FF
			}
		}

		switch {
		case value == 0x09, value == 0x0A, value == 0x0D:
		case value >= 0x20 && value <= 0x7E:
		case value == 0x85:
		case value >= 0xA0 && value <= 0xD7FF:
		case value >= 0xE000 && value <= 0xFFFD:
		case value >= 0x10000 && value <= 0x10FFFF:
		default:
			return p.setReaderError("control characters are not allowed")
		}

		p.rawPos += width
		p.buffer = utf8.AppendRune(p.buffer, value)
		p.unread++
	}
	return true
}
