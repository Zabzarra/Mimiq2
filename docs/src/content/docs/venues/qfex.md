---
title: QFEX
description: Execution venue only.
sidebar:
  order: 10
---

<div class="mq-venue-head"><span class="mq-logo"><img src="/venues/qfex.svg" alt="QFEX" style="height:39px"></span><span class="mq-badge accent">Execution venue</span></div>

<a class="mq-btn" href="https://www.qfex.com" target="_blank" rel="noopener">Open QFEX ↗</a>

## Link it

The bot asks for: **API key, secret key**.

> Enter your QFEX API secret: Shown once when the key is created. Stored encrypted.

## Cost with Mimiq

<div class="mq-fee-card">
<div class="mq-row"><span class="mq-k">Taker</span><span class="mq-v">from 5.0</span></div>
<div class="mq-row"><span class="mq-k">Maker</span><span class="mq-v">from 2.0</span></div>
<div class="mq-row"><span class="mq-k">Note</span><span class="mq-v">by asset class (equities are higher)</span></div>
</div>

<p class="mq-note">Entry level, lowest volume tier. The venue's own fee schedule is the reference: <a href="https://docs.qfex.com/qfex/fees" target="_blank" rel="noopener">fee page</a> · checked 8 Oct 2026.</p>

## What Mimiq can do here

- Stop-loss and take-profit are placed as native orders on the venue
- Mimiq can set the leverage per market
- Partial close from the bot
- Closes use reduce-only orders
- Minimum order: 10 USD
