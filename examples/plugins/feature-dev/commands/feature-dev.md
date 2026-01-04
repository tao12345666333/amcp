---
description: Guided 7-phase feature development workflow
argument-hint: <feature description>
---

# Feature Development Workflow

You are running the `/feature-dev` command to guide a structured feature development process.

## Your Task

Guide the user through the 7-phase feature development workflow. Follow each phase strictly and wait for user input where indicated.

**Feature Request:** {{args}}

---

## Phase 1: Discovery

**Goal:** Understand what needs to be built

1. If the feature request is unclear, ask clarifying questions:
   - What problem are you solving?
   - Who are the users?
   - What are the constraints?

2. Summarize your understanding and confirm with the user:
   ```
   ## My Understanding
   
   You want to build: [summary]
   
   Key requirements:
   - [requirement 1]
   - [requirement 2]
   
   Is this correct? Should I proceed to explore the codebase?
   ```

**⏸️ WAIT for user confirmation before proceeding to Phase 2.**

---

## Phase 2: Codebase Exploration

**Goal:** Understand relevant existing code and patterns

1. Use `grep` and `read_file` to explore:
   - Similar existing features
   - Architecture patterns
   - Relevant abstractions
   - Configuration patterns

2. Present your findings:
   ```
   ## Codebase Analysis
   
   ### Similar Features Found:
   - [feature]: [location] - [description]
   
   ### Key Patterns:
   - [pattern name]: [how it's used]
   
   ### Files to Modify:
   - [file]: [why]
   
   ### Dependencies:
   - [dependency]: [purpose]
   ```

---

## Phase 3: Clarifying Questions

**Goal:** Resolve all ambiguities before design

Present all questions that need answers:

```
## Clarifying Questions

Before designing the architecture, I need to clarify:

1. **[Topic]**: [Question]
2. **[Topic]**: [Question]
3. **[Topic]**: [Question]

Please answer these questions so I can design the best solution.
```

**⏸️ WAIT for user answers before proceeding to Phase 4.**

---

## Phase 4: Architecture Design

**Goal:** Design multiple implementation approaches

Present 2-3 approaches with trade-offs:

```
## Architecture Options

### Approach 1: Minimal Changes
[Description]
- Pros: [list]
- Cons: [list]
- Estimated effort: [low/medium/high]

### Approach 2: Clean Architecture
[Description]
- Pros: [list]
- Cons: [list]
- Estimated effort: [low/medium/high]

### Approach 3: Pragmatic Balance
[Description]
- Pros: [list]
- Cons: [list]
- Estimated effort: [low/medium/high]

## My Recommendation

I recommend **Approach [N]** because [reasons].

Which approach would you like to proceed with?
```

**⏸️ WAIT for user to choose an approach before proceeding to Phase 5.**

---

## Phase 5: Implementation

**Goal:** Build the feature

1. Confirm before starting:
   ```
   Ready to implement using Approach [N]. 
   
   I will:
   1. [Step 1]
   2. [Step 2]
   3. [Step 3]
   
   Shall I proceed?
   ```

2. **⏸️ WAIT for explicit approval.**

3. Implement the feature:
   - Follow the chosen architecture
   - Use established patterns from the codebase
   - Write clean, documented code
   - Update configuration if needed

---

## Phase 6: Quality Review

**Goal:** Review the implementation

After implementation, perform a self-review:

```
## Implementation Review

### Files Changed:
- [file]: [changes made]

### Quality Checklist:
- [ ] Follows codebase conventions
- [ ] Error handling implemented
- [ ] Edge cases covered
- [ ] No security issues
- [ ] Code is documented

### Potential Improvements:
- [improvement 1]
- [improvement 2]

### Testing Suggestions:
- [test case 1]
- [test case 2]
```

---

## Phase 7: Summary

**Goal:** Wrap up and document

```
## Feature Complete! 🎉

### What was built:
[Summary of the feature]

### Files changed:
- [file 1]
- [file 2]

### How to use:
[Usage instructions]

### Next steps:
1. Test the feature
2. Review the changes
3. Commit with message: `feat: [description]`
```

---

## Important Guidelines

1. **Never skip phases** - Each phase has a purpose
2. **Wait for user input** where indicated with ⏸️
3. **Be thorough** in exploration and design
4. **Follow existing patterns** in the codebase
5. **Ask questions** rather than making assumptions
