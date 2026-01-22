## Design for Multipart Form-Data Conformance Suite

### Goals

1. **Language-independent** - raw binary test files with JSON metadata
2. **Bidirectional** - test both parsing and generation
3. **Comprehensive** - cover spec requirements, edge cases, and browser variations
4. **Self-describing** - each test case explains what it's testing

### Proposed Directory Structure

```
multipart-conformance/
├── README.md
├── schema/
│   ├── test-case.schema.json      # JSON Schema for test definitions
│   └── parsed-result.schema.json  # Schema for expected parse results
├── tests/
│   ├── basic/
│   │   ├── 001-single-text-field/
│   │   │   ├── test.json          # Metadata and expected results
│   │   │   ├── input.raw          # Raw HTTP body bytes
│   │   │   └── headers.json       # HTTP headers (Content-Type with boundary)
│   │   ├── 002-single-file/
│   │   ├── 003-multiple-fields/
│   │   └── ...
│   ├── filenames/
│   │   ├── 020-ascii-filename/
│   │   ├── 021-unicode-filename-utf8/
│   │   ├── 022-filename-star-encoding/
│   │   ├── 023-filename-with-quotes/
│   │   ├── 024-filename-with-backslash/
│   │   └── ...
│   ├── boundaries/
│   │   ├── 040-simple-boundary/
│   │   ├── 041-boundary-with-hyphens/
│   │   ├── 042-long-boundary/
│   │   ├── 043-boundary-like-content/
│   │   └── ...
│   ├── line-endings/
│   │   ├── 060-crlf-standard/
│   │   ├── 061-lf-only-lenient/
│   │   ├── 062-mixed-endings/
│   │   └── ...
│   ├── content-types/
│   │   ├── 080-explicit-content-type/
│   │   ├── 081-missing-content-type/
│   │   ├── 082-content-type-with-charset/
│   │   └── ...
│   ├── edge-cases/
│   │   ├── 100-empty-file/
│   │   ├── 101-empty-field-value/
│   │   ├── 102-binary-content/
│   │   ├── 103-large-file-reference/
│   │   ├── 104-duplicate-field-names/
│   │   ├── 105-whitespace-in-headers/
│   │   └── ...
│   ├── malformed/
│   │   ├── 200-missing-final-boundary/
│   │   ├── 201-wrong-boundary/
│   │   ├── 202-truncated-body/
│   │   ├── 203-missing-content-disposition/
│   │   ├── 204-invalid-header-syntax/
│   │   └── ...
│   └── browser-variations/
│       ├── 300-chrome-style-boundary/
│       ├── 301-firefox-style-boundary/
│       ├── 302-safari-empty-filename/
│       └── ...
└── tools/
    ├── validate-suite.py          # Validates test suite integrity
    ├── generate-raw.py            # Helper to create .raw files
    └── run-reference.py           # Reference implementation
```

### Test Case Schema (`test.json`)

```json
{
  "$schema": "../../../schema/test-case.schema.json",
  "id": "001-single-text-field",
  "name": "Single text field",
  "description": "Basic test with one text form field",
  "spec_references": [
    "RFC 7578 Section 4.2",
    "HTML Living Standard Section 4.10.21.8"
  ],
  "category": "basic",
  "tags": ["required", "parsing", "generation"],
  
  "input": {
    "headers_file": "headers.json",
    "body_file": "input.raw",
    "body_encoding": "binary"
  },
  
  "expected": {
    "valid": true,
    "parts": [
      {
        "name": "username",
        "filename": null,
        "content_type": null,
        "headers": {
          "content-disposition": "form-data; name=\"username\""
        },
        "body_text": "john_doe",
        "body_base64": null,
        "body_file": null
      }
    ]
  },
  
  "parser_options": {
    "strict_line_endings": true,
    "max_header_size": 8192
  },
  
  "notes": "Most basic possible multipart request"
}
```

### Headers File (`headers.json`)

```json
{
  "content-type": "multipart/form-data; boundary=----TestBoundary123"
}
```

### Raw Body File (`input.raw`)

Binary file containing exact bytes:
```
------TestBoundary123\r\n
Content-Disposition: form-data; name="username"\r\n
\r\n
john_doe\r\n
------TestBoundary123--\r\n
```

### Comprehensive Test Categories

#### 1. Basic (Required Conformance)
| ID | Test | Purpose |
|----|------|---------|
| 001 | Single text field | Minimal valid request |
| 002 | Single file upload | Basic file with filename |
| 003 | Multiple text fields | Multiple parts same request |
| 004 | Mixed fields and files | Combined form data |
| 005 | Multiple files same name | Array-style file inputs |

#### 2. Filename Handling
| ID | Test | Purpose |
|----|------|---------|
| 020 | ASCII filename | Simple case |
| 021 | Unicode UTF-8 filename | `文档.pdf` in raw UTF-8 |
| 022 | RFC 5987 filename* | Encoded international name |
| 023 | Both filename and filename* | Fallback pattern |
| 024 | Filename with spaces | `"my document.pdf"` |
| 025 | Filename with quotes | Escaped quotes `\"` |
| 026 | Filename with backslash | Windows paths |
| 027 | Filename with semicolon | Delimiter edge case |
| 028 | Empty filename | `filename=""` |
| 029 | Filename path traversal | `../../../etc/passwd` |

#### 3. Boundary Handling
| ID | Test | Purpose |
|----|------|---------|
| 040 | Simple boundary | Alphanumeric only |
| 041 | Boundary with hyphens | Chrome/Firefox style |
| 042 | Maximum length boundary (70) | Spec limit |
| 043 | Boundary appears in content | Must not match |
| 044 | Boundary with special chars | Allowed chars per RFC |
| 045 | Quoted boundary in header | `boundary="quoted"` |
| 046 | Whitespace around boundary | Trimming behavior |

#### 4. Line Endings
| ID | Test | Purpose |
|----|------|---------|
| 060 | CRLF throughout | Spec-compliant |
| 061 | LF only (lenient) | Common non-compliant |
| 062 | CRLF in headers, LF in body | Mixed |
| 063 | Bare CR handling | Edge case |
| 064 | CRLF in field value | Preserved in content |

#### 5. Headers
| ID | Test | Purpose |
|----|------|---------|
| 080 | Explicit Content-Type | File with MIME type |
| 081 | Missing Content-Type | Default behavior |
| 082 | Content-Type with charset | `text/plain; charset=utf-8` |
| 083 | Additional headers | Content-Transfer-Encoding |
| 084 | Header case insensitivity | `CONTENT-DISPOSITION` |
| 085 | Header whitespace folding | Obsolete but seen |
| 086 | Header parameter ordering | name vs filename order |
| 087 | Unquoted parameter values | `name=field` vs `name="field"` |

#### 6. Content Handling
| ID | Test | Purpose |
|----|------|---------|
| 100 | Empty file (0 bytes) | Valid empty upload |
| 101 | Empty field value | Empty string |
| 102 | Binary content | Null bytes, all byte values |
| 103 | Content matching boundary prefix | `----` in content |
| 104 | Very large content | Reference to external file |
| 105 | UTF-8 BOM in content | Byte order mark |
| 106 | Null bytes in text field | Binary in "text" |

#### 7. Malformed (Error Handling)
| ID | Test | Purpose |
|----|------|---------|
| 200 | Missing final `--` | No terminator |
| 201 | Wrong boundary in body | Mismatch |
| 202 | Truncated mid-part | Incomplete |
| 203 | Missing Content-Disposition | Required header absent |
| 204 | Invalid Content-Disposition | Unparseable |
| 205 | No blank line after headers | Missing separator |
| 206 | Preamble before first boundary | Content before data |
| 207 | Epilogue after final boundary | Content after end |
| 208 | Duplicate headers | Two Content-Dispositions |
| 209 | Boundary without leading CRLF | Missing newline |
| 210 | Control characters in name | `name="field\x00"` |

#### 8. Browser Variations
| ID | Test | Purpose |
|----|------|---------|
| 300 | Chrome WebKit boundary | Real browser output |
| 301 | Firefox boundary style | Real browser output |
| 302 | Safari boundary style | Real browser output |
| 303 | Chrome empty file | How Chrome sends no file |
| 304 | Firefox empty file | How Firefox sends no file |

### Expected Results Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "valid": {
      "type": "boolean",
      "description": "Whether this input should parse successfully"
    },
    "error_type": {
      "type": "string",
      "enum": [
        "boundary_mismatch",
        "missing_terminator", 
        "invalid_header",
        "truncated",
        "missing_content_disposition"
      ],
      "description": "Expected error for invalid inputs"
    },
    "parts": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": { "type": "string" },
          "filename": { "type": ["string", "null"] },
          "filename_star": { 
            "type": ["string", "null"],
            "description": "RFC 5987 encoded filename if present"
          },
          "content_type": { "type": ["string", "null"] },
          "charset": { "type": ["string", "null"] },
          "headers": {
            "type": "object",
            "additionalProperties": { "type": "string" }
          },
          "body_text": {
            "type": ["string", "null"],
            "description": "Expected body as UTF-8 string"
          },
          "body_base64": {
            "type": ["string", "null"],
            "description": "Expected body as base64 for binary"
          },
          "body_sha256": {
            "type": ["string", "null"],
            "description": "Hash for large files"
          },
          "body_size": {
            "type": "integer",
            "description": "Expected body size in bytes"
          }
        },
        "required": ["name"]
      }
    }
  },
  "required": ["valid"]
}
```

### Generation Tests

For testing generators (not just parsers), include reverse tests:

```json
{
  "id": "gen-001-single-field",
  "type": "generation",
  "input_parts": [
    {
      "name": "username",
      "body_text": "john_doe"
    }
  ],
  "constraints": {
    "boundary_pattern": "^-+[A-Za-z0-9]+$",
    "line_endings": "CRLF",
    "must_have_final_terminator": true
  },
  "validation": "round_trip"
}
```

### Tooling

**`validate-suite.py`** - Ensures test suite integrity:
- All referenced files exist
- JSON validates against schemas
- Raw files match described structure
- No duplicate test IDs

**`generate-raw.py`** - Helper for creating test files:
```bash
./generate-raw.py --boundary "----Test" \
  --field name=username value="john_doe" \
  --file name=doc filename="test.pdf" content=@file.pdf \
  --output tests/basic/001/input.raw
```

**`run-reference.py`** - Reference parser to validate expected results

### Implementation Notes

1. **Binary Exactness**: `.raw` files must be byte-for-byte exact; use hex editors or generation tools
2. **Large Files**: For tests > 1MB, use SHA-256 hashes instead of inline content
3. **Versioning**: Include suite version in root `manifest.json`
4. **Licensing**: CC0 or MIT for maximum usability
5. **CI Integration**: Provide GitHub Actions workflow for running against implementations

Would you like me to create the actual test files for some of these cases, or flesh out the JSON schemas further?
