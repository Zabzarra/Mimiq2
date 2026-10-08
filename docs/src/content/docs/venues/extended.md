---
title: Extended
description: Execution venue only.
sidebar:
  order: 9
---

<div class="mq-venue-head"><span class="mq-logo pill" style="background:#f4f7f9"><span class="mq-crop" style="width:133px;height:25px"><img src="/venues/extended.svg" alt="Extended" style="height:109px"></span></span><span class="mq-badge accent">Execution venue</span></div>

<a class="mq-btn" href="https://app.extended.exchange" target="_blank" rel="noopener">Open Extended ↗</a>

## Link it

The bot asks for: **API key, public key, secret key, vault ID**.

> Enter the Stark private key shown next to your API key. NOT your wallet's master private key — Extended's own Stark signing key, trade-scoped. Stored encrypted.

## Cost with Mimiq

<div class="mq-fee-card">
<div class="mq-row"><span class="mq-k">Taker</span><span class="mq-v">2.5 bp</span></div>
<div class="mq-row"><span class="mq-k">Maker</span><span class="mq-v">0 bp</span></div>
<div class="mq-row"><span class="mq-k">Mimiq</span><span class="mq-v">+ 1 bp (0.01%) of trade value</span></div>
<div class="mq-row"><span class="mq-k">Note</span><span class="mq-v">maker rebates possible</span></div>
</div>

<p class="mq-note">Entry level, lowest volume tier. The venue's own fee schedule is the reference: <a href="https://docs.extended.exchange/extended-resources/trading/trading-fees-and-rebates" target="_blank" rel="noopener">fee page</a> · checked 8 Oct 2026.</p>

## What Mimiq can do here

- Stop-loss and take-profit are placed as native orders on the venue
- Mimiq can set the leverage per market
- Partial close from the bot
- Closes use reduce-only orders
- Minimum order: 1 USD
