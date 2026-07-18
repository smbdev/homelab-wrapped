"""Playwright smoke suite: real browser, real user flows (spec §9).

Small and fast by design — logic is covered by unit tests; this verifies the
player actually works in a browser: loading, navigation, rendering, redaction,
and the export download.
"""

import pytest

pytestmark = pytest.mark.e2e


def test_index_lists_and_navigates(page, server_url):
    page.goto(server_url)
    page.get_by_role("link", name="Your 2026").click()
    page.wait_for_url("**/story/2026")
    assert "Your 2026" in page.locator(".stage").inner_text()


def test_story_loads_with_intro(page, server_url):
    page.goto(f"{server_url}/story/2026")
    stage = page.locator(".stage").inner_text()
    # the kicker chip renders uppercase via CSS text-transform
    assert "homelab wrapped" in stage.lower()
    assert "Your 2026" in stage


def test_click_advances_and_left_click_goes_back(page, server_url):
    page.goto(f"{server_url}/story/2026")
    page.mouse.click(800, 400)
    assert "hours watched" in page.locator(".stage").inner_text()
    page.mouse.click(50, 400)
    assert "Tap anywhere" in page.locator(".stage").inner_text()


def test_keyboard_navigation(page, server_url):
    page.goto(f"{server_url}/story/2026")
    page.keyboard.press("ArrowRight")
    assert "hours watched" in page.locator(".stage").inner_text()
    page.keyboard.press("ArrowLeft")
    assert "Tap anywhere" in page.locator(".stage").inner_text()
    page.keyboard.press("End")
    assert "That's a wrap" in page.locator(".stage").inner_text()


def test_swipe_navigation(page, server_url):
    page.goto(f"{server_url}/story/2026")
    page.mouse.move(600, 400)
    page.mouse.down()
    page.mouse.move(450, 400)
    page.mouse.up()
    assert "hours watched" in page.locator(".stage").inner_text()


def test_progress_segments_track_and_jump(page, server_url):
    page.goto(f"{server_url}/story/2026")
    segs = page.locator(".progress .seg")
    assert segs.count() == 7  # intro + 5 facts + outro
    page.keyboard.press("ArrowRight")
    assert "current" in segs.nth(1).get_attribute("class")
    assert "done" in segs.nth(0).get_attribute("class")
    segs.nth(0).click()
    assert "Tap anywhere" in page.locator(".stage").inner_text()


def test_count_up_reaches_final_value(page, server_url):
    page.goto(f"{server_url}/story/2026")
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(1100)
    assert page.locator(".display").inner_text() == "412"


def test_top_list_renders_items(page, server_url):
    page.goto(f"{server_url}/story/2026")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    items = page.locator(".toplist li")
    assert items.count() == 2
    assert "The Bear" in items.nth(0).inner_text()
    assert "31 eps" in items.nth(0).inner_text()


def test_heatmap_renders_levelled_cells(page, server_url):
    page.goto(f"{server_url}/story/2026")
    page.keyboard.press("End")
    page.keyboard.press("ArrowLeft")
    assert page.locator(".heatmap .cell").count() > 150  # Jan..Jun of grid days
    assert page.locator(".heatmap .l4").count() >= 1  # the 12-photo day peaks


def test_private_card_excluded_from_export(page, server_url):
    page.goto(f"{server_url}/story/2026")
    page.keyboard.press("End")
    rows = page.locator(".export-list li")
    texts = [rows.nth(i).inner_text() for i in range(rows.count())]
    private_row = next(t for t in texts if "132 photos" in t)
    assert "off the record" in private_row.lower()  # chip renders uppercase via CSS
    # and it has no download button
    assert page.locator(".export-list li.private button").count() == 0


def test_png_export_downloads(page, server_url):
    page.goto(f"{server_url}/story/2026")
    page.keyboard.press("End")
    with page.expect_download() as dl:
        page.get_by_role("button", name="PNG").first.click()
    assert dl.value.suggested_filename == "wrapped-media-total_hours.png"


def test_empty_story_shows_quiet_card(page, server_url):
    page.goto(f"{server_url}/story/2026-02")
    page.keyboard.press("ArrowRight")
    assert "A quiet one" in page.locator(".stage").inner_text()


def test_unknown_story_404s_with_listing(page, server_url):
    response = page.goto(f"{server_url}/story/1999")
    assert response.status == 404
    assert page.get_by_role("link", name="Your 2026").count() == 1


def test_reduced_motion_shows_final_number_instantly(browser, server_url, auth_cookie):
    context = browser.new_context(reduced_motion="reduce")
    context.add_cookies([{"name": "wrapped_session", "value": auth_cookie, "url": server_url}])
    page = context.new_page()
    page.goto(f"{server_url}/story/2026")
    page.keyboard.press("ArrowRight")
    assert page.locator(".display").inner_text() == "412"  # no count-up wait
    context.close()


def test_no_console_errors_through_full_story(page, server_url):
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(f"{server_url}/story/2026")
    for _ in range(7):
        page.keyboard.press("ArrowRight")
    page.wait_for_timeout(300)
    assert errors == []
