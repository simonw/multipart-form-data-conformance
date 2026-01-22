# Node.js Multipart Conformance Test Report

**Test Date:** January 2025
**Node.js Version:** 22.x
**Libraries Tested:**
- multer 2.0.2
- formidable 3.5.x
- busboy 1.6.x

## Summary

This report covers three of the most popular Node.js multipart/form-data parsing libraries.

### Overall Results (174 tests across 3 parsers)

| Result | Count | Percentage |
|--------|-------|------------|
| Passed | 118 | 68% |
| Failed | 27 | 16% |
| Skipped | 29 | 17% |
| **Total** | **174** | 100% |

### Results by Parser

| Parser | Passed | Failed | Skipped | Pass Rate |
|--------|--------|--------|---------|-----------|
| **busboy** | 39 | 7 | 12 | 67% |
| **formidable** | 42 | 9 | 7 | 72% |
| **multer** | 37 | 11 | 10 | 64% |

## Key Findings

### Part Ordering

A critical difference between these libraries is how they handle the order of parts:

| Library | Preserves Order? | Behavior |
|---------|------------------|----------|
| **busboy** | Yes | Events fire in order; our implementation preserves this |
| **multer** | No | Returns files first, then fields |
| **formidable** | No | Returns fields first, then files |

This affects test `004-mixed-fields-files` which expects parts in their original order (title, file, description). Only busboy passes this test.

### Empty Filename Handling

All three libraries struggle with `filename=""` (empty string filename):

| Test | Expected | Actual (all parsers) |
|------|----------|---------------------|
| 028-empty-filename | `filename: ""` | `filename: null` or no part |
| 303-chrome-empty-file | `filename: ""` | `filename: null` or rejected |
| 304-firefox-empty-file | `filename: ""` | `filename: null` or rejected |

**Impact:** Applications cannot distinguish between "no filename parameter" and "empty filename parameter" (which browsers send when no file is selected).

### Path/Backslash in Filenames

Test `026-filename-with-backslash` expects `folder\file.txt` to be preserved, but:
- **multer/busboy**: Return `file.txt` (strips path)
- **formidable**: Returns `file.txt` (strips path)

This is actually a **security feature** - these libraries strip path components to prevent directory traversal. The test `029-filename-path-traversal` (`../../../etc/passwd`) shows similar sanitization.

### Unicode Filenames

Test `021-unicode-filename-utf8` with filename `文档.pdf`:
- **formidable**: Passes (correctly decodes UTF-8)
- **multer/busboy**: Fail (encoding issues - returns garbled text)

## Detailed Results by Parser

### Multer

**Failed Tests (11):**

| Test ID | Issue |
|---------|-------|
| 004-mixed-fields-files | Part ordering (files before fields) |
| 044-boundary-special-chars | Cannot parse boundary with special characters |
| 300-chrome-webkit-boundary | Part ordering issue |
| 301-firefox-boundary | Part ordering issue |
| 302-safari-boundary | Part ordering issue |
| 303-chrome-empty-file | Empty filename returns no part |
| 304-firefox-empty-file | Empty filename returns no part |
| 021-unicode-filename-utf8 | UTF-8 filename encoding issue |
| 026-filename-with-backslash | Path stripped (security feature) |
| 028-empty-filename | Empty filename returns no part |
| 029-filename-path-traversal | Path stripped (security feature) |

**Skipped Tests (10):** Optional features including lenient line endings, RFC 5987 filename*, whitespace handling.

### Formidable

**Failed Tests (9):**

| Test ID | Issue |
|---------|-------|
| 004-mixed-fields-files | Part ordering (fields before files) |
| 081-missing-content-type | Filename not detected without Content-Type |
| 086-parameter-ordering | Filename not detected with non-standard parameter order |
| 100-empty-file | Rejects empty files by default (`allowEmptyFiles: false`) |
| 303-chrome-empty-file | Rejects empty files |
| 304-firefox-empty-file | Rejects empty files |
| 025-filename-with-quotes | Quote handling in filename |
| 026-filename-with-backslash | Path stripped (security feature) |
| 028-empty-filename | Empty filename handling |

**Note:** Formidable's empty file rejection can be fixed by setting `allowEmptyFiles: true`.

**Skipped Tests (7):** Optional features and lenient parsing of malformed inputs.

### Busboy

**Failed Tests (7):**

| Test ID | Issue |
|---------|-------|
| 044-boundary-special-chars | "Malformed content type" error |
| 303-chrome-empty-file | `filename: ""` returns `null` |
| 304-firefox-empty-file | `filename: ""` returns `null` |
| 021-unicode-filename-utf8 | UTF-8 filename encoding issue |
| 026-filename-with-backslash | Path stripped (security feature) |
| 028-empty-filename | Empty filename returns `null` |
| 029-filename-path-traversal | Path stripped (security feature) |

**Skipped Tests (12):** Optional features, lenient parsing, and some HTTP client rejections for malformed test inputs.

## Running the Tests

```bash
cd examples/nodejs
npm install
npm test
```

## Recommendations

1. **For preserving part order:** Use busboy directly or ensure your application doesn't depend on part ordering.

2. **For empty file detection:** Check `body_size === 0` as a workaround since `filename === ""` isn't reliably detected.

3. **For Unicode filenames:** Formidable has the best support; consider it for international applications.

4. **For security:** The path-stripping behavior is intentional and good - don't try to "fix" it.

5. **For empty files with formidable:** Set `allowEmptyFiles: true` in options if you need to accept empty file uploads.

## Architecture Notes

This implementation uses Express.js with three separate endpoints:

- `POST /parse/multer` - Uses multer middleware with memory storage
- `POST /parse/formidable` - Uses formidable's Promise-based API with in-memory streaming
- `POST /parse/busboy` - Uses busboy's event-based API with order preservation

All three return the same JSON response format for comparison.
