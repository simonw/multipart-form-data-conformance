# Go Standard Library Multipart Conformance Test Report

**Test Date:** January 2025
**Go Version:** 1.21+
**Package:** `mime/multipart` (standard library)

## Summary

| Result | Count | Percentage |
|--------|-------|------------|
| Passed | 49 | 84% |
| Skipped | 7 | 12% |
| Failed | 2 | 4% |
| **Total** | **58** | 100% |

Go's standard library `mime/multipart` package passes most conformance tests. The 2 failures are due to Go's stricter Content-Type parsing and intentional filename sanitization. The 7 skipped tests are optional features or cases where Go is more lenient than required.

## Test Results by Category

### Passed (49 tests)

Go's multipart parser handles most cases correctly:

- **Basic parsing** (5/5): Single fields, files, multiple fields, mixed content, arrays
- **Boundaries** (6/7): Simple, hyphens, long, content matching, quoted, whitespace
- **Browser variations** (5/5): Chrome, Firefox, Safari boundary styles, empty files
- **Content-Types** (8/8): Explicit, missing, charset, additional headers, case-insensitivity, header folding, parameter ordering, unquoted
- **Edge cases** (7/8): Empty file, empty field, binary content, boundary prefix, large files, UTF-8 BOM, null bytes, preamble
- **Filenames** (8/10): ASCII, Unicode UTF-8, spaces, quotes, backslash, semicolon, empty filename
- **Line endings** (5/5): CRLF standard, LF-only (lenient), mixed endings, bare CR, CRLF in values
- **Malformed inputs** (5/10): Wrong boundary, no blank line, epilogue, no leading CRLF

### Skipped - Optional or Lenient Parsing (7 tests)

These tests are either optional features or cases where Go's parser is more lenient than required:

| Test ID | Feature | Why Skipped |
|---------|---------|-------------|
| 022-filename-star-encoding | RFC 5987 `filename*` | Go doesn't decode RFC 5987 extended parameters (optional) |
| 023-both-filename-star | RFC 5987 with fallback | Same as above (optional) |
| 200-missing-final-terminator | Malformed input | Go parses successfully (lenient) |
| 203-missing-content-disposition | Malformed input | Go parses successfully (lenient) |
| 204-invalid-content-disposition | Malformed input | Go parses successfully (lenient) |
| 208-duplicate-headers | Duplicate Content-Disposition | Uses first value instead of last (optional) |
| 210-control-chars-in-name | Control characters | Go rejects malformed headers (strict - optional) |

### Failed - Conformance Issues (2 tests)

#### 1. Path Traversal Filename Sanitization

| Test ID | Issue |
|---------|-------|
| 029-filename-path-traversal | Go strips path components, returns `"passwd"` instead of `"../../../etc/passwd"` |

**What's happening:**

Go's `mime/multipart.Part.FileName()` method calls `filepath.Base()` to extract only the filename portion, stripping any directory path components:

```go
// From Go's mime/multipart/multipart.go
func (p *Part) FileName() string {
    // ...
    return filepath.Base(filename)
}
```

**Expected behavior** (per conformance test):
```json
{
  "filename": "../../../etc/passwd"
}
```

**Actual behavior** (Go stdlib):
```json
{
  "filename": "passwd"
}
```

**Impact:**

This is actually a **security feature** - Go sanitizes filenames to prevent path traversal attacks. The conformance test notes state: "Parsers should return the raw filename. Applications MUST sanitize before using in filesystem paths."

Go chose to sanitize at the parser level rather than requiring applications to do so. This is a valid security-conscious design decision, though it means applications cannot access the raw unsanitized filename if needed for logging or other purposes.

**Workaround:**

If you need the raw filename, you can parse the `Content-Disposition` header directly:

```go
cd := part.Header.Get("Content-Disposition")
_, params, _ := mime.ParseMediaType(cd)
rawFilename := params["filename"]
```

#### 2. Special Characters in Boundary

| Test ID | Issue |
|---------|-------|
| 044-boundary-special-chars | Go's `mime.ParseMediaType` rejects boundaries with special chars |

**What's happening:**

RFC 2046 allows these characters in boundary strings: `DIGIT / ALPHA / ' ( ) + _ , - . / : = ?`

The test uses boundary: `boundary'()+_,-./:=?`

Go's `mime.ParseMediaType` function in the standard library fails to parse this:

```
failed to parse Content-Type: mime: invalid media parameter
```

**Expected behavior:**
```json
{
  "valid": true,
  "parts": [{"name": "field", "body_text": "value"}]
}
```

**Actual behavior:**
```json
{
  "valid": false,
  "error_type": "parse_error",
  "error_message": "failed to parse Content-Type: mime: invalid media parameter"
}
```

**Impact:**

This is a real conformance issue. While uncommon, RFC 2046 explicitly allows these special characters in boundaries. Go's MIME package is overly strict in rejecting them.

**Root Cause:**

Go's `mime` package uses a stricter definition of valid parameter characters than RFC 2046 specifies. This is a known limitation of the standard library.

**Workaround:**

If you encounter boundaries with special characters, you may need to extract the boundary manually:

```go
contentType := r.Header.Get("Content-Type")
// Manual extraction if mime.ParseMediaType fails
if idx := strings.Index(contentType, "boundary="); idx != -1 {
    boundary = contentType[idx+9:]
    // Handle potential quoting
}
```

## Running the Tests

```bash
cd examples/go-stdlib
go test -v ./...
```

## Summary of Go's Behavior

### Strengths

1. **Security-conscious**: Sanitizes filenames to prevent path traversal
2. **Lenient parsing**: Handles many malformed inputs gracefully
3. **Good Unicode support**: Properly handles UTF-8 filenames
4. **Flexible line endings**: Accepts LF-only, mixed, and bare CR line endings
5. **Header folding support**: Handles obsolete HTTP/1.0 header continuation
6. **Empty filename handling**: Correctly distinguishes `filename=""` from no filename

### Limitations

1. **No RFC 5987 support**: `filename*` extended parameter encoding not supported
2. **Strict boundary parsing**: Rejects some RFC-compliant special characters in boundaries
3. **Filename sanitization**: Cannot access raw unsanitized filenames through the standard API

## Recommendations

1. **For Go team**: Consider relaxing boundary character validation to match RFC 2046
2. **For users needing raw filenames**: Parse `Content-Disposition` header directly
3. **For RFC 5987 support**: Use a third-party library or implement manual decoding
