"""إسناد المتحدث — تصنيف لغوي بالمحتوى + سياق تبادل الأدوار (لا يتطلب قاعدة بيانات)."""
from app.pipelines.speaker import attribute_speaker, label_ar
from app.pipelines.stt import MOCK_DIALOGUE


def test_mock_dialogue_maps_patient_then_doctor():
    """الحوار التجريبي: 3 أدوار للمريض (تحية/شكوى) ثم 9 للطبيب (فحص/تقييم/خطة)."""
    expected = ["patient"] * 3 + ["doctor"] * 9
    prev = None
    got = []
    for line in MOCK_DIALOGUE:
        speaker, confidence = attribute_speaker(line, prev)
        assert 0.0 <= confidence <= 1.0
        got.append(speaker)
        prev = speaker
    assert got == expected


def test_clear_cues_are_high_confidence():
    doctor, dc = attribute_speaker("خليني أقيس لك الضغط والنبض")
    patient, pc = attribute_speaker("السلام عليكم دكتور، أنا أحس بصداع من ثلاثة أيام")
    assert doctor == "doctor" and dc >= 0.7
    assert patient == "patient" and pc >= 0.7


def test_turn_taking_breaks_neutral_ties():
    """جملة محايدة («طيب، تمام») تُرجَّح للطرف المقابل للدور السابق."""
    after_patient, _ = attribute_speaker("طيب تمام", prev_speaker="patient")
    after_doctor, _ = attribute_speaker("طيب تمام", prev_speaker="doctor")
    assert after_patient == "doctor"
    assert after_doctor == "patient"


def test_labels():
    assert label_ar("doctor") == "الطبيب"
    assert label_ar("patient") == "المريض"
