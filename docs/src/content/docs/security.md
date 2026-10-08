---
title: Security
description: How Mimiq protects your keys and your account.
---

- **Keys at rest.** AES-256-GCM with a separate key per user (HKDF-SHA256). The user ID is bound into every ciphertext.
- **No wallet keys.** Mimiq asks only for API credentials from the venue. All of them are for trading only.
- **Invite-only.** Wrong invite codes lock a user out for a while. A per-user rate limit applies to every action in the bot.
- **Fee approvals.** The signing page checks that the right wallet is connected before it asks for a signature. The server checks the signer again.
- **Logs.** The bot token is removed from all log output.
- **Open for review.** The security-relevant source code is published for review: [github.com/Zabzarra/Mimiq2](https://github.com/Zabzarra/Mimiq2). It is for reading, not for reuse.

Found a problem? Write to mimiq.tech@proton.me or use GitHub's private security advisory on that repository.
