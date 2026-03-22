# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Comicarr, please report it responsibly:

1. **Do NOT open a public GitHub issue** for security vulnerabilities
2. Email security concerns to the maintainer via GitHub's private vulnerability reporting:
   - Go to the [Security tab](https://github.com/frankieramirez/comicarr/security/advisories) and click "Report a vulnerability"
3. Include as much detail as possible: steps to reproduce, affected versions, and potential impact

You should receive a response within 72 hours. We will work with you to understand and address the issue before any public disclosure.

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest  | Yes       |

## Security Practices

- API keys and credentials are never logged in plaintext
- Configuration files with credentials (`config.ini`) are excluded from version control
- The Docker image runs as a non-root user with configurable PUID/PGID
- All database queries use parameterized statements to prevent SQL injection
- The CarePackage feature redacts sensitive fields before export

## Known Scanner Findings

The following items may be flagged by automated security scanners but are **not security vulnerabilities**:

### ComicVine API Key in `lib/comictaggerlib/comicvinetalker.py`

This is the ComicTagger project's publicly distributed default API key, inherited from the upstream Mylar3 codebase. It is not a private credential — the same key is visible in the public ComicTagger repository.

### CherryPy Test Certificate in Git History

A test RSA certificate (`cherrypy/test/test.pem`) exists in historical commits from when CherryPy was vendored. This is a well-known test fixture from the CherryPy project, not a production credential. The file was removed when vendored dependencies were cleaned up.

## Dependencies

We monitor dependencies for known vulnerabilities via GitHub Dependabot. If you notice a dependency with a known CVE, please open an issue or PR with the update.
