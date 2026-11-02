package pipeline_test

import (
	"archive/zip"
	"bytes"
	"context"
	"net"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"gusby/internal/config"
	"gusby/internal/ingest"
	"gusby/internal/llm"
	"gusby/internal/pipeline"
	"gusby/internal/store"
)

func getTestStore(t *testing.T) *store.Store {
	t.Helper()
	cfg := config.LoadConfig()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	s, err := store.NewStore(ctx, cfg.DatabaseURL)
	if err != nil {
		t.Skipf("PostgreSQL not accessible (%v), skipping pipeline test", err)
	}
	return s
}

func TestSSRFProtection(t *testing.T) {
	// 1. Loopback addresses must be blocked
	loopbacks := []string{"127.0.0.1", "127.0.0.2", "::1"}
	for _, ipStr := range loopbacks {
		ip := net.ParseIP(ipStr)
		if !ingest.IsPrivateOrLoopbackIP(ip) {
			t.Errorf("expected loopback %s to be blocked", ipStr)
		}
	}

	// 2. Cloud metadata service must be blocked
	metaIP := net.ParseIP("169.254.169.254")
	if !ingest.IsPrivateOrLoopbackIP(metaIP) {
		t.Errorf("expected cloud metadata IP 169.254.169.254 to be blocked")
	}

	// 3. RFC1918 Private IPs must be blocked
	privateIPs := []string{"10.0.0.1", "172.16.0.5", "192.168.1.100"}
	for _, ipStr := range privateIPs {
		ip := net.ParseIP(ipStr)
		if !ingest.IsPrivateOrLoopbackIP(ip) {
			t.Errorf("expected private IP %s to be blocked", ipStr)
		}
	}

	// 4. Public IPs must NOT be blocked
	publicIP := net.ParseIP("8.8.8.8")
	if ingest.IsPrivateOrLoopbackIP(publicIP) {
		t.Errorf("public IP 8.8.8.8 should NOT be blocked")
	}

	// 5. Test FetchSafeURL with loopback / unsupported scheme
	ctx := context.Background()
	_, _, err := ingest.FetchSafeURL(ctx, "ftp://example.com/file")
	if err != ingest.ErrUnsupportedScheme {
		t.Errorf("expected ErrUnsupportedScheme for ftp, got %v", err)
	}

	_, _, err = ingest.FetchSafeURL(ctx, "http://127.0.0.1:8000/admin")
	if err == nil || !strings.Contains(err.Error(), "forbidden") {
		t.Errorf("expected blocked error for 127.0.0.1, got %v", err)
	}
}

func TestUnicodeChunkerAndOffsets(t *testing.T) {
	// Source text in Vietnamese with composite diacritics
	vnText := "Trí tuệ nhân tạo (AI) đang phát triển vượt bậc. Đồ thị tri thức (Knowledge Graph) giúp kết nối các khái niệm chặt chẽ với nhau dựa trên bằng chứng xác thực."

	userID := uuid.New()
	docID := uuid.New()

	chunks := pipeline.ChunkDocument(userID, docID, vnText)
	if len(chunks) == 0 {
		t.Fatalf("expected at least 1 chunk")
	}

	chunk := chunks[0]
	if chunk.ChunkText != vnText {
		t.Errorf("expected chunk text to match original, got %q", chunk.ChunkText)
	}

	// Verify rune and byte offset consistency
	extractedByRune := string([]rune(vnText)[chunk.CharStart:chunk.CharEnd])
	if extractedByRune != vnText {
		t.Errorf("rune slicing failed: expected %q, got %q", vnText, extractedByRune)
	}

	extractedByByte := vnText[chunk.ByteStart:chunk.ByteEnd]
	if extractedByByte != vnText {
		t.Errorf("byte slicing failed: expected %q, got %q", vnText, extractedByByte)
	}
}

func TestDeterministicEvidenceValidation(t *testing.T) {
	chunkText := "Albert Einstein published the theory of general relativity in 1915. It fundamentally altered the understanding of gravity."

	// 1. Valid verbatim quote
	validQuote := "published the theory of general relativity in 1915"
	span := pipeline.ValidateEvidence(chunkText, validQuote, 100, 50)
	if !span.IsValid {
		t.Errorf("expected valid evidence span, got invalid")
	}
	if span.DocumentByteStart != 100+16 {
		t.Errorf("expected byte start %d, got %d", 100+16, span.DocumentByteStart)
	}

	// 2. Hallucinated / Non-existent quote must be rejected
	hallucinatedQuote := "Einstein discovered black holes in Switzerland"
	invalidSpan := pipeline.ValidateEvidence(chunkText, hallucinatedQuote, 100, 50)
	if invalidSpan.IsValid {
		t.Errorf("expected invalid evidence span for hallucination, but got valid")
	}

	// 3. Vietnamese verbatim quote with diacritics
	vnChunk := "Đồ thị tri thức biểu diễn các mối quan hệ giữa các thực thể."
	vnQuote := "các mối quan hệ giữa các thực thể"
	vnSpan := pipeline.ValidateEvidence(vnChunk, vnQuote, 0, 0)
	if !vnSpan.IsValid {
		t.Errorf("expected valid evidence span for Vietnamese text, got invalid")
	}
}

func TestDOCXExtraction(t *testing.T) {
	// Construct minimal valid in-memory DOCX zip archive
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)

	docXML := `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Hello Gusby Knowledge Graph</w:t></w:r></w:p>
    <w:p><w:r><w:t>Second paragraph of facts.</w:t></w:r></w:p>
  </w:body>
</w:document>`

	w, err := zw.Create("word/document.xml")
	if err != nil {
		t.Fatalf("failed to create zip entry: %v", err)
	}
	if _, err := w.Write([]byte(docXML)); err != nil {
		t.Fatalf("failed to write docXML: %v", err)
	}
	if err := zw.Close(); err != nil {
		t.Fatalf("failed to close zip: %v", err)
	}

	doc, err := ingest.ExtractFromDOCX(buf.Bytes(), "sample.docx")
	if err != nil {
		t.Fatalf("DOCX extraction failed: %v", err)
	}

	if !strings.Contains(doc.SourceText, "Hello Gusby Knowledge Graph") {
		t.Errorf("expected extracted text to contain 'Hello Gusby Knowledge Graph', got %q", doc.SourceText)
	}
	if doc.SourceType != "docx" {
		t.Errorf("expected source_type 'docx', got %s", doc.SourceType)
	}
}

func TestPipelineExtraction_MockIntegration(t *testing.T) {
	s := getTestStore(t)
	defer s.Close()
	ctx := context.Background()

	userID := uuid.New()
	_, err := s.CreateUser(ctx, "pipe-"+userID.String()[:8]+"@example.com", "argon-hash-pw-test")
	if err != nil {
		t.Fatalf("create user failed: %v", err)
	}

	chunkText := "DNA stores genetic information in all known living organisms. Watson and Crick identified the double helix structure of DNA in 1953."
	chunk := &store.DocumentChunk{
		ID:         uuid.New(),
		UserID:     userID,
		DocumentID: uuid.New(),
		ChunkIndex: 0,
		ChunkText:  chunkText,
		ByteStart:  0,
		ByteEnd:    len(chunkText),
		CharStart:  0,
		CharEnd:    len([]rune(chunkText)),
	}

	mockLLM := llm.NewMockClient("")
	// Script concept extraction response
	mockLLM.SetResponse("Extract key concepts", `{
		"concepts": [
			{"name": "DNA", "category": "Biology", "core_idea": "Molecule storing genetic information.", "confidence": 0.98},
			{"name": "Double Helix", "category": "Structure", "core_idea": "Spiral structure of DNA.", "confidence": 0.95}
		]
	}`)

	// Script proposition extraction response
	mockLLM.SetResponse("EXTRACTED CONCEPTS", `{
		"propositions": [
			{
				"subject": "DNA",
				"predicate": "Has structure",
				"object": "Double Helix",
				"evidence_quote": "double helix structure of DNA",
				"confidence": 0.94
			}
		]
	}`)

	res, err := pipeline.ExtractChunk(ctx, mockLLM, chunk)
	if err != nil {
		t.Fatalf("ExtractChunk failed: %v", err)
	}

	if len(res.Concepts) != 2 {
		t.Errorf("expected 2 concepts, got %d", len(res.Concepts))
	}
	if len(res.Propositions) != 1 {
		t.Fatalf("expected 1 proposition, got %d", len(res.Propositions))
	}

	prop := res.Propositions[0]
	if !prop.IsValidEvidence {
		t.Errorf("expected evidence quote %q to be valid in chunk text", prop.EvidenceQuote)
	}
	if prop.EvidenceCharStart == nil || *prop.EvidenceCharStart <= 0 {
		t.Errorf("expected valid char start offset, got %v", prop.EvidenceCharStart)
	}
}
