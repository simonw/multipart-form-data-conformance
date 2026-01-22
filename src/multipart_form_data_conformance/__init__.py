"""
Multipart Form-Data Conformance Test Suite.

A language-independent test suite for validating HTTP multipart/form-data
parsers and generators.
"""

from pathlib import Path


def get_tests_dir() -> Path:
    """Return the path to the tests directory containing conformance test cases."""
    return Path(__file__).parent / "tests"


def get_schema_dir() -> Path:
    """Return the path to the schema directory."""
    return Path(__file__).parent / "schema"


def get_manifest_path() -> Path:
    """Return the path to the manifest.json file."""
    return Path(__file__).parent / "manifest.json"
