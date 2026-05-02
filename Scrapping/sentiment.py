from typing import Callable, List, Optional, Tuple

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_NAME = "cardiffnlp/twitter-xlm-roberta-base-sentiment"
ID2LABEL = {0: "negativo", 1: "neutral", 2: "positivo"}


class SentimentAnalyzer:
    def __init__(self, model_name: str = MODEL_NAME):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        # `use_fast=False` evita rutas de conversión que pueden requerir tiktoken
        # para algunos modelos/tokenizers en ciertos entornos.
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=False)
        except Exception as exc:
            raise RuntimeError(
                "No se pudo cargar el tokenizer. Asegúrate de instalar "
                "`sentencepiece` (y opcionalmente `tiktoken`) en el entorno."
            ) from exc
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name).to(self.device)
        self.model.eval()

    @torch.inference_mode()
    def predict(
        self,
        texts: List[str],
        batch_size: int = 16,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[List[str], List[float]]:
        if not texts:
            return [], []

        labels: List[str] = []
        scores: List[float] = []
        total_batches = (len(texts) + batch_size - 1) // batch_size

        for batch_idx, start in enumerate(range(0, len(texts), batch_size), start=1):
            if progress_callback:
                progress_callback(batch_idx, total_batches)

            chunk = texts[start : start + batch_size]
            encoded = self.tokenizer(
                chunk,
                truncation=True,
                padding=True,
                max_length=512,
                return_tensors="pt",
            ).to(self.device)
            logits = self.model(**encoded).logits
            probs = torch.softmax(logits, dim=1)
            best_scores, best_ids = torch.max(probs, dim=1)

            labels.extend(ID2LABEL[int(idx)] for idx in best_ids.tolist())
            scores.extend(float(sc) for sc in best_scores.tolist())

        return labels, scores
