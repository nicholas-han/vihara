"""Offline regression checks for web requests, background jobs and cached results."""
import json
import pytest
from plumber.hyperliquid import tradfi_web as web


@pytest.mark.parametrize('options', [
    {'top': 0}, {'top': 51}, {'days': 0}, {'days': 731},
    {'start': '2026-02-01', 'end': '2026-01-01'},
])
def test_invalid_query_rejected_before_any_job_starts(options):
    state = web.AppState()
    with pytest.raises(ValueError):
        state.start(options)
    assert state.snapshot()['running'] is False


def test_time_range_uses_utc_and_dexs_are_trimmed():
    top, start, end, dexs = web.parse_options({'start': '2026-01-01', 'end': '2026-01-02', 'dex': 'xyz, flx, '})
    assert top == 10 and end - start == 86_400_000
    assert dexs == ['xyz', 'flx']


def test_partial_history_failure_does_not_hide_successful_contracts():
    def info(payload):
        if payload['type'] == 'metaAndAssetCtxs':
            return [{'universe': [{'name': 'xyz:GOLD'}, {'name': 'xyz:CL'}]},
                    [{'dayNtlVlm': '200'}, {'dayNtlVlm': '100'}]]
        if payload['coin'] == 'xyz:CL':
            raise RuntimeError('offline fixture failure')
        if payload['startTime'] == 0:
            return [{'coin': 'xyz:GOLD', 'time': 1000, 'fundingRate': '-0.0001'}]
        return []
    progress = []
    result = web.build_data({'top': 2, 'dex': 'xyz', 'start': '1970-01-01', 'end': '1970-01-02'}, progress.append, info)
    assert len(result['funding']) == 1
    assert result['errors'] == {'xyz:CL': 'offline fixture failure'}
    assert [m['status'] for m in result['markets']] == ['ok', 'error']
    assert progress[-1] == '下载资金费率 2/2 · xyz:CL'
    assert result['snapshot_end_utc'] != result['end_utc_exclusive']


def test_failed_refresh_keeps_last_successful_data(tmp_path, monkeypatch):
    cache = tmp_path / 'cache.json'
    previous = {'markets': [{'coin': 'xyz:GOLD'}], 'funding': []}
    cache.write_text(json.dumps(previous))
    state = web.AppState(cache)
    def fail(*args):
        raise RuntimeError('network unavailable')
    monkeypatch.setattr(web, 'build_data', fail)
    state.running = True
    state._run({})
    snapshot = state.snapshot(with_result=True)
    assert snapshot['result'] == previous
    assert snapshot['error'] == 'network unavailable'
    assert snapshot['running'] is False
    assert json.loads(cache.read_text()) == previous


def test_cache_failure_does_not_discard_downloaded_data(tmp_path, monkeypatch):
    parent = tmp_path / 'not-a-directory'
    parent.write_text('occupied')
    state = web.AppState(parent / 'data.json')
    result = {'markets': [], 'funding': []}
    monkeypatch.setattr(web, 'build_data', lambda *args: result)
    state._run({})
    assert state.snapshot(with_result=True)['result'] == result
    assert '缓存写入失败' in state.snapshot()['error']


def test_running_job_is_not_duplicated():
    state = web.AppState()
    state.running = True
    assert state.start({}) is False


def test_malformed_cache_is_reported(tmp_path):
    cache = tmp_path / 'cache.json'
    cache.write_text('[]')
    state = web.AppState(cache)
    assert state.snapshot()['has_result'] is False
    assert '无法读取缓存' in state.snapshot()['error']


def test_all_history_requests_failing_preserves_cache_and_memory(tmp_path, monkeypatch):
    previous = {'markets': [{'coin': 'xyz:GOLD', 'dayNtlVlm': '100'}], 'funding': []}
    cache = tmp_path / 'cache.json'
    cache.write_text(json.dumps(previous))
    state = web.AppState(cache)
    original_build = web.build_data
    def info(payload):
        if payload['type'] == 'metaAndAssetCtxs':
            return [{'universe': [{'name': 'xyz:GOLD'}]}, [{'dayNtlVlm': '100'}]]
        raise RuntimeError('funding endpoint unavailable')
    monkeypatch.setattr(web, 'build_data', lambda opts, report: original_build(opts, report, info))
    state._run({'top': 1, 'dex': 'xyz', 'days': 1})
    assert state.snapshot(with_result=True)['result'] == previous
    assert json.loads(cache.read_text()) == previous
    assert '所有合约' in state.snapshot()['error']
    assert state.snapshot()['running'] is False


def test_successful_empty_history_can_replace_previous_cache(tmp_path, monkeypatch):
    state = web.AppState(tmp_path / 'cache.json')
    empty_result = {'markets': [{'coin': 'xyz:GOLD', 'status': 'empty'}], 'funding': [], 'errors': {}}
    monkeypatch.setattr(web, 'build_data', lambda *args: empty_result)
    state._run({})
    assert state.snapshot(with_result=True)['result'] == empty_result
    assert state.snapshot()['error'] is None
