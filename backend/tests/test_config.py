import pytest

from app.config import Settings


def test_settings_defaults(monkeypatch):
    for var in ("TOKEN_FACTORY_API_KEY", "TAVILY_API_KEY", "TOKEN_FACTORY_BASE_URL",
                "PLANNER_MODEL", "VERIFIER_MODELS", "DB_PATH"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TOKEN_FACTORY_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    s = Settings(_env_file=None)
    assert s.token_factory_base_url == "https://api.tokenfactory.nebius.com/v1"
    assert s.planner_model == ""            # must be pinned from /v1/models (Task 14)
    assert s.verifier_models == []          # comma-separated env var
    assert s.db_path == "vera.db"


def test_settings_verifier_models_split(monkeypatch):
    monkeypatch.setenv("TOKEN_FACTORY_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    monkeypatch.setenv("VERIFIER_MODELS", "a,b")
    assert Settings(_env_file=None).verifier_models == ["a", "b"]


def test_verifier_models_must_differ_from_planner(monkeypatch):
    monkeypatch.setenv("TOKEN_FACTORY_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    monkeypatch.setenv("PLANNER_MODEL", "nemotron")
    monkeypatch.setenv("VERIFIER_MODELS", "nemotron,other")
    with pytest.raises(ValueError, match="verifier"):
        Settings(_env_file=None)


def test_verifier_models_need_two(monkeypatch):
    monkeypatch.setenv("TOKEN_FACTORY_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    monkeypatch.setenv("VERIFIER_MODELS", "only-one")
    with pytest.raises(ValueError, match="verifier"):
        Settings(_env_file=None)


def test_build_app_refuses_unconfigured_models():
    from app.main import build_app
    from app.config import Settings
    hermetic = Settings(_env_file=None, token_factory_api_key="k", tavily_api_key="t",
                        planner_model="", verifier_models=[])
    with pytest.raises(ValueError, match="PLANNER_MODEL"):
        build_app(hermetic)
