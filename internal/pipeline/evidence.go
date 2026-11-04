package pipeline

import (
	"strings"
	"unicode/utf8"

	"golang.org/x/text/unicode/norm"
)

type EvidenceSpan struct {
	IsValid           bool
	NormalizedQuote   string
	RelativeByteStart int
	RelativeByteEnd   int
	DocumentByteStart int
	DocumentByteEnd   int
	DocumentCharStart int
	DocumentCharEnd   int
}

// ValidateEvidence deterministic verification of verbatim quote against chunk text
func ValidateEvidence(chunkText, quote string, chunkByteStart, chunkCharStart int) EvidenceSpan {
	if quote == "" || chunkText == "" {
		return EvidenceSpan{IsValid: false}
	}

	normQuote := norm.NFC.String(strings.TrimSpace(quote))
	normChunk := norm.NFC.String(chunkText)

	idx := strings.Index(normChunk, normQuote)
	if idx == -1 {
		// Try case-insensitive fallback if exact casing differs only slightly
		lowerChunk := strings.ToLower(normChunk)
		lowerQuote := strings.ToLower(normQuote)
		idx = strings.Index(lowerChunk, lowerQuote)
		if idx == -1 {
			// Strict precision: verbatim quote is not present in source text
			return EvidenceSpan{IsValid: false, NormalizedQuote: normQuote}
		}
	}

	relByteStart := idx
	relByteEnd := idx + len(normQuote)

	// Relative rune offset inside chunk
	relCharStart := utf8.RuneCountInString(normChunk[:relByteStart])
	relCharEnd := relCharStart + utf8.RuneCountInString(normQuote)

	// Absolute offsets relative to root document
	docByteStart := chunkByteStart + relByteStart
	docByteEnd := chunkByteStart + relByteEnd

	docCharStart := chunkCharStart + relCharStart
	docCharEnd := chunkCharStart + relCharEnd

	return EvidenceSpan{
		IsValid:           true,
		NormalizedQuote:   normQuote,
		RelativeByteStart: relByteStart,
		RelativeByteEnd:   relByteEnd,
		DocumentByteStart: docByteStart,
		DocumentByteEnd:   docByteEnd,
		DocumentCharStart: docCharStart,
		DocumentCharEnd:   docCharEnd,
	}
}
