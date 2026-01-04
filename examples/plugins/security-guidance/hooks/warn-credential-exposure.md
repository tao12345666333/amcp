---
name: warn-credential-exposure
enabled: true
event: file
action: warn
pattern: (password|passwd|secret|api[_-]?key|token|credential).*[:=].*['"][^'"]{8,}['"]
---

🔐 **Potential Credential Exposure Detected!**

The code you're writing appears to contain hardcoded credentials:

- Passwords
- API keys
- Tokens
- Secrets

## Security Risks

- Credentials in code can be accidentally committed to version control
- Anyone with repository access can see them
- Credentials may leak through logs or error messages

## Recommended Solutions

1. **Use environment variables:**
   ```python
   import os
   api_key = os.environ.get('API_KEY')
   ```

2. **Use a secrets manager:**
   - AWS Secrets Manager
   - HashiCorp Vault
   - Azure Key Vault

3. **Use .env files (for development):**
   ```
   # .env (add to .gitignore!)
   API_KEY=your_key_here
   ```

4. **Use configuration files outside the repo:**
   ```python
   config = load_config('/etc/myapp/config.yaml')
   ```

## Checklist

- [ ] Is this file in `.gitignore`?
- [ ] Are credentials stored separately from code?
- [ ] Would exposing this be a security risk?

Please review this file before proceeding.
