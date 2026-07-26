from __future__ import annotations

from pathlib import Path

import pytest

from atf.config import ConfigError, load_manifest, resolve_env, resolve_env_refs, resolve_manifest

MANIFEST = """
catalog: ./catalog
specs: ./specs
default_env: dev
adapters:
  - my_suite.adapters
mutable_envs: [dev]
environments:
  dev:
    adapters:
      rest:
        base_url: https://dev.example.test
        auth: { header: X-Actor, value_env: ATF_ACTOR }
    clients:
      api:
        base_url: https://dev.example.test
  prod:
    adapters:
      rest: { base_url: https://prod.example.test }
display:
  systems:
    rest: { label: API, color: "#2f6be0" }
"""


def write(tmp_path: Path, text: str = MANIFEST, name: str = "atf.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_and_resolves_paths(tmp_path):
    manifest = load_manifest(write(tmp_path))
    assert manifest.root == tmp_path
    assert manifest.catalog_dir == (tmp_path / "catalog").resolve()
    assert manifest.specs_dir == (tmp_path / "specs").resolve()
    assert manifest.default_env == "dev"
    assert manifest.adapter_modules == ["my_suite.adapters"]
    assert manifest.mutable_envs == {"dev"}
    assert manifest.is_mutable("dev") and not manifest.is_mutable("prod")
    assert manifest.env("dev").adapters["rest"]["base_url"] == "https://dev.example.test"
    assert manifest.env("dev").clients["api"] == {"base_url": "https://dev.example.test"}
    assert manifest.display.system("rest").label == "API"
    assert manifest.display.system("unknown").label == "Unknown"


def test_unknown_environment(tmp_path):
    manifest = load_manifest(write(tmp_path))
    with pytest.raises(ConfigError) as err:
        manifest.env("nope")
    assert "known: dev, prod" in str(err.value)


def test_missing_required_keys(tmp_path):
    with pytest.raises(ConfigError) as err:
        load_manifest(write(tmp_path, "catalog: ./catalog\n"))
    message = str(err.value)
    assert "default_env" in message
    assert "environments" in message


def test_default_env_must_exist(tmp_path):
    text = "default_env: staging\nenvironments:\n  dev: {}\n"
    with pytest.raises(ConfigError) as err:
        load_manifest(write(tmp_path, text))
    assert "no entry under environments" in str(err.value)


def test_mutable_envs_must_be_known(tmp_path):
    text = "default_env: dev\nmutable_envs: [ghost]\nenvironments:\n  dev: {}\n"
    with pytest.raises(ConfigError) as err:
        load_manifest(write(tmp_path, text))
    assert "unknown environment(s) ghost" in str(err.value)


def test_invalid_yaml(tmp_path):
    with pytest.raises(ConfigError) as err:
        load_manifest(write(tmp_path, "default_env: [\n"))
    assert "invalid YAML" in str(err.value)


def test_resolution_prefers_env_override(tmp_path, monkeypatch):
    path = write(tmp_path)
    monkeypatch.setenv("ATF_MANIFEST", str(path))
    assert resolve_manifest(Path("/")) == path.resolve()


def test_resolution_walks_upward(tmp_path, monkeypatch):
    monkeypatch.delenv("ATF_MANIFEST", raising=False)
    path = write(tmp_path)
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert resolve_manifest(deep) == path.resolve()


def test_resolution_failure_hints_at_init(tmp_path, monkeypatch):
    monkeypatch.delenv("ATF_MANIFEST", raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ConfigError) as err:
        resolve_manifest(empty)
    assert "atf init" in str(err.value)


def test_missing_manifest_override(tmp_path, monkeypatch):
    monkeypatch.setenv("ATF_MANIFEST", str(tmp_path / "gone.yaml"))
    with pytest.raises(ConfigError):
        resolve_manifest()


def test_resolve_env(tmp_path, monkeypatch):
    manifest = load_manifest(write(tmp_path))
    monkeypatch.delenv("ATF_ENV", raising=False)
    assert resolve_env(manifest) == "dev"
    monkeypatch.setenv("ATF_ENV", "prod")
    assert resolve_env(manifest) == "prod"


def test_env_refs_are_resolved(monkeypatch):
    monkeypatch.setenv("ATF_TOKEN", "s3cret")
    settings = {"auth": {"bearer": {"token_env": "ATF_TOKEN"}}, "urls": [{"value_env": "ATF_TOKEN"}]}
    assert resolve_env_refs(settings) == {
        "auth": {"bearer": {"token": "s3cret"}},
        "urls": [{"value": "s3cret"}],
    }


def test_missing_env_var_is_an_error(monkeypatch):
    monkeypatch.delenv("ATF_TOKEN", raising=False)
    with pytest.raises(ConfigError) as err:
        resolve_env_refs({"token_env": "ATF_TOKEN"})
    assert "ATF_TOKEN is not set" in str(err.value)


def test_toml_is_rejected(tmp_path):
    path = tmp_path / "atf.toml"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError) as err:
        load_manifest(path)
    assert "atf.toml is not supported" in str(err.value)
