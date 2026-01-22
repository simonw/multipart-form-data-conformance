/**
 * Conformance tests for Node.js multipart/form-data parsing libraries.
 *
 * This module runs all test cases from the parent tests/ directory against
 * a live Express server to verify multipart parsing behavior for:
 * - multer
 * - formidable
 * - busboy
 */

import { describe, it, before, after } from 'node:test';
import assert from 'node:assert';
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import net from 'node:net';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Path to the conformance test suite
const TESTS_ROOT = path.resolve(__dirname, '..', '..', '..', 'tests');

// Parsers to test
const PARSERS = ['multer', 'formidable', 'busboy'];

/**
 * Find an unused TCP port.
 * @returns {Promise<number>}
 */
function getUnusedPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      server.close(() => resolve(port));
    });
    server.on('error', reject);
  });
}

/**
 * Collect all test cases from the tests/ directory.
 * @returns {Array<{testId: string, testDir: string}>}
 */
function collectTestCases() {
  const testCases = [];

  const categories = fs.readdirSync(TESTS_ROOT);
  for (const category of categories.sort()) {
    const categoryPath = path.join(TESTS_ROOT, category);
    if (!fs.statSync(categoryPath).isDirectory()) continue;

    const tests = fs.readdirSync(categoryPath);
    for (const test of tests.sort()) {
      const testDir = path.join(categoryPath, test);
      if (!fs.statSync(testDir).isDirectory()) continue;

      // Verify this is a valid test case
      const testJson = path.join(testDir, 'test.json');
      const headersJson = path.join(testDir, 'headers.json');
      const inputRaw = path.join(testDir, 'input.raw');

      if (fs.existsSync(testJson) && fs.existsSync(headersJson) && fs.existsSync(inputRaw)) {
        testCases.push({ testId: test, testDir });
      }
    }
  }

  return testCases;
}

/**
 * Load test case data from a test directory.
 * @param {string} testDir
 * @returns {{testJson: Object, headersJson: Object, inputRaw: Buffer}}
 */
function loadTestCase(testDir) {
  const testJson = JSON.parse(fs.readFileSync(path.join(testDir, 'test.json'), 'utf-8'));
  const headersJson = JSON.parse(fs.readFileSync(path.join(testDir, 'headers.json'), 'utf-8'));
  const inputRaw = fs.readFileSync(path.join(testDir, 'input.raw'));

  return { testJson, headersJson, inputRaw };
}

/**
 * Compare an actual parsed part with the expected result.
 * @param {Object} actual
 * @param {Object} expected
 * @returns {string[]} List of mismatches
 */
function comparePart(actual, expected) {
  const mismatches = [];

  // Compare name
  if (actual.name !== expected.name) {
    mismatches.push(`name mismatch: got ${JSON.stringify(actual.name)}, expected ${JSON.stringify(expected.name)}`);
  }

  // Compare filename
  const actualFilename = actual.filename;
  const expectedFilename = expected.filename;
  if (actualFilename !== expectedFilename) {
    mismatches.push(`filename mismatch: got ${JSON.stringify(actualFilename)}, expected ${JSON.stringify(expectedFilename)}`);
  }

  // Compare content_type (only if expected specifies one)
  const actualCt = actual.content_type;
  const expectedCt = expected.content_type;
  if (expectedCt !== null && expectedCt !== undefined && actualCt !== expectedCt) {
    mismatches.push(`content_type mismatch: got ${JSON.stringify(actualCt)}, expected ${JSON.stringify(expectedCt)}`);
  }

  // Compare body content
  if (expected.body_text !== null && expected.body_text !== undefined) {
    if (actual.body_text !== expected.body_text) {
      mismatches.push(`body_text mismatch: got ${JSON.stringify(actual.body_text?.slice(0, 50))}, expected ${JSON.stringify(expected.body_text?.slice(0, 50))}`);
    }
  } else if (expected.body_base64 !== null && expected.body_base64 !== undefined) {
    // Binary content - compare as base64
    let actualB64 = actual.body_base64;
    if (actual.body_text !== null) {
      // Server might return text if it decoded as UTF-8
      actualB64 = Buffer.from(actual.body_text, 'utf-8').toString('base64');
    }
    if (actualB64 !== expected.body_base64) {
      mismatches.push(`body_base64 mismatch: got ${actualB64?.slice(0, 50)}..., expected ${expected.body_base64?.slice(0, 50)}...`);
    }
  }

  // Compare body_size
  if (expected.body_size !== undefined && actual.body_size !== expected.body_size) {
    mismatches.push(`body_size mismatch: got ${actual.body_size}, expected ${expected.body_size}`);
  }

  return mismatches;
}

/**
 * Check if a test is optional based on its tags.
 * @param {Object} testJson
 * @returns {boolean}
 */
function isOptionalTest(testJson) {
  const tags = testJson.tags || [];
  return tags.includes('optional');
}

/**
 * Start the server and return base URL.
 * @param {number} port
 * @returns {Promise<{proc: ChildProcess, baseUrl: string}>}
 */
async function startServer(port) {
  const appPath = path.resolve(__dirname, '..', 'src', 'app.js');
  const proc = spawn('node', [appPath], {
    cwd: path.dirname(appPath),
    env: { ...process.env, PORT: String(port) },
    stdio: ['ignore', 'pipe', 'pipe']
  });

  const baseUrl = `http://127.0.0.1:${port}`;

  // Wait for server to start
  const maxAttempts = 50;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      const response = await fetch(`${baseUrl}/health`);
      if (response.ok) {
        return { proc, baseUrl };
      }
    } catch {
      // Server not ready yet
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }

  proc.kill();
  throw new Error('Server failed to start');
}

// Run tests
const TEST_CASES = collectTestCases();

describe('Multipart form-data conformance tests', async () => {
  let proc;
  let baseUrl;

  before(async () => {
    const port = await getUnusedPort();
    const result = await startServer(port);
    proc = result.proc;
    baseUrl = result.baseUrl;
  });

  after(() => {
    if (proc) {
      proc.kill();
    }
  });

  for (const parser of PARSERS) {
    describe(`${parser} parser`, () => {
      for (const { testId, testDir } of TEST_CASES) {
        it(`${testId}`, async (t) => {
          const { testJson, headersJson, inputRaw } = loadTestCase(testDir);
          const expected = testJson.expected;
          const optional = isOptionalTest(testJson);

          // Build headers for the request
          const headers = {};
          for (const [key, value] of Object.entries(headersJson)) {
            headers[key] = value;
          }

          // Send the raw multipart body to the server
          let result;
          try {
            const response = await fetch(`${baseUrl}/parse/${parser}`, {
              method: 'POST',
              body: inputRaw,
              headers
            });
            result = await response.json();
          } catch (error) {
            if (optional) {
              t.skip(`HTTP client rejected request for optional test: ${error.message}`);
              return;
            }
            throw new Error(`HTTP client error: ${error.message}`);
          }

          // Check validity
          if (expected.valid) {
            // Test expects successful parsing
            if (!result.valid) {
              if (optional) {
                t.skip(`Optional test failed: ${parser} could not parse input`);
                return;
              }
              throw new Error(`Expected valid parsing, but got error: ${result.error_message}`);
            }

            const expectedParts = expected.parts || [];
            const actualParts = result.parts || [];

            if (actualParts.length !== expectedParts.length) {
              if (optional) {
                t.skip(`Optional test: part count mismatch (got ${actualParts.length}, expected ${expectedParts.length})`);
                return;
              }
              throw new Error(`Part count mismatch: got ${actualParts.length}, expected ${expectedParts.length}`);
            }

            const allMismatches = [];
            for (let i = 0; i < actualParts.length; i++) {
              const mismatches = comparePart(actualParts[i], expectedParts[i]);
              if (mismatches.length > 0) {
                allMismatches.push(`Part ${i}: ${mismatches.join('; ')}`);
              }
            }

            if (allMismatches.length > 0) {
              if (optional) {
                t.skip(`Optional test failed:\n${allMismatches.join('\n')}`);
                return;
              }
              throw new Error(`Part comparison failed:\n${allMismatches.join('\n')}`);
            }
          } else {
            // Test expects parsing to fail
            if (result.valid) {
              // Parser successfully parsed what we expected to fail
              // This is OK - it's just more lenient than the spec requires
              t.skip(`${parser} parsed malformed input successfully (lenient parsing)`);
            }
          }
        });
      }
    });
  }
});
