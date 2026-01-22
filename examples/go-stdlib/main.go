// Package main provides a multipart/form-data parsing server for conformance testing.
//
// This server accepts POST requests with multipart/form-data content and
// returns a JSON response with the parsed parts, suitable for conformance testing.
package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"mime"
	"mime/multipart"
	"net/http"
	"strings"
	"unicode/utf8"
)

// ParseResponse represents the JSON response from the parse endpoint.
type ParseResponse struct {
	Valid        bool    `json:"valid"`
	Parts        []Part  `json:"parts,omitempty"`
	ErrorType    *string `json:"error_type,omitempty"`
	ErrorMessage *string `json:"error_message,omitempty"`
}

// Part represents a parsed multipart part.
type Part struct {
	Name        string  `json:"name"`
	Filename    *string `json:"filename"`
	ContentType *string `json:"content_type"`
	BodyText    *string `json:"body_text"`
	BodyBase64  *string `json:"body_base64"`
	BodySize    int     `json:"body_size"`
}

// parseMultipart handles POST /parse requests.
func parseMultipart(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	// Parse the Content-Type header to get the boundary
	contentType := r.Header.Get("Content-Type")
	mediaType, params, err := mime.ParseMediaType(contentType)
	if err != nil {
		writeError(w, "parse_error", fmt.Sprintf("failed to parse Content-Type: %v", err))
		return
	}

	if !strings.HasPrefix(mediaType, "multipart/") {
		writeError(w, "parse_error", fmt.Sprintf("expected multipart content type, got: %s", mediaType))
		return
	}

	boundary, ok := params["boundary"]
	if !ok {
		writeError(w, "boundary_mismatch", "missing boundary parameter in Content-Type")
		return
	}

	// Create a multipart reader
	reader := multipart.NewReader(r.Body, boundary)
	defer r.Body.Close()

	var parts []Part

	for {
		part, err := reader.NextPart()
		if err == io.EOF {
			break
		}
		if err != nil {
			errType := classifyError(err)
			writeError(w, errType, err.Error())
			return
		}

		// Read the part body
		body, err := io.ReadAll(part)
		if err != nil {
			writeError(w, "parse_error", fmt.Sprintf("failed to read part body: %v", err))
			return
		}

		// Get form field name from Content-Disposition
		name := part.FormName()

		// Get filename (if present)
		var filename *string
		fn := part.FileName()
		// Check if filename parameter was present in Content-Disposition
		// part.FileName() returns empty string for both no-filename and filename=""
		// We need to check the raw header to distinguish
		cd := part.Header.Get("Content-Disposition")
		if hasFilenameParam(cd) {
			filename = &fn
		}

		// Get Content-Type (if present)
		var contentType *string
		ct := part.Header.Get("Content-Type")
		if ct != "" {
			contentType = &ct
		}

		// Determine body representation (text or base64)
		var bodyText *string
		var bodyBase64 *string

		if utf8.Valid(body) {
			s := string(body)
			bodyText = &s
		} else {
			s := base64.StdEncoding.EncodeToString(body)
			bodyBase64 = &s
		}

		parts = append(parts, Part{
			Name:        name,
			Filename:    filename,
			ContentType: contentType,
			BodyText:    bodyText,
			BodyBase64:  bodyBase64,
			BodySize:    len(body),
		})
	}

	response := ParseResponse{
		Valid: true,
		Parts: parts,
	}

	json.NewEncoder(w).Encode(response)
}

// hasFilenameParam checks if the Content-Disposition header contains a filename parameter.
func hasFilenameParam(cd string) bool {
	// Look for filename= or filename*= in the header
	lower := strings.ToLower(cd)
	return strings.Contains(lower, "filename=") || strings.Contains(lower, "filename*=")
}

// classifyError maps common multipart parsing errors to error types.
func classifyError(err error) string {
	msg := strings.ToLower(err.Error())
	switch {
	case strings.Contains(msg, "boundary"):
		return "boundary_mismatch"
	case strings.Contains(msg, "content-disposition"):
		return "missing_content_disposition"
	case strings.Contains(msg, "header"):
		return "invalid_header"
	default:
		return "parse_error"
	}
}

// writeError writes a JSON error response.
func writeError(w http.ResponseWriter, errType, errMessage string) {
	response := ParseResponse{
		Valid:        false,
		ErrorType:    &errType,
		ErrorMessage: &errMessage,
	}
	json.NewEncoder(w).Encode(response)
}

// healthCheck handles GET /health requests.
func healthCheck(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

func main() {
	http.HandleFunc("/parse", parseMultipart)
	http.HandleFunc("/health", healthCheck)

	port := "8080"
	log.Printf("Starting server on :%s", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
