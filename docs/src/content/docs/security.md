---
title: Security and your keys
description: What Mimiq stores, how it is protected, and what it never holds.
---

**Mimiq never holds your funds.** Your money stays on the venue, in your account.

- **What you give Mimiq.** Only the API credentials the venue issues for trading, never your wallet key. They cannot withdraw. [Link a venue](/guide/link-venue/) walks through it.
- **Keys at rest.** AES-256-GCM with a separate key per user (HKDF-SHA256). The user ID is bound into every ciphertext. The message with your key is deleted from the chat.
- **Invite-only.** Wrong invite codes lock a user out for a while. A per-user rate limit applies to every action in the bot.
- **Fee approvals.** The signing page checks that the right wallet is connected before it asks for a signature. The server checks the signer again.
- **Logs.** The bot token is removed from all log output.
- **Open for review.** The security-relevant source code is published for review: [github.com/Zabzarra/Mimiq2](https://github.com/Zabzarra/Mimiq2). It is for reading, not for reuse.

Found a problem? Write to mimiq.tech@proton.me or use GitHub's private security advisory on that repository.
