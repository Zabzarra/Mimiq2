---
title: Non-custodial and your keys
description: What Mimiq stores, and how.
---

**Mimiq never holds your funds.** Your money stays on the venue, in your account.

**What you give Mimiq.** The API credentials the venue issues for trading. Each venue page lists exactly what the bot asks for. It is never your wallet key. All of these keys are for trading only. They cannot withdraw funds.

**How it is stored.**
- Encrypted with AES-256-GCM.
- A separate key per user (HKDF-SHA256).
- The message with your key is deleted from the chat.

**Fees.** Mimiq takes 1 bp on most venues. See [Fees](/fees/).

**Invite-only.** Wrong invite codes lock a user out for a while.
