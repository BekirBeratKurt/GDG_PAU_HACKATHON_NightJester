"""code_guardian birim testleri: geçici git repolarında snapshot davranışı."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from libs.code_guardian import CodeGuardian, GitError, is_git_repo, run_git, snapshot_repo
from libs.device_state_tracker import DeviceError, clear_error, get_error_status

LABEL_TIME = datetime(2026, 11, 27, 3, 0, 0)
MIN_INTERVAL_SEC = 300.0


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    run_git(path, "init", "-q")
    # Test makinesinde global kimlik olmasa da çalışsın diye repo içi kimlik.
    run_git(path, "config", "user.name", "Test")
    run_git(path, "config", "user.email", "test@example.com")
    run_git(path, "config", "core.autocrlf", "false")
    (path / "app.py").write_text("print('v1')\n", encoding="utf-8")
    run_git(path, "add", "app.py")
    run_git(path, "commit", "-q", "-m", "ilk")
    clear_error(DeviceError.GIT_ERROR)
    return path


def _stash_list(repo: Path) -> list[str]:
    output = run_git(repo, "stash", "list")
    return output.splitlines() if output else []


def test_snapshot_stores_stash_without_touching_worktree(repo: Path) -> None:
    (repo / "app.py").write_text("print('v2 kaydedilmiş ama commitlenmemiş')\n", encoding="utf-8")
    status_before = run_git(repo, "status", "--porcelain")

    result = snapshot_repo(repo, LABEL_TIME)

    assert result.success
    stashes = _stash_list(repo)
    assert len(stashes) == 1
    assert "nightjester: uyku anı 2026-11-27 03:00:00" in stashes[0]
    assert run_git(repo, "status", "--porcelain") == status_before
    assert "v2" in (repo / "app.py").read_text(encoding="utf-8")
    assert "v2" in run_git(repo, "show", "stash@{0}:app.py")


def test_no_changes_no_stash(repo: Path) -> None:
    result = snapshot_repo(repo, LABEL_TIME)
    assert result.success
    assert "Değişiklik yok" in result.message
    assert _stash_list(repo) == []


def test_only_untracked_files_no_stash(repo: Path) -> None:
    (repo / "yeni.py").write_text("x = 1\n", encoding="utf-8")
    result = snapshot_repo(repo, LABEL_TIME)
    assert result.success
    assert "takip edilmeyen" in result.message
    assert _stash_list(repo) == []
    assert (repo / "yeni.py").exists()


def test_min_interval_blocks_second_snapshot(repo: Path) -> None:
    guardian = CodeGuardian([repo], MIN_INTERVAL_SEC)
    (repo / "app.py").write_text("print('v2')\n", encoding="utf-8")
    assert len(guardian.protect(now_sec=1000.0, label_time=LABEL_TIME)) == 1

    (repo / "app.py").write_text("print('v3')\n", encoding="utf-8")
    assert guardian.protect(now_sec=1000.0 + MIN_INTERVAL_SEC - 1, label_time=LABEL_TIME) == []
    assert len(_stash_list(repo)) == 1

    assert len(guardian.protect(now_sec=1000.0 + MIN_INTERVAL_SEC, label_time=LABEL_TIME)) == 1
    assert len(_stash_list(repo)) == 2


def test_invalid_repo_is_detected(tmp_path: Path) -> None:
    assert not is_git_repo(tmp_path / "olmayan")
    plain = tmp_path / "duz_klasor"
    plain.mkdir()
    assert not is_git_repo(plain)


def test_git_failure_raises_error_and_returns_failed_result(tmp_path: Path) -> None:
    clear_error(DeviceError.GIT_ERROR)
    guardian = CodeGuardian([tmp_path / "olmayan"], MIN_INTERVAL_SEC)
    results = guardian.protect(now_sec=0.0, label_time=LABEL_TIME)
    assert len(results) == 1 and not results[0].success
    assert get_error_status(DeviceError.GIT_ERROR)
    clear_error(DeviceError.GIT_ERROR)


def test_run_git_error_raises(repo: Path) -> None:
    with pytest.raises(GitError):
        run_git(repo, "olmayan-komut")
