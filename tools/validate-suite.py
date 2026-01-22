#!/usr/bin/env python3
"""
Validate the multipart/form-data conformance test suite.

Checks:
- All required files exist
- JSON files validate against schemas
- Test IDs are unique and match directory names
- Categories match parent directories
- Boundaries are consistent between headers and raw files
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False


# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))
from lib.multipart_utils import parse_boundary


class ValidationResult:
    """Holds validation results."""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.tests_checked: int = 0

    def add_error(self, path: str, message: str):
        self.errors.append(f"{path}: {message}")

    def add_warning(self, path: str, message: str):
        self.warnings.append(f"{path}: {message}")

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        lines = []
        lines.append(f"Tests checked: {self.tests_checked}")
        lines.append(f"Errors: {len(self.errors)}")
        lines.append(f"Warnings: {len(self.warnings)}")

        if self.errors:
            lines.append("\nErrors:")
            for err in self.errors:
                lines.append(f"  - {err}")

        if self.warnings:
            lines.append("\nWarnings:")
            for warn in self.warnings:
                lines.append(f"  - {warn}")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.is_valid,
            "tests_checked": self.tests_checked,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": self.errors,
            "warnings": self.warnings,
        }


def load_schemas(schema_dir: Path) -> Dict[str, Any]:
    """Load JSON schemas from schema directory."""
    schemas = {}

    test_case_schema = schema_dir / "test-case.schema.json"
    if test_case_schema.exists():
        with open(test_case_schema, "r") as f:
            schemas["test-case"] = json.load(f)

    headers_schema = schema_dir / "headers.schema.json"
    if headers_schema.exists():
        with open(headers_schema, "r") as f:
            schemas["headers"] = json.load(f)

    return schemas


def validate_json_schema(data: Dict, schema: Dict, path: str, result: ValidationResult):
    """Validate JSON data against schema."""
    if not HAS_JSONSCHEMA:
        result.add_warning(path, "jsonschema not installed, skipping schema validation")
        return

    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        result.add_error(path, f"Schema validation failed: {e.message}")


def validate_test_directory(
    test_dir: Path,
    category: str,
    schemas: Dict[str, Any],
    result: ValidationResult,
    seen_ids: set,
):
    """Validate a single test directory."""
    rel_path = test_dir.name

    # Check required files exist
    test_json = test_dir / "test.json"
    headers_json = test_dir / "headers.json"
    input_raw = test_dir / "input.raw"

    if not test_json.exists():
        result.add_error(rel_path, "Missing test.json")
        return

    if not headers_json.exists():
        result.add_error(rel_path, "Missing headers.json")

    if not input_raw.exists():
        result.add_error(rel_path, "Missing input.raw")

    # Load and validate test.json
    try:
        with open(test_json, "r") as f:
            test_data = json.load(f)
    except json.JSONDecodeError as e:
        result.add_error(rel_path, f"Invalid JSON in test.json: {e}")
        return

    # Validate against schema
    if "test-case" in schemas:
        validate_json_schema(test_data, schemas["test-case"], f"{rel_path}/test.json", result)

    # Check ID matches directory name
    test_id = test_data.get("id", "")
    if test_id != test_dir.name:
        result.add_error(rel_path, f"ID '{test_id}' doesn't match directory name '{test_dir.name}'")

    # Check ID uniqueness
    if test_id in seen_ids:
        result.add_error(rel_path, f"Duplicate test ID: {test_id}")
    seen_ids.add(test_id)

    # Check ID format (NNN-kebab-case)
    if not re.match(r"^\d{3}-[a-z0-9-]+$", test_id):
        result.add_error(rel_path, f"Invalid ID format: {test_id} (expected NNN-kebab-case)")

    # Check category matches parent directory
    test_category = test_data.get("category", "")
    if test_category != category:
        result.add_error(
            rel_path,
            f"Category '{test_category}' doesn't match parent directory '{category}'",
        )

    # Validate headers.json
    if headers_json.exists():
        try:
            with open(headers_json, "r") as f:
                headers_data = json.load(f)

            if "headers" in schemas:
                validate_json_schema(headers_data, schemas["headers"], f"{rel_path}/headers.json", result)

            # Check boundary consistency (skip for invalid/malformed tests)
            content_type = headers_data.get("content-type", "")
            boundary = parse_boundary(content_type)
            expected_valid = test_data.get("expected", {}).get("valid", True)

            if not boundary:
                result.add_error(rel_path, "Cannot extract boundary from Content-Type header")
            elif input_raw.exists() and expected_valid:
                # Only check boundary consistency for valid tests
                # Malformed tests may intentionally have mismatched boundaries
                with open(input_raw, "rb") as f:
                    raw_content = f.read()

                boundary_bytes = f"--{boundary}".encode("utf-8")
                if boundary_bytes not in raw_content:
                    result.add_error(
                        rel_path,
                        f"Boundary '{boundary}' not found in input.raw",
                    )

        except json.JSONDecodeError as e:
            result.add_error(rel_path, f"Invalid JSON in headers.json: {e}")

    # Check raw file for basic structure (if valid test)
    if input_raw.exists() and test_data.get("expected", {}).get("valid", True):
        with open(input_raw, "rb") as f:
            raw_content = f.read()

        # Check for boundary terminator (unless testing missing terminator)
        expected = test_data.get("expected", {})
        if expected.get("valid", True) or expected.get("error_type") != "missing_terminator":
            boundary = parse_boundary(headers_data.get("content-type", "") if headers_json.exists() else "")
            if boundary:
                terminator = f"--{boundary}--".encode("utf-8")
                if terminator not in raw_content:
                    result.add_warning(rel_path, "Final boundary terminator (--boundary--) not found")

    result.tests_checked += 1


def validate_suite(suite_dir: Path) -> ValidationResult:
    """Validate the entire test suite."""
    result = ValidationResult()
    seen_ids: set = set()

    # Load schemas
    schema_dir = suite_dir / "schema"
    schemas = load_schemas(schema_dir) if schema_dir.exists() else {}

    if not schemas:
        result.add_warning("schema/", "No schemas found, skipping schema validation")

    # Find all test directories
    tests_dir = suite_dir / "tests"
    if not tests_dir.exists():
        result.add_error("tests/", "Tests directory not found")
        return result

    # Expected categories
    categories = [
        "basic",
        "filenames",
        "boundaries",
        "line-endings",
        "content-types",
        "edge-cases",
        "malformed",
        "browser-variations",
    ]

    for category in categories:
        category_dir = tests_dir / category
        if not category_dir.exists():
            result.add_warning(f"tests/{category}/", "Category directory not found")
            continue

        # Find test directories (NNN-name format)
        for test_dir in sorted(category_dir.iterdir()):
            if test_dir.is_dir() and re.match(r"^\d{3}-", test_dir.name):
                validate_test_directory(test_dir, category, schemas, result, seen_ids)

    return result


def main():
    parser = argparse.ArgumentParser(description="Validate multipart conformance test suite")
    parser.add_argument(
        "suite_dir",
        nargs="?",
        default=".",
        help="Path to test suite root (default: current directory)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Only output errors",
    )

    args = parser.parse_args()

    suite_dir = Path(args.suite_dir).resolve()

    # Check this looks like a test suite
    if not (suite_dir / "tests").exists() and not (suite_dir / "schema").exists():
        print(f"Error: {suite_dir} doesn't appear to be a test suite root", file=sys.stderr)
        sys.exit(1)

    result = validate_suite(suite_dir)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        if not args.quiet or not result.is_valid:
            print(result.summary())

    sys.exit(0 if result.is_valid else 1)


if __name__ == "__main__":
    main()
