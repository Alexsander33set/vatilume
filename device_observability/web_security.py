"""Small ASGI request limit, independent of JSON/Pydantic validation."""
import asyncio
from starlette.responses import JSONResponse

MAX_BODY_BYTES = 16 * 1024


class LimitedBodyMiddleware:
    def __init__(self, app, maximum=MAX_BODY_BYTES, timeout=10):
        self.app, self.maximum, self.timeout = app, maximum, timeout

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        lengths = [value for key, value in scope['headers'] if key.lower() == b'content-length']
        if lengths:
            if len(lengths) != 1 or not lengths[0].isdigit():
                return await JSONResponse({'detail': 'Tamanho da solicitação inválido.'}, status_code=400)(scope, receive, send)
            if len(lengths[0]) > 8 or int(lengths[0]) > self.maximum:
                return await self.reject(scope, receive, send, 413)
        body = bytearray()

        async def collect():
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect': return False
                part = message.get('body', b'')
                if len(body) + len(part) > self.maximum: return None
                body.extend(part)
                if not message.get('more_body', False): return True

        try:
            complete = await asyncio.wait_for(collect(), self.timeout)
        except asyncio.TimeoutError:
            return await self.reject(scope, receive, send, 408)
        if complete is None: return await self.reject(scope, receive, send, 413)
        if complete is False: return
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
            return await receive()
        await self.app(scope, replay, send)

    async def reject(self, scope, receive, send, status):
        message = 'A solicitação excede o limite de 16 KiB.' if status == 413 else 'A solicitação demorou demais.'
        await JSONResponse({'detail': message}, status_code=status, headers={'Connection': 'close'})(scope, receive, send)
