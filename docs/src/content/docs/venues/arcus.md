---
title: Arcus
description: Copy source and execution venue.
sidebar:
  order: 4
---

<div class="mq-venue-head"><span class="mq-logo"><img src="/venues/arcus.png" alt="Arcus" style="height:44px"></span><span class="mq-badge accent">Copy source + execution</span></div>

<a class="mq-btn" href="https://app.arcus.xyz/ref/MIMIQ2" target="_blank" rel="noopener">Open Arcus ↗</a>

## Link it

The bot asks for: **account ID, API key**.

> Enter your Arcus API key (Ed25519 private key, 64 hex chars). You can create one via the Arcus app or API — see docs.arcus.xyz:

## Cost with Mimiq

<div class="mq-fee-card">
<div class="mq-row"><span class="mq-k">Taker</span><span class="mq-v">2.25 bp</span></div>
<div class="mq-row"><span class="mq-k">Maker</span><span class="mq-v">0 bp</span></div>
</div>

<p class="mq-note">Entry level, lowest volume tier. The venue's own fee schedule is the reference: <a href="https://api.arcus.xyz/v1/feetiers" target="_blank" rel="noopener">fee page</a> · checked 8 Oct 2026.</p>

## What Mimiq can do here

- Stop-loss and take-profit are placed as native orders on the venue
- Mimiq can set the leverage per market
- Partial close from the bot
- Closes use reduce-only orders
- Minimum order: 10 USD
