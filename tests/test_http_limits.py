import asyncio
from tracework.http_limits import BodyLimitMiddleware


def test_streaming_body_limit_before_parser():
    sent = []

    async def endpoint(scope, receive, send):
        await receive()
        await receive()
        raise AssertionError("Oversized stream reached endpoint")

    events = iter(
        [
            {"type": "http.request", "body": b"a" * 8, "more_body": True},
            {"type": "http.request", "body": b"b" * 8},
        ]
    )

    async def receive():
        return next(events)

    async def send(message):
        sent.append(message)

    asyncio.run(
        BodyLimitMiddleware(endpoint, 10)({"type": "http", "method": "POST", "headers": []}, receive, send)
    )
    assert sent[0]["status"] == 413


def test_content_length_limit_is_immediate():
    sent = []

    async def forbidden(*args):
        raise AssertionError("Should not read oversized body")

    async def send(message):
        sent.append(message)

    asyncio.run(
        BodyLimitMiddleware(forbidden, 10)(
            {"type": "http", "headers": [(b"content-length", b"20")]}, forbidden, send
        )
    )
    assert sent[0]["status"] == 413
