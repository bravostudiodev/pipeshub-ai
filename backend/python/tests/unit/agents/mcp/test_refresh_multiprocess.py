"""Two real Python processes share a rotation lease, not an asyncio lock."""
import asyncio
import multiprocessing
import time
from collections import defaultdict
from copy import deepcopy

from app.agents.mcp import oauth_client, token_refresh
from app.agents.mcp.models import OAuthTokens
from tests.unit.agents.mcp.test_refresh_coordination import CLIENT, CRED, record


class SharedConfig:
    """Atomic test backend shared by processes through local IPC."""

    def __init__(self, data, mutex) -> None:
        self.data = data
        self.mutex = mutex

    async def get_config(self, key, default=None, **kwargs) -> object:
        with self.mutex:
            entry = self.data.get(key)
            if entry is None or (entry[1] is not None and entry[1] < time.monotonic()):
                return default
            return deepcopy(entry[0])

    async def create_config_if_absent(self, key, value, *, ttl_seconds=None) -> bool:
        with self.mutex:
            entry = self.data.get(key)
            if entry is not None and (entry[1] is None or entry[1] >= time.monotonic()):
                return False
            self.data[key] = (deepcopy(value), time.monotonic() + ttl_seconds if ttl_seconds else None)
            return True

    async def compare_and_set_config(self, key, expected, value) -> bool:
        with self.mutex:
            entry = self.data.get(key)
            if entry is None or entry[0] != expected or (entry[1] is not None and entry[1] < time.monotonic()):
                return False
            if value is None:
                del self.data[key]
            else:
                self.data[key] = (deepcopy(value), entry[1])
            return True


def refresh_worker(data, mutex, count, barrier, results) -> None:
    token_refresh._refresh_locks = defaultdict(asyncio.Lock)

    async def rotate(**kwargs) -> OAuthTokens:
        with mutex:
            count.value += 1
        await asyncio.sleep(0.15)
        return OAuthTokens(access_token="refreshed", refresh_token="rotated", token_url="https://example.test/token")

    oauth_client.refresh_access_token = rotate
    barrier.wait(timeout=15)
    result = asyncio.run(token_refresh.refresh_credential_record(
        "inst-1", "user-1", SharedConfig(data, mutex), stale_access_token="old",
    ))
    results.put(result.access_token)


def test_separate_processes_refresh_a_rotating_token_only_once() -> None:
    ctx = multiprocessing.get_context("spawn")
    with ctx.Manager() as manager:
        data = manager.dict({CRED: (record(), None), CLIENT: ({"clientId": "client"}, None)})
        mutex, count = manager.RLock(), manager.Value("i", 0)
        barrier, results = ctx.Barrier(2), ctx.Queue()
        processes = [ctx.Process(target=refresh_worker, args=(data, mutex, count, barrier, results)) for _ in range(2)]
        try:
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=20)
                assert process.exitcode == 0
            assert [results.get(timeout=2) for _ in processes] == ["refreshed", "refreshed"]
            assert count.value == 1
            assert data[CRED][0]["oauthTokens"]["refreshToken"] == "rotated"
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=2)
            results.close()
