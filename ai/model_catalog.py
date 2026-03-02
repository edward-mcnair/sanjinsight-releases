"""
ai/model_catalog.py

Curated list of GGUF models suitable for SanjINSIGHT's AI assistant.

All models are instruction-tuned, available from bartowski's HuggingFace
repositories (well-maintained, high-quality GGUF quantisations).

Models are ordered from smallest to largest so the UI can list them that way.
"""

from __future__ import annotations

# Ordered small → large for UI display
MODEL_ORDER: list[str] = [
    "qwen25_1b5_q4",
    "phi35_mini_q4",
    "qwen25_7b_q4",
]

MODEL_CATALOG: dict[str, dict] = {
    "qwen25_1b5_q4": {
        "name":        "Qwen 2.5 — 1.5B  (Lightweight)",
        "filename":    "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
        "url": (
            "https://huggingface.co/bartowski/Qwen2.5-1.5B-Instruct-GGUF"
            "/resolve/main/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"
        ),
        "size_gb":     1.0,
        "min_ram_gb":  4,
        "description": (
            "Fastest and smallest model. Good for older PCs or systems "
            "with limited available memory (4–6 GB)."
        ),
    },
    "phi35_mini_q4": {
        "name":        "Phi 3.5 Mini — 3.8B  (Balanced)",
        "filename":    "Phi-3.5-mini-instruct-Q4_K_M.gguf",
        "url": (
            "https://huggingface.co/bartowski/Phi-3.5-mini-instruct-GGUF"
            "/resolve/main/Phi-3.5-mini-instruct-Q4_K_M.gguf"
        ),
        "size_gb":     2.4,
        "min_ram_gb":  6,
        "description": (
            "Best balance of speed and quality. Runs well on most modern "
            "PCs (6–16 GB RAM or 4+ GB VRAM)."
        ),
    },
    "qwen25_7b_q4": {
        "name":        "Qwen 2.5 — 7B  (High Quality)",
        "filename":    "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "url": (
            "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF"
            "/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf"
        ),
        "size_gb":     4.5,
        "min_ram_gb":  10,
        "description": (
            "Highest quality responses. Recommended for high-end PCs with "
            "16 GB+ RAM or 8+ GB VRAM."
        ),
    },
}
