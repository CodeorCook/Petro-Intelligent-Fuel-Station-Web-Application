"""Private local evidence store. Staging manifests are owned and expire after 24h.

Objects stay at one immutable random path; submission atomically claims them
by inserting TEP_MINH_CHUNG in the same DB transaction as the snapshot.
No move/copy occurs during submission, so rollback leaves valid owned staging,
not unreferenced permanent copies. Committed attachments are never garbage-collected.
"""
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path

from fastapi import HTTPException

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_STAGED_FILES = 10
STAGING_TTL_SECONDS = 24 * 3600
FORMATS = {".pdf":"application/pdf", ".png":"image/png", ".jpg":"image/jpeg", ".jpeg":"image/jpeg"}


class PrivateEvidenceStore:
    def __init__(self,root: Path | str):
        self.root=Path(root).resolve()
        public=(Path(__file__).resolve().parents[1]/"static").resolve()
        if self.root==public or public in self.root.parents:
            raise ValueError("Evidence storage must be outside app/static")

    def manifest_path(self,token):
        if not re.fullmatch(r"[0-9a-f]{32}",token):raise HTTPException(404,"Không tìm thấy minh chứng")
        return self.root/"staging"/(token+".json")

    def object_path(self,relative):
        if not re.fullmatch(r"objects/[0-9a-f]{32}\.(pdf|png|jpg|jpeg)",relative):
            raise HTTPException(404,"Đường dẫn minh chứng không hợp lệ")
        path=(self.root/relative).resolve()
        if self.root not in path.parents:raise HTTPException(404,"Đường dẫn minh chứng không hợp lệ")
        return path

    def stage(self,owner,name,mime,data: bytes,*,scope="enterprise",station_id=None):
        if not data:raise HTTPException(400,"Tệp minh chứng không được rỗng")
        if len(data)>MAX_FILE_BYTES:raise HTTPException(413,"Tệp không được vượt quá 5 MB")
        if not name or len(name)>255 or Path(name).name!=name or any(c in name for c in ("/","\\")) or any(ord(c)<32 or ord(c)==127 for c in name):
            raise HTTPException(400,"Tên tệp không hợp lệ")
        extension=Path(name).suffix.lower()
        valid=(extension==".pdf" and data.startswith(b"%PDF-") and b"%%EOF" in data[-1024:]
               or extension==".png" and data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16]==b"IHDR"
               or extension in (".jpg",".jpeg") and data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"))
        if not valid or FORMATS.get(extension)!=mime:
            raise HTTPException(400,"Chỉ nhận PDF, PNG, JPEG có định dạng và chữ ký tệp phù hợp")
        token=secrets.token_hex(16)
        relative=f"objects/{token}{extension}"
        meta=dict(token=token,owner=owner,name=name,mime=mime,size=len(data),
                  sha256=hashlib.sha256(data).hexdigest(),path=relative,created=time.time(),scope=scope,station_id=station_id)
        (self.root/"objects").mkdir(parents=True,exist_ok=True,mode=0o700)
        (self.root/"staging").mkdir(parents=True,exist_ok=True,mode=0o700)
        path=self.object_path(relative)
        manifest=self.manifest_path(token)
        try:
            with path.open("xb") as file:file.write(data)
            os.chmod(path,0o600)
            with manifest.open("x",encoding="utf-8") as file:json.dump(meta,file)
            os.chmod(manifest,0o600)
        except OSError as error:
            path.unlink(missing_ok=True); manifest.unlink(missing_ok=True)
            raise HTTPException(503,"Không thể lưu minh chứng. Vui lòng thử lại.") from error
        return meta

    def read(self,token,owner,*,allow_expired=False):
        try:meta=json.loads(self.manifest_path(token).read_text(encoding="utf-8"))
        except (OSError,ValueError) as error:raise HTTPException(404,"Không tìm thấy minh chứng") from error
        if meta["owner"]!=owner:raise HTTPException(403,"Không có quyền sử dụng minh chứng này")
        if not allow_expired and time.time()-meta["created"]>STAGING_TTL_SECONDS:
            raise HTTPException(400,"Minh chứng nháp đã hết hạn; vui lòng tải lại")
        path=self.object_path(meta["path"])
        if not path.is_file():raise HTTPException(404,"Tệp minh chứng không còn khả dụng")
        return meta

    def verify(self,meta):
        path=self.object_path(meta["path"])
        try:
            mismatch=path.stat().st_size!=meta["size"] or hashlib.sha256(path.read_bytes()).hexdigest()!=meta["sha256"]
        except OSError as error:raise HTTPException(503,"Không thể đọc minh chứng lúc này") from error
        if mismatch:raise HTTPException(409,"Minh chứng đã thay đổi; vui lòng tải lại")

    def remove(self,meta):
        self.object_path(meta["path"]).unlink(missing_ok=True)
        self.manifest_path(meta["token"]).unlink(missing_ok=True)


def get_evidence_store():
    return PrivateEvidenceStore(os.getenv("ENTERPRISE_EVIDENCE_DIR") or str(Path(__file__).resolve().parents[2]/"var/private_evidence"))
