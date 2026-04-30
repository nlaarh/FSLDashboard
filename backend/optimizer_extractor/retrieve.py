"""Drive the FSL Optimization Center UI via Playwright to generate JSON files for runs.

Auth model:
  - SF CLI provides a refresh token (one-time `sf org login web --alias prod`).
  - Lightning UI access additionally requires MFA enrollment for the browser fingerprint.
  - First run: launches headed Chromium → user enrolls MFA once → state saved to
    ~/.fslapp/sf_browser_state.json. Subsequent runs use saved state, fully headless.

Batch mode: opens ONE browser, processes many run IDs in the same Lightning session.
  - 5-10x faster than relaunching browser per run
  - Avoids LWC cold-start blank-content issue
"""

import os
import time
import logging
import urllib.request
import urllib.parse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from .auth import SFSession

log = logging.getLogger('optimizer_extractor.retrieve')

_OPT_CENTER_URL = '/lightning/n/FSL__OptimizationCenter'
_GENERATE_BUTTON = 'button:has-text("Retrieve Files")'
_INPUT_BOX = 'input[placeholder^="Enter ID"]'
_DEBUG_DIR = '/tmp/optimizer_extractor_debug'

_STATE_FILE = Path.home() / '.fslapp' / 'sf_browser_state.json'


def _state_exists() -> bool:
    return _STATE_FILE.exists() and _STATE_FILE.stat().st_size > 100


def bootstrap_browser_state(session: SFSession) -> None:
    """One-time interactive: launch headed browser, user completes MFA, save state."""
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    log.info("Launching headed browser for one-time MFA enrollment...")
    log.info("→ Complete the verification in the browser; the window will close automatically.")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(
            viewport={'width': 1400, 'height': 900},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
        page = ctx.new_page()
        fd = f"{session.instance_url}/secur/frontdoor.jsp?sid={session.access_token}&retURL=%2Flightning%2Fpage%2Fhome"
        page.goto(fd)
        try:
            page.wait_for_url('**/lightning/**', timeout=300_000)
            log.info("Reached Lightning — saving browser state for future headless runs.")
        except PWTimeout:
            log.error("MFA enrollment timed out. Re-run to retry.")
            raise
        ctx.storage_state(path=str(_STATE_FILE))
        ctx.close()
        browser.close()
    log.info(f"Saved browser state → {_STATE_FILE}")


def _open_lightning_to_opt_files(page, session: SFSession) -> None:
    """Navigate to Optimization Center → Optimization Request Files tab."""
    fd = f"{session.instance_url}/secur/frontdoor.jsp?sid={session.access_token}&retURL={_OPT_CENTER_URL}"
    page.goto(fd, wait_until='domcontentloaded')
    page.wait_for_selector('text=Optimization Center', timeout=60_000)

    # Dismiss the occasional "Sorry to interrupt — CSS Error" modal
    css_err = page.locator('text=CSS Error')
    if css_err.count() > 0 and css_err.is_visible():
        log.info("dismissing CSS Error modal")
        page.click('button:has-text("Refresh")')
        page.wait_for_selector('text=Optimization Center', timeout=30_000)

    # Give Lightning a moment to fully boot before clicking — LWC sometimes renders
    # blank if we click too fast right after navigation.
    time.sleep(3)

    # Click "Optimization Request Files" tab and wait for input box
    for attempt in (1, 2, 3, 4):
        page.click('text=Optimization Request Files', timeout=15_000)
        try:
            page.wait_for_selector(_INPUT_BOX, timeout=30_000, state='visible')
            return
        except PWTimeout:
            if attempt == 4:
                os.makedirs(_DEBUG_DIR, exist_ok=True)
                page.screenshot(path=f'{_DEBUG_DIR}/init_no_input.png', full_page=True)
                raise
            log.info(f"LWC blank on attempt {attempt}, reloading + waiting longer...")
            page.reload()
            page.wait_for_selector('text=Optimization Center', timeout=45_000)
            time.sleep(5)   # extra warm-up


def _retrieve_in_page(page, session: SFSession, run_id: str,
                       timeout_ms: int = 60_000) -> tuple[bytes, bytes] | None:
    """Trigger Generate Files for one run on an already-open page.
    Page must already be on the Optimization Request Files tab.
    Returns (request.json bytes, response.json bytes) or None on failure.
    """
    try:
        # Clear input and type new run ID
        input_el = page.locator(_INPUT_BOX)
        input_el.click()
        input_el.fill('')   # clear
        input_el.fill(run_id)
        page.click(_GENERATE_BUTTON)

        # Poll for either success row or error toast
        deadline = time.time() + (timeout_ms / 1000)
        outcome = None
        while time.time() < deadline:
            body_text = page.locator('body').inner_text()
            if f"Request_{run_id}.json" in body_text and f"Response_{run_id}.json" in body_text:
                outcome = 'success'
                break
            if "couldn't retrieve" in body_text or 'Insufficient Privileges' in body_text:
                outcome = 'error'
                break
            time.sleep(2)

        if outcome != 'success':
            os.makedirs(_DEBUG_DIR, exist_ok=True)
            page.screenshot(path=f'{_DEBUG_DIR}/{run_id}_{outcome or "timeout"}.png', full_page=True)
            log.warning(f"[{run_id}] outcome={outcome}; screenshot saved")
            return None

        return _download_via_rest(session, run_id)

    except Exception as e:
        log.exception(f"[{run_id}] retrieve_in_page failed: {e}")
        os.makedirs(_DEBUG_DIR, exist_ok=True)
        try:
            page.screenshot(path=f'{_DEBUG_DIR}/{run_id}_exception.png', full_page=True)
        except Exception:
            pass
        return None


def retrieve_batch(session: SFSession, run_ids: list[str], headless: bool = True,
                    on_result=None) -> dict[str, tuple[bytes, bytes] | None]:
    """Process many run IDs in ONE browser session. Returns {run_id: (req, resp) | None}.

    on_result(run_id, result) is called after each retrieval — useful to upload
    immediately rather than holding everything in memory.
    """
    if not _state_exists():
        bootstrap_browser_state(session)

    results: dict[str, tuple[bytes, bytes] | None] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(
            storage_state=str(_STATE_FILE),
            viewport={'width': 1400, 'height': 900},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
        page = ctx.new_page()
        try:
            log.info(f"Batch start: {len(run_ids)} runs in one session")
            _open_lightning_to_opt_files(page, session)

            for i, run_id in enumerate(run_ids, 1):
                log.info(f"[{i}/{len(run_ids)}] retrieving {run_id}")
                result = _retrieve_in_page(page, session, run_id)
                results[run_id] = result
                if on_result:
                    try:
                        on_result(run_id, result)
                    except Exception:
                        log.exception(f"[{run_id}] on_result callback failed")
        finally:
            ctx.close()
            browser.close()

    ok = sum(1 for v in results.values() if v is not None)
    log.info(f"Batch done: {ok}/{len(run_ids)} succeeded")
    return results


def retrieve_one(session: SFSession, run_id: str, headless: bool = True,
                 timeout_ms: int = 60_000) -> tuple[bytes, bytes] | None:
    """Convenience: extract a single run. Internally uses batch mode."""
    return retrieve_batch(session, [run_id], headless=headless).get(run_id)


def _download_via_rest(session: SFSession, run_id: str) -> tuple[bytes, bytes] | None:
    """Once the UI has triggered creation, ContentVersion holds the files. Download both."""
    soql = (
        f"SELECT Id, Title FROM ContentVersion "
        f"WHERE Title LIKE 'Request_{run_id}%' OR Title LIKE 'Response_{run_id}%' "
        "ORDER BY CreatedDate DESC LIMIT 4"
    )
    url = f"{session.instance_url}/services/data/v59.0/query?q={urllib.parse.quote(soql)}"
    req = urllib.request.Request(url, headers={'Authorization': f'Bearer {session.access_token}'})
    rows = json.loads(urllib.request.urlopen(req).read()).get('records', [])
    request_id = next((r['Id'] for r in rows if r['Title'].startswith('Request_')), None)
    response_id = next((r['Id'] for r in rows if r['Title'].startswith('Response_')), None)
    if not (request_id and response_id):
        log.warning(f"[{run_id}] expected files not found in ContentVersion")
        return None

    def fetch(cv_id: str) -> bytes:
        u = f"{session.instance_url}/services/data/v59.0/sobjects/ContentVersion/{cv_id}/VersionData"
        r = urllib.request.Request(u, headers={'Authorization': f'Bearer {session.access_token}'})
        return urllib.request.urlopen(r).read()

    return fetch(request_id), fetch(response_id)
