"""테스트용 SSH 서버(#213). 127.0.0.1에 asyncssh 서버를 따로 스레드의 이벤트 루프로 띄운다.

run_task는 Runner.run_sync로 자기 루프를 돌리므로, 서버는 다른 스레드의 루프에 둔다.
호스트 키와 클라이언트 키는 실행 중에 만들고 어디에도 저장하지 않는다.
서버는 respond()로 정한 명령에만 정한 출력을 돌려준다. 그 밖의 명령은 violations에 남기고
종료 코드 127로 끝낸다(테스트가 violations가 비었는지 따로 확인한다).
"""

import asyncio
import json
import socket
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncssh

FIXTURES = Path(__file__).parent / "fixtures" / "ssh"


def fixture_outputs() -> dict[str, dict[str, Any]]:
    data = json.loads((FIXTURES / "outputs.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def new_key() -> asyncssh.SSHKey:
    return asyncssh.generate_private_key("ssh-ed25519")


def public_line(key: asyncssh.SSHKey) -> str:
    """공개 키 한 줄("ssh-ed25519 AAAA…"). 설정 host_key에 넣는 모양."""
    return " ".join(key.export_public_key().decode().split()[:2])


def private_text(key: asyncssh.SSHKey) -> str:
    """OpenSSH 개인 키 본문(여러 줄). SSH_TOOL_PRIVATE_KEY에 넣는 모양."""
    return key.export_private_key().decode()


def free_port() -> int:
    """지금 아무도 듣지 않는 포트(연결 거부를 만들 때 쓴다)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class Response:
    stdout: bytes = b""
    stderr: bytes = b""
    exit_status: int = 0
    delay: float = 0.0
    signal: str | None = None


class FakeSshServer:
    def __init__(self) -> None:
        self.host_key = new_key()
        self.client_key = new_key()
        # OpenSSH 형식은 내보낼 때마다 임의 검사 값이 바뀌므로 한 번만 만든다
        self._client_key_text = private_text(self.client_key)
        self.responses: dict[str, Response] = {}
        self.commands: list[str] = []
        self.violations: list[str] = []
        self.connections = 0
        self.usernames: list[str] = []
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._server: Any = None
        self.port = 0
        self._silent: Any = None
        self.silent_port = 0

    # 서버 쪽

    def start(self) -> "FakeSshServer":
        self._thread.start()
        asyncio.run_coroutine_threadsafe(self._start(), self._loop).result(10)
        return self

    async def _start(self) -> None:
        server = self

        class Server(asyncssh.SSHServer):
            def connection_made(self, conn: Any) -> None:
                server.connections += 1

            def begin_auth(self, username: str) -> bool:
                server.usernames.append(username)
                return True

        authorized = asyncssh.import_authorized_keys(self.client_key.export_public_key().decode())
        self._server = await asyncssh.create_server(
            Server,
            "127.0.0.1",
            0,
            server_host_keys=[self.host_key],
            authorized_client_keys=authorized,
            process_factory=self._handle,
            encoding=None,
        )
        self.port = self._server.sockets[0].getsockname()[1]

        async def silent(reader: Any, writer: Any) -> None:  # 접속은 받고 아무 말도 하지 않는다
            server.connections += 1
            await asyncio.sleep(30)

        self._silent = await asyncio.start_server(silent, "127.0.0.1", 0)
        self.silent_port = self._silent.sockets[0].getsockname()[1]

    async def _handle(self, process: Any) -> None:
        command = process.command or ""
        self.commands.append(command)
        response = self.responses.get(command)
        if response is None:
            self.violations.append(command)
            process.stderr.write(b"unknown command\n")
            process.exit(127)
            return
        if response.delay:
            await asyncio.sleep(response.delay)
        try:
            for start in range(0, len(response.stdout), 4096):
                process.stdout.write(response.stdout[start : start + 4096])
                await process.stdout.drain()
            process.stderr.write(response.stderr)
        except Exception:  # 클라이언트가 먼저 끊었다(출력 상한)
            return
        if response.signal:
            process.exit_with_signal(response.signal)
        else:
            process.exit(response.exit_status)

    def stop(self) -> None:
        async def close() -> None:
            self._server.close()
            self._silent.close()

        asyncio.run_coroutine_threadsafe(close(), self._loop).result(10)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(10)

    # 테스트 쪽

    def reset(self) -> None:
        """테스트 사이에 정한 출력과 기록을 비운다(서버는 모듈마다 하나만 띄운다)."""
        self.responses.clear()
        self.commands.clear()
        self.violations.clear()
        self.usernames.clear()
        self.connections = 0

    def respond(self, command: str, **kwargs: Any) -> None:
        for key in ("stdout", "stderr"):
            if isinstance(kwargs.get(key), str):
                kwargs[key] = kwargs[key].encode()
        self.responses[command] = Response(**kwargs)

    def load_fixtures(self) -> None:
        for item in fixture_outputs().values():
            self.respond(item["command"], stdout=item["stdout"], exit_status=item["exit_status"])

    @property
    def host_key_line(self) -> str:
        return public_line(self.host_key)

    @property
    def client_key_text(self) -> str:
        return self._client_key_text
