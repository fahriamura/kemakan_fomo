"""fomoater farm — public edition (CloakBrowser + Playwright).

Flow per account (isolated persistent stealth profile):
  1. fomoater.com/r/<REF>          -> referral cookie
  2. /api/auth/x                   -> X login (jf flow) -> Authorize app -> fomo_sid
  3. /api/me                       -> check current tasks/wallet
  4. X actions via intent pages (logged-in session):
       follow @fomoater, like+repost pinned tweet, post a unique tweet
  5. POST /api/tasks               -> claim follow / like / tweet{url}
  6. POST /api/wallet {address}    -> bind the generated EVM wallet
  7. /api/me                       -> verify points / tickets / wallet

Accounts file:  accounts.txt  (one "username password" per line)
Wallets output: wallets.json  (address + private key per account, index-aligned)

Usage:
  python fomo_farm.py                # run all accounts in accounts.txt
  python fomo_farm.py --only USER    # run a single account
  python fomo_farm.py --remaining    # skip accounts already complete
  python fomo_farm.py --ref CODE     # referral code (else prompted / env FOMO_REF)
  python fomo_farm.py --headless     # headless mode (default is headed)
"""
import argparse
import json
import os
import random
import sys
import time
from pathlib import Path
from urllib.parse import quote

import x_login

try:
    from cloakbrowser import launch_persistent_context
    CLOAK = True
except ImportError:
    CLOAK = False
    print("[!] cloakbrowser not installed — falling back to plain Playwright "
          "(weaker anti-detection). pip install cloakbrowser")

BASE = Path(__file__).parent
PROFILES = BASE / "profiles"
REPORTS = BASE / "reports"
PROFILES.mkdir(exist_ok=True)
REPORTS.mkdir(exist_ok=True)

PINNED_ID = "2100970604031582326"
FOMO_X = "fomoater"

TWEET_TEXTS = [
    "the ant knew first. staying curious with @fomoater",
    "found an ant, missed the alpha, still early. @fomoater",
    "a little curious, a little early. whitelisting with @fomoater",
    "he looked for alpha and found an ant. @fomoater",
    "good things come to the curious. in. @fomoater",
    "overthinking early entries since forever. @fomoater knows",
    "the ant was the alpha all along. @fomoater",
]


def log(username, *a):
    print(f"[{username}] " + " ".join(str(x) for x in a), flush=True)


# ---------------------------------------------------------------- accounts
def load_accounts():
    """accounts.txt: one 'username password' per line. '#' comments allowed."""
    af = BASE / "accounts.txt"
    if not af.exists():
        sys.exit(f"[!] create {af} first: one 'username password' per line")
    out = []
    for ln in af.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split()
        if len(parts) < 2:
            print(f"[!] skipping malformed line: {ln!r}")
            continue
        out.append({"username": parts[0], "password": parts[1]})
    return out


# ---------------------------------------------------------------- wallets
def load_wallets(n_needed=None):
    """Load or create wallets.json aligned by account index.
    Each entry: {"username", "address", "privateKey"} (never share the file)."""
    wf = BASE / "wallets.json"
    wallets = json.loads(wf.read_text()) if wf.exists() else []
    need = n_needed if n_needed is not None else len(load_accounts())
    changed = False
    while len(wallets) < need:
        wallets.append(_new_wallet())
        changed = True
    if changed:
        wf.write_text(json.dumps(wallets, indent=2))
        print(f"[+] wallets.json updated -> {len(wallets)} entries")
    return wallets


def _new_wallet():
    try:
        from eth_account import Account
        acct = Account.create()
        return {"address": acct.address, "privateKey": acct.key.hex()}
    except ImportError:
        sys.exit("[!] eth-account not installed: pip install eth-account")


def ensure_wallet_fields(wallets, accounts):
    """Keep 'username' aligned with accounts.txt order for readability."""
    for i, (w, a) in enumerate(zip(wallets, accounts)):
        if w.get("username") != a["username"]:
            w["username"] = a["username"]
    (BASE / "wallets.json").write_text(json.dumps(wallets, indent=2))


# ---------------------------------------------------------------- api via page
def api_fetch(page, path, method="GET", body=None):
    """Same-origin fetch from the fomoater page context (carries fomo_sid)."""
    return page.evaluate(
        """async ([path, method, body]) => {
            const r = await fetch(path, {
                method, credentials: 'include',
                headers: body ? {'Content-Type': 'application/json'} : undefined,
                body: body ? JSON.stringify(body) : undefined,
            });
            let data = null;
            try { data = await r.json(); } catch (e) {}
            return {status: r.status, data};
        }""",
        [path, method, body],
    )


# ---------------------------------------------------------------- X intent actions
def click_intent_button(page, texts, timeout=20000):
    """Click first visible actionable button matching any text (intent dialog)."""
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for want in texts:
            try:
                loc = page.locator(f'button:has-text("{want}")').first
                if loc.count() > 0 and loc.is_visible() and loc.is_enabled():
                    loc.click(timeout=6000)
                    return want
            except Exception:
                pass
            try:
                hit = page.evaluate(
                    """([w]) => {
                        const b = [...document.querySelectorAll('button,[role=button]')]
                          .find(e => e.offsetParent && !e.disabled &&
                                    e.innerText.toLowerCase().includes(w.toLowerCase()));
                        if (b) { b.click(); return b.innerText.trim().slice(0, 40); }
                        return null;
                    }""", [want])
                if hit:
                    return hit
            except Exception:
                pass
        page.wait_for_timeout(1500)
    return None


def do_follow(page, user):
    page.goto(f"https://x.com/intent/follow?screen_name={FOMO_X}",
              wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)
    clicked = click_intent_button(page, ["Follow", "Ikuti"])
    already = page.locator(
        'button:has-text("Following"), button:has-text("Mengikuti")').count() > 0
    log(user, f"follow: clicked={clicked} already={already}")
    return bool(clicked or already)


def do_like(page, user):
    page.goto(f"https://x.com/intent/like?tweet_id={PINNED_ID}",
              wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2500)
    clicked = click_intent_button(page, ["Like", "Suka"])
    log(user, f"like: clicked={clicked}")
    return bool(clicked)


def do_retweet(page, user):
    for attempt in range(2):
        page.goto(f"https://x.com/intent/retweet?tweet_id={PINNED_ID}",
                  wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)
        clicked = click_intent_button(
            page, ["Repost", "Retweet", "Tweet ulang", "Bu ulang tweet"])
        if clicked:
            log(user, f"retweet: clicked={clicked}")
            return True
        states = page.eval_on_selector_all(
            "button,[role=button]",
            """els => els.map(e => (e.innerText||'').trim())
                     .filter(t => t && /repost|retweet|ulang/i.test(t))""")
        if any("ed" in s.lower().split()[-1] or "sudah" in s.lower() for s in states):
            log(user, "retweet: already reposted")
            return True
        page.wait_for_timeout(3000)
    page.screenshot(path=str(REPORTS / f"{user}_retweet_fail.png"))
    return False


def do_tweet(page, user, text):
    """Post a tweet via web intent; return the post URL."""
    page.goto("https://x.com/intent/tweet?text=" + quote(text),
              wait_until="commit", timeout=45000)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(2500)
    ta = page.locator('textarea[name="tweet_text"], #tweet-text, textarea').first
    if ta.count() > 0 and ta.is_visible():
        cur = ta.input_value() or ""
        if not cur.strip():
            ta.fill(text)
    clicked = click_intent_button(page, ["Post", "Posting", "Tweet"])
    log(user, f"tweet: clicked={clicked}")
    if not clicked:
        page.screenshot(path=str(REPORTS / f"{user}_tweet_fail.png"))
        return None
    page.wait_for_timeout(5000)
    url = page.evaluate("""() => {
        const a = [...document.querySelectorAll('a')].find(a =>
            a.offsetParent && /\\/status\\/\\d+/.test(a.href || ''));
        return a ? a.href : null;
    }""")
    if not url:
        page.goto(f"https://x.com/{user}", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)
        url = page.evaluate("""(handle) => {
            const a = [...document.querySelectorAll('a')].find(a =>
                a.offsetParent &&
                new RegExp('/' + handle + '/status/\\\\d+').test(a.getAttribute('href') || ''));
            return a ? ('https://x.com' + a.getAttribute('href')) : null;
        }""", [user])
    log(user, f"tweet url: {url}")
    return url


# ---------------------------------------------------------------- browser
def open_profile(username, headless=False):
    """Open the account's persistent stealth profile via CloakBrowser
    (or plain Playwright fallback). Returns (ctx, page)."""
    if CLOAK:
        ctx = launch_persistent_context(
            str(PROFILES / username),
            headless=headless,
            humanize=True,          # human-like mouse/keyboard/scroll
            stealth_args=True,      # source-level fingerprint patches
            viewport={"width": 1266, "height": 668},
            locale="en-US",
            timezone="Asia/Jakarta",
        )
    else:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILES / username), headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
            viewport={"width": 1266, "height": 668},
            locale="en-US", timezone_id="Asia/Jakarta",
        )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return ctx, page


# ---------------------------------------------------------------- main per-account
def run_account(acct, wallet, ref, headless=False):
    user = acct["username"]
    log(user, f"=== start -> wallet {wallet['address']} ===")
    rep = {"username": user, "wallet": wallet["address"]}
    x_login.REPORTS = str(REPORTS)

    ctx, page = open_profile(user, headless)
    try:
        # 1: referral cookie
        page.goto(f"https://fomoater.com/r/{ref}", wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        # 2: X login + authorize
        res = x_login.login(page, user, acct["password"],
                            log=lambda *a: log(user, *a))
        log(user, "login:", res)
        rep["login"] = res
        if res not in ("ok", "already"):
            page.screenshot(path=str(REPORTS / f"{user}_login_{res}.png"))
            return rep

        # 3: current state
        page.goto("https://www.fomoater.com/home", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        me = api_fetch(page, "/api/me")
        rep["me_start"] = me["data"]
        tasks_done = (me["data"] or {}).get("tasks", {})
        wallet_set = bool((me["data"] or {}).get("user", {}).get("walletAddress"))
        log(user, "me:", json.dumps(tasks_done), "pts:",
            (me["data"] or {}).get("stats", {}).get("points"))

        # 4: X actions (only missing ones)
        tweet_url = None
        if not tasks_done.get("follow"):
            do_follow(page, user)
            page.wait_for_timeout(random.randint(1200, 2500))
        if not tasks_done.get("like"):
            do_like(page, user)
            page.wait_for_timeout(random.randint(1200, 2500))
            do_retweet(page, user)
            page.wait_for_timeout(random.randint(1200, 2500))
        if not tasks_done.get("tweet"):
            tweet_url = do_tweet(page, user, random.choice(TWEET_TEXTS))
            page.wait_for_timeout(random.randint(1500, 3000))

        # 5: claims (same-origin on fomoater)
        page.goto("https://www.fomoater.com/home", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        if not tasks_done.get("follow"):
            r = api_fetch(page, "/api/tasks", "POST", {"taskKey": "follow"})
            log(user, "claim follow:", r["status"])
            rep["claim_follow"] = r["status"]
            page.wait_for_timeout(random.randint(1500, 3000))
        if not tasks_done.get("like"):
            r = api_fetch(page, "/api/tasks", "POST", {"taskKey": "like"})
            log(user, "claim like:", r["status"])
            rep["claim_like"] = r["status"]
            page.wait_for_timeout(random.randint(1500, 3000))
        if not tasks_done.get("tweet"):
            if tweet_url:
                r = api_fetch(page, "/api/tasks", "POST",
                              {"taskKey": "tweet", "url": tweet_url})
                log(user, "claim tweet:", r["status"])
                rep["claim_tweet"] = r["status"]
            else:
                log(user, "claim tweet: SKIPPED (no tweet url)")
                rep["claim_tweet"] = "skipped-no-url"

        # 6: wallet bind
        if not wallet_set:
            r = api_fetch(page, "/api/wallet", "POST", {"address": wallet["address"]})
            log(user, "wallet:", r["status"])
            rep["wallet"] = r["status"]

        # 7: verify
        me2 = api_fetch(page, "/api/me")
        rep["me_end"] = me2["data"]
        st = (me2["data"] or {}).get("stats", {})
        tk = (me2["data"] or {}).get("tasks", {})
        wl = (me2["data"] or {}).get("user", {}).get("walletAddress")
        log(user, f"FINAL tasks={tk} points={st.get('points')}/{st.get('maxPoints')} "
                  f"tickets={st.get('tickets')} wallet={wl}")
        page.screenshot(path=str(REPORTS / f"{user}_final.png"))
    except Exception as e:
        rep["error"] = str(e)
        log(user, "ERROR:", str(e)[:200])
        try:
            page.screenshot(path=str(REPORTS / f"{user}_error.png"))
        except Exception:
            pass
    finally:
        (REPORTS / f"{user}_farm.json").write_text(json.dumps(rep, indent=2, default=str))
        ctx.close()
    return rep


def is_complete(username):
    rep = REPORTS / f"{username}_farm.json"
    if not rep.exists():
        return False
    d = json.loads(rep.read_text())
    me = d.get("me_end") or {}
    return bool(me.get("user", {}).get("walletAddress")
                and all((me.get("tasks") or {}).values()))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="run a single username")
    ap.add_argument("--remaining", action="store_true", help="skip complete accounts")
    ap.add_argument("--headless", action="store_true", help="run headless")
    ap.add_argument("--ref", help="referral code (default: prompt or FOMO_REF env)")
    args = ap.parse_args()

    accounts = load_accounts()
    wallets = load_wallets(len(accounts))
    ensure_wallet_fields(wallets, accounts)

    # ---- referral code ----
    ref = args.ref or os.environ.get("FOMO_REF")
    if not ref:
        ref = input("masukan reff kamu : ").strip()
    if not ref:
        sys.exit("[!] referral code required (or set FOMO_REF env)")
    print(f"[*] referral: {ref}   browser: {'CloakBrowser' if CLOAK else 'Playwright (fallback)'}")

    if args.only:
        sel = [(a, wallets[i]) for i, a in enumerate(accounts)
               if a["username"].lower() == args.only.lower()]
        if not sel:
            sys.exit(f"[!] account '{args.only}' not in accounts.txt")
    elif args.remaining:
        sel = []
        for i, a in enumerate(accounts):
            if is_complete(a["username"]):
                print(f"[skip] {a['username']} already complete")
                continue
            sel.append((a, wallets[i]))
    else:
        sel = [(a, wallets[i]) for i, a in enumerate(accounts)]

    print(f"[*] accounts to run: {[a['username'] for a, _ in sel]}")
    for a, w in sel:
        run_account(a, w, ref, args.headless)
        time.sleep(random.randint(8, 15))


if __name__ == "__main__":
    main()
