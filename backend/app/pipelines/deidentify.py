"""إخفاء المعرفات المباشرة قبل أي إرسال للنموذج وإعادتها بعد الرد — DOC-08 §٦."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class DeidentifyMap:
    """اسم/MRN → رموز جلسة (PATIENT_1, MRN_1) قابلة للعكس بعد الرد."""

    forward: dict[str, str] = field(default_factory=dict)
    backward: dict[str, str] = field(default_factory=dict)
    _counter: int = 0

    def register(self, value: str, kind: str) -> str:
        if not value:
            return value
        if value in self.forward:
            return self.forward[value]
        self._counter += 1
        token = f"[{kind}_{self._counter}]"
        self.forward[value] = token
        self.backward[token] = value
        return token

    def scrub(self, text: str) -> str:
        result = text
        for value, token in sorted(self.forward.items(), key=lambda kv: -len(kv[0])):
            if value:
                result = result.replace(value, token)
        return result

    def restore(self, text: str) -> str:
        result = text
        for token, value in self.backward.items():
            result = result.replace(token, value)
        return result


def build_map(patient_name: str | None, mrn: str | None) -> DeidentifyMap:
    m = DeidentifyMap()
    if patient_name:
        m.register(patient_name, "PATIENT")
    if mrn:
        m.register(mrn, "MRN")
    return m


_NATIONAL_ID = re.compile(r"\b[12]\d{9}\b")  # نمط الهوية الوطنية السعودية


def scrub_freeform(text: str) -> str:
    """طبقة إضافية: إخفاء أنماط هويات وطنية في نص حر."""
    return _NATIONAL_ID.sub("[NATIONAL_ID]", text)
