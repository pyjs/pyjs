import pytest

from scripts.check_distributions import PACKAGES, distributions


def test_installation_requires_every_workspace_distribution(tmp_path):
    for name in PACKAGES:
        (tmp_path / f"{name}-0.5.0-py3-none-any.whl").touch()
        (tmp_path / f"{name}-0.5.0.tar.gz").touch()
    assert len(distributions(tmp_path)) == 3
    (tmp_path / "pyjs_examples-0.5.0-py3-none-any.whl").unlink()
    with pytest.raises(ValueError, match="every workspace package"):
        distributions(tmp_path)


def test_stale_duplicate_wheels_are_not_installed(tmp_path):
    for name in PACKAGES:
        (tmp_path / f"{name}-0.5.0-py3-none-any.whl").touch()
        (tmp_path / f"{name}-0.5.0.tar.gz").touch()
    (tmp_path / "pyjs-0.4.0-py3-none-any.whl").touch()
    with pytest.raises(ValueError, match="one wheel"):
        distributions(tmp_path)


def test_wrong_source_archive_cannot_satisfy_package_count(tmp_path):
    for name in PACKAGES:
        (tmp_path / f"{name}-0.5.0-py3-none-any.whl").touch()
        (tmp_path / f"{name}-0.5.0.tar.gz").touch()
    (tmp_path / "pyjs_examples-0.5.0.tar.gz").rename(tmp_path / "unrelated-0.5.0.tar.gz")
    with pytest.raises(ValueError, match="every workspace package"):
        distributions(tmp_path)
