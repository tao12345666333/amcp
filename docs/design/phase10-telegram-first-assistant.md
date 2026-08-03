# AMCP Phase 10: Telegram-First Personal Assistant (Delegation + Security)

## Status

- **Design finalized** in this document
- **Implementation target**: complete in this phase
- **Scope**: Telegram runtime, policy model, access control, pairing, queue/typing UX, and tests

---

## 1. Goals

Phase 7 made Telegram usable, and Phase 8 simplified automation around an external orchestrator model.
Phase 10 upgrades Telegram from a chat transport into a **secure delegation interface** for personal assistant workflows in both:

- **Private chats** (owner / trusted users)
- **Group chats and forum topics** (mention-gated, policy-driven delegation)

Primary goals:

1. **Secure-by-default inbound access** for DMs and groups
2. **Fine-grained policy controls** at global, group, and topic level
3. **Reliable long-task UX** (typing indicator + bounded queue)
4. **Operational clarity** (status visibility + deterministic enforcement)
5. **Backward compatibility** with existing Telegram deployments

---

## 2. Non-Goals

- Multi-channel unification (WhatsApp/Discord/etc.)
- Marketplace/distribution for skills
- Mobile app surface changes
- Replacing external scheduler design from Phase 8

---

## 3. Problem Statement

Current Telegram behavior is functional but coarse-grained:

- Authorization is mostly global (`allowed_users`)
- Group behavior lacks native `groupPolicy` and mention enforcement strategy
- No first-class DM pairing path for unknown users
- Long-running tasks do not provide continuous typing feedback
- Queue behavior is unbounded, which can degrade responsiveness under burst traffic

These gaps limit AMCP as a robust Telegram-first assistant for real-world delegation in groups.

---

## 4. Target Architecture

```text
Telegram Update
   |
   v
Policy Evaluator
  - DM policy (allowlist/pairing/open/disabled)
  - Group policy (mention/open/allowlist/disabled)
  - group/topic overrides
   |
   v
Message Normalization
  - message type parsing
  - metadata enrichment (chat/thread/mention/reply)
   |
   v
Session Router
  - get/create session per chat
  - queue + bounded backlog
  - typing lifecycle
   |
   v
Agent Runtime (existing AMCP core)
   |
   v
Telegram Delivery
```

---

## 5. Configuration Model

### 5.1 Global Telegram policy

```toml
[telegram]
enabled = true
bot_token = "..."

# Existing allowlists remain supported
allowed_users = [123456789]
admin_users = [123456789]

# New policy controls
dm_policy = "pairing"          # allowlist | pairing | open | disabled
group_policy = "mention"       # mention | open | allowlist | disabled
group_allow_users = []          # sender allowlist for group allowlist mode

# Runtime controls
typing_indicator = true
typing_interval_seconds = 4
max_queue_size = 20

[telegram.pairing]
enabled = true
code_ttl_seconds = 1800
max_pending = 200
```

### 5.2 Group / topic overrides

```toml
[telegram.groups."-1001234567890"]
enabled = true
group_policy = "allowlist"
require_mention = true
allow_users = [123456789]

[telegram.groups."-1001234567890".topics."42"]
enabled = true
group_policy = "open"
require_mention = false
allow_users = [123456789, 987654321]
```

Rules:

1. Topic override > Group override > Global policy
2. `require_mention` defaults to true when effective `group_policy = "mention"`
3. Existing configs without new fields remain valid

---

## 6. Access Control Semantics

### 6.1 DM policy

- `disabled`: ignore inbound DMs
- `open`: accept any DM sender
- `allowlist`: require sender in `allowed_users`
- `pairing`: if unknown sender, issue one-time pairing code and block request until approved

### 6.2 Group policy

- `disabled`: ignore all group messages
- `open`: allow group messages directly
- `mention`: require explicit mention or reply-to-bot
- `allowlist`: require sender in effective group allowlist (group/topic/global fallback)

### 6.3 Mention detection

For group/supergroup messages, “mentioned” is true when any of:

- `@bot_username` mention appears
- text_mention / mention entity references bot
- message is a reply to a bot-authored message

---

## 7. Pairing Workflow

1. Unknown DM sender sends message while `dm_policy = pairing`
2. Bot returns:
   - sender Telegram ID
   - pairing code
   - approval instruction (`/pair approve <code>`)
3. Admin approves code
4. Sender ID is added to `allowed_users`
5. Subsequent DMs pass `allowlist` check

Safety notes:

- Pairing entries have TTL
- Expired/invalid codes fail closed
- Approval requires admin authorization

---

## 8. Runtime UX Enhancements

### 8.1 Typing indicator

- Start typing loop when a message enters active processing
- Stop typing when message completes/cancels/fails
- Disabled via `typing_indicator = false`

### 8.2 Bounded queue

- Queue remains per session
- If queue reaches `max_queue_size`, reject new messages with explicit backpressure response
- `/status` shows active + queued count

---

## 9. Command Surface Changes

- New admin command: `/pair approve <code>`
- Existing command updates:
  - `/status` includes queue/runtime metrics
  - `/help` includes pairing command when caller is admin

No existing command behavior is removed.

---

## 10. Data and Compatibility

- Config decoding remains permissive; unknown keys are ignored
- New fields serialize only when set/non-default where appropriate
- Existing `allowed_users`/`admin_users` remain canonical authorization storage
- Pairing approvals write back to config through existing `save_config` path

---

## 11. Test Plan

Core test additions:

1. Config decode/encode for new Telegram policy fields
2. DM policy matrix (`open`, `allowlist`, `pairing`, `disabled`)
3. Group policy matrix (`mention`, `open`, `allowlist`, `disabled`)
4. Mention + reply-to-bot detection
5. Group/topic override precedence
6. Pairing code creation + approval + expiry behavior
7. Queue limit rejection behavior
8. Typing loop lifecycle start/stop behavior (mocked bot API)

Validation commands:

```bash
ruff check src tests
python -m pytest tests -q
```

---

## 12. Rollout Plan

1. **Step 1**: ship config + evaluator + tests
2. **Step 2**: enable typing + queue controls
3. **Step 3**: enable pairing commands
4. **Step 4**: production hardening with real group/topic configs

Recommended migration for existing users:

1. Set `dm_policy = "pairing"`
2. Keep `group_policy = "mention"` initially
3. Add explicit group/topic overrides only where delegation is needed

---

## 13. Success Criteria

Phase 10 is complete when:

1. All policy paths are enforced exactly as configured
2. Pairing flow works end-to-end with admin approval
3. Queue and typing behavior improve long-task UX without regressions
4. New tests pass in CI with no fallback to undocumented behavior
