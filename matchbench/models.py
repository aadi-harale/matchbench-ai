from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from threading import BoundedSemaphore

import numpy as np
import onnxruntime as ort
from numpy.typing import NDArray
from tokenizers import Tokenizer

from .model_assets import MODEL_IDS

EMBED_ID = MODEL_IDS["embed"]
RERANK_ID = MODEL_IDS["rank"]


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
