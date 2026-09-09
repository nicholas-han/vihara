import json
from customized_orders import cli
from customized_orders.store import Store


def test_cli_private_config_create_worker_cancel_status(tmp_path,monkeypatch,setup,capsys):
    e,g,clock,_=setup
    calendar=tmp_path/'calendar.json'
    calendar.write_text(json.dumps(e.calendar.records));calendar.chmod(0o600)
    config=tmp_path/'trading.toml'
    config.write_text(f'''calendar = "{calendar}"
state_dir = "{tmp_path}/runtime"
[accounts.paper]
max_quantity = "1000"
max_notional = "200000"
[accounts.paper.instruments."HK.00700"]
cas = true
verified_for = "2026-09-10"
source = "fixture"
lot_size = 100
tick_size = "0.2"
tick_lower = "50"
tick_upper = "200"
auction_risk_price = "110"
''');config.chmod(0o600)
    class Frozen:
        @staticmethod
        def now(tz):return clock()
    monkeypatch.setattr(cli,'datetime',Frozen)
    monkeypatch.setattr('builtins.input',lambda _: 'CONFIRM')
    base=['--config',str(config),'--account','paper']
    assert cli.main(base+['create','--symbol','HK.00700','--side','BUY','--quantity','100','--limit-price','100','--trade-date','2026-09-10']) == 0
    output=capsys.readouterr().out
    pid=json.loads(output.splitlines()[-1])['parent_order_id']
    assert 'unpriced closing auction' in output
    assert cli.main(base+['worker','--once']) == 0
    assert cli.main(base+['worker','--once']) == 0
    capsys.readouterr()
    assert cli.main(base+['status',pid]) == 0
    assert json.loads(capsys.readouterr().out)['state'] == 'LIMIT_WORKING'
    assert cli.main(base+['cancel',pid]) == 0
    assert 'not yet confirmed' in capsys.readouterr().out
    assert cli.main(base+['worker','--once']) == 0
    assert cli.main(base+['worker','--once']) == 0
    capsys.readouterr()
    assert cli.main(base+['status',pid]) == 0
    assert json.loads(capsys.readouterr().out)['state'] == 'CANCELLED_BY_USER'
