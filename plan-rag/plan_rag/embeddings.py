from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import gc
import os
from pathlib import Path
import re
import subprocess
from threading import RLock
from typing import Any, Callable, TypeVar


_ResultT = TypeVar("_ResultT")


class EmbeddingError(RuntimeError):
    """The configured embedding backend could not serve a request."""


@dataclass(frozen=True, slots=True)
class EmbeddingDeviceSelection:
    requested: str
    effective: str
    reason: str
    gpu_visible: bool = False

    def metadata(self) -> dict[str, str | bool]:
        return {
            "requested": self.requested,
            "effective": self.effective,
            "gpu_visible": self.gpu_visible,
            "reason": self.reason,
        }


class FlagEmbeddingBgeM3Client:
    """Local BGE-M3 client exposing dense, sparse, and ColBERT outputs.

    The heavy FlagEmbedding dependency is imported lazily so non-vector
    operations can still run without loading the model.
    """

    def __init__(
        self,
        model_name_or_path: str,
        *,
        use_fp16: bool = True,
        device_selection: EmbeddingDeviceSelection | None = None,
        local_llm_pid_file: str = "",
    ) -> None:
        self.model_name_or_path = model_name_or_path
        self._model_class: Any | None = None
        self._use_fp16 = use_fp16
        self._local_llm_pid_file = local_llm_pid_file
        self._lock = RLock()
        self._closed = False
        self._promotion_attempted = False
        self.device_selection = device_selection or EmbeddingDeviceSelection(
            requested="cpu",
            effective="cpu",
            reason="not_configured",
        )
        # Importing FlagEmbedding and constructing BGE-M3 are intentionally
        # deferred until the first vector operation. MCP discovery and status
        # therefore do not wait for model loading or CUDA initialization.
        self._model: Any | None = None

    @property
    def device_status(self) -> dict[str, str | bool]:
        with self._lock:
            return self.device_selection.metadata()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            model, self._model = self._model, None
            try:
                self._close_model(model)
            finally:
                model = None
                self._collect_model_garbage()

    def __enter__(self) -> FlagEmbeddingBgeM3Client:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        def operation(model: Any) -> list[list[float]]:
            output = self._encode_model(
                model,
                texts,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            return _coerce_dense_vectors(output.get("dense_vecs"), len(texts))

        return self._run_with_model(operation)

    def sparse_lexical_weights(
        self,
        texts: Sequence[str],
    ) -> list[dict[str, float]]:
        if not texts:
            return []

        def operation(model: Any) -> list[dict[str, float]]:
            output = self._encode_model(
                model,
                texts,
                return_dense=False,
                return_sparse=True,
                return_colbert_vecs=False,
            )
            weights = output.get("lexical_weights")
            if not isinstance(weights, Sequence) or isinstance(weights, str):
                raise EmbeddingError("FlagEmbedding response missing lexical_weights")
            if len(weights) != len(texts):
                raise EmbeddingError(
                    "sparse weight count mismatch: "
                    f"expected {len(texts)}, got {len(weights)}"
                )
            rows: list[dict[str, float]] = []
            for row in weights:
                if not isinstance(row, dict):
                    raise EmbeddingError("lexical_weights row is not a dictionary")
                rows.append(
                    {
                        str(token): float(weight)
                        for token, weight in row.items()
                        if isinstance(weight, int | float)
                    }
                )
            return rows

        return self._run_with_model(operation)

    def colbert_scores(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []

        def operation(model: Any) -> list[float]:
            query_output = self._encode_model(
                model,
                [query],
                return_dense=False,
                return_sparse=False,
                return_colbert_vecs=True,
            )
            document_output = self._encode_model(
                model,
                documents,
                return_dense=False,
                return_sparse=False,
                return_colbert_vecs=True,
            )
            query_vecs = _coerce_sequence_field(
                query_output.get("colbert_vecs"),
                expected=1,
                field_name="colbert_vecs",
            )[0]
            document_vecs = _coerce_sequence_field(
                document_output.get("colbert_vecs"),
                expected=len(documents),
                field_name="colbert_vecs",
            )
            scores: list[float] = []
            for document_vec in document_vecs:
                score = model.colbert_score(query_vecs, document_vec)
                scores.append(_coerce_scalar(score))
            return scores

        return self._run_with_model(operation)

    def _create_model(self, device: str) -> Any:
        if self._model_class is None:
            try:
                from FlagEmbedding import BGEM3FlagModel
            except ImportError as error:
                raise EmbeddingError(
                    "FlagEmbedding backend requested but FlagEmbedding is not "
                    "installed; rebuild the Plan RAG environment with: "
                    "uv sync --frozen"
                ) from error
            self._model_class = BGEM3FlagModel
        return self._model_class(
            self.model_name_or_path,
            use_fp16=self._use_fp16,
            devices=device,
        )

    def _run_with_model(self, operation: Callable[[Any], _ResultT]) -> _ResultT:
        with self._lock:
            self._require_open()
            if self._promotion_is_eligible():
                self.device_selection = EmbeddingDeviceSelection(
                    requested="auto",
                    effective="cuda:0",
                    reason="local_llm_released",
                    gpu_visible=True,
                )
            model = self._ensure_model()
            try:
                return operation(model)
            except Exception:
                if not self.device_selection.effective.startswith("cuda"):
                    raise
                # A visible GPU can still be unusable in a sandbox or fail
                # during CUDA initialization/inference. Keep FTS and vector
                # synchronization available by retrying once on CPU.
                self._close_model_quietly(model)
                self._model = None
                self._collect_model_garbage()
                self.device_selection = EmbeddingDeviceSelection(
                    requested=self.device_selection.requested,
                    effective="cpu",
                    reason="cuda_initialization_failed",
                    gpu_visible=self.device_selection.gpu_visible,
                )
                return operation(self._ensure_model())

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            self._model = self._create_model(self.device_selection.effective)
        except Exception as error:
            if not self.device_selection.effective.startswith("cuda"):
                if isinstance(error, EmbeddingError):
                    raise
                raise EmbeddingError(
                    f"FlagEmbedding BGE-M3 initialization failed on CPU: {error}"
                ) from error
            self._collect_model_garbage()
            self.device_selection = EmbeddingDeviceSelection(
                requested=self.device_selection.requested,
                effective="cpu",
                reason="cuda_initialization_failed",
                gpu_visible=self.device_selection.gpu_visible,
            )
            try:
                self._model = self._create_model("cpu")
            except Exception as cpu_error:
                raise EmbeddingError(
                    "FlagEmbedding BGE-M3 initialization failed after CPU fallback: "
                    f"{cpu_error}"
                ) from cpu_error
        return self._model

    def _promotion_is_eligible(self) -> bool:
        return (
            not self._promotion_attempted
            and self.device_selection.requested == "auto"
            and self.device_selection.effective == "cpu"
            and self.device_selection.reason == "local_llm_active"
            and not _local_llm_is_active(self._local_llm_pid_file)
        )

    def _require_open(self) -> None:
        if self._closed:
            raise EmbeddingError("FlagEmbedding client is closed")

    @staticmethod
    def _close_model(model: Any | None) -> None:
        stop_self_pool = getattr(model, "stop_self_pool", None)
        if callable(stop_self_pool):
            try:
                stop_self_pool()
                return
            except Exception:
                close = getattr(model, "close", None)
                if callable(close):
                    close()
                    return
                raise
        close = getattr(model, "close", None)
        if callable(close):
            close()

    @classmethod
    def _close_model_quietly(cls, model: Any | None) -> None:
        try:
            cls._close_model(model)
        except Exception:
            pass

    @staticmethod
    def _collect_model_garbage() -> None:
        try:
            gc.collect()
        except Exception:
            pass
        try:
            _empty_cuda_cache()
        except Exception:
            pass

    @staticmethod
    def _encode_model(
        model: Any,
        texts: Sequence[str],
        **flags: bool,
    ) -> dict[str, Any]:
        try:
            output = model.encode(list(texts), **flags)
        except Exception as error:
            raise EmbeddingError(f"FlagEmbedding encode failed: {error}") from error
        if not isinstance(output, dict):
            raise EmbeddingError("FlagEmbedding encode response was not a dictionary")
        return output


def build_embedding_client(
    *,
    backend: str,
    model_path: str,
    use_fp16: bool,
    device: str = "auto",
    local_llm_pid_file: str = "",
) -> FlagEmbeddingBgeM3Client:
    normalized = backend.strip().casefold().replace("-", "_")
    if normalized in {"flag", "flag_embedding", "flagembedding", "bge_m3"}:
        if not model_path:
            raise EmbeddingError(
                "PLAN_RAG_EMBEDDING_MODEL_PATH must point to a local BGE-M3 model "
                "directory for the FlagEmbedding backend"
            )
        resolved_model_path = Path(model_path).expanduser()
        if not resolved_model_path.is_dir():
            raise EmbeddingError(
                "PLAN_RAG_EMBEDDING_MODEL_PATH must point to an existing local "
                "BGE-M3 model directory; download or copy the model before running "
                "Plan RAG"
            )
        selection = resolve_embedding_device(
            device,
            local_llm_pid_file=local_llm_pid_file,
        )
        return FlagEmbeddingBgeM3Client(
            model_path,
            use_fp16=use_fp16,
            device_selection=selection,
            local_llm_pid_file=local_llm_pid_file,
        )
    raise EmbeddingError(f"unknown embedding backend: {backend}")


def resolve_embedding_device(
    requested_device: str,
    *,
    local_llm_pid_file: str = "",
    cuda_available: bool | None = None,
) -> EmbeddingDeviceSelection:
    requested = requested_device.strip().casefold() or "auto"
    if cuda_available is None:
        available, unavailable_reason, gpu_visible = _probe_cuda_details()
    else:
        available = cuda_available
        unavailable_reason = "cuda_unavailable"
        gpu_visible = cuda_available
    if requested == "auto":
        if _local_llm_is_active(local_llm_pid_file):
            return EmbeddingDeviceSelection(
                requested, "cpu", "local_llm_active", gpu_visible=gpu_visible
            )
        if available:
            return EmbeddingDeviceSelection(
                requested, "cuda:0", "cuda_available", gpu_visible=True
            )
        return EmbeddingDeviceSelection(
            requested, "cpu", unavailable_reason, gpu_visible=gpu_visible
        )
    if requested == "cpu":
        return EmbeddingDeviceSelection(
            requested, "cpu", "explicit", gpu_visible=gpu_visible
        )
    if re.fullmatch(r"cuda(?::[0-9]+)?", requested):
        if available:
            return EmbeddingDeviceSelection(
                requested, requested, "explicit", gpu_visible=True
            )
        return EmbeddingDeviceSelection(
            requested, "cpu", unavailable_reason, gpu_visible=gpu_visible
        )
    raise EmbeddingError("PLAN_RAG_EMBEDDING_DEVICE must be auto, cpu, cuda, or cuda:N")


def _local_llm_is_active(pid_file: str) -> bool:
    if not pid_file:
        return False
    try:
        pid = int(Path(pid_file).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _probe_cuda_details() -> tuple[bool, str, bool]:
    try:
        import torch
    except ImportError:
        visibility = _probe_nvml_visibility()
        if visibility == "blocked":
            return False, "gpu_access_blocked", False
        return False, "cuda_unavailable", visibility == "visible"
    try:
        if not torch.cuda.is_available():
            visibility = _probe_nvml_visibility()
            if visibility == "blocked":
                return False, "gpu_access_blocked", False
            if visibility == "visible":
                return False, "cuda_initialization_failed", True
            return False, "cuda_unavailable", False
        if int(torch.cuda.device_count()) <= 0:
            return False, "cuda_unavailable", False
        # This forces a real driver call, distinguishing mere CUDA package
        # presence from a device usable by the host process.
        torch.cuda.get_device_properties(0)
    except (PermissionError, OSError) as error:
        message = str(error).casefold()
        if isinstance(error, PermissionError) or any(
            marker in message
            for marker in ("permission", "not permitted", "access denied", "blocked")
        ):
            return False, "gpu_access_blocked", False
        return False, "cuda_initialization_failed", True
    except Exception:
        return False, "cuda_initialization_failed", True
    return True, "cuda_available", True


def _probe_nvml_visibility() -> str:
    """Classify host GPU visibility without importing another Python backend."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=2,
            text=True,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return "unavailable"
    if result.returncode == 0 and result.stdout.strip():
        return "visible"
    message = f"{result.stdout}\n{result.stderr}".casefold()
    if any(
        marker in message
        for marker in ("permission", "not permitted", "access denied", "blocked")
    ):
        return "blocked"
    return "unavailable"


def _empty_cuda_cache() -> None:
    try:
        import torch
    except ImportError:
        return
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _coerce_dense_vectors(value: Any, expected: int) -> list[list[float]]:
    rows = _coerce_sequence_field(value, expected=expected, field_name="dense_vecs")
    embeddings: list[list[float]] = []
    for row in rows:
        vector = _coerce_vector(row)
        if not vector:
            raise EmbeddingError("dense_vecs response contained an empty vector")
        embeddings.append(vector)
    return embeddings


def _coerce_sequence_field(value: Any, *, expected: int, field_name: str) -> list[Any]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise EmbeddingError(f"FlagEmbedding response missing {field_name}")
    rows = list(value)
    if len(rows) != expected:
        raise EmbeddingError(
            f"{field_name} count mismatch: expected {expected}, got {len(rows)}"
        )
    return rows


def _coerce_vector(value: Any) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise EmbeddingError("dense vector row is not a sequence")
    return [float(item) for item in value]


def _coerce_scalar(value: Any) -> float:
    if hasattr(value, "item"):
        value = value.item()
    return float(value)
