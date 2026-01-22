"""
Starlette application that parses multipart/form-data and returns JSON.

This server accepts POST requests with multipart/form-data content and
returns a JSON response with the parsed parts, suitable for conformance testing.
"""

import base64
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.requests import Request


async def parse_multipart(request: Request) -> JSONResponse:
    """
    Parse multipart/form-data and return JSON with the parsed parts.

    Returns a JSON object with:
    - valid: bool - whether parsing succeeded
    - parts: list of parsed parts (if valid)
    - error_type: string error type (if invalid)
    """
    try:
        form = await request.form()
        parts = []

        for field_name in form:
            # form.getlist() returns all values for a field name
            values = form.getlist(field_name)
            for value in values:
                part = {"name": field_name}

                # Check if it's a file upload (UploadFile) or a plain form field
                if hasattr(value, "filename"):
                    # It's a file upload
                    part["filename"] = value.filename if value.filename else None
                    part["content_type"] = value.content_type if value.content_type else None

                    # Read the file content
                    content = await value.read()
                    part["body_size"] = len(content)

                    # Try to decode as text, fall back to base64 for binary
                    try:
                        part["body_text"] = content.decode("utf-8")
                        part["body_base64"] = None
                    except UnicodeDecodeError:
                        part["body_text"] = None
                        part["body_base64"] = base64.b64encode(content).decode("ascii")
                else:
                    # It's a plain form field (string value)
                    part["filename"] = None
                    part["content_type"] = None
                    part["body_text"] = value
                    part["body_base64"] = None
                    part["body_size"] = len(value.encode("utf-8")) if value else 0

                parts.append(part)

        return JSONResponse({
            "valid": True,
            "parts": parts
        })
    except Exception as e:
        # Map common exceptions to error types
        error_type = "parse_error"
        error_message = str(e)

        # Try to identify specific error types
        if "boundary" in error_message.lower():
            error_type = "boundary_mismatch"
        elif "content-disposition" in error_message.lower():
            error_type = "missing_content_disposition"

        return JSONResponse({
            "valid": False,
            "error_type": error_type,
            "error_message": error_message
        })


async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse({"status": "ok"})


app = Starlette(
    debug=True,
    routes=[
        Route("/parse", parse_multipart, methods=["POST"]),
        Route("/health", health_check, methods=["GET"]),
    ],
)
