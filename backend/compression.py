"""Compress text responses and cache the hashed build files for a year.

Before this the 2.1 MB main JavaScript file and every large JSON answer were sent uncompressed. gzip makes
them roughly a quarter of the size. File downloads (photos, exports, database dumps) are left alone: they are
already compressed or streamed and gzip would only cost CPU.
"""

from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

# Streamed / binary downloads: never wrapped in gzip
NO_GZIP_PREFIXES = ('/api/accounting/sf-photo/', '/api/admin/system/health/db/', '/api/admin/reference/')
NO_GZIP_SUFFIXES = ('/export',)


class SelectiveGZipMiddleware:
    def __init__(self, app, minimum_size: int = 1024):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            path = scope.get('path', '')
            if path.startswith(NO_GZIP_PREFIXES) or path.endswith(NO_GZIP_SUFFIXES):
                return await self.app(scope, receive, send)
        return await self.gzip(scope, receive, send)


class ImmutableStaticFiles(StaticFiles):
    """For the content-hashed /assets build output: a changed file always has a new name, so cache it for a year."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        return response
