#!/usr/bin/env python3
"""
Reference multipart/form-data parser and test runner.

This is a reference implementation for validating the test suite's expected results.
It is NOT meant to be a production parser - use proper multipart libraries for that.

Usage:
    ./run-reference.py --test tests/basic/001-single-text-field
    ./run-reference.py --category basic
    ./run-reference.py --all
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from lib.multipart_utils import (
    Part,
    ParseResult,
    parse_boundary,
    parse_content_disposition,
    compare_parts,
)


CRLF = b"\r\n"
LF = b"\n"


class MultipartParser:
    """
    Reference implementation of multipart/form-data parser.

    This parser is intentionally simple and follows the specs closely.
    It can operate in strict mode (CRLF only) or lenient mode (LF accepted).
    """

    def __init__(self, strict: bool = True):
        self.strict = strict

    def parse(self, body: bytes, boundary: str) -> ParseResult:
        """Parse a multipart/form-data body."""
        if not boundary:
            return ParseResult(
                valid=False,
                error_type="invalid_boundary",
                error_message="No boundary provided",
            )

        # Boundary markers
        delimiter = f"--{boundary}".encode("utf-8")
        close_delimiter = f"--{boundary}--".encode("utf-8")

        # Find the first boundary
        first_boundary_pos = body.find(delimiter)
        if first_boundary_pos == -1:
            return ParseResult(
                valid=False,
                error_type="boundary_mismatch",
                error_message=f"Boundary '{boundary}' not found in body",
            )

        # Content before first boundary is the preamble (ignored)
        pos = first_boundary_pos + len(delimiter)

        # Skip line ending after first boundary
        pos = self._skip_line_ending(body, pos)
        if pos is None:
            return ParseResult(
                valid=False,
                error_type="truncated",
                error_message="Unexpected end after first boundary",
            )

        parts: List[Part] = []

        while pos < len(body):
            # Parse headers for this part
            headers, header_end = self._parse_headers(body, pos)
            if headers is None:
                return ParseResult(
                    valid=False,
                    error_type="invalid_header",
                    error_message=f"Failed to parse headers at position {pos}",
                )

            pos = header_end

            # Check for Content-Disposition header
            content_disposition = None
            for key, value in headers.items():
                if key.lower() == "content-disposition":
                    content_disposition = value
                    break

            if content_disposition is None:
                return ParseResult(
                    valid=False,
                    error_type="missing_content_disposition",
                    error_message="Missing Content-Disposition header",
                )

            # Parse Content-Disposition
            cd_params = parse_content_disposition(content_disposition)
            if cd_params["name"] is None:
                return ParseResult(
                    valid=False,
                    error_type="missing_name",
                    error_message="Missing name parameter in Content-Disposition",
                )

            # Find the end of this part (next boundary)
            body_end = self._find_next_boundary(body, pos, delimiter)
            if body_end is None:
                return ParseResult(
                    valid=False,
                    error_type="truncated",
                    error_message="Part body not terminated by boundary",
                )

            # Extract body (excluding trailing CRLF before boundary)
            part_body = body[pos:body_end]

            # Get Content-Type if present
            content_type = None
            charset = None
            for key, value in headers.items():
                if key.lower() == "content-type":
                    content_type = value.split(";")[0].strip()
                    # Extract charset if present
                    charset_match = re.search(r"charset=([^\s;]+)", value, re.IGNORECASE)
                    if charset_match:
                        charset = charset_match.group(1).strip('"')
                    break

            # Create Part object
            part = Part(
                name=cd_params["name"],
                filename=cd_params["filename"],
                filename_star=cd_params.get("filename_star"),
                content_type=content_type,
                charset=charset,
                headers={k.lower(): v for k, v in headers.items()},
                body=part_body,
            )
            parts.append(part)

            # Move to after the boundary
            pos = body_end

            # Skip the CRLF before boundary
            if body[pos:pos + 2] == CRLF:
                pos += 2
            elif body[pos:pos + 1] == LF and not self.strict:
                pos += 1

            # Skip the boundary itself
            if body[pos:].startswith(close_delimiter):
                # Final boundary - we're done
                break
            elif body[pos:].startswith(delimiter):
                pos += len(delimiter)
                # Skip line ending after boundary
                new_pos = self._skip_line_ending(body, pos)
                if new_pos is None:
                    break
                pos = new_pos
            else:
                return ParseResult(
                    valid=False,
                    error_type="boundary_mismatch",
                    error_message="Expected boundary not found",
                )

        # Check for final terminator
        if close_delimiter not in body:
            return ParseResult(
                valid=False,
                error_type="missing_terminator",
                error_message="Missing final boundary terminator",
                parts=parts,  # Still return partial results
            )

        return ParseResult(valid=True, parts=parts)

    def _skip_line_ending(self, body: bytes, pos: int) -> Optional[int]:
        """Skip CRLF or LF (if lenient). Returns new position or None."""
        if pos >= len(body):
            return None

        if body[pos:pos + 2] == CRLF:
            return pos + 2
        elif body[pos:pos + 1] == LF and not self.strict:
            return pos + 1
        elif body[pos:pos + 1] == LF and self.strict:
            return None  # Invalid in strict mode

        return pos  # No line ending to skip

    def _parse_headers(self, body: bytes, pos: int) -> Tuple[Optional[Dict[str, str]], int]:
        """Parse MIME headers starting at pos. Returns (headers, end_position)."""
        headers: Dict[str, str] = {}

        while pos < len(body):
            # Find end of line
            crlf_pos = body.find(CRLF, pos)
            lf_pos = body.find(LF, pos)

            if crlf_pos == pos:
                # Empty line - end of headers
                return headers, pos + 2
            elif lf_pos == pos and not self.strict:
                # Empty line with LF only (lenient mode)
                return headers, pos + 1

            # Find the line ending
            if crlf_pos != -1 and (lf_pos == -1 or crlf_pos < lf_pos):
                line_end = crlf_pos
                next_pos = crlf_pos + 2
            elif lf_pos != -1 and not self.strict:
                line_end = lf_pos
                next_pos = lf_pos + 1
            else:
                # No valid line ending found
                return None, pos

            # Extract line
            line = body[pos:line_end]

            try:
                line_str = line.decode("utf-8")
            except UnicodeDecodeError:
                line_str = line.decode("latin-1")

            # Parse header
            if ":" in line_str:
                name, value = line_str.split(":", 1)
                headers[name.strip()] = value.strip()
            elif line_str.startswith((" ", "\t")) and headers:
                # Header continuation (obsolete but handle it)
                last_key = list(headers.keys())[-1]
                headers[last_key] += " " + line_str.strip()
            else:
                # Invalid header line
                return None, pos

            pos = next_pos

        return None, pos  # Ran out of data

    def _find_next_boundary(self, body: bytes, pos: int, delimiter: bytes) -> Optional[int]:
        """Find the position where the next boundary starts (before CRLF)."""
        # Look for CRLF + delimiter or LF + delimiter
        search_crlf = CRLF + delimiter
        search_lf = LF + delimiter

        crlf_pos = body.find(search_crlf, pos)
        lf_pos = body.find(search_lf, pos) if not self.strict else -1

        if crlf_pos != -1 and (lf_pos == -1 or crlf_pos <= lf_pos):
            return crlf_pos
        elif lf_pos != -1:
            return lf_pos

        return None


def run_test(test_dir: Path, strict: bool = True) -> Dict[str, Any]:
    """Run a single test and return results."""
    test_json = test_dir / "test.json"
    headers_json = test_dir / "headers.json"
    input_raw = test_dir / "input.raw"

    result = {
        "test_id": test_dir.name,
        "passed": False,
        "skipped": False,
        "errors": [],
    }

    # Load test case
    if not test_json.exists():
        result["errors"].append("Missing test.json")
        return result

    with open(test_json, "r") as f:
        test_data = json.load(f)

    # Check if this is a lenient-only test
    tags = test_data.get("tags", [])
    is_lenient_test = "lenient" in tags

    # Skip lenient tests in strict mode
    if is_lenient_test and strict:
        result["skipped"] = True
        result["passed"] = True
        result["skip_reason"] = "Lenient test skipped in strict mode (use --lenient)"
        return result

    # Load headers
    if not headers_json.exists():
        result["errors"].append("Missing headers.json")
        return result

    with open(headers_json, "r") as f:
        headers = json.load(f)

    # Load raw body
    if not input_raw.exists():
        result["errors"].append("Missing input.raw")
        return result

    with open(input_raw, "rb") as f:
        body = f.read()

    # Parse
    boundary = parse_boundary(headers.get("content-type", ""))
    parser = MultipartParser(strict=strict)
    parse_result = parser.parse(body, boundary)

    result["actual"] = parse_result.to_dict()

    # Choose expected based on mode
    if not strict and "lenient_expected" in test_data:
        expected = test_data["lenient_expected"]
    else:
        expected = test_data.get("expected", {})
    result["expected"] = expected

    # Check validity
    if expected.get("valid", True) != parse_result.valid:
        result["errors"].append(
            f"Validity mismatch: expected {expected.get('valid', True)}, got {parse_result.valid}"
        )
        if parse_result.error_message:
            result["errors"].append(f"Parser error: {parse_result.error_message}")

    # For invalid inputs, check error type
    if not expected.get("valid", True):
        expected_error = expected.get("error_type")
        if expected_error and parse_result.error_type != expected_error:
            result["errors"].append(
                f"Error type mismatch: expected {expected_error}, got {parse_result.error_type}"
            )
    else:
        # For valid inputs, compare parts
        expected_parts = expected.get("parts", [])
        differences = compare_parts(expected_parts, parse_result.parts)
        result["errors"].extend(differences)

    result["passed"] = len(result["errors"]) == 0
    return result


def find_tests(suite_dir: Path, category: Optional[str] = None) -> List[Path]:
    """Find all test directories."""
    tests_dir = suite_dir / "tests"
    tests = []

    if category:
        category_dir = tests_dir / category
        if category_dir.exists():
            for test_dir in sorted(category_dir.iterdir()):
                if test_dir.is_dir() and re.match(r"^\d{3}-", test_dir.name):
                    tests.append(test_dir)
    else:
        for category_dir in sorted(tests_dir.iterdir()):
            if category_dir.is_dir():
                for test_dir in sorted(category_dir.iterdir()):
                    if test_dir.is_dir() and re.match(r"^\d{3}-", test_dir.name):
                        tests.append(test_dir)

    return tests


def main():
    parser = argparse.ArgumentParser(
        description="Run reference parser against test suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--test", "-t",
        metavar="PATH",
        help="Run a single test directory",
    )
    parser.add_argument(
        "--category", "-c",
        help="Run all tests in a category",
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Run all tests",
    )
    parser.add_argument(
        "--suite-dir", "-d",
        default=".",
        help="Path to test suite root (default: current directory)",
    )
    parser.add_argument(
        "--lenient",
        action="store_true",
        help="Use lenient parsing (accept LF instead of CRLF)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output for each test",
    )

    args = parser.parse_args()

    if not any([args.test, args.category, args.all]):
        parser.print_help()
        sys.exit(1)

    suite_dir = Path(args.suite_dir).resolve()
    strict = not args.lenient

    # Collect tests to run
    if args.test:
        test_path = Path(args.test)
        if not test_path.is_absolute():
            test_path = suite_dir / test_path
        tests = [test_path]
    elif args.category:
        tests = find_tests(suite_dir, args.category)
    else:
        tests = find_tests(suite_dir)

    if not tests:
        print("No tests found", file=sys.stderr)
        sys.exit(1)

    # Run tests
    results = []
    passed = 0
    failed = 0
    skipped = 0

    for test_dir in tests:
        result = run_test(test_dir, strict=strict)
        results.append(result)

        if result.get("skipped"):
            skipped += 1
            if args.verbose and not args.json:
                print(f"SKIP: {result['test_id']} ({result.get('skip_reason', 'skipped')})")
        elif result["passed"]:
            passed += 1
            if args.verbose and not args.json:
                print(f"PASS: {result['test_id']}")
        else:
            failed += 1
            if not args.json:
                print(f"FAIL: {result['test_id']}")
                for error in result["errors"]:
                    print(f"      {error}")

    # Summary
    if args.json:
        output = {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "results": results,
        }
        print(json.dumps(output, indent=2))
    else:
        summary = f"\nTotal: {len(results)}, Passed: {passed}, Failed: {failed}"
        if skipped > 0:
            summary += f", Skipped: {skipped}"
        print(summary)

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
