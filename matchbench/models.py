from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from threading import BoundedSemaphore

import httpx
import numpy as np
import onnxruntime as ort
from numpy.typing import NDArray
from tokenizers import Tokenizer

MODELS = {
    "embed": ("sentence-transformers/all-MiniLM-L6-v2", "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"),
    "rank": ("cross-encoder/ms-marco-MiniLM-L6-v2", "233902d25c440f23af6f7d6e94d2946bac0bee0a"),
}
WEIGHTS = "onnx/model_quint8_avx2.onnx"
MODEL_IDS = {key: f"{repo}@{rev}:{WEIGHTS}" for key, (repo, rev) in MODELS.items()}
EMBED_ID = MODEL_IDS["embed"]
RERANK_ID = MODEL_IDS["rank"]


def download_models(target: Path) -> None:
    def download(key: str) -> None:
        repo, revision = MODELS[key]
        directory = target / key
        directory.mkdir(parents=True, exist_ok=True)
        with httpx.Client(follow_redirects=True, timeout=90) as client:
            for name, remote, minimum in (
                ("tokenizer.json", "tokenizer.json", 500),
                ("model.onnx", WEIGHTS, 10_000_000),
            ):
                path = directory / name
                if path.exists() and path.stat().st_size > minimum:
                    continue
                temporary = path.with_suffix(".part")
                try:
                    url = f"https://huggingface.co/{repo}/resolve/{revision}/{remote}"
                    with client.stream("GET", url, params={"download": "true"}) as response:
                        response.raise_for_status()
                        with temporary.open("wb") as stream:
                            for chunk in response.iter_bytes():
                                stream.write(chunk)
                    if temporary.stat().st_size < minimum:
                        raise RuntimeError(f"Invalid model asset {key}/{name}")
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(download, MODELS))


class Encoder:
    def __init__(self, path: Path, max_length: int):
        self.tokenizer = Tokenizer.from_file(str(path / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=max_length)
        self.tokenizer.enable_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(path / "model.onnx"), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.inputs = {item.name for item in self.session.get_inputs()}

    def run(self, inputs: list[str] | list[tuple[str, str]]):
        batch = self.tokenizer.encode_batch(inputs)
        mask = np.asarray([item.attention_mask for item in batch], dtype=np.int64)
        arrays = {
            "input_ids": np.asarray([item.ids for item in batch], dtype=np.int64),
            "attention_mask": mask,
            "token_type_ids": np.asarray([item.type_ids for item in batch], dtype=np.int64),
        }
        output = self.session.run(None, {key: arrays[key] for key in self.inputs})[0]
        return output, mask


class Models:
    def __init__(self, path: Path):
        self.path = path
        self.rerank_slots = BoundedSemaphore(2)
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rerank")

    def available(self, key: str) -> bool:
        directory = self.path / key
        return (directory / "model.onnx").is_file() and (directory / "tokenizer.json").is_file()

    @lru_cache(maxsize=4)
    def load(self, key: str) -> Encoder:
        if not self.available(key):
            raise FileNotFoundError(f"{key} model assets unavailable")
        return Encoder(self.path / key, max_length=256)

    def embed(self, inputs: list[str]) -> NDArray[np.float32]:
        encoder = self.load("embed")
        chunks = []
        for offset in range(0, len(inputs), 32):
            tokens, mask = encoder.run(inputs[offset:offset + 32])
            pooled = (tokens * mask[:, :, None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)
            chunks.append(pooled / np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9))
        return np.concatenate(chunks).astype(np.float32)

    @lru_cache(maxsize=256)
    def query_vector(self, query: str) -> NDArray[np.float32]:
        return self.embed([query])[0]

    def rerank(self, query: str, documents: list[str], timeout: float) -> list[float]:
        if not self.rerank_slots.acquire(blocking=False):
            raise TimeoutError("Reranker is busy")

        def predict():
            try:
                encoder = self.load("rank")
                results: list[float] = []
                for offset in range(0, len(documents), 16):
                    pairs = [(query, document) for document in documents[offset:offset + 16]]
                    raw, _ = encoder.run(pairs)
                    results.extend(float(value) for value in raw.reshape(-1))
                return results
            finally:
                self.rerank_slots.release()

        return self.pool.submit(predict).result(timeout=timeout)
