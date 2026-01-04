---
description: Multi-agent code review with confidence scoring
argument-hint: "<files...> [--git] [--focus <area>] [--threshold <N>]"
---

# Code Review Command

You are running the `/code-review` command to perform automated code review.

## Your Task

Perform a comprehensive code review using multiple perspectives. Rate each issue with a confidence score and only report issues above the threshold.

**Arguments:** {{args}}

---

## Step 1: Parse Arguments

Parse the command arguments:
- Files/directories to review
- `--git`: Review uncommitted changes
- `--focus <area>`: Focus area (security, performance, style, bugs, all)
- `--threshold <N>`: Confidence threshold (default: 50)

If `--git` is specified, run `git diff --cached` or `git diff` to get changes.

---

## Step 2: Gather Context

1. Look for project guidelines:
   - README.md
   - CONTRIBUTING.md
   - .editorconfig
   - Code style configuration files

2. Understand the codebase conventions:
   - Naming patterns
   - File organization
   - Error handling patterns
   - Testing patterns

---

## Step 3: Review from Multiple Perspectives

### 3.1 Bug Detection
Look for:
- Logic errors and off-by-one mistakes
- Null/undefined handling issues
- Edge cases not covered
- Race conditions
- Resource leaks (files, connections, memory)
- Error handling gaps

### 3.2 Security Analysis
Look for:
- Input validation issues
- SQL/Command injection vulnerabilities
- XSS vulnerabilities
- Authentication/authorization issues
- Sensitive data exposure
- Insecure configurations

### 3.3 Style & Quality
Look for:
- Naming convention violations
- Code organization issues
- Missing documentation
- High complexity (long functions, deep nesting)
- Code duplication
- Magic numbers/strings

---

## Step 4: Score Each Issue

For each issue found, assign a confidence score (0-100):

**Scoring Guidelines:**
- **90-100**: Definite bug or vulnerability, clear evidence
- **70-89**: Very likely an issue, strong indicators
- **50-69**: Probable issue, worth investigating
- **30-49**: Possible issue, may be intentional
- **0-29**: Uncertain, likely false positive

**Factors that increase confidence:**
- Clear violation of documented project guidelines
- Obvious logical error
- Known vulnerability pattern
- Inconsistent with surrounding code

**Factors that decrease confidence:**
- Could be intentional design decision
- Depends on external context
- Common pattern in codebase
- Edge case scenario

---

## Step 5: Filter and Format Output

Only include issues with confidence >= threshold (default 50).

Format output as:

```markdown
## Code Review Results

**Files reviewed:** [count]
**Issues found:** [count above threshold]
**Filtered (low confidence):** [count below threshold]

### 🔴 Critical Issues

1. **[Issue Title]** (confidence: [N])
   - **Location:** [file:line]
   - **Category:** [security/bug/style]
   - **Issue:** [description]
   - **Suggestion:** [how to fix]

### 🟡 Medium Issues

[...]

### 🟢 Low Priority

[...]

---

## Summary

[Brief summary of code health and main areas of concern]

**Recommended actions:**
1. [Action 1]
2. [Action 2]
```

---

## Important Guidelines

1. **Be specific** - Include file paths and line numbers
2. **Be actionable** - Provide concrete fix suggestions
3. **Be honest** - Use appropriate confidence scores
4. **Prioritize** - Critical issues first
5. **Context matters** - Consider the project's conventions
6. **Avoid noise** - Skip issues you're not confident about
