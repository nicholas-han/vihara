"""Local-only, zero-dependency UI for public TradFi funding data."""
from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .tradfi_funding import (FUNDING_INTERVAL_HOURS, PublicInfo, aggregate_funding,
                             funding_frequency, funding_history, parse_time,
                             select_markets, utc_iso)

ROOT = Path(__file__).with_name("web")


def parse_options(options):
    top, days = int(options.get("top", 10)), int(options.get("days", 30))
    if not 1 <= top <= 50 or not 1 <= days <= 730:
        raise ValueError("合约数量须为 1–50，回看天数须为 1–730")
    end = parse_time(options["end"]) if options.get("end") else int(time.time() * 1000)
    start = parse_time(options["start"]) if options.get("start") else end - days * 86_400_000
    if not 0 <= start < end or end - start > 730 * 86_400_000:
        raise ValueError("时间范围须有效且不超过 730 天；结束时间不包含在内")
    dexs = [s.strip() for s in options.get("dex", "").split(",") if s.strip()]
    return top, start, end, dexs or None


def build_data(options, progress=lambda _: None, info=None):
    top, start, end, dexs = parse_options(options)
    info = info or PublicInfo()
    snapshot_start = utc_iso(int(time.time() * 1000))
    progress("发现 DEX 并读取各市场成交额…")
    def reporting_info(payload):
        if payload["type"] == "metaAndAssetCtxs":
            progress(f"读取市场：{payload['dex'] or '原生市场'}")
        return info(payload)
    markets, unclassified = select_markets(reporting_info, top, dexs)
    snapshot_end = utc_iso(int(time.time() * 1000))
    rows, errors = [], {}
    for index, market in enumerate(markets, 1):
        coin = market["coin"]
        progress(f"下载资金费率 {index}/{len(markets)} · {coin}")
        try:
            history = funding_history(info, coin, start, end)
            market.update(funding_records=len(history), status="ok" if history else "empty",
                          funding_frequency=funding_frequency([r["time"] for r in history]))
            rows.extend(dict(item, rank=market["rank"], dayNtlVlm=market["dayNtlVlm"]) for item in history)
        except (ValueError, KeyError, TypeError, RuntimeError) as exc:
            market.update(status="error", funding_records=0,
                          funding_frequency={"interval_hours": FUNDING_INTERVAL_HOURS, "label": "每小时",
                                             "observed_interval_hours": None, "same_across_assets": True})
            errors[coin] = str(exc)
    return {"snapshot_start_utc": snapshot_start, "snapshot_end_utc": snapshot_end,
            "start_utc_inclusive": utc_iso(start), "end_utc_exclusive": utc_iso(end),
            "classification": "保守 TradFi 标的白名单；不是官方完整分类，新增或未识别标的可能遗漏",
            "ranking": "当前滚动 24h dayNtlVlm；同一标的跨 DEX 分别排名",
            "funding_spec": {"interval_hours": FUNDING_INTERVAL_HOURS, "label": "每小时",
                             "same_across_assets": True, "annualization": "简单年化 = 每小时费率 × 8,760",
                             "cumulative": "按 UTC 日/周/月对实际记录求和；缺失记录不填零"},
            "options": options, "markets": markets, "funding": rows,
            "cumulative": aggregate_funding(rows, "month"),
            "unclassified": unclassified, "errors": errors}


class AppState:
    def __init__(self, cache=None):
        self.lock = threading.Lock()
        self.cache = cache
        self.running = False
        self.progress = "就绪"
        self.error = None
        self.result = None
        if cache and cache.exists():
            try:
                candidate = json.loads(cache.read_text(encoding="utf-8"))
                if not isinstance(candidate.get("markets"), list) or not isinstance(candidate.get("funding"), list):
                    raise ValueError("缺少 markets 或 funding 数组")
                self.result = candidate
                self.progress = "已加载本地快照，点击刷新可获取新数据"
            except (ValueError, OSError, AttributeError) as exc:
                self.error = f"无法读取缓存：{exc}"

    def snapshot(self, with_result=False):
        with self.lock:
            state = {"running": self.running, "progress": self.progress, "error": self.error,
                     "has_result": self.result is not None}
            if with_result:
                state["result"] = self.result
            return state

    def set_progress(self, message):
        with self.lock:
            self.progress = message

    def start(self, options):
        parse_options(options)
        with self.lock:
            if self.running:
                return False
            self.running, self.error, self.progress = True, None, "开始读取…"
        threading.Thread(target=self._run, args=(options,), daemon=True).start()
        return True

    def _run(self, options):
        try:
            result = build_data(options, self.set_progress)
            warning = None
            if self.cache:
                try:
                    self.cache.parent.mkdir(parents=True, exist_ok=True)
                    temp = self.cache.with_suffix(".tmp")
                    temp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                    temp.replace(self.cache)
                except OSError as exc:
                    warning = f"数据已加载，但缓存写入失败：{exc}"
            with self.lock:
                self.result, self.error, self.progress = result, warning, "下载完成"
        except Exception as exc:
            with self.lock:
                self.error, self.progress = str(exc), "下载失败，保留已有数据"
        finally:
            with self.lock:
                self.running = False


def handler_for(state):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body, content_type="application/json; charset=utf-8"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def local_request(self):
            host = self.headers.get("Host", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            origin = self.headers.get("Origin")
            return host in allowed and (origin is None or origin == f"http://{host}")

        def do_GET(self):
            if not self.local_request():
                self.reply(403, {"error": "Local access only"})
                return
            path = urlparse(self.path).path
            if path in ("/api/state", "/api/result"):
                self.reply(200, state.snapshot(with_result=path == "/api/result"))
                return
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/funding_math.js": ("funding_math.js", "text/javascript; charset=utf-8"),
                     "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path not in files:
                self.reply(404, {"error": "Not found"})
                return
            filename, content_type = files[path]
            self.reply(200, (ROOT / filename).read_bytes(), content_type)

        def do_POST(self):
            if not self.local_request():
                self.reply(403, {"error": "Local access only"})
                return
            if self.path != "/api/refresh":
                self.reply(404, {"error": "Not found"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8192:
                    raise ValueError("Invalid request size")
                options = json.loads(self.rfile.read(size))
                if not isinstance(options, dict):
                    raise ValueError("Expected JSON object")
                if state.start(options):
                    self.reply(202, state.snapshot())
                else:
                    self.reply(409, {"error": "已有下载正在进行"})
            except (ValueError, TypeError, AttributeError, OverflowError) as exc:
                self.reply(400, {"error": str(exc)})

        def log_message(self, *_):
            pass
    return Handler


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cache", type=Path, default=Path("/tmp/hyperliquid-tradfi-funding/web-cache.json"))
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(AppState(args.cache)))
    print(f"TradFi funding UI: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
