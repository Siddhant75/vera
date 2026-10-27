from app.config import Settings


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("TOKEN_FACTORY_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    s = Settings()
    assert s.token_factory_base_url == "https://api.tokenfactory.nebius.com/v1"
    assert s.planner_model == ""            # must be pinned from /v1/models (Task 14)
    assert s.verifier_models == []          # comma-separated env var
    assert s.db_path == "vera.db"


def test_settings_verifier_models_split(monkeypatch):
    monkeypatch.setenv("TOKEN_FACTORY_API_KEY", "k")
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    monkeypatch.setenv("VERIFIER_MODELS", "a,b")
    assert Settings().verifier_models == ["a", "b"]
