"""Ensure relocation and paths containing spaces work without loading legacy data."""
import importlib.util
from pathlib import Path


def launcher():
    path = Path(__file__).parents[1] / 'scripts/run_records_web.py'
    spec = importlib.util.spec_from_file_location('holdings_launcher', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_paths_from_repo_env_not_working_directory(tmp_path, monkeypatch):
    module = launcher()
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / '.env').write_text(
        'VIHARA_DATA_DIR="/private/Vihara Archive"\n'
        'PORTFOLIO_HOLDINGS_DB_PATH="/private/Vihara Archive/data/holdings.sqlite3"\n'
        'INSTRUMENTS_DIR="/private/Vihara Archive/references/holdings"\n'
        'PORTFOLIO_DB_PATH=legacy.sqlite3\n'
    )
    monkeypatch.setattr(module, 'ROOT', repo)
    monkeypatch.chdir(tmp_path)
    for key in ('VIHARA_DATA_DIR','PORTFOLIO_HOLDINGS_DB_PATH','INSTRUMENTS_DIR','PORTFOLIO_DB_PATH'):
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)
    module.load_local_paths()
    assert module.os.environ['PORTFOLIO_HOLDINGS_DB_PATH'] == '/private/Vihara Archive/data/holdings.sqlite3'
    assert module.os.environ['INSTRUMENTS_DIR'] == '/private/Vihara Archive/references/holdings'
    assert 'PORTFOLIO_DB_PATH' not in module.os.environ
    monkeypatch.setenv('PORTFOLIO_HOLDINGS_DB_PATH', '/explicit/holdings.sqlite3')
    module.load_local_paths()
    assert module.os.environ['PORTFOLIO_HOLDINGS_DB_PATH'] == '/explicit/holdings.sqlite3'
