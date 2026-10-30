"""Isolated public research UI preview, deliberately without data or secrets.

This is NOT the VIP app, an odds feed, a betting model, or an entitlement
acceptance. Only deploy on a separate free Render web service with no envVars.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTML = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>JABBAZI · Research Preview (No Live Data)</title>
<style>
:root{color-scheme:dark;font:16px system-ui;background:#0d0b10;color:#f7f4f7}
body{margin:0 auto;max-width:950px;padding:30px 18px 80px}
h1{font-size:clamp(28px,6vw,48px);letter-spacing:-.04em;margin:0}
h2{font-size:22px}p{line-height:1.55;color:#c9c1cd}
small,.muted{color:#aaa1af}
.eyebrow{color:#ff5ca8;font-size:12px;font-weight:800;letter-spacing:.12em}
.banner{background:#2b1422;border:1px solid #b54a79;border-radius:14px;padding:16px;margin:22px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(235px,1fr));gap:12px}
.card{border:1px solid #3a3040;border-radius:16px;background:#18141c;padding:20px}
.pill{display:inline-block;border:1px solid #665367;border-radius:999px;padding:6px 12px;font-size:12px;color:#ffc3df}
hr{border:0;border-top:1px solid #3a3040;margin:30px 0}
a{color:#ff88c0}
</style>
<body><header><span class="eyebrow">JABBAZI GURU · V6 ISOLATED UI PREVIEW</span>
<h1>Paid Player Model Research</h1>
<p>NBA · NFL · NHL — Source-aware integration preview</p></header>
<div class="banner"><strong>DEMONSTRATION ONLY · NO LIVE PLAYER DATA</strong>
<p>This isolated preview has no provider credentials, no production database, no VIP sessions,
no sportsbook odds, no predictions, and no wagering functionality. It does not establish paid
endpoint access or model calibration.</p></div>
<div class="grid">
<article class="card"><span class="eyebrow">NBA</span><h2>Player model research</h2>
<span class="pill">UNVERIFIED · RESEARCH ONLY</span>
<p>LAB saved player-model signals require separate authenticated entitlement.
JABBAZI exact-line hit probabilities remain unapproved.</p><small>Player rows: unavailable</small></article>
<article class="card"><span class="eyebrow">NFL</span><h2>Player model research</h2>
<span class="pill">UNVERIFIED · RESEARCH ONLY</span>
<p>LAB saved player-model signals require separate authenticated entitlement.
JABBAZI exact-line hit probabilities remain unapproved.</p><small>Player rows: unavailable</small></article>
<article class="card"><span class="eyebrow">NHL</span><h2>Sportsbook prop research</h2>
<span class="pill">LAB PLAYER PROPS UNSUPPORTED</span>
<p>Verify NHL Sports API odds separately; JABBAZI player probabilities
require independent calibration and identity checks.</p><small>Player rows: unavailable</small></article>
</div>
<hr><h2>Release gate</h2><p>Live NBA/NFL LAB acceptance, NHL Sports API coverage, exact-line model
calibration, and production VIP/Discord end-to-end acceptance are all required
before a production release. All wagers are disabled in this preview.</p>
<p><a href="https://github.com/jabbazi/jabbazi-betting-model/pull/80" rel="noopener noreferrer">View draft PR #80</a></p>
</body></html>"""

def health():
    return {
        "status": "PREVIEW_ONLY",
        "live_data": False,
        "provider_requests": False,
        "production_approved": False,
        "betting_enabled": False,
    }

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            payload = json.dumps(health()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        elif self.path in ("/", "/index.html"):
            payload = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        else:
            self.send_error(404, "Not found")
            return
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        # Never log query strings, user identifiers or request headers.
        pass

def main():
    port = int(os.getenv("PORT", "10000"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid PORT")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()

if __name__ == "__main__":
    main()
