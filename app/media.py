"""The demo video and its poster, streamed from a private Cloud Storage bucket.

Two fixed objects only (no path parameters, so nothing else in the bucket can be requested). The
bucket is named by the MEDIA_BUCKET environment variable, set at deploy; without it the routes
answer 503. Range requests are answered with 206 and at most CHUNK bytes, which keeps every
response under Cloud Run's 32 MiB HTTP/1 limit; the browser asks for the next range as it plays
or seeks. Bytes are streamed from the bucket in small pieces, never held in memory whole.
"""

from __future__ import annotations

import os
import re
import threading
import time

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

router = APIRouter()

OBJECTS = {
    "demo.mp4": ("demo/twinevidence-demo.mp4", "video/mp4"),
    "demo-poster.jpg": ("demo/twinevidence-demo-poster.jpg", "image/jpeg"),
}
CHUNK = 8 * 1024 * 1024  # the largest range answered at once
PIECE = 512 * 1024  # read from the bucket this much at a time
CACHE_CONTROL = "public, max-age=3600"  # the file may be replaced once
META_TTL_S = 600

_client = None
_meta: dict[str, tuple[float, int, str]] = {}
_lock = threading.Lock()


def _bucket():
    """The media bucket, or None when MEDIA_BUCKET is not set. Tests replace this function."""
    global _client
    name = os.environ.get("MEDIA_BUCKET")
    if not name:
        return None
    if _client is None:
        from google.cloud import storage  # only needed where the media is served

        _client = storage.Client()
    return _client.bucket(name)


class Unavailable(Exception):
    pass


def _blob(name: str):
    bucket = _bucket()
    if bucket is None:
        raise Unavailable("media storage is not configured")
    return bucket.blob(name)


def _size_and_etag(name: str) -> tuple[int, str]:
    """The object's size and generation, cached briefly so each range request skips a metadata call."""
    with _lock:
        hit = _meta.get(name)
    if hit and time.monotonic() - hit[0] < META_TTL_S:
        return hit[1], hit[2]
    try:
        blob = _blob(name)
        blob.reload()
    except Unavailable:
        raise
    except Exception as exc:  # unreachable bucket, missing object or no access
        raise Unavailable("the media is unavailable right now") from exc
    entry = (time.monotonic(), int(blob.size), str(blob.generation))
    with _lock:
        _meta[name] = entry
    return entry[1], entry[2]


def parse_range(header: str | None, size: int) -> tuple[int, int] | None | str:
    """(first, last) of a single ``bytes=`` range, capped at CHUNK bytes; None when there is no
    usable Range header (a full response); "unsatisfiable" for a range outside the file."""
    if not header:
        return None
    m = re.fullmatch(r"\s*bytes=(\d*)-(\d*)\s*", header.split(",")[0])  # several ranges: the first only
    if not m or (m.group(1) == "" and m.group(2) == ""):
        return None
    if m.group(1) == "":  # the last N bytes
        n = int(m.group(2))
        if n == 0:
            return "unsatisfiable"
        first, last = max(0, size - n), size - 1
    else:
        first = int(m.group(1))
        last = int(m.group(2)) if m.group(2) else size - 1
        if first >= size or last < first:
            return "unsatisfiable"
        last = min(last, size - 1)
    return first, min(last, first + CHUNK - 1)


def _stream(name: str, first: int, last: int):
    blob = _blob(name)
    with blob.open("rb", chunk_size=PIECE) as f:
        f.seek(first)
        left = last - first + 1
        while left > 0:
            data = f.read(min(PIECE, left))
            if not data:
                break
            left -= len(data)
            yield data


def _serve(key: str, request: Request, head: bool) -> Response:
    name, content_type = OBJECTS[key]
    try:
        size, etag = _size_and_etag(name)
    except Unavailable as exc:
        return Response(f"{exc}.", status_code=503, media_type="text/plain", headers={"Retry-After": "30"})
    headers = {"Accept-Ranges": "bytes", "Cache-Control": CACHE_CONTROL, "ETag": f'"{etag}"'}
    rng = parse_range(request.headers.get("range"), size)
    if rng == "unsatisfiable":
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
    if rng is None:
        first, last, status = 0, size - 1, 200
    else:
        (first, last), status = rng, 206
        headers["Content-Range"] = f"bytes {first}-{last}/{size}"
    if status == 200 and size > CHUNK:
        # A whole-file request for a large object: stream it without a length (chunked transfer).
        if head:
            return Response(status_code=200, media_type=content_type, headers={**headers, "Content-Length": str(size)})
        return StreamingResponse(_stream(name, 0, size - 1), status_code=200, media_type=content_type, headers=headers)
    headers["Content-Length"] = str(last - first + 1)
    if head:
        return Response(status_code=status, media_type=content_type, headers=headers)
    return StreamingResponse(_stream(name, first, last), status_code=status, media_type=content_type, headers=headers)


@router.api_route("/media/demo.mp4", methods=["GET", "HEAD"])
def demo_video(request: Request) -> Response:
    return _serve("demo.mp4", request, request.method == "HEAD")


@router.api_route("/media/demo-poster.jpg", methods=["GET", "HEAD"])
def demo_poster(request: Request) -> Response:
    return _serve("demo-poster.jpg", request, request.method == "HEAD")
