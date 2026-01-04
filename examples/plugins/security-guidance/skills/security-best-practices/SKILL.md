---
name: security-best-practices
description: Security best practices and vulnerability prevention guidelines
---

# Security Best Practices Skill

When writing code, follow these security best practices to prevent common vulnerabilities.

## Input Validation

**Always validate and sanitize user input:**

```python
# ❌ Bad - trusting user input
user_id = request.args.get('id')
query = f"SELECT * FROM users WHERE id = {user_id}"

# ✅ Good - parameterized query
user_id = request.args.get('id')
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
```

### Validation Checklist
- Validate type, length, format, and range
- Use allowlists over denylists
- Sanitize for the specific output context
- Never trust client-side validation alone

## Authentication

**Implement secure authentication:**

- Use established libraries (e.g., bcrypt, argon2)
- Never store passwords in plain text
- Implement rate limiting on login attempts
- Use secure session management
- Implement proper logout handling

```python
# ✅ Good - using bcrypt
import bcrypt

def hash_password(password: str) -> bytes:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())

def verify_password(password: str, hash: bytes) -> bool:
    return bcrypt.checkpw(password.encode(), hash)
```

## Authorization

**Check permissions on every request:**

```python
# ✅ Good - checking authorization
def delete_post(post_id: int, user: User):
    post = get_post(post_id)
    if post.author_id != user.id and not user.is_admin:
        raise PermissionError("Not authorized")
    delete_post_from_db(post_id)
```

## Secrets Management

**Never hardcode secrets:**

```python
# ❌ Bad
API_KEY = "sk-1234567890abcdef"

# ✅ Good
import os
API_KEY = os.environ.get('API_KEY')
```

### Environment Variables
- Use `.env` files for development (in `.gitignore`)
- Use secrets managers in production
- Rotate secrets regularly
- Use different secrets per environment

## SQL Injection Prevention

**Always use parameterized queries:**

```python
# ❌ Bad - string concatenation
cursor.execute(f"SELECT * FROM users WHERE name = '{name}'")

# ✅ Good - parameterized
cursor.execute("SELECT * FROM users WHERE name = ?", (name,))

# ✅ Good - ORM
User.query.filter_by(name=name).first()
```

## XSS Prevention

**Escape output and use Content Security Policy:**

```python
# ✅ Good - escaping in templates (Jinja2)
{{ user_input }}  # Auto-escaped

# ✅ Good - explicit escaping
from markupsafe import escape
safe_output = escape(user_input)
```

```javascript
// ❌ Bad
element.innerHTML = userInput;

// ✅ Good
element.textContent = userInput;
```

## CSRF Protection

**Implement CSRF tokens:**

```html
<form method="POST">
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
    ...
</form>
```

## Secure Headers

**Set security headers:**

```python
# Flask example
@app.after_request
def set_secure_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Content-Security-Policy'] = "default-src 'self'"
    return response
```

## Error Handling

**Don't expose sensitive information in errors:**

```python
# ❌ Bad - exposing stack trace
except Exception as e:
    return {"error": str(e), "stack": traceback.format_exc()}

# ✅ Good - generic error message
except Exception as e:
    logger.error(f"Error: {e}", exc_info=True)
    return {"error": "An internal error occurred"}
```

## Dependency Security

**Keep dependencies updated:**

```bash
# Check for vulnerabilities
pip-audit
npm audit
snyk test
```

## File Operations

**Validate file paths to prevent path traversal:**

```python
import os

# ✅ Good - validate path is within allowed directory
def safe_read(user_path: str, base_dir: str) -> str:
    full_path = os.path.realpath(os.path.join(base_dir, user_path))
    if not full_path.startswith(os.path.realpath(base_dir)):
        raise ValueError("Path traversal attempt")
    return open(full_path).read()
```

## Logging

**Log security events but not sensitive data:**

```python
# ❌ Bad - logging passwords
logger.info(f"Login attempt: user={username}, password={password}")

# ✅ Good - logging without sensitive data
logger.info(f"Login attempt: user={username}, success={success}")
```

## Quick Reference

| Vulnerability | Prevention |
|--------------|------------|
| SQL Injection | Parameterized queries |
| XSS | Output encoding, CSP |
| CSRF | CSRF tokens |
| Path Traversal | Path validation |
| Command Injection | Avoid shell=True |
| Hardcoded Secrets | Environment variables |
| Weak Passwords | bcrypt/argon2, complexity rules |
