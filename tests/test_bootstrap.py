from __future__ import annotations

import pytest

from atf.bootstrap import bootstrap
from atf.config import ConfigError

MANIFEST = """
catalog: ./catalog
specs: ./specs
default_env: dev
adapters:
  - suite_adapters
mutable_envs: [dev]
environments:
  dev:
    adapters:
      rest:
        base_url: https://dev.example.test
        auth: { bearer: { token_env: ATF_TOKEN } }
      custom: {}
    clients:
      api:
        base_url: https://dev.example.test
        auth: { header: X-Actor, value_env: ATF_ACTOR }
  prod:
    adapters:
      rest: { base_url: https://prod.example.test }
    clients:
      api: { base_url: https://prod.example.test }
"""

TYPES = """
account:
  system: rest
  path: /accounts
  natural_key: email
thing:
  system: custom
  natural_key: name
"""

ADAPTER_MODULE = '''
from atf.adapters import register

BUILT = []


class Custom:
    def __init__(self, settings):
        self.settings = settings

    def find(self, node, ctx):
        return None

    def create(self, node, body, ctx):
        return {"id": "custom-1"}

    def delete(self, node, record, ctx):
        return None


def _factory(settings):
    adapter = Custom(settings)
    BUILT.append(adapter)
    return adapter


register("custom", _factory)
'''


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "atf.yaml").write_text(MANIFEST, encoding="utf-8")
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    (catalog / "resources.yaml").write_text(TYPES, encoding="utf-8")
    (catalog / "accounts.yaml").write_text(
        "primary:\n  resource: account\n  represents: x\n  body: {email: a@b.test}\n", encoding="utf-8"
    )
    (catalog / "things.yaml").write_text(
        "one:\n  resource: thing\n  represents: x\n  body: {name: one}\n", encoding="utf-8"
    )
    (tmp_path / "suite_adapters.py").write_text(ADAPTER_MODULE, encoding="utf-8")
    monkeypatch.setenv("ATF_MANIFEST", str(tmp_path / "atf.yaml"))
    monkeypatch.setenv("ATF_TOKEN", "t0ken")
    monkeypatch.setenv("ATF_ACTOR", "actor-1")
    monkeypatch.delenv("ATF_ENV", raising=False)
    yield tmp_path
    import sys

    sys.modules.pop("suite_adapters", None)
    from atf.adapters import unregister

    unregister("custom")


def test_bootstrap_builds_adapters_clients_and_catalog(project):
    boot = bootstrap()
    assert boot.env == "dev"
    assert set(boot.materializer.nodes) == {"accounts.primary", "things.one"}
    assert set(boot.materializer.adapters) == {"rest", "custom"}
    assert boot.clients == {
        "api": {"base_url": "https://dev.example.test", "auth": {"header": "X-Actor", "value": "actor-1"}}
    }

    rest = boot.materializer.adapters["rest"]
    assert rest.auth == {"bearer": {"token": "t0ken"}}  # env pointer resolved once, at bootstrap


def test_bootstrap_registers_project_adapters(project):
    boot = bootstrap()
    import suite_adapters

    assert len(suite_adapters.BUILT) == 1
    assert boot.materializer.adapters["custom"] is suite_adapters.BUILT[0]


def test_bootstrap_honours_atf_env(project, monkeypatch):
    monkeypatch.setenv("ATF_ENV", "prod")
    boot = bootstrap()
    assert boot.env == "prod"
    assert boot.manifest.is_mutable("prod") is False
    # prod configures no `custom` adapter: that node reports unsupported rather than exploding
    assert boot.materializer.status()["things.one"]["status"] == "unsupported"


def test_explicit_env_beats_the_environment(project, monkeypatch):
    monkeypatch.setenv("ATF_ENV", "prod")
    assert bootstrap("dev").env == "dev"


def test_unknown_env_is_an_error(project):
    with pytest.raises(ConfigError, match="unknown environment"):
        bootstrap("nowhere")


def test_missing_secret_is_an_error(project, monkeypatch):
    monkeypatch.delenv("ATF_TOKEN")
    with pytest.raises(ConfigError, match="ATF_TOKEN is not set"):
        bootstrap()
