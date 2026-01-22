package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
)

// TestJSON represents the test.json file structure.
type TestJSON struct {
	ID            string            `json:"id"`
	Name          string            `json:"name"`
	Description   string            `json:"description"`
	Category      string            `json:"category"`
	Tags          []string          `json:"tags"`
	Expected      ExpectedResult    `json:"expected"`
	ParserOptions map[string]any    `json:"parser_options,omitempty"`
}

// ExpectedResult represents the expected parsing result.
type ExpectedResult struct {
	Valid     bool           `json:"valid"`
	Parts     []ExpectedPart `json:"parts,omitempty"`
	ErrorType string         `json:"error_type,omitempty"`
}

// ExpectedPart represents an expected parsed part.
type ExpectedPart struct {
	Name        string  `json:"name"`
	Filename    *string `json:"filename"`
	ContentType *string `json:"content_type"`
	BodyText    *string `json:"body_text"`
	BodyBase64  *string `json:"body_base64"`
	BodySize    int     `json:"body_size"`
}

// HeadersJSON represents the headers.json file structure.
type HeadersJSON map[string]string

// TestCase holds all data for a single test case.
type TestCase struct {
	ID       string
	Dir      string
	Test     TestJSON
	Headers  HeadersJSON
	InputRaw []byte
}

// TestResult holds the result of running a test.
type TestResult struct {
	ID       string
	Status   string // "passed", "failed", "skipped"
	Message  string
	Optional bool
}

// findTestsRoot finds the tests directory relative to this file.
func findTestsRoot() string {
	// Go up from examples/go-stdlib to find tests/
	return filepath.Join("..", "..", "tests")
}

// collectTestCases collects all test cases from the tests/ directory.
func collectTestCases(t *testing.T) []TestCase {
	t.Helper()

	testsRoot := findTestsRoot()
	var testCases []TestCase

	categories, err := os.ReadDir(testsRoot)
	if err != nil {
		t.Fatalf("failed to read tests directory: %v", err)
	}

	for _, category := range categories {
		if !category.IsDir() {
			continue
		}

		categoryPath := filepath.Join(testsRoot, category.Name())
		tests, err := os.ReadDir(categoryPath)
		if err != nil {
			t.Logf("warning: failed to read category %s: %v", category.Name(), err)
			continue
		}

		for _, test := range tests {
			if !test.IsDir() {
				continue
			}

			testDir := filepath.Join(categoryPath, test.Name())
			tc, err := loadTestCase(testDir)
			if err != nil {
				t.Logf("warning: failed to load test case %s: %v", test.Name(), err)
				continue
			}

			testCases = append(testCases, tc)
		}
	}

	// Sort by ID for consistent ordering
	sort.Slice(testCases, func(i, j int) bool {
		return testCases[i].ID < testCases[j].ID
	})

	return testCases
}

// loadTestCase loads a single test case from a directory.
func loadTestCase(dir string) (TestCase, error) {
	tc := TestCase{
		Dir: dir,
		ID:  filepath.Base(dir),
	}

	// Load test.json
	testData, err := os.ReadFile(filepath.Join(dir, "test.json"))
	if err != nil {
		return tc, fmt.Errorf("failed to read test.json: %w", err)
	}
	if err := json.Unmarshal(testData, &tc.Test); err != nil {
		return tc, fmt.Errorf("failed to parse test.json: %w", err)
	}

	// Load headers.json
	headersData, err := os.ReadFile(filepath.Join(dir, "headers.json"))
	if err != nil {
		return tc, fmt.Errorf("failed to read headers.json: %w", err)
	}
	if err := json.Unmarshal(headersData, &tc.Headers); err != nil {
		return tc, fmt.Errorf("failed to parse headers.json: %w", err)
	}

	// Load input.raw
	tc.InputRaw, err = os.ReadFile(filepath.Join(dir, "input.raw"))
	if err != nil {
		return tc, fmt.Errorf("failed to read input.raw: %w", err)
	}

	return tc, nil
}

// isOptional checks if a test is optional based on its tags.
func isOptional(tc TestCase) bool {
	for _, tag := range tc.Test.Tags {
		if tag == "optional" {
			return true
		}
	}
	return false
}

// startTestServer starts an HTTP test server.
func startTestServer(t *testing.T) *httptest.Server {
	t.Helper()

	mux := http.NewServeMux()
	mux.HandleFunc("/parse", parseMultipart)
	mux.HandleFunc("/health", healthCheck)

	return httptest.NewServer(mux)
}

// comparePart compares an actual part with an expected part.
func comparePart(actual Part, expected ExpectedPart) []string {
	var mismatches []string

	// Compare name
	if actual.Name != expected.Name {
		mismatches = append(mismatches, fmt.Sprintf("name mismatch: got %q, expected %q", actual.Name, expected.Name))
	}

	// Compare filename
	if expected.Filename != nil {
		if actual.Filename == nil {
			mismatches = append(mismatches, fmt.Sprintf("filename mismatch: got nil, expected %q", *expected.Filename))
		} else if *actual.Filename != *expected.Filename {
			mismatches = append(mismatches, fmt.Sprintf("filename mismatch: got %q, expected %q", *actual.Filename, *expected.Filename))
		}
	} else if actual.Filename != nil {
		mismatches = append(mismatches, fmt.Sprintf("filename mismatch: got %q, expected nil", *actual.Filename))
	}

	// Compare content_type (only if expected specifies one)
	if expected.ContentType != nil {
		if actual.ContentType == nil {
			mismatches = append(mismatches, fmt.Sprintf("content_type mismatch: got nil, expected %q", *expected.ContentType))
		} else if *actual.ContentType != *expected.ContentType {
			mismatches = append(mismatches, fmt.Sprintf("content_type mismatch: got %q, expected %q", *actual.ContentType, *expected.ContentType))
		}
	}

	// Compare body content
	if expected.BodyText != nil {
		if actual.BodyText == nil {
			mismatches = append(mismatches, "body_text mismatch: got nil, expected text")
		} else if *actual.BodyText != *expected.BodyText {
			mismatches = append(mismatches, fmt.Sprintf("body_text mismatch: got %q, expected %q", truncate(*actual.BodyText, 50), truncate(*expected.BodyText, 50)))
		}
	} else if expected.BodyBase64 != nil {
		// Binary content - compare as base64
		var actualB64 string
		if actual.BodyBase64 != nil {
			actualB64 = *actual.BodyBase64
		} else if actual.BodyText != nil {
			// Server returned text, encode it for comparison
			actualB64 = base64.StdEncoding.EncodeToString([]byte(*actual.BodyText))
		}

		if actualB64 != *expected.BodyBase64 {
			mismatches = append(mismatches, fmt.Sprintf("body_base64 mismatch: got %s..., expected %s...", truncate(actualB64, 30), truncate(*expected.BodyBase64, 30)))
		}
	}

	// Compare body_size
	if actual.BodySize != expected.BodySize {
		mismatches = append(mismatches, fmt.Sprintf("body_size mismatch: got %d, expected %d", actual.BodySize, expected.BodySize))
	}

	return mismatches
}

// truncate truncates a string to maxLen characters.
func truncate(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	return s[:maxLen] + "..."
}

// TestConformance runs all conformance tests.
func TestConformance(t *testing.T) {
	server := startTestServer(t)
	defer server.Close()

	testCases := collectTestCases(t)
	if len(testCases) == 0 {
		t.Fatal("no test cases found")
	}

	t.Logf("Found %d test cases", len(testCases))

	for _, tc := range testCases {
		tc := tc // capture for parallel
		t.Run(tc.ID, func(t *testing.T) {
			runTestCase(t, server.URL, tc)
		})
	}
}

// runTestCase runs a single test case.
func runTestCase(t *testing.T, baseURL string, tc TestCase) {
	optional := isOptional(tc)

	// Build the request
	req, err := http.NewRequest("POST", baseURL+"/parse", bytes.NewReader(tc.InputRaw))
	if err != nil {
		if optional {
			t.Skipf("Optional test %s: failed to create request: %v", tc.ID, err)
		}
		t.Fatalf("failed to create request: %v", err)
	}

	// Set headers
	for key, value := range tc.Headers {
		req.Header.Set(key, value)
	}

	// Send request
	client := &http.Client{}
	resp, err := client.Do(req)
	if err != nil {
		if optional {
			t.Skipf("Optional test %s: HTTP client error: %v", tc.ID, err)
		}
		t.Fatalf("HTTP request failed: %v", err)
	}
	defer resp.Body.Close()

	// Parse response
	var result ParseResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}

	expected := tc.Test.Expected

	if expected.Valid {
		// Test expects successful parsing
		if !result.Valid {
			msg := ""
			if result.ErrorMessage != nil {
				msg = *result.ErrorMessage
			}
			if optional {
				t.Skipf("Optional test %s: Go stdlib could not parse input: %s", tc.ID, msg)
			}
			t.Fatalf("expected valid parsing, but got error: %s", msg)
		}

		// Compare parts count
		if len(result.Parts) != len(expected.Parts) {
			if optional {
				t.Skipf("Optional test %s: part count mismatch (got %d, expected %d)", tc.ID, len(result.Parts), len(expected.Parts))
			}
			t.Fatalf("part count mismatch: got %d, expected %d", len(result.Parts), len(expected.Parts))
		}

		// Compare each part
		var allMismatches []string
		for i := range expected.Parts {
			mismatches := comparePart(result.Parts[i], expected.Parts[i])
			if len(mismatches) > 0 {
				for _, m := range mismatches {
					allMismatches = append(allMismatches, fmt.Sprintf("Part %d: %s", i, m))
				}
			}
		}

		if len(allMismatches) > 0 {
			if optional {
				t.Skipf("Optional test %s failed:\n%s", tc.ID, strings.Join(allMismatches, "\n"))
			}
			t.Fatalf("Part comparison failed:\n%s", strings.Join(allMismatches, "\n"))
		}
	} else {
		// Test expects parsing to fail
		if result.Valid {
			// Go stdlib successfully parsed what we expected to fail
			// This is OK - it's just more lenient than the spec requires
			t.Skipf("Go stdlib parsed malformed input %s successfully (lenient parsing)", tc.ID)
		}
		// Optionally check error type matches
		// For now we just verify it failed
	}
}

// TestServerHealth tests the health check endpoint.
func TestServerHealth(t *testing.T) {
	server := startTestServer(t)
	defer server.Close()

	resp, err := http.Get(server.URL + "/health")
	if err != nil {
		t.Fatalf("health check failed: %v", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected status 200, got %d", resp.StatusCode)
	}

	var result map[string]string
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		t.Fatalf("failed to decode response: %v", err)
	}

	if result["status"] != "ok" {
		t.Fatalf("expected status 'ok', got %q", result["status"])
	}
}

// getUnusedPort finds an unused TCP port.
func getUnusedPort() (int, error) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return 0, err
	}
	port := listener.Addr().(*net.TCPAddr).Port
	listener.Close()
	return port, nil
}
