---
name: warn-sensitive-files
enabled: true
event: file
action: warn
conditions:
  - field: file_path
    operator: regex_match
    pattern: \.env$|\.env\.|credentials|secrets|\.pem$|\.key$|id_rsa|id_ed25519
---

🔒 **Sensitive File Modification Detected!**

You are modifying a file that may contain sensitive information:

- `.env` files - Environment variables with secrets
- `credentials` - Authentication data
- `secrets` - Secret configurations
- `.pem` / `.key` - Private keys
- SSH keys (`id_rsa`, `id_ed25519`)

## Security Checklist

Before proceeding, please verify:

- [ ] This file is in `.gitignore`
- [ ] The file permissions are restrictive (`chmod 600`)
- [ ] No real secrets are being committed
- [ ] Secrets are using placeholder values in examples

## Git Safety

Add to your `.gitignore`:
```
.env
.env.*
*.pem
*.key
**/secrets/**
credentials.json
```

## File Permissions

Set restrictive permissions:
```bash
chmod 600 .env
chmod 600 *.pem
chmod 600 ~/.ssh/id_*
```

Please review carefully before proceeding.
