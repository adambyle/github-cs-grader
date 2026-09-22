def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.text == "ok\n"


def test_home_page_loads_the_compiled_script(client):
    assert b"/static/js/main.js" in client.get("/").data


def test_signed_out_home_offers_both_sign_ins(client):
    page = client.get("/").text
    assert "/login?as=student" in page
    assert "/login?as=instructor" in page


def test_dev_routes_are_off_unless_enabled(client):
    assert client.get("/dev/github").status_code == 404
    assert client.get("/dev/worker").status_code == 404


def test_pages_are_not_cached_but_static_files_are_untouched(client):
    assert client.get("/").headers["Cache-Control"] == "no-store"
    assert client.get("/static/css/base.css").headers.get("Cache-Control") != "no-store"
