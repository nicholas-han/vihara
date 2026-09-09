"""SDK subscription dispatch over an already-connected, explicitly owned socket."""
import threading
from plumber.models import Unavailable


def manager_type(base):
    class ManagedWebsocket(base):
        def __init__(self, config, connect, timeout_error):
            super().__init__(config.api_url)
            self.finished = threading.Event()
            self._timeout_error = timeout_error
            # The SDK WebSocketApp created above has never started. Replace it
            # with a synchronous connection before any receiver thread can run.
            self.ws = connect("wss" + config.api_url[len("https"): ] + "/ws",
                              timeout=config.timeout, enable_multithread=True)
            self._shutdown_lock = threading.Lock()
            self._transport_closed = False
            try:
                self.ws.settimeout(min(config.timeout, 1.0))
                self.ws.keep_running = True
                self.ws_ready = True
            except BaseException:
                self._shutdown()
                raise

        def _shutdown(self):
            with self._shutdown_lock:
                if not self._transport_closed:
                    self._transport_closed = True
                    self.ws.keep_running = False
                    self.ws.shutdown()

        def run(self):
            try:
                if self.stop_event.is_set():
                    return
                self.ping_sender.start()
                while not self.stop_event.is_set():
                    try:
                        message = self.ws.recv()
                    except self._timeout_error:
                        continue
                    if not message:
                        break
                    self.on_message(self.ws, message)
            except Exception:
                # Do not print raw account events or SDK exceptions from a thread.
                pass
            finally:
                self.stop_event.set()
                try:
                    self._shutdown()
                finally:
                    if self.ping_sender.is_alive():
                        self.ping_sender.join()
                    self.finished.set()

        def stop(self):
            self.stop_event.set()
            self._shutdown()
            if self.is_alive() and threading.current_thread() is not self:
                self.join(timeout=5)
                if self.is_alive():
                    raise Unavailable("HYPERLIQUID_WEBSOCKET_CALLBACK_NOT_STOPPED")
            # If run() has not been scheduled yet, it observes stop_event and
            # exits without connecting: run() contains no connection operation.

    return ManagedWebsocket


def connect_manager(config):
    from hyperliquid.websocket_manager import WebsocketManager
    from websocket import create_connection, WebSocketTimeoutException
    manager = None
    try:
        manager = manager_type(WebsocketManager)(config, create_connection, WebSocketTimeoutException)
        manager.start()
        return manager
    except BaseException:
        if manager is not None:
            manager.stop()
        raise Unavailable("HYPERLIQUID_WEBSOCKET_STARTUP_FAILED") from None
