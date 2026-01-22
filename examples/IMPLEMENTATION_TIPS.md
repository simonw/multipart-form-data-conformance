# Implementation Tips for Conformance Test Runners

This guide explains how to create a conformance test runner for any multipart/form-data parser implementation.

## Overview

Each implementation should:

1. Create a server that accepts multipart/form-data POST requests
2. Parse the incoming data using the library being tested
3. Return a JSON response describing the parsed result
4. Run tests that send each test case's `input.raw` to the server and compare against `expected`

## Server Requirements

Your server needs a single endpoint (e.g., `POST /parse`) that:

1. Accepts raw HTTP request bodies with `Content-Type: multipart/form-data; boundary=...`
2. Parses the multipart data using your library
3. Returns JSON describing what was parsed

### Response Format for Successful Parsing

```json
{
  "valid": true,
  "parts": [
    {
      "name": "field_name",
      "filename": "example.txt",
      "content_type": "text/plain",
      "body_text": "file contents here",
      "body_base64": null,
      "body_size": 19
    }
  ]
}
```

For each part:
- `name`: The form field name (from `Content-Disposition: form-data; name="..."`)
- `filename`: The filename if present, `null` if not a file upload, `""` if empty filename
- `content_type`: The `Content-Type` header value for this part, or `null` if not specified
- `body_text`: The body as a UTF-8 string (if decodable), otherwise `null`
- `body_base64`: The body as base64 (if `body_text` is `null` due to binary content)
- `body_size`: The size of the body in bytes

### Response Format for Parse Errors

```json
{
  "valid": false,
  "error_type": "boundary_mismatch",
  "error_message": "Human-readable error description"
}
```

Common `error_type` values:
- `boundary_mismatch` - Boundary in body doesn't match Content-Type header
- `missing_terminator` - Missing final `--` after last boundary
- `missing_content_disposition` - Part missing required Content-Disposition header
- `invalid_header` - Malformed header in a part
- `parse_error` - Generic parse failure

## Test Runner Logic

For each test directory in `tests/`:

### 1. Load Test Data

```
test_dir/
├── test.json      # Test metadata and expected results
├── headers.json   # HTTP headers (Content-Type with boundary)
└── input.raw      # Raw HTTP request body (binary)
```

### 2. Send Request

- Read `input.raw` as raw bytes (preserve exact binary content)
- Read `headers.json` and use its `content-type` value as the Content-Type header
- POST the raw bytes to your server's parse endpoint

### 3. Compare Results

Check `test.json`'s `expected` field:

**If `expected.valid` is `true`:**
- Verify server returned `valid: true`
- Compare each part in `expected.parts` with the server response
- Check: `name`, `filename`, `content_type`, `body_size`
- For body content, compare either `body_text` or `body_base64` (whichever is specified)

**If `expected.valid` is `false`:**
- The input is malformed; verify server returned `valid: false`
- Optionally check `error_type` matches `expected.error_type`
- Note: Some parsers are more lenient and may successfully parse malformed input

## Handling Edge Cases

### Binary Content

Some tests use `body_base64` instead of `body_text` for binary content. Your server should:
- Try to decode body as UTF-8
- If successful, return `body_text` with the string value
- If decoding fails, return `body_base64` with base64-encoded bytes

### Optional Tests

Tests are classified as **required** or **optional** via the `tags` array in `test.json`:

```json
{
  "tags": ["required", "parsing"]   // Must pass for conformance
}
```

```json
{
  "tags": ["optional", "parsing"]   // Nice to have, not required
}
```

**Optional tests include:**

| Feature | Tags | Description |
|---------|------|-------------|
| RFC 5987 filename* | `optional` | Extended parameter encoding for non-ASCII filenames |
| Lenient line endings | `optional`, `lenient` | LF-only instead of CRLF |
| Header folding | `optional`, `lenient` | Obsolete HTTP/1.x header continuation |
| Separate charset field | `optional` | Extracting charset from Content-Type |
| Preamble handling | `optional` | Ignoring content before first boundary |
| Whitespace in headers | `optional` | Extra whitespace around parameter values |

**Handling optional tests in your runner:**

```python
# Check if test is optional
tags = test_json.get("tags", [])
is_optional = "optional" in tags

# If test fails but is optional, skip instead of fail
if test_failed and is_optional:
    skip(f"Optional feature not supported: {test_id}")
```

### Parser Options

Some tests specify `parser_options` indicating they require specific parser configurations:

```json
{
  "parser_options": {
    "strict_line_endings": false
  }
}
```

If your parser doesn't support the required option, skip the test:

```python
parser_options = test_json.get("parser_options", {})
if parser_options.get("strict_line_endings") == False:
    if not parser_supports_lenient_line_endings:
        skip("Parser requires CRLF line endings")
```

### Empty vs Null Filenames

Distinguish between:
- No filename parameter: `filename` should be `null`
- Empty filename (`filename=""`): `filename` should be `""`

### Multiple Values with Same Name

Some tests have multiple parts with the same field name (e.g., file arrays). Ensure your server returns all parts, not just the first or last.

## Running on a Free Port

To avoid port conflicts, bind your server to port 0 and let the OS assign a free port, or use a port-finding utility. Start the server before running tests and shut it down after.

## Example Test Flow (Pseudocode)

```
server = start_server(port=find_free_port())
base_url = f"http://127.0.0.1:{server.port}"

for test_dir in glob("tests/*/*/"):
    test_json = parse_json(test_dir / "test.json")
    headers = parse_json(test_dir / "headers.json")
    body = read_bytes(test_dir / "input.raw")

    response = http_post(
        url=f"{base_url}/parse",
        body=body,
        headers={"Content-Type": headers["content-type"]}
    )
    result = parse_json(response.body)

    expected = test_json["expected"]

    if expected["valid"]:
        assert result["valid"] == true
        assert len(result["parts"]) == len(expected["parts"])
        for actual, exp in zip(result["parts"], expected["parts"]):
            assert actual["name"] == exp["name"]
            assert actual["filename"] == exp.get("filename")
            # ... compare other fields
    else:
        # Malformed input - parser may reject or be lenient
        if result["valid"]:
            skip("Parser is lenient with this malformed input")
        else:
            assert result["error_type"] == expected.get("error_type")

server.stop()
```

## Writing a Conformance Report

Each implementation should include a `REPORT.md` documenting test results. This helps users understand what works, what doesn't, and why. See `starlette/REPORT.md` for an example.

Your report should include:

### Summary Table

```markdown
| Result | Count | Percentage |
|--------|-------|------------|
| Passed | 46 | 79% |
| Skipped | 9 | 16% |
| Failed | 3 | 5% |
| **Total** | **58** | 100% |
```

### Passed Tests

List categories and counts showing what works correctly.

### Skipped Tests (Optional Features)

For each skipped test, explain:
- Test ID and feature name
- Why it was skipped (optional feature, parser limitation, etc.)

### Failed Tests (Conformance Issues)

For each failure, document:
- **Test ID** and what it tests
- **Expected behavior** - What the spec/test requires
- **Actual behavior** - What your implementation does
- **Impact** - Is this a critical failure or minor metadata issue?
- **Root cause** - If known, what causes this behavior
- **Workaround** - If available, how users can work around the issue

### Recommendations

Suggest improvements or bug reports that could improve conformance.

## See Also

- `starlette/` - Python/Starlette reference implementation
- `starlette/REPORT.md` - Example conformance report
- `../schema/` - JSON schemas for test file validation
- `../tests/` - The actual test cases
