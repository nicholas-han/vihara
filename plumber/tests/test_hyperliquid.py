"""Offline Hyperliquid integration tests. No SDK/network/key material required."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
import json
import os
import subprocess
import sys
import threading
import pytest
from plumber.hyperliquid import HyperliquidConfig, HyperliquidClient, ExchangeService, FundsService, InfoService, WsService, load_config
from plumber.hyperliquid import client as client_module, ws_service, main, prepare_agent
from plumber.models import UnknownResult, Unavailable

ADDRESS = '0x' + '1' * 40
AGENT = '0x' + '2' * 40
SECRET = 'synthetic-secret-not-a-key'


@pytest.fixture
def sdk(monkeypatch):
    calls = []
    class Account:
        @staticmethod
        def from_key(key):
            calls.append(('signer',))
            return NS(address=ADDRESS)
    class Info:
        def __init__(self, url, skip_ws=True, timeout=None):
            self.ws_manager = None if skip_ws else object()
            self.disconnected = 0
            calls.append(('info',url,skip_ws,timeout))
        def user_role(self,address):return {'role':'user'}
        def disconnect_websocket(self):self.disconnected += 1
        def all_mids(self):return {'BTC':'100'}
        def open_orders(self,address):
            calls.append(('orders',address));return [{'coin':'BTC','oid':7},{'coin':'ETH','oid':8}]
        def subscribe(self,sub,callback):calls.append(('subscribe',sub));return 3
        def query_order_by_cloid(self,address,cloid):return {'status':'order','order':{'status':'canceled'}}
    class Exchange:
        def __init__(self,wallet,url,account_address=None,timeout=None):
            self.wallet,self.account_address=wallet,account_address
            self.info=NS(ws_manager=None)
            calls.append(('exchange',url,timeout))
        def __getattr__(self,name):
            def call(*args,**kw):
                calls.append((name,args,kw))
                return {'response':{'data':{'statuses':[{'resting':{'oid':7}}]}}}
            return call
    factory=lambda:(Account,Exchange,Info)
    monkeypatch.setattr(client_module,'load_sdk',factory)
    monkeypatch.setattr(ws_service,'load_sdk',factory)
    from plumber.hyperliquid import _websocket
    monkeypatch.setattr(_websocket,'connect_manager',lambda cfg:NS(finished=threading.Event()))
    return calls,Info,Exchange


def config(**kwargs):
    return HyperliquidConfig(private_key=SECRET,trading_enabled=True,**kwargs)


def test_import_never_loads_optional_sdk_or_environment():
    code="import sys; import plumber.hyperliquid; assert 'hyperliquid' not in sys.modules; assert 'dotenv' not in sys.modules; assert 'eth_account' not in sys.modules"
    env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]),'PYTHONDONTWRITEBYTECODE':'1'}
    subprocess.run([sys.executable,'-c',code],env=env,check=True,capture_output=True)


def test_default_is_readonly_even_with_key(sdk):
    calls,_,_=sdk
    with HyperliquidClient(config()) as c:
        assert InfoService(c).get_mid('BTC')=='100'
        with pytest.raises(ValueError):ExchangeService(c).place_limit_order('BTC','buy',1,100)
    assert not any(x[0] in {'signer','exchange','order'} for x in calls)
    assert 'testnet' in calls[0][1]


@pytest.mark.parametrize('kwargs',[{'network':'MAINNET'},{'trading_enabled':'false'},{'funds_enabled':1},{'timeout':float('nan')},{'timeout':0},{'account_address':'bad'}])
def test_config_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):HyperliquidConfig(**kwargs)


def test_private_config_and_repr(tmp_path):
    key=tmp_path/'agent.key';key.write_text(SECRET);key.chmod(0o600)
    path=tmp_path/'hyperliquid.toml';path.write_text(f'private_key_file = "{key}"\naccount_address = "{AGENT}"\n');path.chmod(0o600)
    cfg=load_config(path)
    assert cfg.private_key==SECRET and cfg.account_address==AGENT
    assert SECRET not in repr(cfg) and AGENT not in repr(cfg)
    path.chmod(0o644)
    with pytest.raises(ValueError):load_config(path)


def test_private_config_rejects_git_symlinks_and_inline_keys(tmp_path):
    path=tmp_path/'config.toml';path.write_text('private_key="NEVER_INLINE"');path.chmod(0o600)
    with pytest.raises(ValueError):load_config(path)
    path.write_text('network="testnet"')
    link=tmp_path/'link.toml';link.symlink_to(path)
    with pytest.raises(ValueError):load_config(link)
    (tmp_path/'.git').mkdir()
    with pytest.raises(ValueError):load_config(path)


def test_private_config_env_explicit_only(tmp_path,monkeypatch):
    monkeypatch.setenv('VIHARA_HL_PRIVATE_KEY',SECRET)
    monkeypatch.setenv('HL_PRIVATE_KEY',SECRET)
    assert HyperliquidConfig().private_key is None
    path=tmp_path/'config.toml';path.write_text('private_key_env="VIHARA_HL_PRIVATE_KEY"');path.chmod(0o600)
    assert load_config(path).private_key==SECRET
    path.write_text('private_key_env="VIHARA_HL_PRIVATE_KEY"\nprivate_key_file="missing"')
    with pytest.raises(ValueError):load_config(path)


def test_mainnet_requires_explicit_mutation_confirmation(sdk):
    with pytest.raises(ValueError,match='Mainnet'):
        HyperliquidClient(config(network='mainnet'),allow_trading=True)
    with HyperliquidClient(config(network='mainnet'),allow_trading=True,confirm_mainnet=True) as c:
        ExchangeService(c).cancel_order('BTC',7)


def test_wallet_fallback_and_agent_address(sdk):
    calls,Info,_=sdk
    with HyperliquidClient(config(),allow_trading=True) as c:
        assert c.address==ADDRESS
        ExchangeService(c).cancel_all_orders('BTC')
    assert ('orders',ADDRESS) in calls
    assert len([x for x in calls if x[0]=='cancel'])==1
    original=Info.user_role
    Info.user_role=lambda self,address:{'role':'agent','data':{'user':AGENT}}
    with HyperliquidClient(config(account_address=AGENT),allow_trading=True) as c:assert c.address==AGENT
    Info.user_role=original
    with HyperliquidClient(HyperliquidConfig(account_address=AGENT)) as c:assert c.address==AGENT


def test_trade_and_funds_capabilities_are_independent(sdk):
    cfg=config(funds_enabled=True)
    with HyperliquidClient(cfg,allow_trading=True) as c:
        with pytest.raises(ValueError):FundsService(c).transfer_usd(1,ADDRESS)
        with pytest.raises(ValueError):c.mutate('usd_transfer',1,ADDRESS)
    with HyperliquidClient(cfg,allow_funds=True) as c:
        FundsService(c).transfer_usd(1,ADDRESS)
        with pytest.raises(ValueError):ExchangeService(c).cancel_order('BTC',7)
        with pytest.raises(ValueError):c.mutate('approve_agent')
    with pytest.raises(ValueError):HyperliquidClient(config(),allow_funds=True)


@pytest.mark.parametrize('side,size,price',[('BUY',1,100),('oops',1,100),('buy',0,100),('sell',float('inf'),100),('buy',True,100),('buy',1,float('nan'))])
def test_invalid_orders_never_reach_exchange(sdk,side,size,price):
    calls,_,_=sdk
    with HyperliquidClient(config(),allow_trading=True) as c:
        with pytest.raises(ValueError):ExchangeService(c).place_limit_order('BTC',side,size,price)
    assert not any(x[0]=='order' for x in calls)


def test_order_forwarding_and_unknown_result_no_retry(sdk):
    calls,_,_=sdk
    with HyperliquidClient(config(),allow_trading=True) as c:
        ExchangeService(c).place_limit_order('BTC','sell',1,100,tif='Alo',reduce_only=True)
        call=next(x for x in calls if x[0]=='order')
        assert call[1]==('BTC',False,1,100,{'limit':{'tif':'Alo'}}) and call[2]['reduce_only']
        def fail(*a,**kw):calls.append(('failed',));raise RuntimeError(SECRET)
        c._exchange.order=fail
        with pytest.raises(UnknownResult) as error:ExchangeService(c).place_limit_order('BTC','buy',1,100)
        assert SECRET not in str(error.value) and error.value.__suppress_context__
        assert calls.count(('failed',))==1


def test_websocket_close_unblocks_run_and_is_idempotent(sdk):
    with WsService() as service:
        service.subscribe_orderbook('BTC',lambda _:None)
        thread=threading.Thread(target=service.run);thread.start()
        service.close();thread.join(timeout=1)
        assert not thread.is_alive()
        assert service._info.disconnected==1
        with pytest.raises(ValueError):service.subscribe_all_mids(lambda _:None)
    assert service._info.disconnected==1


def test_failed_metadata_initialization_never_starts_ws(sdk,monkeypatch):
    from plumber.hyperliquid._sdk import make_info
    _,Info,_=sdk
    original=Info.__init__;instances=[]
    def fail(self,*a,**kw):
        original(self,*a,**kw);instances.append(self);raise RuntimeError('failed init')
    monkeypatch.setattr(Info,'__init__',fail)
    from plumber.hyperliquid import _websocket
    connections=[]
    monkeypatch.setattr(_websocket,'connect_manager',lambda cfg:connections.append(cfg))
    with pytest.raises(RuntimeError):make_info(Info,HyperliquidConfig(),skip_ws=False)
    assert instances[0].ws_manager is None and not connections


def test_demo_default_never_trades(sdk,monkeypatch):
    monkeypatch.setattr(main,'load_config',lambda _:config())
    assert main.main(['--config','unused'])==0
    assert not any(x[0] in {'order','signer'} for x in sdk[0])


def test_demo_cleans_up_after_readback_failure(sdk,monkeypatch):
    monkeypatch.setattr(main,'new_cloid',lambda:NS(to_raw=lambda:'synthetic-intent'))
    with HyperliquidClient(config(),allow_trading=True) as c:
        def fail(*a):raise RuntimeError('query failed')
        c.info.open_orders=fail
        with pytest.raises(RuntimeError):main.demo_trade(c,'BTC',1,100)
    assert any(x[0]=='cancel_by_cloid' for x in sdk[0])


def test_demo_rejects_mainnet(sdk,monkeypatch):
    monkeypatch.setattr(main,'load_config',lambda _:config(network='mainnet'))
    assert main.main(['--config','unused','--trade','--size','1','--price','100'])==2
    assert not sdk[0]


def test_agent_key_saved_private_without_master_or_stdout(tmp_path,monkeypatch,capsys):
    fake=NS(Account=NS(create=lambda:NS(key=b'\x03'*32,address=AGENT)))
    monkeypatch.setitem(sys.modules,'eth_account',fake)
    output=tmp_path/'agent.key';assert prepare_agent.main(['--output',str(output)])==0
    data=json.loads(capsys.readouterr().out)
    assert data['approval']=='NOT_AUTHORIZED' and data['agent_address']==AGENT
    assert output.read_text().strip() not in json.dumps(data)
    assert output.stat().st_mode & 0o077==0
    assert prepare_agent.main(['--output',str(output)])==2
    assert output.read_text().strip()=='0x'+'03'*32


@pytest.mark.parametrize('path,ignored',[
    ('plumber/config/hyperliquid.toml',True),
    ('config/hyperliquid.toml',True),
    ('plumber/config/hyperliquid.example.toml',False),
])
def test_hyperliquid_gitignore(path,ignored):
    root=Path(__file__).resolve().parents[2]
    result=subprocess.run(['git','check-ignore','--no-index',path],cwd=root,capture_output=True,text=True)
    assert result.returncode==(0 if ignored else 1)


def test_public_trade_api_does_not_expose_signing_sdk(sdk):
    with HyperliquidClient(config(),allow_trading=True) as c:
        assert not hasattr(c,'require_exchange')
        assert c.require_capability() is None
        for method in ('usd_transfer','withdraw_from_bridge'):
            with pytest.raises(ValueError):c.mutate(method,1,ADDRESS)
            with pytest.raises(ValueError):c.mutate(method,1,ADDRESS,funds=True)
    assert not any(x[0] in {'usd_transfer','withdraw_from_bridge'} for x in sdk[0])


@pytest.mark.parametrize('role,target',[
    ({'role':'user'},AGENT),
    ({'role':'agent','data':{'user':AGENT}},ADDRESS),
    ({'role':'agent','data':{'user':AGENT}},None),
    ({'role':'missing'},None),
    ({'role':'vault'},None),
    ({'role':'agent','data':{}},AGENT),
])
def test_mismatched_or_unverifiable_account_never_constructs_exchange(sdk,monkeypatch,role,target):
    calls,Info,_=sdk
    monkeypatch.setattr(Info,'user_role',lambda self,address:role)
    with pytest.raises(Unavailable):HyperliquidClient(config(account_address=target),allow_trading=True)
    assert not any(x[0]=='exchange' for x in calls)


def test_agent_cannot_enable_funds_even_for_correct_owner(sdk,monkeypatch):
    calls,Info,_=sdk
    monkeypatch.setattr(Info,'user_role',lambda self,address:{'role':'agent','data':{'user':AGENT}})
    with pytest.raises(Unavailable):HyperliquidClient(config(account_address=AGENT,funds_enabled=True),allow_funds=True)
    assert not any(x[0]=='exchange' for x in calls)


def test_owner_change_blocks_existing_client_before_next_mutation(sdk,monkeypatch):
    calls,Info,_=sdk
    monkeypatch.setattr(Info,'user_role',lambda self,address:{'role':'agent','data':{'user':AGENT}})
    with HyperliquidClient(config(account_address=AGENT),allow_trading=True) as c:
        ExchangeService(c).cancel_order('BTC',7)
        monkeypatch.setattr(Info,'user_role',lambda self,address:{'role':'agent','data':{'user':ADDRESS}})
        with pytest.raises(Unavailable,match='ACCOUNT_VERIFICATION'):ExchangeService(c).place_limit_order('BTC','buy',1,100)
    assert not any(x[0]=='order' for x in calls)


def test_role_query_failure_does_not_become_unknown_mutation(sdk,monkeypatch):
    with HyperliquidClient(config(),allow_trading=True) as c:
        def fail(_):raise RuntimeError(SECRET)
        monkeypatch.setattr(c.info,'user_role',fail)
        with pytest.raises(Unavailable) as error:ExchangeService(c).cancel_order('BTC',7)
        assert not isinstance(error.value,UnknownResult) and SECRET not in str(error.value)
    assert not any(x[0]=='cancel' for x in sdk[0])


def managed_socket_fixture():
    from plumber.hyperliquid._websocket import manager_type
    events=[];stopped=threading.Event()
    class Socket:
        def settimeout(self,value):pass
        def recv(self):
            stopped.wait(1)
            if stopped.is_set():return ''
            raise TimeoutError()
        def shutdown(self):events.append('shutdown');stopped.set()
    class Base(threading.Thread):
        def __init__(self,url):
            super().__init__();self.stop_event=threading.Event()
            self.ping_sender=threading.Thread(target=lambda:self.stop_event.wait())
        def on_message(self,ws,msg):events.append('message')
    def connect(*a,**kw):events.append('connect');return Socket()
    return manager_type(Base),connect,events


def test_close_before_receiver_scheduled_cannot_reopen_connection():
    cls,connect,events=managed_socket_fixture()
    manager=cls(HyperliquidConfig(),connect,TimeoutError)
    manager.stop();manager.start();manager.join(timeout=1)
    assert events==['connect','shutdown'] and not manager.is_alive()
    assert not manager.ping_sender.is_alive() and manager.finished.is_set()


def test_running_socket_stop_closes_both_threads_once():
    cls,connect,events=managed_socket_fixture()
    manager=cls(HyperliquidConfig(),connect,TimeoutError)
    manager.start();manager.stop();manager.stop()
    assert events==['connect','shutdown']
    assert not manager.is_alive() and not manager.ping_sender.is_alive()


def test_socket_setup_failure_closes_connected_transport():
    cls,connect,events=managed_socket_fixture()
    sock=connect()
    def fail(_):raise RuntimeError('setup failure')
    sock.settimeout=fail
    with pytest.raises(RuntimeError):cls(HyperliquidConfig(),lambda *a,**kw:sock,TimeoutError)
    assert events==['connect','shutdown']
