/**
 * Node.js application that parses multipart/form-data using three popular libraries.
 *
 * This server accepts POST requests with multipart/form-data content and
 * returns a JSON response with the parsed parts, suitable for conformance testing.
 *
 * Endpoints:
 * - POST /parse/multer - Parse using multer
 * - POST /parse/formidable - Parse using formidable
 * - POST /parse/busboy - Parse using busboy
 * - GET /health - Health check endpoint
 */

import express from 'express';
import multer from 'multer';
import formidable from 'formidable';
import Busboy from 'busboy';

const app = express();

/**
 * Format a parsed part for the JSON response.
 *
 * @param {Object} options
 * @param {string} options.name - Field name
 * @param {string|null} options.filename - Filename if file upload
 * @param {string|null} options.contentType - Content-Type header value
 * @param {Buffer|string} options.body - Body content
 * @returns {Object} Formatted part object
 */
function formatPart({ name, filename, contentType, body }) {
  const bodyBuffer = Buffer.isBuffer(body) ? body : Buffer.from(body, 'utf-8');
  const bodySize = bodyBuffer.length;

  let bodyText = null;
  let bodyBase64 = null;

  try {
    // Try to decode as UTF-8
    const decoded = bodyBuffer.toString('utf-8');
    // Check if it's valid UTF-8 by re-encoding
    if (Buffer.from(decoded, 'utf-8').equals(bodyBuffer)) {
      bodyText = decoded;
    } else {
      bodyBase64 = bodyBuffer.toString('base64');
    }
  } catch {
    bodyBase64 = bodyBuffer.toString('base64');
  }

  return {
    name,
    filename: filename ?? null,
    content_type: contentType ?? null,
    body_text: bodyText,
    body_base64: bodyBase64,
    body_size: bodySize
  };
}

/**
 * Create an error response.
 *
 * @param {Error} error - The error that occurred
 * @returns {Object} Error response object
 */
function formatError(error) {
  let errorType = 'parse_error';
  const errorMessage = error.message || String(error);

  const lowerMessage = errorMessage.toLowerCase();
  if (lowerMessage.includes('boundary')) {
    errorType = 'boundary_mismatch';
  } else if (lowerMessage.includes('content-disposition')) {
    errorType = 'missing_content_disposition';
  } else if (lowerMessage.includes('header')) {
    errorType = 'invalid_header';
  }

  return {
    valid: false,
    error_type: errorType,
    error_message: errorMessage
  };
}

// ============================================================================
// Multer endpoint
// ============================================================================

// Configure multer to store files in memory
const upload = multer({ storage: multer.memoryStorage() });

app.post('/parse/multer', upload.any(), (req, res) => {
  try {
    const parts = [];

    // Process files (multer puts files in req.files)
    if (req.files && Array.isArray(req.files)) {
      for (const file of req.files) {
        parts.push(formatPart({
          name: file.fieldname,
          filename: file.originalname || null,
          contentType: file.mimetype || null,
          body: file.buffer
        }));
      }
    }

    // Process regular fields (multer puts them in req.body)
    if (req.body) {
      for (const [name, value] of Object.entries(req.body)) {
        // Handle arrays of values with same name
        const values = Array.isArray(value) ? value : [value];
        for (const v of values) {
          parts.push(formatPart({
            name,
            filename: null,
            contentType: null,
            body: v
          }));
        }
      }
    }

    res.json({ valid: true, parts });
  } catch (error) {
    res.json(formatError(error));
  }
}, (error, req, res, next) => {
  // Multer error handler
  res.json(formatError(error));
});

// ============================================================================
// Formidable endpoint
// ============================================================================

import { PassThrough } from 'stream';
import fs from 'fs/promises';

// Helper to create an in-memory stream for formidable
function createMemoryStream() {
  const chunks = [];
  const stream = new PassThrough();
  stream.on('data', (chunk) => chunks.push(chunk));
  stream.getBuffer = () => Buffer.concat(chunks);
  return stream;
}

app.post('/parse/formidable', async (req, res) => {
  try {
    // Track file buffers by hash/filepath
    const fileBuffers = new Map();

    const form = formidable({
      multiples: true,
      // Use custom write stream to capture content in memory
      fileWriteStreamHandler: (file) => {
        const stream = createMemoryStream();
        // Store reference to get buffer later
        stream.on('finish', () => {
          fileBuffers.set(file?.newFilename || stream, stream.getBuffer());
        });
        // formidable expects the stream to have certain properties
        file._writeStream = stream;
        return stream;
      }
    });

    const [fields, files] = await form.parse(req);
    const parts = [];

    // Process regular fields
    for (const [name, values] of Object.entries(fields)) {
      const valueArray = Array.isArray(values) ? values : [values];
      for (const value of valueArray) {
        parts.push(formatPart({
          name,
          filename: null,
          contentType: null,
          body: value
        }));
      }
    }

    // Process files
    for (const [name, fileList] of Object.entries(files)) {
      const fileArray = Array.isArray(fileList) ? fileList : [fileList];
      for (const file of fileArray) {
        // Get body from our captured buffer or from temp file
        let body;
        if (fileBuffers.has(file.newFilename)) {
          body = fileBuffers.get(file.newFilename);
        } else if (file._writeStream && typeof file._writeStream.getBuffer === 'function') {
          body = file._writeStream.getBuffer();
        } else if (file.filepath) {
          // Fallback: read from temp file
          body = await fs.readFile(file.filepath);
        } else {
          body = Buffer.alloc(0);
        }

        parts.push(formatPart({
          name,
          filename: file.originalFilename || null,
          contentType: file.mimetype || null,
          body
        }));
      }
    }

    res.json({ valid: true, parts });
  } catch (error) {
    res.json(formatError(error));
  }
});

// ============================================================================
// Busboy endpoint
// ============================================================================

app.post('/parse/busboy', (req, res) => {
  try {
    const contentType = req.headers['content-type'];
    if (!contentType || !contentType.includes('multipart/form-data')) {
      return res.json(formatError(new Error('Missing multipart/form-data content-type')));
    }

    const busboy = Busboy({ headers: req.headers });
    const parts = [];
    const pendingFiles = new Map();
    let partIndex = 0;
    let hasError = false;

    busboy.on('file', (name, stream, info) => {
      const { filename, mimeType } = info;
      const chunks = [];
      const idx = partIndex++;

      // Reserve a spot in the parts array
      parts[idx] = null;

      stream.on('data', (chunk) => {
        chunks.push(chunk);
      });

      stream.on('end', () => {
        if (hasError) return;
        const body = Buffer.concat(chunks);
        parts[idx] = formatPart({
          name,
          filename: filename || null,
          contentType: mimeType || null,
          body
        });
      });
    });

    busboy.on('field', (name, value, info) => {
      if (hasError) return;
      const idx = partIndex++;
      parts[idx] = formatPart({
        name,
        filename: null,
        contentType: null,
        body: value
      });
    });

    busboy.on('error', (error) => {
      hasError = true;
      res.json(formatError(error));
    });

    busboy.on('close', () => {
      if (hasError) return;
      // Filter out any null entries (shouldn't happen, but safety check)
      const finalParts = parts.filter(p => p !== null);
      res.json({ valid: true, parts: finalParts });
    });

    req.pipe(busboy);
  } catch (error) {
    res.json(formatError(error));
  }
});

// ============================================================================
// Health check endpoint
// ============================================================================

app.get('/health', (req, res) => {
  res.json({ status: 'ok' });
});

// ============================================================================
// Start server
// ============================================================================

const PORT = process.env.PORT || 3000;

const server = app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
  console.log('Endpoints:');
  console.log('  POST /parse/multer - Parse using multer');
  console.log('  POST /parse/formidable - Parse using formidable');
  console.log('  POST /parse/busboy - Parse using busboy');
  console.log('  GET /health - Health check');
});

export { app, server };
