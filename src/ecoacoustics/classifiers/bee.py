"""
Bee buzz classifier using BuzzDetect (OSU Bee Lab).

BuzzDetect uses a YAMNet-based transfer learning model to detect insect
flight buzz in audio. The model outputs per-frame activations for 13 sound
categories; we detect on 'ins_buzz' (insect flight buzz) and 'ins_trill'
(insect trill/stridulation — captured here as a secondary signal).

This classifier runs at 16 kHz (YAMNet's native sample rate). It can run
concurrently on the same physical microphone as bird/bat classifiers because
the pipeline keys AudioCapture by (sample_rate, device), giving each rate a
separate audio stream from the same hardware.

Architecture note for future insect classifiers
-------------------------------------------------
Grasshoppers and bush crickets stridulate at 2–20 kHz and can be detected
with a different model (e.g., AVES fine-tune or a custom sklearn pipeline).
Register them as separate classifiers:
    REGISTRY["grasshopper"] = GrasshopperClassifier
    REGISTRY["cricket"]     = BushCricketClassifier
They will all appear under the 🦗 Insects tab in the web UI.

Author: David Green, Blenheim Palace
BuzzDetect: OSU Bee Lab — github.com/OSU-Bee-Lab/buzzdetect (v1.0.1)
"""

import sys
import logging
from pathlib import Path
from typing import Optional

import numpy as np

from ecoacoustics.classifiers.base import BaseClassifier, Detection
from ecoacoustics.audio.capture import AudioChunk

_log = logging.getLogger(__name__)

_BUZZDETECT_DIR = Path(__file__).parent.parent.parent.parent / "external" / "buzzdetect"
_MODEL_NAME = "model_general"
_BUZZ_CLASS = "ins_buzz"
_TRILL_CLASS = "ins_trill"
_FRAMELENGTH_S = 0.96   # YAMNet frame length
_SAMPLERATE = 16000


class BeeClassifier(BaseClassifier):
    """Detects insect flight buzz using BuzzDetect / YAMNet transfer model."""

    name = "bee"

    def __init__(self, cfg: dict):
        # BuzzDetect outputs raw logits, not probabilities.
        # README: threshold of -1.45 yields ~90% specificity and ~42% sensitivity.
        # Lower = more detections (less specific). Raise to reduce false positives.
        self._logit_threshold: float = cfg.get("logit_threshold", -1.45)
        self._include_trill: bool = cfg.get("include_trill", False)
        self._yamnet = None
        self._yamnet_infer = None
        self._transfer = None
        self._transfer_infer = None
        self._buzz_idx: Optional[int] = None
        self._trill_idx: Optional[int] = None

    @property
    def sample_rate(self) -> int:
        return _SAMPLERATE

    @property
    def freq_min_hz(self) -> Optional[int]:
        return 80

    @property
    def freq_max_hz(self) -> Optional[int]:
        return 1500

    def load(self) -> None:
        if not _BUZZDETECT_DIR.exists():
            _log.info("BuzzDetect model not found — downloading automatically…")
            self._fetch_buzzdetect()
        self._load_models()

    def _fetch_buzzdetect(self) -> None:
        import subprocess
        from rich.console import Console
        _con = Console()
        _con.print("[dim]Downloading BuzzDetect bee model (first-time setup, ~16 MB)…[/dim]")
        _BUZZDETECT_DIR.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", "v1.0.1",
                 "https://github.com/OSU-Bee-Lab/buzzdetect.git",
                 str(_BUZZDETECT_DIR)],
                check=True, capture_output=True, text=True,
            )
            _con.print("[dim]BuzzDetect downloaded.[/dim]")
        except FileNotFoundError:
            raise RuntimeError(
                "git is required to download the BuzzDetect bee model. "
                "Install it with: sudo apt-get install git"
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"Failed to download BuzzDetect: {exc.stderr.strip()}\n"
                "Try manually: git clone --depth 1 --branch v1.0.1 "
                "https://github.com/OSU-Bee-Lab/buzzdetect.git external/buzzdetect"
            ) from exc

    def _load_models(self) -> None:

        import json
        import tensorflow as tf

        yamnet_path = str(_BUZZDETECT_DIR / "embedders" / "yamnet")
        model_path = str(_BUZZDETECT_DIR / "models" / _MODEL_NAME)

        # tf.saved_model.load() works with TF2 SavedModels regardless of
        # Keras version — buzzcode's load_model uses keras.load_model which
        # dropped SavedModel support in Keras 3.
        _log.info("BeeClassifier: loading YAMNet from %s", yamnet_path)
        self._yamnet = tf.saved_model.load(yamnet_path)
        self._yamnet_infer = (
            self._yamnet.signatures.get("serving_default")
            or self._yamnet.__call__
        )

        _log.info("BeeClassifier: loading transfer model from %s", model_path)
        self._transfer = tf.saved_model.load(model_path)
        self._transfer_infer = (
            self._transfer.signatures.get("serving_default")
            or self._transfer.__call__
        )

        with open(f"{model_path}/config_model.txt") as f:
            config = json.load(f)
        classes = config["classes"]
        self._buzz_idx = classes.index(_BUZZ_CLASS)
        self._trill_idx = classes.index(_TRILL_CLASS) if _TRILL_CLASS in classes else None
        _log.info("BeeClassifier: ready — classes=%s buzz_idx=%d", classes, self._buzz_idx)

    def classify(self, chunk: AudioChunk) -> list[Detection]:
        if self._yamnet_infer is None or self._transfer_infer is None:
            return []

        import tensorflow as tf

        audio = chunk.data.astype(np.float32)
        min_samples = int(_FRAMELENGTH_S * _SAMPLERATE)
        if len(audio) < min_samples:
            return []

        try:
            audio_t = tf.constant(audio, dtype=tf.float32)

            raw_emb = self._yamnet_infer(audio_t)
            embeddings = self._extract_embeddings(raw_emb)

            raw_pred = self._transfer_infer(embeddings)
            pred_array = np.array(self._extract_tensor(raw_pred))  # (n_frames, n_classes)

            buzz_logit = float(np.max(pred_array[:, self._buzz_idx]))
            trill_logit = None
            if self._include_trill and self._trill_idx is not None:
                trill_logit = float(np.max(pred_array[:, self._trill_idx]))

            best_logit = buzz_logit if trill_logit is None else max(buzz_logit, trill_logit)
            if best_logit < self._logit_threshold:
                return []

            # Convert logit to a 0–1 confidence for display (sigmoid)
            confidence = float(1.0 / (1.0 + np.exp(-best_logit)))
            category = _BUZZ_CLASS if (trill_logit is None or buzz_logit >= trill_logit) else _TRILL_CLASS
            return [Detection(
                label="Honey Bee",
                confidence=round(confidence, 4),
                classifier=self.name,
                timestamp=chunk.timestamp,
                metadata={
                    "category": category,
                    "buzz_logit": round(buzz_logit, 3),
                    "trill_logit": round(trill_logit, 3) if trill_logit is not None else None,
                    "logit_threshold": self._logit_threshold,
                    "model": _MODEL_NAME,
                },
            )]

        except Exception as exc:
            _log.warning("BeeClassifier.classify error: %s", exc)
            return []

    @staticmethod
    def _extract_embeddings(raw):
        """Extract the 1024-dim YAMNet embedding tensor from whatever the model returns."""
        import tensorflow as tf
        if isinstance(raw, dict):
            for v in raw.values():
                t = tf.constant(v)
                if len(t.shape) >= 2 and t.shape[-1] == 1024:
                    return t
            vals = list(raw.values())
            return vals[1] if len(vals) > 1 else vals[0]
        if isinstance(raw, (list, tuple)):
            for item in raw:
                t = tf.constant(item)
                if len(t.shape) >= 2 and t.shape[-1] == 1024:
                    return t
            return raw[1] if len(raw) > 1 else raw[0]
        return raw

    @staticmethod
    def _extract_tensor(raw):
        """Extract the prediction tensor from model output."""
        if isinstance(raw, dict):
            return list(raw.values())[0]
        if isinstance(raw, (list, tuple)):
            return raw[0]
        return raw

    def cleanup(self) -> None:
        self._yamnet = None
        self._yamnet_infer = None
        self._transfer = None
        self._transfer_infer = None
