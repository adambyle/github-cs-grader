import time
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
import respx

from webapp.github.app_auth import API, HEADERS, GitHubApp, GitHubError, app_jwt


def _expiry(seconds_from_now: int) -> str:
    when = datetime.now(UTC) + timedelta(seconds=seconds_from_now)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def gh(rsa_key):
    return GitHubApp("12345", rsa_key[1], http=httpx.Client(base_url=API, headers=HEADERS))


def test_app_jwt_claims(rsa_key):
    now = time.time()
    token = app_jwt("12345", rsa_key[1], now=now)
    claims = jwt.decode(
        token, rsa_key[0].public_key(), algorithms=["RS256"], options={"verify_iat": False}
    )
    assert claims["iss"] == "12345"
    assert claims["exp"] - claims["iat"] == 600  # GitHub's ten-minute maximum


@respx.mock
def test_installation_token_is_cached(gh):
    route = respx.post(f"{API}/app/installations/7/access_tokens").respond(
        201, json={"token": "ghs_one", "expires_at": _expiry(3600)}
    )
    assert gh.installation_token(7) == "ghs_one"
    assert gh.installation_token(7) == "ghs_one"
    assert route.call_count == 1


@respx.mock
def test_token_near_expiry_is_replaced(gh):
    route = respx.post(f"{API}/app/installations/7/access_tokens")
    route.side_effect = [
        httpx.Response(201, json={"token": "ghs_old", "expires_at": _expiry(60)}),
        httpx.Response(201, json={"token": "ghs_new", "expires_at": _expiry(3600)}),
    ]
    assert gh.installation_token(7) == "ghs_old"
    assert gh.installation_token(7) == "ghs_new"  # 60s left is inside the margin


@respx.mock
def test_github_errors_carry_the_message(gh):
    respx.get(f"{API}/app/installations").respond(401, json={"message": "Bad credentials"})
    with pytest.raises(GitHubError, match="401: Bad credentials"):
        gh.installations()
