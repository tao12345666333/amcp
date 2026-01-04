#!/usr/bin/env python3
"""
Secret Scanner Hook Script

Scans file content for potential secrets, API keys, passwords, and other sensitive information.
This is a PreToolUse hook that scans content being written to files.

Input: JSON via stdin with tool_input containing the file path and content
Output: Exit code 0 = success, 2 = block (high severity secrets found)
"""

import re
import sys
import json

# Common patterns for secrets
SECRET_PATTERNS = {
    'api_key': [
        r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\']([a-zA-Z0-9]{20,})["\']',
        r'(?i)(secret[_-]?key|secretkey)\s*[:=]\s*["\']([a-zA-Z0-9]{20,})["\']',
    ],
    'password': [
        r'(?i)(password|passwd|pwd)\s*[:=]\s*["\']([^"\']{6,})["\']',
        r'(?i)(pass|secret)\s*[:=]\s*["\']([^"\']{6,})["\']',
    ],
    'token': [
        r'(?i)(token|access[_-]?token)\s*[:=]\s*["\']([a-zA-Z0-9]{20,})["\']',
        r'(?i)(bearer[_-]?token|bearer)\s*[:=]\s*["\']([a-zA-Z0-9]{20,})["\']',
    ],
    'aws_key': [
        r'AKIA[0-9A-Z]{16}',
        r'(?i)aws[_-]?(secret[_-]?key|access[_-]?key)\s*[:=]\s*["\']([a-zA-Z0-9+/]{20,})["\']',
    ],
    'github_token': [
        r'ghp_[a-zA-Z0-9]{36}',
        r'gho_[a-zA-Z0-9]{36}',
        r'ghu_[a-zA-Z0-9]{36}',
    ],
    'private_key': [
        r'-----BEGIN (RSA |OPENSSH |DSA |EC |PGP )?PRIVATE KEY-----',
        r'-----BEGIN [A-Z]+ PRIVATE KEY-----',
    ],
    'database_url': [
        r'(?i)(database[_-]?url|db[_-]?url)\s*[:=]\s*["\']([^"\']+)["\']',
        r'mysql://[^@]+@[^/]+/[^\s]+',
        r'postgresql://[^@]+@[^/]+/[^\s]+',
        r'mongodb://[^@]+@[^/]+/[^\s]+',
    ],
}


def scan_content(content: str, file_path: str) -> list:
    """Scan content for potential secrets."""
    findings = []
    
    for category, patterns in SECRET_PATTERNS.items():
        for pattern in patterns:
            try:
                matches = re.finditer(pattern, content, re.MULTILINE)
                for match in matches:
                    line_num = content[:match.start()].count('\n') + 1
                    lines = content.split('\n')
                    line_content = lines[line_num - 1].strip() if line_num <= len(lines) else ""
                    
                    finding = {
                        'category': category,
                        'file': file_path,
                        'line': line_num,
                        'match': match.group(0)[:50] + "..." if len(match.group(0)) > 50 else match.group(0),
                        'context': line_content[:80] + "..." if len(line_content) > 80 else line_content,
                        'severity': 'high' if category in ['private_key', 'aws_key', 'github_token'] else 'medium'
                    }
                    findings.append(finding)
            except re.error:
                continue
    
    return findings


def main():
    """Main hook function."""
    try:
        # Read hook input from stdin
        hook_input = json.load(sys.stdin)
        
        tool_name = hook_input.get('tool_name', '')
        tool_input = hook_input.get('tool_input', {})
        
        # Get file path and content based on tool type
        file_path = tool_input.get('path', tool_input.get('file_path', 'unknown'))
        
        # For write_file, scan the content directly
        # For apply_patch, scan the patch content
        if tool_name == 'write_file':
            content = tool_input.get('content', '')
        elif tool_name == 'apply_patch':
            content = tool_input.get('patch', '')
        else:
            # Not a file writing tool, skip
            sys.exit(0)
        
        if not content:
            # No content to scan
            sys.exit(0)
        
        # Scan for secrets
        findings = scan_content(content, file_path)
        
        if findings:
            high_severity = [f for f in findings if f['severity'] == 'high']
            
            # Prepare output
            output = {
                "feedback": f"⚠️ Found {len(findings)} potential secrets in {file_path}",
            }
            
            if high_severity:
                output["hookSpecificOutput"] = {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"❌ High severity secrets found ({len(high_severity)}): {', '.join(f['category'] for f in high_severity[:3])}. Please remove before proceeding."
                }
                print(json.dumps(output))
                sys.exit(0)  # Exit 0 with deny decision in output
            else:
                # Medium severity - warn but allow
                output["hookSpecificOutput"] = {
                    "hookEventName": "PreToolUse", 
                    "permissionDecision": "continue",
                    "permissionDecisionReason": f"⚠️ Medium severity findings detected ({len(findings)}). Please review."
                }
                print(json.dumps(output))
                sys.exit(0)
        
        # No secrets found
        sys.exit(0)
        
    except json.JSONDecodeError:
        print("Failed to parse hook input", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error scanning for secrets: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()