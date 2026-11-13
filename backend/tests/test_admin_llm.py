# ruff: noqa: F811  (the cognito fixture is imported from test_auth and re-declared)
"""Admin LLM settings (docs/API_CONTRACT.md §10): provider / model / Bedrock auth mode and
provider keys, saved encrypted, never returned."""

import json
from types import SimpleNamespace

import pytest

from app.llm import config_store
from tests.test_auth import bearer, cognito  # noqa: F401 (fixture)

API_KEY = "ABSKexample-bedrock-api-key-1234"
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


def _put(client, body, headers=None):
    return client.put("/api/admin/llm", json=body, headers=headers).json()


def _bedrock(**kw) -> dict:
    return {"model": "anthropic.claude-opus-5-5", "region": "ap-southeast-2", **kw}


# ---- who may ----------------------------------------------------------------------------


def test_the_local_user_is_admin(client):
    assert client.get("/api/me").json()["data"]["is_admin"] is True
    assert client.get("/api/admin/llm").status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/admin/llm"),
        ("PUT", "/api/admin/llm"),
        ("DELETE", "/api/admin/llm"),
        ("POST", "/api/admin/llm/test"),
    ],
)
def test_only_admins(client, cognito, method, path):  # noqa: F811
    body = {"provider": "mock"} if method == "PUT" else None
    r = client.request(method, path, headers=bearer("user-x"), json=body)
    assert (r.status_code, r.json()["error"], r.json()["message"]) == (
        403,
        "FORBIDDEN",
        "Admin only",
    )
    assert client.request(method, path, json=body).status_code == 401  # not signed in


@pytest.mark.parametrize("groups", [["admin"], ["users", "admin"], "[admin users]"])
def test_the_cognito_admin_group(client, cognito, groups):  # noqa: F811
    """A verified token carries a list; behind the API Gateway authorizer a string."""
    h = bearer("boss", **{"cognito:groups": groups})
    assert client.get("/api/me", headers=h).json()["data"]["is_admin"] is True
    assert client.get("/api/admin/llm", headers=h).status_code == 200


# ---- reading and saving -------------------------------------------------------------------


def test_without_saved_settings_the_environment_is_shown(client):
    data = client.get("/api/admin/llm").json()["data"]
    assert data["source"] == "env" and data["provider"] == "mock" and data["storage"] == "file"
    assert data["bedrock"]["auth"] == "iam"
    assert data["bedrock"]["secrets"]["api_key"] == {"set": False, "hint": None, "updated_at": None}


def test_a_saved_key_is_never_returned_and_is_encrypted(client, llm_config_file):
    body = {
        "provider": "bedrock",
        "bedrock": _bedrock(auth="api_key"),
        "secrets": {"bedrock.api_key": API_KEY},
    }
    r = _put(client, body)
    assert (r["status_code"], r["message"]) == (200, "LLM settings saved")
    data = r["data"]
    assert (data["source"], data["provider"], data["updated_by"]) == ("admin", "bedrock", "local")
    secret = data["bedrock"]["secrets"]["api_key"]
    assert secret["set"] is True and secret["hint"] == "…1234" and secret["updated_at"]
    for response in (r, client.get("/api/admin/llm").json()):
        assert API_KEY not in json.dumps(response)
    raw = llm_config_file.read_bytes()
    assert API_KEY.encode() not in raw and b"bedrock" not in raw  # encrypted at rest

    s = config_store.effective_settings()
    assert s.llm_provider == "bedrock" and s.bedrock_auth == "api_key"
    assert s.bedrock_api_key.get_secret_value() == API_KEY
    assert client.get("/api/health").json()["data"]["llm_provider"] == "bedrock"


def test_keys_are_kept_unless_replaced_or_removed(client):
    _put(
        client,
        {
            "provider": "bedrock",
            "bedrock": _bedrock(auth="api_key"),
            "secrets": {"bedrock.api_key": API_KEY},
        },
    )
    # change only the model: the key stays
    data = _put(
        client, {"provider": "bedrock", "bedrock": _bedrock(model="anthropic.x", auth="api_key")}
    )
    assert data["data"]["bedrock"]["secrets"]["api_key"]["set"] is True
    assert config_store.effective_settings().bedrock_model_id == "anthropic.x"
    # remove it: api_key auth is no longer usable
    r = _put(
        client,
        {
            "provider": "bedrock",
            "bedrock": _bedrock(auth="api_key"),
            "secrets": {"bedrock.api_key": None},
        },
    )
    assert r["status_code"] == 422 and "needs a Bedrock API key" in r["message"]
    # removed while another auth is chosen
    r = _put(
        client,
        {
            "provider": "bedrock",
            "bedrock": _bedrock(auth="iam"),
            "secrets": {"bedrock.api_key": None},
        },
    )
    assert r["data"]["bedrock"]["secrets"]["api_key"]["set"] is False


def test_the_access_key_id_is_masked_and_kept(client):
    body = {
        "provider": "bedrock",
        "bedrock": _bedrock(auth="access_key", access_key_id="AKIAIOSFODNN7EXAMPLE"),
        "secrets": {"bedrock.secret_access_key": SECRET},
    }
    data = _put(client, body)["data"]
    assert data["bedrock"]["access_key_id"] == "AKIA****MPLE"
    # the form sends the masked id back unchanged: keep the stored one
    body = {
        "provider": "bedrock",
        "bedrock": _bedrock(auth="access_key", access_key_id="AKIA****MPLE"),
    }
    assert _put(client, body)["status_code"] == 200
    s = config_store.effective_settings()
    assert s.bedrock_access_key_id == "AKIAIOSFODNN7EXAMPLE"
    assert s.bedrock_secret_access_key.get_secret_value() == SECRET


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"provider": "bedrock", "bedrock": _bedrock(auth="access_key")}, "needs access_key_id"),
        ({"provider": "bedrock", "bedrock": _bedrock(auth="assume_role")}, "needs role_arn"),
        (
            {"provider": "bedrock", "bedrock": _bedrock(role_arn="arn:aws:iam::1:user/x")},
            "role_arn",
        ),
        ({"provider": "bedrock", "bedrock": _bedrock(region="Sydney")}, "region"),
        ({"provider": "bedrock", "bedrock": _bedrock(model="")}, "bedrock.model"),
        ({"provider": "anthropic", "anthropic": {"model": "claude-opus-5-5"}}, "needs an API key"),
        ({"provider": "openai", "openai": {"model": "m", "base_url": "ftp://x"}}, "base_url"),
        (
            {"provider": "openai", "openai": {"model": "", "base_url": "http://h/v1"}},
            "openai.model",
        ),
        ({"provider": "mock", "secrets": {"aws.root": "x"}}, "unknown secret"),
        ({"provider": "mock", "secrets": {"openai.api_key": " "}}, "cannot be empty"),
    ],
)
def test_incomplete_or_malformed_settings_are_refused(client, body, message):
    r = _put(client, body)
    assert r["status_code"] == 422 and r["error"] == "VALIDATION_ERROR", r
    assert message in r["message"]
    assert client.get("/api/admin/llm").json()["data"]["source"] == "env"  # nothing saved


def test_keys_from_the_environment_survive_the_first_save(client, monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "anthropic_base_url", "https://gw.example")
    monkeypatch.setattr(s, "anthropic_auth_token", "gw-token-from-the-env-9876")
    data = client.get("/api/admin/llm").json()["data"]
    assert data["anthropic"]["secrets"]["api_key"]["hint"] == "…9876"
    r = _put(
        client,
        {
            "provider": "anthropic",
            "anthropic": {"model": "gemini-3.8-flash", "base_url": "https://gw.example"},
        },
    )
    assert r["status_code"] == 200, r
    eff = config_store.effective_settings()
    # a gateway: the key is the Bearer token
    assert eff.anthropic_auth_token == "gw-token-from-the-env-9876" and eff.anthropic_api_key == ""


def test_reset_goes_back_to_the_environment(client):
    _put(client, {"provider": "bedrock", "bedrock": _bedrock()})
    r = client.delete("/api/admin/llm").json()
    assert r["message"] == "LLM settings reset" and r["data"]["source"] == "env"
    assert config_store.effective_settings().llm_provider == "mock"


def test_an_unreadable_store_falls_back_to_the_environment(client, llm_config_file):
    llm_config_file.write_bytes(b"not a fernet token")
    config_store.forget_cache()
    assert config_store.effective_settings().llm_provider == "mock"
    r = client.get("/api/admin/llm").json()
    assert (r["status_code"], r["error"]) == (500, "INTERNAL")


# ---- providers built from the settings ----------------------------------------------------


def test_the_saved_choice_builds_the_provider(client):
    from app.llm.factory import get_provider
    from app.llm.openai_compatible import OpenAICompatibleProvider

    _put(
        client,
        {
            "provider": "openai",
            "openai": {"model": "qwen2.5:latest", "base_url": "http://localhost:11434/v1"},
            "secrets": {"openai.api_key": "sk-local-123456789"},
        },
    )
    provider = get_provider()
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider._settings.openai_model == "qwen2.5:latest"
    assert provider._settings.openai_api_key.get_secret_value() == "sk-local-123456789"


def test_bedrock_auth_modes():
    from app.config import get_settings
    from app.llm import bedrock

    base = get_settings().model_copy(
        update={"bedrock_region": "ap-southeast-2", "platform_aws_profile": "platform"}
    )
    assert bedrock._auth_kwargs(base) == {"aws_profile": "platform"}  # iam
    from pydantic import SecretStr

    api = base.model_copy(update={"bedrock_auth": "api_key", "bedrock_api_key": SecretStr(API_KEY)})
    assert bedrock._auth_kwargs(api) == {"api_key": API_KEY}
    pair = base.model_copy(
        update={
            "bedrock_auth": "access_key",
            "bedrock_access_key_id": "AKIAIOSFODNN7EXAMPLE",
            "bedrock_secret_access_key": SecretStr(SECRET),
        }
    )
    assert bedrock._auth_kwargs(pair) == {
        "aws_access_key": "AKIAIOSFODNN7EXAMPLE",
        "aws_secret_key": SECRET,
    }
    for incomplete in ("api_key", "access_key", "assume_role"):
        with pytest.raises(bedrock.LLMError, match=incomplete):
            bedrock._auth_kwargs(base.model_copy(update={"bedrock_auth": incomplete}))
    # each mode builds a Mantle client
    for s in (api, pair):
        assert bedrock.BedrockProvider(s).client is not None


def test_bedrock_assume_role_reuses_credentials_that_outlive_a_job(aws, monkeypatch):
    from app.aws import credentials
    from app.config import get_settings
    from app.llm import bedrock

    sts = aws.client("sts")
    calls = []
    original = sts.assume_role

    def assume_role(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(sts, "assume_role", assume_role)
    monkeypatch.setattr(
        credentials, "platform_session", lambda: SimpleNamespace(client=lambda _: sts)
    )
    bedrock._role_cache.clear()
    s = get_settings().model_copy(
        update={
            "bedrock_auth": "assume_role",
            "bedrock_role_arn": "arn:aws:iam::487450071041:role/AutoAWSBedrockInvoke",
            "bedrock_external_id": "ext-1",
            "bedrock_region": "ap-southeast-2",
        }
    )
    first = bedrock._auth_kwargs(s)
    assert set(first) == {"aws_access_key", "aws_secret_key", "aws_session_token"}
    assert bedrock._auth_kwargs(s) == first and len(calls) == 1
    assert calls[0]["ExternalId"] == "ext-1" and calls[0]["RoleSessionName"] == "autoaws-bedrock"


# ---- test endpoint --------------------------------------------------------------------------


def test_the_test_button_reports_success_and_failure(client):
    data = client.post("/api/admin/llm/test").json()["data"]
    assert data["ok"] is True and data["provider"] == "mock" and data["latency_ms"] is not None
    _put(
        client,
        {"provider": "openai", "openai": {"model": "m", "base_url": "http://127.0.0.1:9/v1"}},
    )
    data = client.post("/api/admin/llm/test").json()["data"]
    assert data["ok"] is False and data["provider"] == "openai" and data["error"]


def test_on_lambda_the_agent_worker_runs_the_test(client, monkeypatch):
    from app.config import get_settings
    from app.handlers import agent_worker
    from app.platform import dispatch
    from tests.test_serverless import FakePlatform

    result = agent_worker.handler({"mode": "llm_test"})
    assert result["ok"] is True and result["provider"] == "mock"

    s = get_settings()
    monkeypatch.setattr(s, "runtime", "lambda")
    monkeypatch.setattr(s, "agent_worker_function", "autoaws-agent-worker")
    fake = FakePlatform()
    fake.verify_payload = result
    monkeypatch.setattr(dispatch, "_client", fake)
    data = client.post("/api/admin/llm/test").json()["data"]
    assert data == result
    sync = [k for op, k in fake.calls if k.get("InvocationType") == "RequestResponse"]
    assert json.loads(sync[-1]["Payload"]) == {"mode": "llm_test"}


# ---- Secrets Manager backend (deployed) -------------------------------------------------


def test_secrets_manager_backend(aws, monkeypatch):
    from app.aws import credentials
    from app.config import get_settings

    sm = aws.client("secretsmanager")
    sm.create_secret(Name="autoaws/llm-config", SecretString="{}")
    monkeypatch.setattr(
        credentials, "platform_session", lambda: SimpleNamespace(client=lambda _: sm)
    )
    s = get_settings().model_copy(
        update={
            "llm_config_backend": "secretsmanager",
            "llm_config_secret_id": "autoaws/llm-config",
        }
    )
    assert config_store.load(s, fresh=True) == {}
    doc = config_store.updated(
        {},
        {"provider": "bedrock", "bedrock": _bedrock(auth="api_key")},
        {"bedrock.api_key": API_KEY},
        "admin",
        s,
    )
    config_store.save(doc, s)
    stored = json.loads(sm.get_secret_value(SecretId="autoaws/llm-config")["SecretString"])
    assert (
        stored["secrets"]["bedrock.api_key"]["value"] == API_KEY
    )  # inside the KMS-encrypted secret
    assert config_store.load(s, fresh=True)["provider"] == "bedrock"
    assert config_store.view(stored, s)["storage"] == "secretsmanager"

    missing = s.model_copy(update={"llm_config_secret_id": "autoaws/missing"})
    assert config_store.load(missing, fresh=True) == {}
