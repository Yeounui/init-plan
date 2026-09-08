from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Sequence
import sys
import types
from typing import Any

import pytest

from plan_rag.embeddings import (
    EmbeddingDeviceSelection,
    EmbeddingError,
    FlagEmbeddingBgeM3Client,
    _probe_cuda_details,
)


def _cpu_started_client(
    monkeypatch: pytest.MonkeyPatch,
    model_class: type,
) -> FlagEmbeddingBgeM3Client:
    module = types.ModuleType("FlagEmbedding")
    module.BGEM3FlagModel = model_class
    monkeypatch.setitem(sys.modules, "FlagEmbedding", module)
    return FlagEmbeddingBgeM3Client(
        "/models/bge-m3",
        use_fp16=True,
        device_selection=EmbeddingDeviceSelection(
            requested="auto",
            effective="cpu",
            reason="local_llm_active",
        ),
        local_llm_pid_file="/tmp/llama.pid",
    )


class _LifecycleModel:
    created: list[_LifecycleModel] = []
    fail_cuda_init = False
    fail_cuda_encode = False

    def __init__(
        self,
        model_name_or_path: str,
        *,
        use_fp16: bool,
        devices: str,
    ) -> None:
        if self.fail_cuda_init and devices.startswith("cuda"):
            raise RuntimeError("cuda initialization failed")
        self.model_name_or_path = model_name_or_path
        self.use_fp16 = use_fp16
        self.devices = devices
        self.encode_calls = 0
        self.close_calls = 0
        self.stop_pool_calls = 0
        type(self).created.append(self)

    def encode(
        self,
        texts: Sequence[str],
        *,
        return_dense: bool,
        return_sparse: bool,
        return_colbert_vecs: bool,
    ) -> dict[str, Any]:
        self.encode_calls += 1
        if self.fail_cuda_encode and self.devices.startswith("cuda"):
            raise RuntimeError("cuda inference failed")
        output: dict[str, Any] = {}
        marker = 1.0 if self.devices == "cpu" else 2.0
        if return_dense:
            output["dense_vecs"] = [[marker, float(len(text))] for text in texts]
        if return_sparse:
            output["lexical_weights"] = [
                {f"{self.devices}:{text}": marker} for text in texts
            ]
        if return_colbert_vecs:
            output["colbert_vecs"] = [
                (self.devices, *text.casefold().split()) for text in texts
            ]
        return output

    def colbert_score(
        self,
        query_vecs: Sequence[str],
        document_vecs: Sequence[str],
    ) -> float:
        return float(self.devices.startswith("cuda")) + float(
            len(set(query_vecs) & set(document_vecs))
        )

    def close(self) -> None:
        self.close_calls += 1

    def stop_self_pool(self) -> None:
        self.stop_pool_calls += 1


@pytest.fixture(autouse=True)
def _reset_lifecycle_model() -> None:
    _LifecycleModel.created = []
    _LifecycleModel.fail_cuda_init = False
    _LifecycleModel.fail_cuda_encode = False


@pytest.mark.parametrize("operation_name", ["dense", "sparse", "colbert"])
def test_first_embedding_operation_lazily_promotes_a_cpu_started_client(
    monkeypatch: pytest.MonkeyPatch,
    operation_name: str,
) -> None:
    checks = 0

    def inactive(_pid_file: str) -> bool:
        nonlocal checks
        checks += 1
        return False

    monkeypatch.setattr("plan_rag.embeddings._local_llm_is_active", inactive)
    client = _cpu_started_client(monkeypatch, _LifecycleModel)

    assert client.device_status == {
        "requested": "auto",
        "effective": "cpu",
        "gpu_visible": False,
        "reason": "local_llm_active",
    }
    assert checks == 0
    assert _LifecycleModel.created == []

    if operation_name == "dense":
        assert client.embed(["alpha"]) == [[2.0, 5.0]]
    elif operation_name == "sparse":
        assert client.sparse_lexical_weights(["alpha"]) == [{"cuda:0:alpha": 2.0}]
    else:
        assert client.colbert_scores("alpha", ["alpha beta"]) == [3.0]

    (cuda_model,) = _LifecycleModel.created
    assert cuda_model.devices == "cuda:0"
    assert cuda_model.use_fp16 is True
    assert client.device_status == {
        "requested": "auto",
        "effective": "cuda:0",
        "gpu_visible": True,
        "reason": "local_llm_released",
    }


def test_lazy_client_uses_cpu_when_local_llm_remains_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "plan_rag.embeddings._local_llm_is_active",
        lambda _pid_file: True,
    )
    client = _cpu_started_client(monkeypatch, _LifecycleModel)

    assert client.embed(["first"]) == [[1.0, 5.0]]
    assert client.device_status["effective"] == "cpu"
    assert [model.devices for model in _LifecycleModel.created] == ["cpu"]


@pytest.mark.parametrize("failure", ["initialization", "inference"])
def test_cuda_promotion_failure_falls_back_once_for_process_lifetime(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    monkeypatch.setattr(
        "plan_rag.embeddings._local_llm_is_active", lambda _pid_file: False
    )
    if failure == "initialization":
        _LifecycleModel.fail_cuda_init = True
    else:
        _LifecycleModel.fail_cuda_encode = True
    client = _cpu_started_client(monkeypatch, _LifecycleModel)

    assert client.embed(["first"]) == [[1.0, 5.0]]
    assert client.device_status == {
        "requested": "auto",
        "effective": "cpu",
        "gpu_visible": True,
        "reason": "cuda_initialization_failed",
    }

    assert client.embed(["second"]) == [[1.0, 6.0]]
    if failure == "initialization":
        assert len(_LifecycleModel.created) == 1
        assert _LifecycleModel.created[0].devices == "cpu"
    else:
        assert len(_LifecycleModel.created) == 2
        assert _LifecycleModel.created[0].stop_pool_calls == 1
        assert _LifecycleModel.created[1].devices == "cpu"


def test_explicit_cpu_policy_never_promotes(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("FlagEmbedding")
    module.BGEM3FlagModel = _LifecycleModel
    monkeypatch.setitem(sys.modules, "FlagEmbedding", module)
    monkeypatch.setattr(
        "plan_rag.embeddings._local_llm_is_active", lambda _pid_file: False
    )
    client = FlagEmbeddingBgeM3Client(
        "/models/bge-m3",
        device_selection=EmbeddingDeviceSelection("cpu", "cpu", "explicit"),
        local_llm_pid_file="/tmp/llama.pid",
    )

    assert client.embed(["alpha"]) == [[1.0, 5.0]]
    assert [model.devices for model in _LifecycleModel.created] == ["cpu"]


def test_concurrent_requests_create_only_one_cuda_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "plan_rag.embeddings._local_llm_is_active", lambda _pid_file: False
    )
    client = _cpu_started_client(monkeypatch, _LifecycleModel)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(client.embed, ([f"text-{i}"] for i in range(16))))

    assert all(result[0][0] == 2.0 for result in results)
    assert [model.devices for model in _LifecycleModel.created] == ["cuda:0"]


def test_close_is_idempotent_and_rejects_later_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "plan_rag.embeddings._local_llm_is_active", lambda _pid_file: True
    )
    client = _cpu_started_client(monkeypatch, _LifecycleModel)

    client.close()
    client.close()

    assert _LifecycleModel.created == []
    with pytest.raises(EmbeddingError, match="closed"):
        client.embed(["alpha"])


def test_model_disposal_collects_references_and_releases_cuda_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collections = 0
    cache_releases = 0

    def collect() -> int:
        nonlocal collections
        collections += 1
        return 0

    def empty_cuda_cache() -> None:
        nonlocal cache_releases
        cache_releases += 1

    monkeypatch.setattr(
        "plan_rag.embeddings._local_llm_is_active", lambda _pid_file: False
    )
    monkeypatch.setattr("plan_rag.embeddings.gc.collect", collect)
    monkeypatch.setattr("plan_rag.embeddings._empty_cuda_cache", empty_cuda_cache)
    client = _cpu_started_client(monkeypatch, _LifecycleModel)

    client.embed(["promote"])
    assert collections == 0
    assert cache_releases == 0

    client.close()
    assert collections == 1
    assert cache_releases == 1
    assert _LifecycleModel.created[0].stop_pool_calls == 1


def test_close_falls_back_when_model_has_no_stop_self_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CloseOnlyModel(_LifecycleModel):
        created: list[CloseOnlyModel] = []
        stop_self_pool = None

    monkeypatch.setattr(
        "plan_rag.embeddings._local_llm_is_active", lambda _pid_file: True
    )
    client = _cpu_started_client(monkeypatch, CloseOnlyModel)

    client.embed(["load"])
    client.close()

    assert CloseOnlyModel.created[0].close_calls == 1


def test_gpu_probe_distinguishes_host_access_block_from_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockedCuda:
        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def device_count() -> int:
            return 1

        @staticmethod
        def get_device_properties(_index: int) -> object:
            raise PermissionError("GPU access blocked")

    blocked_torch = types.ModuleType("torch")
    blocked_torch.cuda = BlockedCuda()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", blocked_torch)
    assert _probe_cuda_details() == (False, "gpu_access_blocked", False)

    class MissingCuda(BlockedCuda):
        @staticmethod
        def is_available() -> bool:
            return False

    missing_torch = types.ModuleType("torch")
    missing_torch.cuda = MissingCuda()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", missing_torch)
    monkeypatch.setattr(
        "plan_rag.embeddings._probe_nvml_visibility",
        lambda: "unavailable",
    )
    assert _probe_cuda_details() == (False, "cuda_unavailable", False)

    monkeypatch.setattr(
        "plan_rag.embeddings._probe_nvml_visibility",
        lambda: "visible",
    )
    assert _probe_cuda_details() == (False, "cuda_initialization_failed", True)
