"""Protect the independence of the dev-only corpus experiment."""
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[3]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("relative", ["production", "production/child", "."])
def test_dev_storage_cannot_overlap_production(tmp_path, relative):
    module = load("serve_validation_library")
    env = tmp_path / ".env"
    env.write_text("APP_MODE=mock\nDATA_DIR=" + str(tmp_path / "production"), encoding="utf-8")
    with pytest.raises(ValueError, match="disjoint"):
        module.validation_settings(env, tmp_path / relative)


def test_separate_storage_has_no_production_paths(tmp_path):
    module = load("serve_validation_library")
    env = tmp_path / ".env"
    env.write_text("APP_MODE=mock\nDATA_DIR=" + str(tmp_path / "production"), encoding="utf-8")
    target = tmp_path / "dev"
    settings = module.validation_settings(env, target)
    assert settings.db_path == target / "library.sqlite"
    assert settings.files_dir == target / "raw" and settings.index_dir == target / "indexes"
    assert not target.exists()


def test_existing_unmarked_data_is_not_adopted(tmp_path):
    module = load("serve_validation_library")
    env = tmp_path / ".env"
    env.write_text("APP_MODE=mock\nDATA_DIR=" + str(tmp_path / "production"), encoding="utf-8")
    target = tmp_path / "dev"
    target.mkdir()
    (target / "old.sqlite").write_bytes(b"existing")
    with pytest.raises(ValueError, match="marker"):
        module.validation_settings(env, target)


@pytest.mark.parametrize("marker", [{}, {"validation_only": False},
                                   {"validation_only": True, "code": {"commit": "other"}}])
def test_preview_requires_matching_validation_marker(marker):
    module = load("preview_domain_trial")
    api = Mock()
    api.request.return_value = marker
    with pytest.raises(ValueError, match="identity"):
        module.require_dev(api, {"commit": "frozen"})
    api.submit.assert_not_called()
