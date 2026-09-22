import pytest

from webapp import config


def test_complete_environment_loads(environ):
    settings = config.load(environ)
    assert settings["GITHUB_APP_ID"] == "12345"
    assert settings["BASE_URL"] == "http://localhost:5000"  # trailing slash dropped


def test_every_missing_variable_is_named_at_once(environ):
    del environ["GITHUB_APP_ID"]
    environ["FLASK_SECRET_KEY"] = "   "
    with pytest.raises(config.ConfigError) as exc:
        config.load(environ)
    assert "GITHUB_APP_ID" in str(exc.value)
    assert "FLASK_SECRET_KEY" in str(exc.value)


def test_missing_private_key_is_reported(environ, tmp_path):
    environ["GITHUB_APP_PRIVATE_KEY_PATH"] = str(tmp_path / "nope.pem")
    with pytest.raises(config.ConfigError, match="private key"):
        config.load(environ)
