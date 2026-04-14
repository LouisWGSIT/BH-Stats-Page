import re


def _selector_block(css: str, selector: str) -> str:
    pattern = rf"{re.escape(selector)}\s*\{{(.*?)\}}"
    match = re.search(pattern, css, flags=re.S)
    assert match is not None, f"Missing selector block: {selector}"
    return match.group(1)


def _assert_props(css: str, selector: str, props: list[str]) -> None:
    block = _selector_block(css, selector)
    for prop in props:
        assert re.search(rf"\b{re.escape(prop)}\s*:", block), (
            f"Selector {selector} is missing property '{prop}'"
        )


def test_dashboard_css_contract_guards_against_global_structure_break(client):
    css_res = client.get("/styles.css")
    assert css_res.status_code == 200
    css = css_res.text

    # Basic CSS sanity guard against malformed edits.
    assert css.count("{") == css.count("}")

    # Core shell blocks that should remain valid regardless of race-track changes.
    _assert_props(
        css,
        ".download-btn",
        ["background", "border", "color", "padding", "font-size", "cursor", "transition"],
    )
    _assert_props(css, ".download-btn:hover", ["background", "box-shadow", "transform"])
    _assert_props(css, ".dashboard-nav", ["display", "align-items", "gap", "border-left", "border-right"])
    _assert_props(
        css,
        ".nav-arrow",
        ["width", "height", "display", "align-items", "justify-content", "transition"],
    )
    _assert_props(css, ".dashboard-title", ["font-size", "min-width", "text-align"])
    _assert_props(css, ".layout", ["display", "gap", "overflow", "height"])
    _assert_props(css, "main.layout", ["display", "visibility", "pointer-events"])

    # Overall dashboard sections should be present and isolated from shell styling.
    _assert_props(css, ".overall-stats-view", ["display", "padding", "overflow", "gap"])
    _assert_props(css, ".overall-section-grid", ["display", "grid-template-columns", "grid-auto-rows"])
    _assert_props(css, ".overall-support-grid", ["display", "grid-template-columns", "gap"])


def test_overall_dashboard_has_short_viewport_compaction_rules(client):
    css_res = client.get("/styles.css")
    assert css_res.status_code == 200
    css = css_res.text

    # Contract: lower effective viewport heights should trigger compact sizing rules.
    assert "@media (max-height: 980px)" in css
    compact_slice = css[css.find("@media (max-height: 980px)"):]

    for token in [
        ".overall-stats-view",
        ".overall-section-grid",
        ".overall-trend-grid",
        ".overall-support-grid",
        ".overall-submetrics",
    ]:
        assert token in compact_slice
