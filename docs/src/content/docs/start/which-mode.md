---
title: Copy Trading or Delta Neutral?
description: What each mode does, what it needs, and how wallets switch between them.
---

import { Aside } from '@astrojs/starlight/components';

| | Copy trading | Delta-neutral |
|---|---|---|
| **What it does** | Mirrors a trader's position changes | Long on one venue, short the same token on another |
| **Return comes from** | The trader's performance | The funding-rate spread |
| **You choose** | A trader, and 1:1 or scaled sizing | A pair, or a Smart Plan that runs it for you |
| **Needs** | 1 venue | 2 venues |
| **Safety** | Stop-loss and take-profit | Stop-loss, take-profit and funding auto-close |
| **Main risk** | The trader's losses | Funding turning against you, a leg being liquidated |

## Wallets

A **wallet** is your trading profile: its own mode, trader, settings and linked venues. Create more with `➕ New Wallet`. **One wallet runs one mode at a time**, so use two wallets to run both.

Switch with `🔁 Switch to DN` or `🔁 Switch to Copy`. It takes effect within about 30 seconds.

<Aside type="caution" title="Before you switch">
The copy engine stops managing the wallet. Close or manage open copy positions yourself first, because they are not watched in delta-neutral mode. The same applies the other way round.
</Aside>
