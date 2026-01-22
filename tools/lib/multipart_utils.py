"""
Shared utilities for multipart form-data conformance suite tools.
"""

import re
import hashlib
import json
import base64
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field


# RFC 2046 boundary characters: DIGIT / ALPHA / "'" / "(" / ")" / "+" / "_" / "," / "-" / "." / "/" / ":" / "=" / "?"
# Plus space (but not as last char). Max 70 chars.
BOUNDARY_CHAR_PATTERN = re.compile(r"^[0-9A-Za-z'()+_,\-./:=? ]{1,70}$")

# Content-Type header boundary extraction patterns
BOUNDARY_QUOTED_PATTERN = re.compile(r'boundary="([^"]+)"', re.IGNORECASE)
BOUNDARY_UNQUOTED_PATTERN = re.compile(r'boundary=\s*([^\s;]+)', re.IGNORECASE)


@dataclass
class Part:
    """Represents a single part in a multipart message."""
    name: str
    filename: Optional[str] = None
    filename_star: Optional[str] = None
    content_type: Optional[str] = None
    charset: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    @property
    def body_text(self) -> Optional[str]:
        """Return body as UTF-8 text, or None if not valid UTF-8."""
        try:
            return self.body.decode('utf-8')
        except UnicodeDecodeError:
            return None

    @property
    def body_base64(self) -> str:
        """Return body as base64 encoded string."""
        return base64.b64encode(self.body).decode('ascii')

    @property
    def body_sha256(self) -> str:
        """Return SHA-256 hash of body as lowercase hex."""
        return hashlib.sha256(self.body).hexdigest()

    @property
    def body_size(self) -> int:
        """Return size of body in bytes."""
        return len(self.body)

    def to_dict(self, include_body_text: bool = True) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "name": self.name,
            "filename": self.filename,
            "content_type": self.content_type,
        }

        if self.filename_star:
            result["filename_star"] = self.filename_star
        if self.charset:
            result["charset"] = self.charset
        if self.headers:
            result["headers"] = self.headers

        # Include body representation
        if include_body_text and self.body_text is not None:
            result["body_text"] = self.body_text
        else:
            result["body_base64"] = self.body_base64

        result["body_size"] = self.body_size

        return result


@dataclass
class ParseResult:
    """Result of parsing a multipart message."""
    valid: bool
    parts: List[Part] = field(default_factory=list)
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {"valid": self.valid}
        if self.error_type:
            result["error_type"] = self.error_type
        if self.error_message:
            result["error_message"] = self.error_message
        if self.parts:
            result["parts"] = [p.to_dict() for p in self.parts]
        return result


def parse_boundary(content_type: str) -> Optional[str]:
    """
    Extract boundary from Content-Type header.

    Handles both quoted and unquoted boundary values:
    - boundary="----WebKitFormBoundary..."
    - boundary=----WebKitFormBoundary...

    Returns None if no boundary found.
    """
    if not content_type:
        return None

    # Try quoted first
    match = BOUNDARY_QUOTED_PATTERN.search(content_type)
    if match:
        return match.group(1)

    # Try unquoted
    match = BOUNDARY_UNQUOTED_PATTERN.search(content_type)
    if match:
        return match.group(1).rstrip()

    return None


def validate_boundary(boundary: str) -> Tuple[bool, Optional[str]]:
    """
    Validate boundary string per RFC 2046.

    Returns (is_valid, error_message).
    """
    if not boundary:
        return False, "Boundary cannot be empty"

    if len(boundary) > 70:
        return False, f"Boundary exceeds maximum length of 70 (got {len(boundary)})"

    if boundary.endswith(' '):
        return False, "Boundary cannot end with a space"

    # Check all characters are valid
    if not BOUNDARY_CHAR_PATTERN.match(boundary):
        invalid_chars = set(c for c in boundary if not re.match(r"[0-9A-Za-z'()+_,\-./:=? ]", c))
        return False, f"Boundary contains invalid characters: {invalid_chars}"

    return True, None


def read_test_case(test_dir: Path) -> Dict[str, Any]:
    """
    Load and return a test case from a directory.

    Returns dict with 'test', 'headers', and 'body' keys.
    """
    test_json = test_dir / "test.json"
    headers_json = test_dir / "headers.json"
    input_raw = test_dir / "input.raw"

    result = {}

    if test_json.exists():
        with open(test_json, 'r', encoding='utf-8') as f:
            result['test'] = json.load(f)

    if headers_json.exists():
        with open(headers_json, 'r', encoding='utf-8') as f:
            result['headers'] = json.load(f)

    if input_raw.exists():
        with open(input_raw, 'rb') as f:
            result['body'] = f.read()

    return result


def hash_file(path: Path) -> str:
    """Calculate SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def compare_parts(expected: List[Dict], actual: List[Part]) -> List[str]:
    """
    Compare expected parts with actual parsed parts.

    Returns list of differences (empty if match).
    """
    differences = []

    if len(expected) != len(actual):
        differences.append(f"Part count mismatch: expected {len(expected)}, got {len(actual)}")
        return differences

    for i, (exp, act) in enumerate(zip(expected, actual)):
        prefix = f"Part {i}"

        # Compare name
        if exp.get('name') != act.name:
            differences.append(f"{prefix}: name mismatch - expected {exp.get('name')!r}, got {act.name!r}")

        # Compare filename
        exp_filename = exp.get('filename')
        if exp_filename != act.filename:
            differences.append(f"{prefix}: filename mismatch - expected {exp_filename!r}, got {act.filename!r}")

        # Compare content_type
        exp_ct = exp.get('content_type')
        if exp_ct != act.content_type:
            differences.append(f"{prefix}: content_type mismatch - expected {exp_ct!r}, got {act.content_type!r}")

        # Compare body
        if 'body_text' in exp and exp['body_text'] is not None:
            if exp['body_text'] != act.body_text:
                differences.append(f"{prefix}: body_text mismatch - expected {exp['body_text']!r}, got {act.body_text!r}")
        elif 'body_base64' in exp and exp['body_base64'] is not None:
            if exp['body_base64'] != act.body_base64:
                differences.append(f"{prefix}: body_base64 mismatch")
        elif 'body_sha256' in exp and exp['body_sha256'] is not None:
            if exp['body_sha256'] != act.body_sha256:
                differences.append(f"{prefix}: body_sha256 mismatch - expected {exp['body_sha256']}, got {act.body_sha256}")

        # Compare body_size if specified
        if 'body_size' in exp:
            if exp['body_size'] != act.body_size:
                differences.append(f"{prefix}: body_size mismatch - expected {exp['body_size']}, got {act.body_size}")

    return differences


def parse_content_disposition(header_value: str) -> Dict[str, Optional[str]]:
    """
    Parse Content-Disposition header value.

    Returns dict with 'type', 'name', 'filename', 'filename_star' keys.
    """
    result = {
        'type': None,
        'name': None,
        'filename': None,
        'filename_star': None,
    }

    if not header_value:
        return result

    # Tokenize carefully to handle quoted strings with semicolons
    tokens = _tokenize_header_params(header_value)

    # First token is the disposition type
    if tokens:
        result['type'] = tokens[0].strip().lower()

    # Parse remaining tokens as key=value parameters
    for token in tokens[1:]:
        token = token.strip()
        if '=' not in token:
            continue

        key, value = token.split('=', 1)
        key = key.strip().lower()
        value = value.strip()

        # Remove quotes if present
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
            # Handle escaped quotes
            value = value.replace('\\"', '"')
            # Handle escaped backslashes
            value = value.replace('\\\\', '\\')

        if key == 'name':
            result['name'] = value
        elif key == 'filename':
            result['filename'] = value
        elif key == 'filename*':
            # RFC 5987 encoded filename
            result['filename_star'] = decode_rfc5987(value)

    return result


def _tokenize_header_params(header_value: str) -> List[str]:
    """
    Split header value into tokens, respecting quoted strings.

    Semicolons inside quoted strings are not treated as delimiters.
    """
    tokens = []
    current = []
    in_quotes = False
    escape_next = False

    for char in header_value:
        if escape_next:
            current.append(char)
            escape_next = False
        elif char == '\\' and in_quotes:
            current.append(char)
            escape_next = True
        elif char == '"':
            current.append(char)
            in_quotes = not in_quotes
        elif char == ';' and not in_quotes:
            tokens.append(''.join(current))
            current = []
        else:
            current.append(char)

    if current:
        tokens.append(''.join(current))

    return tokens


def decode_rfc5987(value: str) -> str:
    """
    Decode RFC 5987 encoded value.

    Format: charset'language'encoded_value
    Example: utf-8''%E6%96%87%E6%A1%A3.pdf
    """
    if "'" not in value:
        return value

    parts = value.split("'", 2)
    if len(parts) != 3:
        return value

    charset, _language, encoded = parts

    # Percent-decode
    try:
        from urllib.parse import unquote
        decoded = unquote(encoded, encoding=charset.lower() or 'utf-8')
        return decoded
    except Exception:
        return value


def encode_rfc5987(value: str, charset: str = 'utf-8') -> str:
    """
    Encode a value per RFC 5987.

    Returns format: charset''encoded_value
    """
    from urllib.parse import quote
    encoded = quote(value, safe='')
    return f"{charset}''{encoded}"
