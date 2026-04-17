"""RQ queue accessor.

Jobs are enqueued by string path (``worker.jobs.ingest.process_drawing``)
so the API doesn't need to import worker code — the worker is the sole
owner of job implementations.
"""

from __future__ import annotations

from functools import lru_cache

from rq import Queue

from app.core.config import get_settings
from app.core.redis import get_redis

INGEST_JOB_PATH = "worker.jobs.ingest.process_drawing"
EXTRACTION_JOB_PATH = "worker.jobs.extract.run_dxf_extraction"


@lru_cache(maxsize=1)
def get_queue() -> Queue:
    s = get_settings()
    return Queue(s.ingest_queue, connection=get_redis())


def enqueue_ingest(drawing_id: str) -> str:
    """Enqueue a drawing for ingest. Returns the RQ job id."""
    job = get_queue().enqueue(
        INGEST_JOB_PATH,
        drawing_id,
        job_timeout=60 * 60,  # 1 hour hard ceiling for ingest
        result_ttl=60 * 60 * 24,
        failure_ttl=60 * 60 * 24 * 7,
    )
    return job.id


def enqueue_extraction(source_id: str) -> str:
    """Enqueue a queued ElementSource for DXF extraction. Returns RQ job id."""
    job = get_queue().enqueue(
        EXTRACTION_JOB_PATH,
        source_id,
        job_timeout=60 * 30,  # 30 min ceiling for extraction
        result_ttl=60 * 60 * 24,
        failure_ttl=60 * 60 * 24 * 7,
    )
    return job.id
