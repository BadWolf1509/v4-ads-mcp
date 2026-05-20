"""Customer Match user list upload — hashing utilities + builder + dispatcher.

Sprint 3b.28 — segundo dispatcher non-mutate fora de GoogleAdsService.mutate
(paralelo a src/google_ads/conversions.py do Sprint 3b.26).

SHA-256 hex digest client-side per Google Ads Customer Match spec.
V4 invariants: phone default country_code +55 (BR-only V4), LGPD consent
GRANTED hardcoded em metadata, enable_partial_failure=True.
"""

from __future__ import annotations

import hashlib
import re


def _normalize_and_hash_email(plaintext: str) -> str:
    """SHA-256 hex digest após lowercase + remove ALL whitespace.

    Per Google Customer Match spec:
    https://developers.google.com/google-ads/api/docs/remarketing/audience-types/customer-match#data-formatting
    """
    normalized = "".join(plaintext.split()).lower()
    return hashlib.sha256(normalized.encode()).hexdigest()


def _normalize_and_hash_phone(plaintext: str) -> str:
    """E.164 normalize + SHA-256 hex digest.

    V4 invariant: phone sem country code prefix (+) → assume +55 (BR).
    Strip non-digit chars except leading +. Numero BR começando com 0 (DDD
    legacy) tem 0 removido antes de adicionar +55.
    """
    digits = re.sub(r"[^\d+]", "", plaintext)
    if not digits.startswith("+"):
        digits = "+55" + digits.lstrip("0")
    return hashlib.sha256(digits.encode()).hexdigest()
