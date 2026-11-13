"""Bound upload bodies before multipart spooling, including chunked requests."""
from fastapi import HTTPException
from starlette.responses import JSONResponse

from app.services.enterprise_evidence import MAX_FILE_BYTES

MAX_UPLOAD_BODY = MAX_FILE_BYTES + 64 * 1024  # one file plus multipart overhead


class EvidenceBodyLimit:
    def __init__(self,app):self.app=app

    async def __call__(self,scope,receive,send):
        path=scope.get("path","")
        upload_path=path=="/api/enterprise/evidence/staging" or (path.startswith("/api/enterprise/stations/") and path.endswith("/evidence/staging"))
        if scope["type"]!="http" or not upload_path or scope.get("method")!="POST":
            return await self.app(scope,receive,send)
        headers=dict(scope.get("headers",[]))
        length=headers.get(b"content-length")
        if length is not None:
            try:too_big=int(length)>MAX_UPLOAD_BODY
            except ValueError:
                return await JSONResponse({"detail":"Content-Length không hợp lệ"},status_code=400)(scope,receive,send)
            if too_big:
                return await JSONResponse({"detail":"Tệp tải lên vượt quá giới hạn 5 MB"},status_code=413)(scope,receive,send)
        received=0
        async def bounded_receive():
            nonlocal received
            message=await receive()
            if message["type"]=="http.request":
                received+=len(message.get("body",b""))
                if received>MAX_UPLOAD_BODY:raise HTTPException(413,"Tệp tải lên vượt quá giới hạn 5 MB")
            return message
        await self.app(scope,bounded_receive,send)
