from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from scientific_tangle_gateway.ingestion import (
    IngestionTaskTransitionError,
    LocalUploadStorage,
)
from scientific_tangle_gateway.normalization import LocalNormalizedDocumentStore
from scientific_tangle_gateway.schemas import (
    AccessLevel,
    DocumentArtifactPayload,
    IngestionTaskPayload,
    NormalizedDocumentPayload,
)
from scientific_tangle_gateway.task_repository import TaskRepository


def create_ingestion_router(
    repository: TaskRepository,
    storage: LocalUploadStorage,
    document_store: LocalNormalizedDocumentStore,
) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/documents/upload",
        response_model=IngestionTaskPayload,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def upload_documents(
        files: list[UploadFile] = File(...),
        access_level: AccessLevel = Form("internal"),
    ) -> IngestionTaskPayload:
        if not files:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нужно загрузить хотя бы один файл",
            )

        task = await storage.save_files(files=files, access_level=access_level)
        return repository.create_task(task)

    @router.get("/tasks/{task_id}", response_model=IngestionTaskPayload)
    async def get_task(task_id: str) -> IngestionTaskPayload:
        task = repository.get_task(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ingestion task не найден",
            )
        return task

    @router.post("/tasks/{task_id}/start", response_model=IngestionTaskPayload)
    async def start_task(task_id: str) -> IngestionTaskPayload:
        try:
            task = repository.update_status(
                task_id,
                status="queued",
            )
        except IngestionTaskTransitionError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Недопустимый переход статуса: {error}",
            ) from error

        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ingestion task не найден",
            )

        return task

    @router.get("/tasks/{task_id}/documents", response_model=list[DocumentArtifactPayload])
    async def list_task_documents(task_id: str) -> list[DocumentArtifactPayload]:
        task = repository.get_task(task_id)
        documents = document_store.list_task_documents(task_id)
        if task is None and not documents:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ingestion task не найден",
            )
        return documents

    @router.get("/documents/{document_id}", response_model=NormalizedDocumentPayload)
    async def get_document(document_id: str) -> NormalizedDocumentPayload:
        document = document_store.get_document(document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="NormalizedDocument не найден",
            )
        return document

    return router
