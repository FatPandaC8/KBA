package ingest

import (
	"archive/zip"
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"strings"

	"github.com/ledongthuc/pdf"
	"golang.org/x/net/html"
	"golang.org/x/text/unicode/norm"
)

var (
	ErrEmptyContent       = errors.New("extracted content is empty")
	ErrScannedPDFNoText   = errors.New("scanned PDFs without a digital text layer are not supported in MVP")
	ErrInvalidDOCXArchive = errors.New("invalid docx file: missing word/document.xml")
)

type ExtractedDocument struct {
	Title       string
	SourceType  string
	SourceURL   *string
	ContentHash string
	SourceText  string
	CharCount   int
	RawContent  []byte
}

func ComputeContentHash(content []byte) string {
	h := sha256.Sum256(content)
	return hex.EncodeToString(h[:])
}

func NormalizeText(raw string) string {
	// Unicode NFC Normalization
	normalized := norm.NFC.String(raw)
	// Normalize Windows \r\n to \n
	normalized = strings.ReplaceAll(normalized, "\r\n", "\n")
	normalized = strings.ReplaceAll(normalized, "\r", "\n")
	return strings.TrimSpace(normalized)
}

func ExtractFromPlainText(title, text string) (*ExtractedDocument, error) {
	normText := NormalizeText(text)
	if len(normText) == 0 {
		return nil, ErrEmptyContent
	}

	hash := ComputeContentHash([]byte(normText))
	if title == "" {
		// Use first line as title
		lines := strings.SplitN(normText, "\n", 2)
		title = strings.TrimSpace(lines[0])
		if len(title) > 60 {
			title = title[:60] + "..."
		}
	}

	runes := []rune(normText)
	return &ExtractedDocument{
		Title:       title,
		SourceType:  "text",
		ContentHash: hash,
		SourceText:  normText,
		CharCount:   len(runes),
		RawContent:  []byte(text),
	}, nil
}

func ExtractFromHTML(rawHTML []byte, sourceURL string) (*ExtractedDocument, error) {
	doc, err := html.Parse(bytes.NewReader(rawHTML))
	if err != nil {
		return nil, fmt.Errorf("failed to parse HTML: %w", err)
	}

	var title string
	var textBuf bytes.Buffer

	var traverse func(*html.Node)
	traverse = func(n *html.Node) {
		if n.Type == html.ElementNode {
			// Skip scripts, styles, noscript, and header/footer elements
			switch strings.ToLower(n.Data) {
			case "script", "style", "noscript", "svg", "nav", "footer":
				return
			case "title":
				if n.FirstChild != nil && title == "" {
					title = strings.TrimSpace(n.FirstChild.Data)
				}
			case "p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "article", "section":
				textBuf.WriteString("\n")
			}
		}

		if n.Type == html.TextNode {
			text := strings.TrimSpace(n.Data)
			if len(text) > 0 {
				textBuf.WriteString(text)
				textBuf.WriteString(" ")
			}
		}

		for c := n.FirstChild; c != nil; c = c.NextSibling {
			traverse(c)
		}

		if n.Type == html.ElementNode {
			switch strings.ToLower(n.Data) {
			case "p", "h1", "h2", "h3", "h4", "h5", "h6", "li":
				textBuf.WriteString("\n")
			}
		}
	}

	traverse(doc)

	cleaned := NormalizeText(textBuf.String())
	if len(cleaned) == 0 {
		return nil, ErrEmptyContent
	}

	if title == "" {
		title = sourceURL
	}

	hash := ComputeContentHash([]byte(cleaned))
	runes := []rune(cleaned)

	return &ExtractedDocument{
		Title:       title,
		SourceType:  "url",
		SourceURL:   &sourceURL,
		ContentHash: hash,
		SourceText:  cleaned,
		CharCount:   len(runes),
		RawContent:  rawHTML,
	}, nil
}

func ExtractFromDOCX(rawDOCX []byte, filename string) (*ExtractedDocument, error) {
	zipReader, err := zip.NewReader(bytes.NewReader(rawDOCX), int64(len(rawDOCX)))
	if err != nil {
		return nil, fmt.Errorf("failed to open docx zip: %w", err)
	}

	var docFile *zip.File
	for _, f := range zipReader.File {
		if f.Name == "word/document.xml" {
			docFile = f
			break
		}
	}
	if docFile == nil {
		return nil, ErrInvalidDOCXArchive
	}

	rc, err := docFile.Open()
	if err != nil {
		return nil, fmt.Errorf("failed to read word/document.xml: %w", err)
	}
	defer rc.Close()

	xmlBytes, err := io.ReadAll(rc)
	if err != nil {
		return nil, err
	}

	// Parse XML extracting w:t elements
	decoder := xml.NewDecoder(bytes.NewReader(xmlBytes))
	var buf bytes.Buffer
	for {
		token, err := decoder.Token()
		if err != nil {
			if errors.Is(err, io.EOF) {
				break
			}
			return nil, fmt.Errorf("XML decode error: %w", err)
		}

		switch elem := token.(type) {
		case xml.StartElement:
			if elem.Name.Local == "p" {
				buf.WriteString("\n")
			}
		case xml.CharData:
			buf.Write(elem)
		}
	}

	cleaned := NormalizeText(buf.String())
	if len(cleaned) == 0 {
		return nil, ErrEmptyContent
	}

	title := filename
	if title == "" {
		title = "Document.docx"
	}

	hash := ComputeContentHash([]byte(cleaned))
	runes := []rune(cleaned)

	return &ExtractedDocument{
		Title:       title,
		SourceType:  "docx",
		ContentHash: hash,
		SourceText:  cleaned,
		CharCount:   len(runes),
		RawContent:  rawDOCX,
	}, nil
}

func ExtractFromPDF(rawPDF []byte, filename string) (*ExtractedDocument, error) {
	reader, err := pdf.NewReader(bytes.NewReader(rawPDF), int64(len(rawPDF)))
	if err != nil {
		return nil, fmt.Errorf("failed to parse PDF structure: %w", err)
	}

	var buf bytes.Buffer
	numPages := reader.NumPage()
	for i := 1; i <= numPages; i++ {
		page := reader.Page(i)
		if page.V.IsNull() {
			continue
		}
		text, err := page.GetPlainText(nil)
		if err == nil && len(text) > 0 {
			buf.WriteString(text)
			buf.WriteString("\n")
		}
	}

	cleaned := NormalizeText(buf.String())
	if len(cleaned) == 0 {
		// Distinguish scanned PDF (0 characters extracted) from digital PDF
		return nil, ErrScannedPDFNoText
	}

	title := filename
	if title == "" {
		title = "Document.pdf"
	}

	hash := ComputeContentHash([]byte(cleaned))
	runes := []rune(cleaned)

	return &ExtractedDocument{
		Title:       title,
		SourceType:  "pdf",
		ContentHash: hash,
		SourceText:  cleaned,
		CharCount:   len(runes),
		RawContent:  rawPDF,
	}, nil
}
