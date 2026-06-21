from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.core.config import get_settings
from app.core.exceptions import (
    DocumentParsingError,
    DocumentTooLargeError,
    DocumentValidationError,
    UnsupportedDocumentTypeError,
)
from app.models.document import ParsedDocument
from app.services import DocumentService

router = APIRouter(tags=["documents"])


@router.post(
    "/upload",
    response_model=ParsedDocument,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(file: UploadFile = File(...)) -> ParsedDocument:
    """Validate, parse, and persist one supported document."""
    settings = get_settings()
    content = await file.read(settings.max_upload_size_bytes + 1)
    service = DocumentService(settings)

    try:
        return service.process(
            filename=file.filename,
            content_type=file.content_type,
            content=content,
        )
    except DocumentTooLargeError as error:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(error),
        ) from error
    except UnsupportedDocumentTypeError as error:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(error),
        ) from error
    except DocumentValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error
    except DocumentParsingError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    finally:
        await file.close()
