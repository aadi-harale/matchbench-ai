"""Pinned public ONNX artifacts shared by local, Docker, and Vercel builds."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from shutil import copyfileobj
from sys import argv
from urllib.request import urlopen

MODELS = {
    "embed": ("sentence-transformers/all-MiniLM-L6-v2", "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"),
    "rank": ("cross-encoder/ms-marco-MiniLM-L6-v2", "233902d25c440f23af6f7d6e94d2946bac0bee0a"),
}
WEIGHTS = "onnx/model_quint8_avx2.onnx"
MODEL_IDS = {key: f"{repo}@{rev}:{WEIGHTS}" for key, (repo, rev) in MODELS.items()}


def download_models(target: Path) -> None:
    def download(key: str) -> None:
        repo, revision = MODELS[key]
        directory = target / key
        directory.mkdir(parents=True, exist_ok=True)
        for name, remote, minimum in (
            ("tokenizer.json", "tokenizer.json", 500),
            ("model.onnx", WEIGHTS, 10_000_000),
        ):
            path = directory / name
            if path.exists() and path.stat().st_size > minimum:
                continue
            temporary = path.with_suffix(".part")
            try:
                url = f"https://huggingface.co/{repo}/resolve/{revision}/{remote}?download=true"
                with urlopen(url, timeout=90) as response, temporary.open("wb") as stream:
                    copyfileobj(response, stream)
                if temporary.stat().st_size < minimum:
                    raise RuntimeError(f"Invalid model asset {key}/{name}")
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(download, MODELS))


if __name__ == "__main__":
    download_models(Path(argv[1] if len(argv) > 1 else ".models"))
