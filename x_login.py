"""X (Twitter) login for fomoater OAuth — CloakBrowser edition.

Proven flow (jf onboarding form, validated on fresh accounts):
  1. GET /api/auth/x  -> lands on x.com/i/oauth2/authorize (guest consent w/ 'Log in' link)
  2. Direct-nav to x.com/i/flow/login?redirect_after_login=<authorize_url>
     -> lands on /i/jf/onboarding/web (single card: username + inert password)
  3. Fill username field, click the 'Continue' button scoped to its form
  4. Password input activates (login_enter_password); type password, scoped Continue
  5. Redirects back to authorize -> 'Authorize app' -> click
  6. -> fomoater /api/auth/callback/x -> fomo_sid cookie -> /home

Safety rules:
  - Never clicks phone / Google / Apple login options.
  - Never clicks "Send code" buttons (phone verification traps).
  - Detects challenge screens (arkose / phone verify / "temporarily limited")
    and returns 'challenge' so the caller can surface it for manual action.
  - URI-decode recovery: if X dumps us on "To use this App you have to be
    logged in to X." even though the session cookie is valid, re-navigate to
    the saved authorize URL once instead of burning a fresh login attempt.
"""
import time
from urllib.parse import quote

REPORTS = None  # set by caller (path) if you want screenshots


def _shot(page, name):
    if REPORTS is None:
        return
    try:
        from pathlib import Path
        Path(REPORTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(REPORTS) / f"{name}.png"))
    except Exception:
        pass


def _human_type(page, text, base_delay=60):
    """Type with randomized per-character delay (80-200ms jitter)."""
    import random
    for ch in text:
        page.keyboard.type(ch, delay=random.randint(base_delay, base_delay + 140))
        time.sleep(random.uniform(0.01, 0.05))


def _scoped_continue(page, input_sel):
    """Click the text-'Continue' button inside the same form as the given input."""
    return page.evaluate(
        """([sel]) => {
            const inp = [...document.querySelectorAll(sel)]
                        .find(e => !e.inert && e.offsetParent);
            if (!inp) return 'no-input';
            const scope = inp.closest('form') || document;
            const btns = [...scope.querySelectorAll('button')]
                         .filter(b => b.offsetParent && !b.disabled);
            const cont = btns.find(b => b.innerText.trim().toLowerCase() === 'continue');
            if (cont) { cont.click(); return 'clicked'; }
            return 'buttons:' + btns.map(b => b.innerText.trim().slice(0, 18)).join(',');
        }""",
        [input_sel],
    )


def _active(page, sel):
    try:
        el = page.locator(sel).first
        if el.count() == 0:
            return False
        if not el.is_visible():
            return False
        return not el.evaluate("e => e.inert || e.disabled")
    except Exception:
        return False


def login(page, username, password, log=print):
    """Drive the full OAuth handshake. Returns 'ok' | 'already' | 'challenge' | 'timeout'."""
    # already signed into fomoater?
    page.goto("https://www.fomoater.com/api/auth/x", wait_until="commit")
    page.wait_for_timeout(4000)

    if "fomoater.com" in page.url.split("//", 1)[-1].split("/", 1)[0]:
        return "already"  # authed + consented in a previous run

    url = page.url
    auth_url = url  # saved for URI-decode recovery
    if "/oauth2/authorize" not in url:
        log(f"[!] unexpected url after /api/auth/x: {url[:90]}")

    # consent page but logged IN? (has 'Authorize app') -> skip the login form
    body = page.locator("body").inner_text()
    if "Authorize app" not in body:
        login_url = ("https://x.com/i/flow/login?hide_message=true&redirect_after_login="
                     + quote(url, safe=""))
        page.goto(login_url, wait_until="domcontentloaded")
        page.wait_for_timeout(4500)

        # --- username step ---
        deadline = time.time() + 20
        while time.time() < deadline:
            if _active(page, '#jf-input-username_or_email') or _active(page, 'input[name="text"]'):
                break
            page.wait_for_timeout(1000)

        sel = '#jf-input-username_or_email'
        if not _active(page, sel):
            sel = 'input[name="text"]'
        if not _active(page, sel):
            _shot(page, "xlogin_no_username_field")
            log("[!] no username field reachable")
            return "challenge"
        inp = page.locator(sel).first
        inp.click()
        _human_type(page, username)
        page.wait_for_timeout(700)
        r = _scoped_continue(page, sel)
        log(f"[username continue: {r}]")
        page.wait_for_timeout(5000)

        # --- password step ---
        deadline = time.time() + 20
        while time.time() < deadline:
            if _active(page, 'input[name="password"]'):
                break
            page.wait_for_timeout(1000)
        if not _active(page, 'input[name="password"]'):
            _shot(page, "xlogin_no_password_field")
            b = page.locator("body").inner_text()[:250].replace("\n", " | ")
            log(f"[!] password never activated. body: {b}")
            return "challenge"  # phone/arkose/"temporarily limited" screens land here
        pinp = page.locator('input[name="password"]').first
        pinp.click()
        _human_type(page, password)
        page.wait_for_timeout(700)
        r = _scoped_continue(page, 'input[name="password"]')
        log(f"[password continue: {r}]")
        page.wait_for_timeout(7000)

    # --- authorize consent ---
    for i in range(8):
        host = page.url.split("//", 1)[-1].split("/", 1)[0]
        if "fomoater.com" in host:
            return "ok"
        # URI-decode recovery: "To use this App you have to be logged in to X."
        # appears when X mis-decodes redirect_after_login. The session cookie IS
        # valid at this point -> re-navigate to the saved authorize URL once.
        body_early = ""
        try:
            body_early = page.locator("body").inner_text().lower()
        except Exception:
            pass
        if ("logged in to x" in body_early or "have to be logged in" in body_early) and i < 4:
            log("[decode-recovery] re-navigating to saved authorize url")
            page.goto(auth_url, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            continue
        try:
            btn = page.locator('button:has-text("Authorize app")').first
            if btn.count() > 0 and btn.is_visible():
                btn.click(timeout=8000)
                log("[authorize clicked]")
                for _ in range(25):  # consent POST can take up to ~25s
                    page.wait_for_timeout(1000)
                    host = page.url.split("//", 1)[-1].split("/", 1)[0]
                    if "fomoater.com" in host:
                        return "ok"
                continue
        except Exception:
            pass
        # challenge screens?
        body = page.locator("body").inner_text().lower()
        if any(h in body for h in ("verify", "challenge", "arkose", "suspicious", "locked")):
            _shot(page, "xlogin_challenge")
            return "challenge"
        page.wait_for_timeout(3000)

    host = page.url.split("//", 1)[-1].split("/", 1)[0]
    return "ok" if "fomoater.com" in host else "timeout"
