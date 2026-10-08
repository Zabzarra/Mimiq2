/* wallet-guard.js — the ONE wrong-wallet guard for every fee-approval signing page
 * (Hyperliquid, Lighter, Lighter RH, RiseX, and any venue added later).
 *
 * A signing session knows which wallet must sign (`expected_address`, from the linked account).
 * The page asks the guard on every connect / account switch; on a mismatch it shows a banner that
 * names the right wallet and DISABLES the sign button, so no signature is ever requested from the
 * wrong wallet. The server still verifies the signer (that stays the final, unbypassable check).
 *
 * Usage (see approve_app/_test_approval_pages_contract.py — every approval page must do this):
 *   <script src="/assets/wallet-guard.js"></script>
 *   const guard = WalletGuard.create({
 *     button:     primaryBtn,                       // the Sign / Connect button to lock
 *     anchor:     walletPill,                       // the banner is inserted before this element
 *     getAddress: () => connectedAddressFullCase,   // currently connected wallet (or null)
 *     statusUrl:  `/api/<venue>-status/${token}`,   // optional: guard.load() reads expected_address
 *   });
 *   guard.check()  after every connect / disconnect / account change
 *   guard.isMismatch()  before signing
 */
(function (root) {
  'use strict';

  function shortAddr(a) { return a.slice(0, 6) + '…' + a.slice(-4); }

  function create(opts) {
    var expected = null;
    var mismatch = false;
    var banner = null;

    function ensureBanner() {
      if (banner || typeof document === 'undefined') return banner;
      banner = document.getElementById('walletWarn');
      if (!banner) {
        banner = document.createElement('div');
        banner.id = 'walletWarn';
        banner.style.cssText = 'display:none;margin:10px 0;padding:10px 12px;' +
          'border:1px solid rgba(255,107,107,.45);border-radius:10px;background:rgba(255,107,107,.08);' +
          'color:#ff8a8a;font-size:13px;line-height:1.4';
        banner.innerHTML = '⚠️ <strong>Wrong wallet connected.</strong> Switch to ' +
          '<strong id="walletWarnAddr"></strong> in your wallet to continue.';
        var anchor = opts.anchor || (opts.button && opts.button.parentNode);
        if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(banner, anchor);
      }
      return banner;
    }

    function check() {
      var addr = String((opts.getAddress && opts.getAddress()) || '').toLowerCase();
      mismatch = !!(expected && addr && addr !== expected);
      var b = ensureBanner();
      if (b) {
        b.style.display = mismatch ? 'block' : 'none';
        if (mismatch) {
          var el = b.querySelector('#walletWarnAddr');
          if (el) el.textContent = shortAddr(expected);
        }
      }
      if (opts.button) opts.button.disabled = mismatch;
      return mismatch;
    }

    function setExpected(addr) {
      expected = String(addr || '').toLowerCase() || null;
      return check();
    }

    function load() {
      // Reads expected_address from the session's status endpoint. Resolves with the parsed
      // JSON (so the page can still react to e.g. "not_found"); never throws — the server
      // enforces the check again when the signature is submitted.
      if (!opts.statusUrl) return Promise.resolve(null);
      return fetch(opts.statusUrl)
        .then(function (r) { return r.json(); })
        .then(function (d) { setExpected(d && d.expected_address); return d; })
        .catch(function () { return null; });
    }

    return { check: check, setExpected: setExpected, load: load,
             isMismatch: function () { return mismatch; },
             expected: function () { return expected; } };
  }

  root.WalletGuard = { create: create };
  if (typeof module !== 'undefined' && module.exports) module.exports = root.WalletGuard;
})(typeof window !== 'undefined' ? window : globalThis);
