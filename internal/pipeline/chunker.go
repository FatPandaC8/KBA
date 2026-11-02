package pipeline

import (
	"unicode/utf8"

	"github.com/google/uuid"

	"gusby/internal/store"
)

const (
	TargetChunkSize = 2000 // characters
	MinChunkSize    = 1000 // characters
	MaxChunkSize    = 2500 // characters
	OverlapSize     = 150  // characters
)

// ChunkDocument slices normalized source text into boundary-aware chunks with exact byte and rune offsets
func ChunkDocument(userID, docID uuid.UUID, sourceText string) []*store.DocumentChunk {
	if len(sourceText) == 0 {
		return nil
	}

	runes := []rune(sourceText)
	totalRunes := len(runes)

	var chunks []*store.DocumentChunk
	chunkIndex := 0
	runeStart := 0

	for runeStart < totalRunes {
		runeEnd := runeStart + TargetChunkSize
		if runeEnd >= totalRunes {
			runeEnd = totalRunes
		} else {
			// Find natural break boundary (paragraph \n\n, newline \n, or sentence boundary . ! ?)
			boundary := findBoundary(runes, runeStart+MinChunkSize, runeEnd)
			if boundary > runeStart {
				runeEnd = boundary
			}
		}

		chunkRunes := runes[runeStart:runeEnd]
		chunkText := string(chunkRunes)

		// Compute byte offsets from rune indices
		byteStart := len(string(runes[:runeStart]))
		byteEnd := byteStart + len(string(chunkRunes))

		chunks = append(chunks, &store.DocumentChunk{
			ID:         uuid.New(),
			UserID:     userID,
			DocumentID: docID,
			ChunkIndex: chunkIndex,
			ChunkText:  chunkText,
			ByteStart:  byteStart,
			ByteEnd:    byteEnd,
			CharStart:  runeStart,
			CharEnd:    runeEnd,
		})

		chunkIndex++

		// Advance runeStart with overlap if not at the end
		if runeEnd >= totalRunes {
			break
		}
		runeStart = runeEnd - OverlapSize
		if runeStart < 0 {
			runeStart = 0
		}
	}

	return chunks
}

func findBoundary(runes []rune, minIdx, maxIdx int) int {
	if maxIdx > len(runes) {
		maxIdx = len(runes)
	}

	// 1. Look for double newline (paragraph break) from maxIdx down to minIdx
	for i := maxIdx - 1; i >= minIdx; i-- {
		if runes[i] == '\n' && i > 0 && runes[i-1] == '\n' {
			return i + 1
		}
	}

	// 2. Look for sentence terminators (. ! ?) followed by whitespace or newline
	for i := maxIdx - 1; i >= minIdx; i-- {
		r := runes[i]
		if (r == '.' || r == '!' || r == '?' || r == ';' || r == '。') && (i+1 < len(runes) && (runes[i+1] == ' ' || runes[i+1] == '\n')) {
			return i + 1
		}
	}

	// 3. Look for single newline
	for i := maxIdx - 1; i >= minIdx; i-- {
		if runes[i] == '\n' {
			return i + 1
		}
	}

	// 4. Look for space
	for i := maxIdx - 1; i >= minIdx; i-- {
		if runes[i] == ' ' {
			return i + 1
		}
	}

	// Fallback to maxIdx
	return maxIdx
}

// ByteToRuneOffset converts a UTF-8 byte offset to a Unicode rune offset in the given string
func ByteToRuneOffset(text string, byteOffset int) int {
	if byteOffset <= 0 {
		return 0
	}
	if byteOffset >= len(text) {
		return utf8.RuneCountInString(text)
	}
	return utf8.RuneCountInString(text[:byteOffset])
}

// RuneToByteOffset converts a Unicode rune offset to a UTF-8 byte offset in the given string
func RuneToByteOffset(text string, runeOffset int) int {
	if runeOffset <= 0 {
		return 0
	}
	runes := []rune(text)
	if runeOffset >= len(runes) {
		return len(text)
	}
	return len(string(runes[:runeOffset]))
}
