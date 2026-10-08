---
title: Hyperliquid
description: Copy source and execution venue.
sidebar:
  order: 1
---

<div class="mq-venue-head"><span class="mq-logo"><img src="/venues/hyperliquid.svg" alt="Hyperliquid" style="height:45px"></span><span class="mq-badge accent">Copy source + execution</span></div>

<a class="mq-btn" href="https://app.hyperliquid.xyz/join/MIMIQ" target="_blank" rel="noopener">Open Hyperliquid ↗</a>

## Link it

The bot asks for: **account ID, secret key**.

> Enter your API wallet private key. Create one at app.hyperliquid.xyz → More → API and approve it for this account. It can only sign orders — no withdrawals. NOT your master wallet key. Stored encrypted.

## Cost with Mimiq

<div class="mq-fee-card">
<div class="mq-row"><span class="mq-k">Taker</span><span class="mq-v">4.5 bp</span></div>
<div class="mq-row"><span class="mq-k">Maker</span><span class="mq-v">1.5 bp</span></div>
<div class="mq-row"><span class="mq-k">Mimiq</span><span class="mq-v">+ 1 bp (0.01%) of trade value</span></div>
</div>

<p class="mq-note">Entry level, lowest volume tier. The venue's own fee schedule is the reference: <a href="https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees" target="_blank" rel="noopener">fee page</a> · checked 8 Oct 2026.</p>

## What Mimiq can do here

- Stop-loss and take-profit are placed as native orders on the venue
- Mimiq can set the leverage per market
- Resting limit orders of the copied trader are mirrored
- Partial close from the bot
- Closes use reduce-only orders
- Minimum order: 10 USD
