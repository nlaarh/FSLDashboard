"""Text answers are gzipped, downloads are not, and hashed build files are cached for a year."""

import gzip

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.testclient import TestClient

from compression import ImmutableStaticFiles, SelectiveGZipMiddleware

BIG = {'rows': [{'name': 'driver', 'value': i} for i in range(400)]}


def _app(tmp_path):
    (tmp_path / 'index-abc12345.js').write_text('console.log(1);' * 400)
    app = FastAPI()
    app.add_middleware(SelectiveGZipMiddleware, minimum_size=1024)

    @app.get('/api/big')
    def big(): return JSONResponse(BIG)

    @app.get('/api/small')
    def small(): return {'ok': True}

    @app.get('/api/accounting/sf-photo/123')
    def photo(): return StreamingResponse(iter([b'x' * 5000]), media_type='image/jpeg')

    @app.get('/api/admin/reference/rates/export')
    def export(): return StreamingResponse(iter([b'a,b\n' * 2000]), media_type='text/csv')

    app.mount('/assets', ImmutableStaticFiles(directory=tmp_path), name='assets')
    return TestClient(app)


def test_big_json_is_gzipped_and_decodes_to_the_same_data(tmp_path):
    r = _app(tmp_path).get('/api/big', headers={'Accept-Encoding': 'gzip'})
    assert r.headers['content-encoding'] == 'gzip' and r.json() == BIG


def test_small_answers_are_left_alone(tmp_path):
    assert 'content-encoding' not in _app(tmp_path).get('/api/small', headers={'Accept-Encoding': 'gzip'}).headers


def test_client_that_does_not_ask_for_gzip_gets_plain_data(tmp_path):
    r = _app(tmp_path).get('/api/big', headers={'Accept-Encoding': 'identity'})
    assert 'content-encoding' not in r.headers and r.json() == BIG


def test_downloads_are_never_gzipped(tmp_path):
    c = _app(tmp_path)
    for path in ('/api/accounting/sf-photo/123', '/api/admin/reference/rates/export'):
        assert 'content-encoding' not in c.get(path, headers={'Accept-Encoding': 'gzip'}).headers, path


def test_hashed_build_file_is_compressed_and_cached_for_a_year(tmp_path):
    r = _app(tmp_path).get('/assets/index-abc12345.js', headers={'Accept-Encoding': 'gzip'})
    assert r.headers['content-encoding'] == 'gzip'
    assert 'max-age=31536000' in r.headers['cache-control'] and 'immutable' in r.headers['cache-control']
    assert len(gzip.compress(b'console.log(1);' * 400)) < 6000


def test_missing_asset_is_not_marked_immutable(tmp_path):
    r = _app(tmp_path).get('/assets/nope.js')
    assert r.status_code == 404 and 'immutable' not in r.headers.get('cache-control', '')
