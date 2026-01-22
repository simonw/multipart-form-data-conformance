#!/usr/bin/env python3
"""
Generate raw multipart/form-data files for testing.

Usage:
    ./generate-raw.py --boundary "----TestBoundary" \
        --field name=username value="john_doe" \
        --file name=doc filename="test.pdf" content=@file.pdf \
        --output tests/basic/001/input.raw

    ./generate-raw.py --boundary "----TestBoundary" \
        --field name=username value="john_doe" \
        --dump  # Show hex dump instead of writing
"""

import argparse
import base64
import sys
from pathlib import Path
from typing import List, Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from lib.multipart_utils import validate_boundary


CRLF = b"\r\n"
LF = b"\n"


class MultipartBuilder:
    """Build multipart/form-data messages byte-by-byte."""

    def __init__(
        self,
        boundary: str,
        line_ending: bytes = CRLF,
        include_final_terminator: bool = True,
        preamble: Optional[bytes] = None,
        epilogue: Optional[bytes] = None,
    ):
        self.boundary = boundary
        self.line_ending = line_ending
        self.include_final_terminator = include_final_terminator
        self.preamble = preamble
        self.epilogue = epilogue
        self.parts: List[bytes] = []

    def add_field(
        self,
        name: str,
        value: bytes,
        content_type: Optional[str] = None,
        extra_headers: Optional[dict] = None,
    ):
        """Add a text field."""
        headers = self._build_headers(name, None, content_type, extra_headers)
        self.parts.append(headers + value)

    def add_file(
        self,
        name: str,
        filename: str,
        content: bytes,
        content_type: Optional[str] = None,
        filename_star: Optional[str] = None,
        extra_headers: Optional[dict] = None,
    ):
        """Add a file field."""
        headers = self._build_headers(name, filename, content_type, extra_headers, filename_star)
        self.parts.append(headers + content)

    def add_raw_part(self, raw_bytes: bytes):
        """Add a completely raw part (for malformed tests)."""
        self.parts.append(raw_bytes)

    def _build_headers(
        self,
        name: str,
        filename: Optional[str],
        content_type: Optional[str],
        extra_headers: Optional[dict],
        filename_star: Optional[str] = None,
    ) -> bytes:
        """Build part headers."""
        # Content-Disposition
        cd = f'Content-Disposition: form-data; name="{name}"'
        if filename is not None:
            # Escape quotes and backslashes in filename
            escaped_filename = filename.replace('\\', '\\\\').replace('"', '\\"')
            cd += f'; filename="{escaped_filename}"'
        if filename_star is not None:
            cd += f"; filename*={filename_star}"

        lines = [cd.encode('utf-8')]

        # Content-Type
        if content_type:
            lines.append(f"Content-Type: {content_type}".encode('utf-8'))

        # Extra headers
        if extra_headers:
            for key, value in extra_headers.items():
                lines.append(f"{key}: {value}".encode('utf-8'))

        # Join headers and add blank line
        header_block = self.line_ending.join(lines) + self.line_ending + self.line_ending
        return header_block

    def build(self) -> bytes:
        """Build the complete multipart message."""
        result = b""

        # Preamble (before first boundary)
        if self.preamble:
            result += self.preamble

        boundary_bytes = f"--{self.boundary}".encode('utf-8')
        final_boundary_bytes = f"--{self.boundary}--".encode('utf-8')

        # Each part
        for i, part in enumerate(self.parts):
            result += boundary_bytes + self.line_ending
            result += part
            # Add CRLF after part content (before next boundary)
            if i < len(self.parts) - 1 or self.include_final_terminator:
                result += self.line_ending

        # Final boundary
        if self.include_final_terminator:
            result += final_boundary_bytes + self.line_ending

        # Epilogue (after final boundary)
        if self.epilogue:
            result += self.epilogue

        return result


def hex_dump(data: bytes, width: int = 16) -> str:
    """Generate a hex dump of binary data."""
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        hex_part = " ".join(f"{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:08x}  {hex_part:<{width * 3}}  |{ascii_part}|")
    return "\n".join(lines)


def parse_field_args(args: List[str]) -> dict:
    """Parse field arguments like name=value."""
    result = {}
    for arg in args:
        if '=' in arg:
            key, value = arg.split('=', 1)
            result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Generate raw multipart/form-data files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Simple text field
  %(prog)s --boundary "----Test" --field name=user value="john" -o input.raw

  # File upload
  %(prog)s --boundary "----Test" --file name=doc filename="test.pdf" content=@test.pdf -o input.raw

  # Multiple fields with dump
  %(prog)s --boundary "----Test" --field name=a value=1 --field name=b value=2 --dump

  # LF line endings (non-compliant)
  %(prog)s --boundary "----Test" --field name=x value=y --line-ending lf -o input.raw

  # Malformed: no final terminator
  %(prog)s --boundary "----Test" --field name=x value=y --no-terminator -o input.raw
        """,
    )

    parser.add_argument("--boundary", "-b", required=True, help="Boundary string")
    parser.add_argument(
        "--field",
        action="append",
        nargs="+",
        metavar="KEY=VALUE",
        help="Add text field (name=X value=Y [content-type=Z])",
    )
    parser.add_argument(
        "--file",
        action="append",
        nargs="+",
        metavar="KEY=VALUE",
        help="Add file field (name=X filename=Y content=@path|content-base64=Z [content-type=W])",
    )
    parser.add_argument(
        "--raw-part",
        action="append",
        metavar="BASE64",
        help="Add raw part bytes (base64 encoded)",
    )
    parser.add_argument(
        "--line-ending",
        choices=["crlf", "lf"],
        default="crlf",
        help="Line ending style (default: crlf)",
    )
    parser.add_argument(
        "--no-terminator",
        action="store_true",
        help="Omit final boundary terminator (for malformed tests)",
    )
    parser.add_argument(
        "--preamble",
        help="Content before first boundary",
    )
    parser.add_argument(
        "--epilogue",
        help="Content after final boundary",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--dump",
        action="store_true",
        help="Show hex dump instead of writing binary",
    )
    parser.add_argument(
        "--headers-output",
        help="Also write headers.json file",
    )
    parser.add_argument(
        "--validate-boundary",
        action="store_true",
        help="Validate boundary per RFC 2046",
    )

    args = parser.parse_args()

    # Validate boundary if requested
    if args.validate_boundary:
        valid, error = validate_boundary(args.boundary)
        if not valid:
            print(f"Invalid boundary: {error}", file=sys.stderr)
            sys.exit(1)

    # Build message
    line_ending = CRLF if args.line_ending == "crlf" else LF
    preamble = args.preamble.encode('utf-8') if args.preamble else None
    epilogue = args.epilogue.encode('utf-8') if args.epilogue else None

    builder = MultipartBuilder(
        boundary=args.boundary,
        line_ending=line_ending,
        include_final_terminator=not args.no_terminator,
        preamble=preamble,
        epilogue=epilogue,
    )

    # Add fields
    if args.field:
        for field_args in args.field:
            params = parse_field_args(field_args)
            name = params.get("name", "")
            value = params.get("value", "").encode('utf-8')
            content_type = params.get("content-type")
            builder.add_field(name, value, content_type)

    # Add files
    if args.file:
        for file_args in args.file:
            params = parse_field_args(file_args)
            name = params.get("name", "")
            filename = params.get("filename", "")
            content_type = params.get("content-type")
            filename_star = params.get("filename*")

            # Get content
            if "content" in params:
                content_spec = params["content"]
                if content_spec.startswith("@"):
                    # Read from file
                    with open(content_spec[1:], "rb") as f:
                        content = f.read()
                else:
                    content = content_spec.encode('utf-8')
            elif "content-base64" in params:
                content = base64.b64decode(params["content-base64"])
            else:
                content = b""

            builder.add_file(name, filename, content, content_type, filename_star)

    # Add raw parts
    if args.raw_part:
        for raw_b64 in args.raw_part:
            builder.add_raw_part(base64.b64decode(raw_b64))

    # Build the message
    result = builder.build()

    # Output
    if args.dump:
        print(hex_dump(result))
        print(f"\nTotal: {len(result)} bytes")
    elif args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "wb") as f:
            f.write(result)
        print(f"Wrote {len(result)} bytes to {args.output}")
    else:
        sys.stdout.buffer.write(result)

    # Write headers.json if requested
    if args.headers_output:
        import json
        headers = {
            "content-type": f"multipart/form-data; boundary={args.boundary}"
        }
        Path(args.headers_output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.headers_output, "w") as f:
            json.dump(headers, f, indent=2)
            f.write("\n")
        print(f"Wrote headers to {args.headers_output}")


if __name__ == "__main__":
    main()
