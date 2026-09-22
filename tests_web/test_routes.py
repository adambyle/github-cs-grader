def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.text == "ok\n"


def test_home_page_loads_the_compiled_script(client):
    assert b"/static/js/main.js" in client.get("/").data


def test_dev_routes_are_off_unless_enabled(client):
    assert client.get("/dev/github").status_code == 404
    assert client.get("/dev/worker").status_code == 404
