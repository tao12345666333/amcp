---
name: warn-security-antipatterns
enabled: true
event: file
action: warn
pattern: eval\(|exec\(|os\.system\(|subprocess\.call\(.*shell=True|innerHTML\s*=|\.html\(|dangerouslySetInnerHTML|pickle\.load|yaml\.load\([^,]*\)|sqlite.*\+.*user|SELECT.*\+.*input
---

⚠️ **Security Anti-Pattern Detected!**

The code contains patterns that are commonly associated with security vulnerabilities:

## Detected Patterns

### Code Injection
- `eval()` / `exec()` - Can execute arbitrary code
- `os.system()` - Shell command injection risk
- `subprocess.call(..., shell=True)` - Shell injection risk

### XSS (Cross-Site Scripting)
- `innerHTML = ` - Can inject malicious scripts
- `.html()` - jQuery HTML injection
- `dangerouslySetInnerHTML` - React XSS risk

### Deserialization
- `pickle.load()` - Can execute arbitrary code
- `yaml.load()` without Loader - Code execution risk

### SQL Injection
- String concatenation in SQL queries

## Safer Alternatives

### Instead of `eval()`/`exec()`:
```python
# Use ast.literal_eval for data
import ast
data = ast.literal_eval(user_input)

# Or use specific parsers
import json
data = json.loads(user_input)
```

### Instead of `os.system()`:
```python
import subprocess
subprocess.run(['command', 'arg1', 'arg2'], check=True)
```

### Instead of `innerHTML`:
```javascript
// Use textContent for text
element.textContent = userInput;

// Or sanitize HTML
import DOMPurify from 'dompurify';
element.innerHTML = DOMPurify.sanitize(userInput);
```

### Instead of `pickle.load()`:
```python
import json
data = json.loads(file_content)
```

### Instead of `yaml.load()`:
```python
import yaml
data = yaml.safe_load(content)  # Use safe_load!
```

### For SQL queries:
```python
# Use parameterized queries
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
```

Please review and update the code to use safer alternatives.
