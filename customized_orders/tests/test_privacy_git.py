import json
from pathlib import Path
import subprocess
import pytest
from customized_orders.config import load,ConfigError


def private_config(tmp_path,extra=""):
    cal=tmp_path / "calendar.json"
    cal.write_text("{}")
    cal.chmod(0o600)
    p=tmp_path / "trading.toml"
    p.write_text(f"""calendar = "{cal}"
state_dir = "{tmp_path}/state"
[accounts.paper]
mode = "SHADOW"
connection = "futu"
max_quantity = "100"
max_notional = "20000"
[accounts.paper.instruments."HK.00700"]
cas = true
[connections.futu]
account_id = 987654321
unlock_env = "SECRET_ENV"
{extra}
""")
    p.chmod(0o600)
    return p


def test_private_configuration_does_not_expose_identifiers(tmp_path,setup):
    cfg=load(private_config(tmp_path))
    assert cfg.connection.account_id == 987654321
    assert "987654321" not in repr(cfg)
    e,g,t,s=setup
    pid=e.create("HK.00700","BUY",100,100,"2026-09-10")
    e.step(pid);e.step(pid)
    assert "987654321" not in json.dumps(s.status(pid))
    for file in tmp_path.rglob("*.sqlite3*"):
        assert b"987654321" not in file.read_bytes()


def test_toml_parse_error_does_not_echo_sensitive_input(tmp_path):
    p=private_config(tmp_path,'password = "secret" invalid')
    with pytest.raises(ConfigError) as caught: load(p)
    assert "secret" not in str(caught.value)


def test_gitignore_private_runtime_and_trackable_templates():
    root=Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        pytest.skip("Run in the repository to verify its gitignore")
    ignored=[".env.live","config/trading.toml","config/accounts.local.toml","private/accounts.json",
             "customized_orders/config/trading.local.toml","state/orders/live/orders.sqlite3-wal",
             "any.sqlite3-shm","orders.db-journal","trading.log","credentials.json","private-key.pem"]
    for path in ignored:
        result=subprocess.run(["git","check-ignore","--no-index","-q",path],cwd=root)
        assert result.returncode == 0,path
    for path in ["customized_orders/config/trading.example.toml","customized_orders/config/trading-calendar.example.json","plumber/plumber/futu.py"]:
        result=subprocess.run(["git","check-ignore","--no-index","-q",path],cwd=root)
        assert result.returncode == 1,path


def test_account_alias_cannot_silently_switch_real_accounts(setup):
    e,g,t,s=setup
    s.verify_account(987654321)
    s.verify_account(987654321)
    with pytest.raises(ValueError):
        s.verify_account(987654322)
    s.db.execute('PRAGMA wal_checkpoint(FULL)')
    assert b'987654321' not in s.path.read_bytes()


def test_live_enabled_must_be_a_boolean(tmp_path):
    p=private_config(tmp_path)
    p.write_text(p.read_text().replace('mode = "SHADOW"','mode = "SHADOW"\nlive_enabled = "false"'))
    with pytest.raises(ConfigError):load(p)
