"""
Conversation document upload endpoint (TODO-11).

POST /conversations/{conversation_id}/documents
  - Accepts multipart file upload from authenticated end users
  - Validates ownership, file type, and file size
  - Runs DocumentIndexingPipeline.process_conversation_file()
  - Returns chunk count and index metadata
"""
import os
import tempfile

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, get_current_user
from app.core.database import validate_tenant_id, get_set_tenant_sql
from app.core.session import get_async_session

logger = structlog.get_logger()

router = APIRouter(tags=["chat"])

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
_SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".txt"}
_SUPPORTED_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
}


@router.post("/conversations/{conversation_id}/documents")
async def upload_conversation_document(
    conversation_id: str,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """
    Upload a document to a conversation for context-aware chat.

    The document is parsed, chunked, embedded, and stored in pgvector
    under index_id = f"conv-{tenant_id}-{conversation_id}". Subsequent
    chat queries in this conversation will search this index alongside
    the KB index.

    Limits:
    - File size: 20 MB
    - Supported types: PDF, DOCX, PPTX, TXT
    """
    from app.modules.documents.indexing import DocumentIndexingPipeline

    # Guard: platform-scope users have no tenant context
    try:
        validate_tenant_id(current_user.tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Document upload is not available for platform-scope users.",
        )

    # Validate filename and extension
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No filename provided.",
        )
    safe_filename = os.path.basename(file.filename)[:255]
    ext = os.path.splitext(safe_filename)[1].lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported file type '{ext}'. Accepted: PDF, DOCX, PPTX, TXT",
        )

    # Validate MIME type (guards against extension spoofing, e.g. malicious.exe renamed to .pdf)
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type and content_type not in _SUPPORTED_MIMES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported content type '{content_type}'. Accepted: PDF, DOCX, PPTX, TXT",
        )

    # Read file in 64 KB chunks up to limit (DoS guard)
    content = bytearray()
    chunk_size = 64 * 1024  # 64 KB
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        content.extend(chunk)
        if len(content) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="File exceeds the 20 MB upload limit.",
            )

    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File is empty.",
        )

    # Set RLS context so conversations table is visible to this tenant
    rls_sql, rls_params = get_set_tenant_sql(current_user.tenant_id)
    await session.execute(text(rls_sql), rls_params)

    # Verify conversation ownership (prevents cross-user and cross-tenant uploads)
    conv_result = await session.execute(
        text(
            "SELECT id FROM conversations "
            "WHERE id = CAST(:conv_id AS uuid) "
            "AND user_id = CAST(:user_id AS uuid) "
            "AND tenant_id = CAST(:tenant_id AS uuid)"
        ),
        {
            "conv_id": conversation_id,
            "user_id": current_user.id,
            "tenant_id": current_user.tenant_id,
        },
    )
    if conv_result.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{conversation_id}' not found.",
        )

    # Write to temp file, run pipeline, clean up
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=ext, prefix="conv_upload_"
        ) as tmp:
            tmp.write(bytes(content))
            tmp_path = tmp.name

        pipeline = DocumentIndexingPipeline()
        result = await pipeline.process_conversation_file(
            file_path=tmp_path,
            conversation_id=conversation_id,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            original_filename=safe_filename,
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    if result["chunks_indexed"] == 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Document was uploaded but no content could be indexed. "
                "The file may be corrupt, password-protected, or contain no extractable text."
            ),
        )

    logger.info(
        "conversation_document_upload_complete",
        conversation_id=conversation_id,
        file_name=safe_filename,
        chunks_indexed=result["chunks_indexed"],
        tenant_id=current_user.tenant_id,
    )

    return {
        "conversation_id": conversation_id,
        "file_name": safe_filename,
        "chunks_indexed": result["chunks_indexed"],
        "index_id": result["index_id"],
    }
