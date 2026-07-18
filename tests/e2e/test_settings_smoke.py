"""Settings page smoke: the add-a-service flow in a real browser."""

import pytest

pytestmark = pytest.mark.e2e


def test_form_fields_follow_selected_service(page, server_url):
    page.goto(f"{server_url}/settings")
    page.get_by_role("button", name="Jellyfin").click()
    assert page.locator("#plugin-fields input[name=db_path]").count() == 1
    page.get_by_role("button", name="Immich").click()
    assert page.locator("#plugin-fields input[name=api_key]").count() == 1
    # api keys are masked while typing
    assert page.locator("input[name=api_key]").get_attribute("type") == "password"


def test_add_and_remove_service(page, server_url):
    page.goto(f"{server_url}/settings")
    page.get_by_role("button", name="Generic CSV/JSON").click()
    page.fill("input[name=name]", "my-export")
    page.fill("#plugin-fields input[name=path]", "/data/export.csv")
    page.get_by_role("button", name="Add & test connection").click()
    page.wait_for_selector(".hw-notice")
    connected = page.get_by_role("region", name="Connected services")
    assert "my-export" in connected.inner_text()

    page.get_by_role("button", name="Remove my-export").click()
    page.get_by_role("button", name="Yes, do it").click()  # confirm dialog gates removal
    page.wait_for_selector(".hw-notice:not(.hw-notice--err)")
    assert connected.locator("li").count() == 0
