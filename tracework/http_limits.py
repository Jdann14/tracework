"""Limit HTTP bodies before multipart parsing can spool an unbounded upload."""

from starlette.responses import JSONResponse


class BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app, limit):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "Invalid content length"}, status_code=400)(
                scope, receive, send
            )
        if declared > self.limit:
            return await JSONResponse({"detail": "Request body exceeds upload limit"}, status_code=413)(
                scope, receive, send
            )
        total = 0

        async def limited_receive():
            nonlocal total
            event = await receive()
            total += len(event.get("body", b""))
            if total > self.limit:
                raise BodyTooLarge()
            return event

        try:
            await self.app(scope, limited_receive, send)
        except BodyTooLarge:
            await JSONResponse({"detail": "Request body exceeds upload limit"}, status_code=413)(
                scope, receive, send
            )
