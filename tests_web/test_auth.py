import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from conftest import sign_in_as

from webapp import auth, crypto
from webapp.access import safe_next
from webapp.extensions import db
from webapp.github.app_auth import API
from webapp.github.user_auth import TOKEN_URL, TokenSet
from webapp.models import User

PROFILE = {
    "id": 583231,
    "login": "octocat",
    "name": "The Octocat",
    "avatar_url": "https://avatars.githubusercontent.com/u/583231?v=4",
}
EMAILS = [
    {"email": "old@example.com", "primary": False, "verified": True},
    {"email": "octo@example.com", "primary": True, "verified": True},
]
TOKENS = {
    "access_token": "ghu_access",
    "expires_in": 28800,
    "refresh_token": "ghr_refresh",
    "refresh_token_expires_in": 15897600,
    "token_type": "bearer",
    "scope": "",
}


def start_login(client, mode="student", next_path=None):
    """GET /login and return the query GitHub would receive."""
    url = f"/login?as={mode}" + (f"&next={next_path}" if next_path else "")
    resp = client.get(url)
    assert resp.status_code == 302
    location = urlparse(resp.headers["Location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == (
        "https://github.com/login/oauth/authorize"
    )
    return {k: v[0] for k, v in parse_qs(location.query).items()}


def mock_github(profile=PROFILE, tokens=TOKENS):
    token_route = respx.post(TOKEN_URL).respond(200, json=tokens)
    respx.get(f"{API}/user").respond(200, json=profile)
    respx.get(f"{API}/user/emails").respond(200, json=EMAILS)
    return token_route


def users(app):
    with app.app_context():
        return db.session.scalars(db.select(User)).all()


def test_login_sends_state_and_pkce(client):
    q = start_login(client)
    assert q["client_id"] == "Iv23test"
    assert q["redirect_uri"] == "http://localhost:5000/auth/github/callback"
    assert q["code_challenge_method"] == "S256"
    with client.session_transaction() as s:
        pending = s["oauth"]
    assert pending["state"] == q["state"]
    digest = hashlib.sha256(pending["verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == q["code_challenge"]


@respx.mock
def test_callback_signs_in_and_stores_encrypted_tokens(app, client):
    q = start_login(client, mode="instructor", next_path="/somewhere")
    token_route = mock_github()
    resp = client.get(f"/auth/github/callback?code=abc&state={q['state']}")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/somewhere"

    sent = parse_qs(token_route.calls.last.request.content.decode())
    assert sent["code"] == ["abc"]
    assert "code_verifier" in sent

    [user] = users(app)
    assert (user.login, user.mode, user.email) == ("octocat", "instructor", "octo@example.com")
    with app.app_context():
        stored = db.session.get(User, user.id).token
        assert stored.access_token_enc != "ghu_access"  # never stored in the clear
        assert crypto.decrypt(stored.access_token_enc) == "ghu_access"
        assert crypto.decrypt(stored.refresh_token_enc) == "ghr_refresh"
    with client.session_transaction() as s:
        assert s["user_id"] == user.id
        assert "oauth" not in s
    assert "octocat" in client.get("/").text


@respx.mock
def test_renamed_account_is_the_same_user(app, client):
    mock_github()
    client.get(f"/auth/github/callback?code=a&state={start_login(client)['state']}")
    respx.get(f"{API}/user").respond(200, json={**PROFILE, "login": "octo-renamed"})
    client.get(f"/auth/github/callback?code=b&state={start_login(client)['state']}")
    [user] = users(app)
    assert user.login == "octo-renamed"


def test_callback_with_wrong_state_is_refused(app, client):
    start_login(client)
    resp = client.get("/auth/github/callback?code=abc&state=forged", follow_redirects=True)
    assert "start here or has expired" in resp.text  # "didn't" is HTML-escaped
    assert users(app) == []


def test_callback_without_starting_is_refused(app, client):
    resp = client.get("/auth/github/callback?code=abc&state=x", follow_redirects=True)
    assert "start here or has expired" in resp.text  # "didn't" is HTML-escaped


def test_cancelled_sign_in(client):
    start_login(client)
    resp = client.get("/auth/github/callback?error=access_denied", follow_redirects=True)
    assert "Sign-in was cancelled" in resp.text


@respx.mock
def test_github_refusing_the_code_is_reported(app, client):
    q = start_login(client)
    respx.post(TOKEN_URL).respond(
        200, json={"error": "bad_verification_code", "error_description": "The code is incorrect."}
    )
    resp = client.get(f"/auth/github/callback?code=old&state={q['state']}", follow_redirects=True)
    assert "The code is incorrect." in resp.text
    assert users(app) == []


@respx.mock
def test_sign_in_survives_missing_email_permission(app, client):
    q = start_login(client)
    respx.post(TOKEN_URL).respond(200, json=TOKENS)
    respx.get(f"{API}/user").respond(200, json=PROFILE)
    respx.get(f"{API}/user/emails").respond(403, json={"message": "Resource not accessible"})
    client.get(f"/auth/github/callback?code=a&state={q['state']}")
    [user] = users(app)
    assert user.email is None


def test_mode_switch_and_logout(app, client, make_user):
    user = make_user("ada", mode="student")
    sign_in_as(client, user)
    assert "Switch to instructor" in client.get("/").text
    client.post("/account/mode", data={"mode": "instructor"})
    assert "Switch to student" in client.get("/").text
    client.post("/logout")
    assert "/login?as=student" in client.get("/").text


def test_posts_need_a_csrf_token(app, client, make_user):
    app.config["WTF_CSRF_ENABLED"] = True
    sign_in_as(client, make_user())
    assert client.post("/logout").status_code == 400


@pytest.mark.parametrize(
    "target,ok",
    [
        ("/courses/3", True),
        ("https://evil.example/", False),
        ("//evil.example/", False),
        ("/\\evil.example", False),
        (None, False),
    ],
)
def test_safe_next(target, ok):
    assert safe_next(target) == (target if ok else None)


@respx.mock
def test_expiring_token_is_refreshed(app, make_user):
    user = make_user()
    with app.app_context():
        u = db.session.get(User, user.id)
        soon = datetime.now(UTC) + timedelta(minutes=2)
        auth.store_tokens(u, TokenSet("ghu_old", soon, "ghr_old", soon + timedelta(days=30)))
        db.session.commit()
        route = respx.post(TOKEN_URL).respond(200, json={**TOKENS, "access_token": "ghu_new"})
        assert auth.user_access_token(u) == "ghu_new"
        assert parse_qs(route.calls.last.request.content.decode())["grant_type"] == [
            "refresh_token"
        ]
        assert auth.user_access_token(u) == "ghu_new"  # no second refresh
        assert route.call_count == 1


@respx.mock
def test_failed_refresh_means_sign_in_again(app, make_user):
    user = make_user()
    with app.app_context():
        u = db.session.get(User, user.id)
        past = datetime.now(UTC) - timedelta(minutes=1)
        auth.store_tokens(u, TokenSet("ghu_old", past, "ghr_revoked", past + timedelta(days=1)))
        db.session.commit()
        respx.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"error": "bad_refresh_token"})
        )
        with pytest.raises(auth.NeedsSignIn):
            auth.user_access_token(u)
