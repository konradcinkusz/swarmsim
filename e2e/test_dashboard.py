"""The dashboard, driven in a real browser: the person's side of the agent write gate
(docs/adr/0009) and the stop buttons. Locators by role and accessible name
(architecture-standards E2E-ACCEPTANCE-TESTING §3); every wait is a web-first assertion."""

import re
import uuid

from playwright.sync_api import expect


def _unique(name: str) -> str:
    return f"{name} {uuid.uuid4().hex[:6]}"


def test_a_person_approves_an_agents_plan_and_it_flies_only_with_the_code(page, agent):
    name = _unique("Agent survey")
    agent(name)

    page.goto("/")
    plan = page.get_by_role("article", name=name)
    expect(plan).to_contain_text("PendingApproval")
    plan.get_by_role("button", name="Approve").click()

    code = plan.get_by_label("Approval code")
    expect(code).to_have_text(re.compile(r"^[A-Za-z0-9_-]{32}$"))
    expect(plan).to_contain_text("Approved")
    plan.get_by_role("button", name="Dispatch now").click()

    expect(
        page.get_by_text(re.compile(rf'"{re.escape(name)}" — Active'))
    ).to_be_visible()
    expect(page.get_by_role("article", name=name)).to_have_count(0)  # no longer waiting
    expect(page.locator("#drone-table tbody tr")).to_have_count(2)


def test_the_approval_code_is_shown_once_and_a_reload_forgets_it(page, agent):
    name = _unique("Shown once")
    agent(name)

    page.goto("/")
    plan = page.get_by_role("article", name=name)
    plan.get_by_role("button", name="Approve").click()
    expect(plan.get_by_label("Approval code")).to_be_visible()

    page.reload()
    plan = page.get_by_role("article", name=name)
    expect(plan).to_contain_text("Approved")
    expect(plan.get_by_label("Approval code")).to_have_count(0)
    expect(plan.get_by_role("button", name="Dispatch now")).to_have_count(0)


def test_a_plan_whose_drones_would_collide_cannot_be_approved(page, agent):
    # Lanes 1 m apart are too close wherever the drones start (the swarm's state carries
    # over between tests, and the preview plans from where the drones are).
    name = _unique("Lanes too close")
    agent(name, drone_count=2, spacing=1.0)

    page.goto("/")
    plan = page.get_by_role("article", name=name)
    expect(plan).to_contain_text("Conflicted")
    expect(plan).to_contain_text("drone_1 and drone_2 within")
    expect(plan.get_by_role("button", name="Approve")).to_be_disabled()
    plan.get_by_role("button", name="Reject").click()
    expect(page.get_by_role("article", name=name)).to_have_count(0)


def test_land_all_lands_every_drone_where_it_is(page):
    page.goto("/")
    page.get_by_role("button", name="Start demo mission").click()
    expect(page.get_by_role("status").filter(has_text="dispatched")).to_be_visible()
    rows = page.locator("#drone-table tbody tr")
    expect(rows).to_have_count(3)

    page.get_by_role("button", name="Land all drones now").click()

    expect(page.get_by_text("Land all sent")).to_be_visible()
    expect(page.get_by_text("No mission is flying.")).to_be_visible()
    for row in rows.all():
        expect(row).to_contain_text(re.compile("Landing|Landed"))
