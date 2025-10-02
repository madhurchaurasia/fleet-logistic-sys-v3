import os
import ssl
import socket
from http.client import HTTPSConnection

HOST = os.environ.get("PUBLIC_IP", "110.238.78.42")
PORT = int(os.environ.get("HTTPS_PORT", "443"))
WSS_PATH = "/ws"


def check_tcp_port():
    with socket.create_connection((HOST, PORT), timeout=5):
        return True


def check_https_headers():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = HTTPSConnection(HOST, PORT, context=ctx, timeout=5)
    conn.request("GET", "/")
    resp = conn.getresponse()
    headers = dict(resp.getheaders())
    conn.close()
    return resp.status, headers.get("Server", "")


def check_wss():
    try:
        import asyncio
        import websockets
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("websockets package is required") from exc

    async def ws():
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        url = f"wss://{HOST}:{PORT}{WSS_PATH}" if PORT != 443 else f"wss://{HOST}{WSS_PATH}"
        async with websockets.connect(
            url,
            ssl=ctx,
            ping_interval=10,
            ping_timeout=10,
        ) as client:
            await client.send("ping")
    asyncio.run(ws())



def main():
    try:
        check_tcp_port()
        print(f"[1] TCP {PORT}: OK")
    except Exception as exc:  # pragma: no cover
        print(f"[1] TCP {PORT}: FAIL -> {exc}")
        return
    try:
        status, server = check_https_headers()
        print(f"[2] HTTPS GET /: {status} | Server header: {server}")
    except Exception as exc:  # pragma: no cover
        print(f"[2] HTTPS GET /: FAIL -> {exc}")
        return
    try:
        check_wss()
        print("[3] WSS connect: OK")
    except Exception as exc:  # pragma: no cover
        print(f"[3] WSS connect: FAIL -> {exc}\nInstall: pip install websockets")


if __name__ == "__main__":
    main()
