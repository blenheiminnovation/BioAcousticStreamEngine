"""
Insect classifier — Orthoptera (grasshoppers & bush crickets).

Built around OpenSoundscape's CNN model format, which is the engine used by
OrthopterOSS (the Orthoptera classifier referenced in the 2025 ScienceDirect
review of passive acoustic monitoring of Orthoptera).

How to activate
---------------
1. Obtain a trained model — either:
   a. Wait for OrthopterOSS to be publicly released (imminent as of 2025).
      It will be pip-installable and target ~17 species at ~86% accuracy.
   b. Train your own using OpenSoundscape + InsectSet459/ECOSoundSet data
      (European coverage: ~200 species including UK targets).

2. Place the model file at the path configured in settings.yaml:
      insect:
        model_path: "models/orthoptera.model"  # or .pt

3. Add "insect" to classifiers.active in settings.yaml.
   The classifier loads silently if OpenSoundscape is not installed or the
   model file is absent — it simply returns no detections.

Supported UK/European species (example — depends on model)
-----------------------------------------------------------
  Chorthippus brunneus        — Field Grasshopper
  Chorthippus parallelus      — Meadow Grasshopper
  Chorthippus albomarginatus  — Lesser Marsh Grasshopper
  Omocestus viridulus         — Common Green Grasshopper
  Tettigonia viridissima      — Great Green Bush-cricket
  Roeseliana roeselii         — Roesel's Bush-cricket
  Pholidoptera griseoaptera   — Dark Bush-cricket
  Leptophyes punctatissima    — Speckled Bush-cricket
  Meconema thalassinum        — Oak Bush-cricket
  Gryllus campestris          — Field Cricket

Audio
-----
  Sample rate : 44.1 kHz (captures full Orthoptera stridulation range)
  Band        : 2–20 kHz (grasshopper chirps 3–8 kHz, bush crickets up to 40 kHz)
  Microphone  : Standard microphone (unlike bats, no ultrasonic mic required for
                most grasshopper species; bush crickets benefit from a wider-range mic)

OpenSoundscape model API (for model developers)
-----------------------------------------------
  from opensoundscape.ml.cnn import load_model
  model = load_model("path/to/model.model")
  # model.classes  — list of species names
  # model.predict(file_paths, clip_duration=3, overlap_fraction=0)
  #   returns pd.DataFrame, index=file_paths, columns=species names, values=scores

Author: David Green, Blenheim Palace
References:
  - OrthopterOSS (2025): 17 spp., 86.4% TPR, OpenSoundscape-based
  - InsectSet459: Faiss et al. (2025), 459 spp., EU/UK coverage
  - ECOSoundSet: Funosas et al. (2025), 200 EU Orthoptera spp., finely annotated
  - OpenSoundscape: Lapp et al. (2023), Methods in Ecology and Evolution
"""

import logging
import tempfile
from pathlib import Path
from typing import Any, Optional

import numpy as np
import soundfile as sf

from ecoacoustics.audio.capture import AudioChunk
from ecoacoustics.classifiers.base import BaseClassifier, Detection

_log = logging.getLogger(__name__)


class InsectClassifier(BaseClassifier):
    """Orthoptera classifier using an OpenSoundscape CNN model.

    Silently inactive when OpenSoundscape is not installed or no model file
    is configured — add 'insect' to classifiers.active once a model is ready.
    """

    name = "insect"

    def __init__(self, config: dict[str, Any]):
        self._min_confidence: float = config.get("min_confidence", 0.5)
        self._model_path: Optional[str] = config.get("model_path")
        self._clip_duration: float = config.get("clip_duration", 3.0)
        self._model = None
        self._classes: list[str] = []

    @property
    def sample_rate(self) -> int:
        return 44100

    @property
    def freq_min_hz(self) -> int:
        return 2000

    @property
    def freq_max_hz(self) -> int:
        return 20000

    def load(self) -> None:
        """Load the OpenSoundscape CNN model if configured and available."""
        if not self._model_path:
            _log.info(
                "InsectClassifier: no model_path configured — "
                "add 'model_path' under 'insect' in settings.yaml once a model is available. "
                "OrthopterOSS (2025) is the recommended source."
            )
            return

        model_file = Path(self._model_path)
        if not model_file.exists():
            _log.warning(
                "InsectClassifier: model file not found at '%s' — "
                "classifier inactive. Download or train a model and check the path.",
                self._model_path,
            )
            return

        try:
            from opensoundscape.ml.cnn import load_model as osp_load_model
        except ImportError:
            _log.warning(
                "InsectClassifier: OpenSoundscape is not installed. "
                "Install it with: pip install opensoundscape"
            )
            return

        try:
            _log.info("InsectClassifier: loading model from %s", self._model_path)
            self._model = osp_load_model(str(model_file))
            self._classes = list(self._model.classes)
            _log.info(
                "InsectClassifier: ready — %d species: %s",
                len(self._classes), self._classes
            )
        except Exception as exc:
            _log.error("InsectClassifier: failed to load model: %s", exc)

    def classify(self, chunk: AudioChunk) -> list[Detection]:
        """Classify a chunk using the loaded OpenSoundscape CNN.

        OpenSoundscape's CNN.predict() takes file paths, so the chunk is
        written to a temp WAV file, classified, and the file is cleaned up.

        Args:
            chunk: Pre-processed audio at 44.1 kHz, bandpass 2–20 kHz.

        Returns:
            Detection objects for any species scoring above min_confidence,
            or an empty list if no model is loaded.
        """
        if self._model is None:
            return []

        audio = chunk.data.astype(np.float32)
        detections: list[Detection] = []

        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            sf.write(tmp_path, audio, self.sample_rate, subtype="PCM_16")

            scores_df = self._model.predict(
                [tmp_path],
                clip_overlap_fraction=0,
                batch_size=1,
                activation_layer="sigmoid",
                num_workers=0,
            )

            # scores_df: index=clip paths, columns=species names, values=scores
            if scores_df is None or scores_df.empty:
                return []

            row = scores_df.iloc[0]
            for species, score in row.items():
                if float(score) >= self._min_confidence:
                    detections.append(Detection(
                        label=species,
                        confidence=round(float(score), 4),
                        classifier=self.name,
                        timestamp=chunk.timestamp,
                        metadata={
                            "model": str(Path(self._model_path).name),
                            "group": _orthoptera_group(str(species)),
                        },
                    ))

            return sorted(detections, key=lambda d: -d.confidence)

        except Exception as exc:
            _log.warning("InsectClassifier.classify error: %s", exc)
            return []
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass

    def cleanup(self) -> None:
        self._model = None


def _orthoptera_group(species: str) -> str:
    """Label a species as Grasshopper, Bush Cricket, or Cricket from its name."""
    s = species.lower()
    if any(w in s for w in ("grasshopper", "chorthippus", "omocestus",
                             "stenobothrus", "gomphocerippus", "myrmeleotettix")):
        return "Grasshopper"
    if any(w in s for w in ("bush-cricket", "bush cricket", "tettigonia",
                             "roesel", "pholidoptera", "leptophyes",
                             "meconema", "conocephalus", "metrioptera")):
        return "Bush Cricket"
    if any(w in s for w in ("cricket", "gryllus", "acheta", "gryllotalpa")):
        return "Cricket"
    return "Orthoptera"
