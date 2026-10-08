# Mimiq — Security Review

Source-available for review. **Not open source** — see `LICENSE`.

Mimiq is an invite-only Telegram bot for automated perp trading across several DEXes. It is
**non-custodial**: users connect the API / signing credentials a venue issues for trading, not a
wallet seed (see the table of requested fields below). This repository exists so that you can verify how Mimiq handles credentials,
access and signatures. It is not the trading bot and it is not meant to be run.

## How to read it

`full` = the whole module (comments removed, docstrings shortened, numeric limits shown as `...`).
`excerpt` = only the named functions / classes. `stub` = signatures only. Nothing here is
runnable on its own.

| Path | Shown as | What you can verify |
|---|---|---|
| `mimiq2/encryption.py` | excerpt | how venue API keys are encrypted and decrypted (AES-256-GCM, HKDF, AAD) |
| `mimiq2/snapshot.py` | excerpt | where keys are decrypted: in memory, when an adapter is built |
| `mimiq2/dex/spec.py` | excerpt | `WalletCreds`: everything an adapter receives |
| `mimiq2/handlers/link.py`, `link_risex.py` | full | how users enter credentials and what happens to them |
| `mimiq2/handlers/invite.py`, `waitlist.py`, `handlers/__init__.py` | full | the invite gate, the waitlist in front of it, and in which order handlers are registered |
| `mimiq2/rate_limiter.py`, `rate_limit.py` | full | limits on credential-linking actions; the per-user flood limit |
| `mimiq2/database.py` | excerpt | identifier validation, ownership accessor, invite redemption and lockout, per-user salt |
| `mimiq2/main_bot.py`, `mimiq2/config.py` | excerpt | handler registration, bot-token redaction in logs |
| `approve_app/server.py` | excerpt | signing sessions, signer checks, bot authentication, dashboard login (and the code they call) |
| `approve_app/static/**` | full | the pages users sign on, incl. the shared wrong-wallet guard |
| `mimiq2/dex/fee_gate.py` | stub | "no fee approval, no new exposure" gate |
| `docs/` | full | the public documentation (Starlight), published at docs.mimiq.tech |
| `mimiq2/engine.py`, `base_executor.py`, `dn/pair_executor.py` | stub | where orders originate (signatures only) |

## What each venue asks the user for

Generated from `mimiq2/dex/registry.py`. Where a venue has its own prompt it names the key the
venue issues for API use and says explicitly not to enter a wallet key. Venues shown as
"generic prompt" use the default dialog ("Enter your private key (needed for order signing)").

| Venue | Fields requested | Prompt for the secret field |
|---|---|---|
| Ondo Finance | `account_id`, `private_key` | Enter your *Ondo API signing secret* (paired with the key ID above, from Ondo's dashboard → API Keys). ⚠️ NOT your wallet's private key. Stored encrypted. |
| Propr | `api_key` | (generic prompt) |
| Hyperliquid | `account_id`, `private_key` | Enter your *API wallet private key*. Create one at app.hyperliquid.xyz → More → *API* and approve it for this account. It can only sign orders — no withdrawals. ⚠️ NOT your master wallet key. Stored encrypted. |
| RiseX | `account_id`, `private_key` | Enter your *RiseX session-signer private key* (registered as an authorized signer on your RiseX account via `registerSigner`). ⚠️ NOT your wallet's master private key — a separate signer key that can only sign orders. Stored encrypted. |
| Hibachi | `account_id`, `api_key`, `private_key` | Enter your Hibachi *API private key* (Settings → API Keys). ⚠️ NOT your wallet key. Stored encrypted. |
| Lighter | `account_id`, `api_key` | Enter your Lighter *API private key*: |
| Lighter (Robinhood Chain) | `account_id`, `api_key` | Enter your Lighter (Robinhood Chain) *API private key*: |
| Arcus | `account_id`, `api_key` | Enter your *Arcus API key* (Ed25519 private key, 64 hex chars). You can create one via the Arcus app or API — see docs.arcus.xyz: |
| Perpl | `api_key`, `private_key` | Enter the *Ed25519 private key* shown when you created the API key (64 hex chars): _Trade-only — it cannot withdraw. Stored encrypted._ |
| Extended | `api_key`, `public_key`, `private_key`, `vault_id` | Enter the *Stark private key* shown next to your API key. ⚠️ NOT your wallet's master private key — Extended's own Stark signing key, trade-scoped. Stored encrypted. |
| QFEX | `api_key`, `private_key` | Enter your *QFEX API secret*: _Shown once when the key is created. Stored encrypted._ |

## Security properties

| Area | Implementation |
|---|---|
| Venue API keys at rest | AES-256-GCM; per-user key from HKDF-SHA256(master key, random per-user salt, `uid:<id>`); fresh nonce per encryption |
| Blob swapping | the Telegram user id is bound into every ciphertext as AAD |
| Per-user salt | created atomically (an existing salt is never replaced), so parallel first calls end with one stored salt |
| Older blobs | `decrypt()` also reads blobs written by two earlier schemes so existing data stays readable; everything written today uses the scheme above |
| Master key | supplied through the environment; not stored in the database or in this repository |
| Wallet seeds / keys | Mimiq never generates or holds a wallet; what it asks each venue for is listed above, stored encrypted like every other credential |
| Credential entry | the message holding a key is deleted from the chat before anything else happens; keys are encrypted before they are written; the plaintext is cleared afterwards |
| Invite gate | registered before every other handler; failed codes are counted and lock the user out, on the Telegram path and on the web dashboard |
| Waitlist | stores only the Telegram id and name plus three answers (interest, venues, monthly volume); no wallet address, no e-mail; `/leavewaitlist` deletes the entry |
| Invite redemption | an atomic update, so a code cannot be over-used by parallel requests |
| SQL | parameterised queries; column names validated before use in DDL |
| Wallet ownership | `get_wallet_owned(wallet_id, telegram_id)` returns a wallet only to its owner; wallet listings are filtered by owner |
| Fee approvals | each submit handler (Hyperliquid, Lighter, Lighter RH, RiseX, Ondo) recovers the signer from the signature and, whenever the session knows the expected account, rejects a different signer before the approval is recorded (Hyperliquid additionally validates the signature itself); `wallet-guard.js` disables the sign button while the wrong wallet is connected |
| Bot to approval server | shared-secret bearer token, compared in constant time; without a configured secret every bot-only endpoint refuses (no unauthenticated mode); signing sessions live in memory only and their lifetime is checked on every access |
| Dashboard | login is a wallet signature over an EIP-4361 sign-in message that names the domain (a phishing site cannot reuse it), with a one-time nonce; an invite code is only looked at after the signature is verified; then a signed session token; every request is tied to the token's owner |
| Abuse limits | a per-user flood limit on every Telegram update, checked before the invite gate; per-IP limits on the signing and login endpoints; extra per-user limits on credential-linking actions |
| Logs | the Telegram bot token is redacted from all log output |
| Fee gate | orders that open or increase a position are refused unless the venue fee approval exists (and, on Lighter, the account is on a paid tier); closes and stops stay allowed |

## Reporting a vulnerability

Please use GitHub's private security advisory on this repository or write to
mimiq.tech@proton.me. Do not open a public issue for a vulnerability.
