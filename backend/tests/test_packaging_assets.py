"""أصول التشغيل المشحونة — تُفشل الحزمةَ محلياً بدل أن تسقط في الإنتاج.

الخلل الذي كشفه النشر: `pip install .` ينسخ كود بايثون فقط، فوقع عامل arq
(يعمل من site-packages) على برومبتات مفقودة → MDF-5032 على كل زيارة.
هذه الاختبارات تثبّت أن كل أصل يُقرأ وقت التشغيل مُعلَن ومشحون.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_every_active_prompt_version_exists_and_loads():
    """كل إصدار برومبت مُعلَن في PROMPT_VERSIONS له ملف قابل للقراءة."""
    from app.pipelines.llm import load_prompt
    from app.pipelines.run import PROMPT_VERSIONS

    for prompt_id, version in PROMPT_VERSIONS.items():
        content = load_prompt(prompt_id, version)
        assert content.strip(), f"{prompt_id}@{version} فارغ"
        assert "[OUTPUT CONTRACT" in content or "[TASK]" in content, \
            f"{prompt_id}@{version} بلا عقد مخرج"

    # م14 خارج PROMPT_VERSIONS (يُستدعى من خدمته)
    from app.services.patient_summary import PROMPT_ID, PROMPT_VERSION

    assert load_prompt(PROMPT_ID, PROMPT_VERSION).strip()


def test_prompts_declared_as_package_data():
    """البرومبتات مُعلَنة في pyproject — وإلا لا تُشحن مع الحزمة المثبَّتة."""
    config = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    package_data = config["tool"]["setuptools"].get("package-data", {})
    patterns = package_data.get("app", [])
    assert any("prompts" in pattern for pattern in patterns), \
        "prompts/*.txt غير معلَنة في [tool.setuptools.package-data] — ستُفقد في الإنتاج"


def test_claim_rules_resolve_and_parse():
    """قواعد جاهزية المطالبة تُحلّ وتُقرأ — أياً كان مجلد العمل."""
    from app.services.claim_readiness import _resolve_rules_dir, load_rules

    rules_dir = _resolve_rules_dir()
    assert rules_dir.is_dir(), f"مجلد القواعد غير موجود: {rules_dir}"
    rules = load_rules()
    assert rules, "لا قواعد محمّلة"
    for rule in rules:
        assert rule.get("rule_id") and rule.get("type") and rule.get("severity")
        assert rule["severity"] in ("pass", "warn", "block")
        assert rule.get("message_ar"), f"{rule['rule_id']} بلا رسالة عربية"


def test_dockerfile_ships_rules_directory():
    """صورة الباك اند تنسخ مجلد القواعد (يُقرأ من مجلد العمل وقت التشغيل)."""
    dockerfile = (BACKEND / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY rules" in dockerfile, "مجلد rules غير منسوخ إلى الصورة"
