from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select

from models import Document


class DocumentVersionConflictError(ValueError):
    pass


class DocumentState(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"


class DocumentLifecycle:
    def __init__(self, sessions):
        self._sessions = sessions

    def start_upload(self, *, owner_id: int, source: str, version: str, content: str) -> Document:
        if owner_id < 1:
            raise ValueError("owner_id 必须为正整数")
        if not source.strip():
            raise ValueError("source 不能为空")
        if not version.strip():
            raise ValueError("version 不能为空")
        if not content.strip():
            raise ValueError("content 不能为空")
        digest = sha256(content.encode("utf-8")).hexdigest()
        with self._sessions() as session:
            existing = session.scalar(select(Document).where(
                Document.owner_id == owner_id,
                Document.source == source,
                Document.document_version == version,
            ))
            #如果版本相同但是内容不同 显示冲突
            if existing is not None:
                if existing.content_hash != digest:
                    raise DocumentVersionConflictError("相同版本的内容冲突")
                return existing
            #现在的时间
            now = self._now()
            #创建文档版本 现在还是pending 还没上传
            document = Document(
                id=uuid4().hex,
                owner_id=owner_id,
                source=source,
                document_version=version,
                content_hash=digest,
                state=DocumentState.PENDING,
                created_at=now,
                updated_at=now,
            )
            #上传到document表 记录文档状态 注意是document表不是向量数据库
            session.add(document)
            session.commit()
            return document

    def get(self, document_id: str) -> Document:
        with self._sessions() as session:
            document = session.get(Document, document_id)
            if document is None:
                raise KeyError("文档不存在")
            return document

    def get_for_owner(self, *, owner_id: int, document_id: str) -> Document | None:
        with self._sessions() as session:
            return session.scalar(
                select(Document).where(
                    Document.id == document_id,
                    Document.owner_id == owner_id,
                )
            )

    def get_version(
        self,
        *,
        owner_id: int,
        source: str,
        version: str,
    ) -> Document | None:
        with self._sessions() as session:
            return session.scalar(
                select(Document).where(
                    Document.owner_id == owner_id,
                    Document.source == source,
                    Document.document_version == version,
                )
            )

    def list_for_owner(self, owner_id: int) -> list[Document]:
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(Document)
                    .where(Document.owner_id == owner_id)
                    .order_by(Document.updated_at.desc(), Document.id.desc())
                )
            )

    def mark_processing(self, document_id: str) -> Document:
        return self._transition(document_id, DocumentState.PROCESSING)

    def mark_failed(self, document_id: str, message: str) -> Document:
        if not message.strip():
            raise ValueError("失败原因不能为空")
        return self._transition(document_id, DocumentState.FAILED, error_message=message)

    def activate(self, document_id: str) -> Document:
        with self._sessions() as session:
            with session.begin():
                document = session.get(Document, document_id)
                if document is None:
                    raise KeyError("文档不存在")

                # Lock every version of this source in a stable order.
                locked = session.scalars(
                    select(Document)
                    .where(
                        Document.owner_id == document.owner_id,
                        Document.source == document.source,
                    )
                    .order_by(Document.id)
                    .with_for_update()
                ).all()
                document = next(item for item in locked if item.id == document_id)
                if document.state != DocumentState.PROCESSING:
                    raise ValueError("只有 processing 文档可以激活")

                current = next(
                    (
                        item
                        for item in locked
                        if item.state == DocumentState.READY
                        and item.id != document.id
                    ),
                    None,
                )
                if current is not None:
                    current.state = DocumentState.DELETED
                    current.active_version = None
                    current.updated_at = self._now()
                document.state = DocumentState.READY
                document.active_version = document.document_version
                document.error_message = None
                document.updated_at = self._now()
                session.flush()
                return document
    def delete(
        self,
        document_id: str,
        store,
        *,
        owner_id: int | None = None,
    ) -> Document:
        """Delete one document version and its vector chunks atomically."""
        with self._sessions() as session:
            with session.begin():
                conditions = [Document.id == document_id]
                if owner_id is not None:
                    conditions.append(Document.owner_id == owner_id)
                document = session.scalar(
                    select(Document).where(*conditions).with_for_update()
                )
                if document is None:
                    raise KeyError("文档不存在")
                if document.state == DocumentState.DELETED:
                    return document
                document.state = DocumentState.DELETING
                document.updated_at = self._now()
                session.flush()
                #向量库也跟着删除 放在同一个事务中
                store.delete_document_version(
                    session,
                    owner_id=document.owner_id,
                    source=document.source,
                    document_version=document.document_version,
                )
                #状态标记为已删除
                document.state = DocumentState.DELETED
                document.active_version = None
                document.updated_at = self._now()
                session.flush()
                return document
    def active_version(self, *, owner_id: int, source: str) -> str | None:
        with self._sessions() as session:
            document = session.scalar(select(Document).where(
                Document.owner_id == owner_id,
                Document.source == source,
                Document.state == DocumentState.READY,
                Document.active_version.is_not(None),
            ))
            return document.active_version if document else None
    #查询该文档是否可用于查询
    def is_queryable(self, document_id: str) -> bool:
        with self._sessions() as session:
            document = session.get(Document, document_id)
            return bool(
                document
                and document.state == DocumentState.READY
                and document.active_version == document.document_version
            )
    #更新文档状态
    def _transition(self, document_id: str, state: DocumentState, **changes) -> Document:
        with self._sessions() as session:
            with session.begin():
                document = session.get(Document, document_id)
                if document is None:
                    raise KeyError("文档不存在")
                document.state = state
                document.updated_at = self._now()
                for key, value in changes.items():
                    setattr(document, key, value)
                session.flush()
                return document

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc).replace(tzinfo=None)
