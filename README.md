# Fomoater Farm — airdrop auto-registration (X auth + tasks + wallet)

Automates fomoater.com whitelist registration end-to-end, per account:

1. **Auto X auth** — OAuth login via the proven jf onboarding flow, clicks
   "Authorize app" itself, survives X's URI-decode quirk, never touches
   phone-verification traps.
2. **Fomo farm** — follows @fomoater, likes + reposts the pinned tweet, posts
   a unique tweet, claims all 3 tasks (30 pts / 3 tickets), binds the wallet.
3. **Wallet generator** — one fresh EVM wallet per account, private keys kept
   in `wallets.json` (index-aligned with `accounts.txt`).

Built on **Playwright + CloakBrowser** (stealth Chromium with source-level
fingerprint patches + humanized input) so it runs reliably for anyone.

## Install

```bash
pip install -r requirements.txt
python -m cloakbrowser download   # fetch the stealth Chromium binary (~200MB, once)
```

## Setup

Create `accounts.txt` in the project folder — one X account per line:

```
usn password
usn password
usn password
```

Lines starting with `#` are ignored. Wallets are generated automatically on
first run (never reuse keys across projects; back up `wallets.json`).

## Run

```bash
python fomo_farm.py
```

You'll be asked:

```
masukan reff kamu :
```

Enter your referral code (it's credited when each account signs up). Then the
script opens a stealth Chromium window per account and does everything:
login → authorize → tasks → claims → wallet.

Useful flags:

```bash
python fomo_farm.py --only usn        # single account
python fomo_farm.py --remaining       # resume: skip accounts already complete
python fomo_farm.py --ref CODE        # skip the referral prompt
python fomo_farm.py --headless        # no window (headed is more reliable)
```

## Output

- `wallets.json` — address + private key per account. **Keep it secret.**
- `reports/` — per-account JSON result + screenshots (login, final state,
  failures).
- `profiles/` — persistent browser profiles (X sessions survive re-runs, so
  re-running is cheap; delete a profile folder to force a fresh login).

## Notes

- X may show a phone-verification or "temporarily limited" screen on fresh
  logins — the script detects it, screenshots it (`reports/*_challenge.png`),
  and moves on. Re-run with `--remaining` later; the persistent profile keeps
  the session so retries rarely re-login. Spacing runs (minutes apart) and
  headed mode reduce this.
- Referral only counts at signup — accounts that already signed up keep their
  original referrer.
- Requirements: Windows/macOS/Linux, ~2GB RAM per browser window, and patience
  between accounts (the script already randomizes delays).

## Disclaimer

Educational use on your own accounts. You are responsible for complying with
the platform's terms.
"# kemakan_fomo" 
