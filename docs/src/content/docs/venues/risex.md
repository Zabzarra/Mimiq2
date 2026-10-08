---
title: RiseX
description: Copy source and execution venue.
sidebar:
  order: 3
---

<div class="mq-venue-head"><span class="mq-logo"><img src="/venues/risex.svg" alt="RiseX" style="height:28px"></span><span class="mq-badge accent">Copy source + execution</span></div>

<a class="mq-btn" href="https://www.rise.trade/invite/mimiq" target="_blank" rel="noopener">Open RiseX ↗</a>

## Link it

The bot asks for: **account ID, secret key**.

> Enter your RiseX session-signer private key (registered as an authorized signer on your RiseX account via registerSigner). NOT your wallet's master private key — a separate signer key that can only sign orders. Stored encrypted.

## Cost with Mimiq

<div class="mq-fee-card">
<div class="mq-row"><span class="mq-k">Taker</span><span class="mq-v">3.0 bp</span></div>
<div class="mq-row"><span class="mq-k">Maker</span><span class="mq-v">1.0 bp</span></div>
<div class="mq-row"><span class="mq-k">Mimiq</span><span class="mq-v">+ 1 bp (0.01%) of trade value</span></div>
</div>

<p class="mq-note">Entry level, lowest volume tier. The venue's own fee schedule is the reference: <a href="https://docs.risechain.com/docs/risex/trading/fees" target="_blank" rel="noopener">fee page</a> · checked 8 Oct 2026.</p>

## What Mimiq can do here

- Stop-loss and take-profit are placed as native orders on the venue
- Mimiq can set the leverage per market
- Partial close from the bot
- Closes use reduce-only orders
- Minimum order: 1 USD
