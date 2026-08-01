"""صفحة ملفات الأكواد المعتمدة /sa/registry (قرار مالك 2026-08-02) —
الحالة، الرفع بخطوتين (معاينة ثم اعتماد)، الإزالة، وحراسة الأدوار."""
from __future__ import annotations

import pytest

from tests.conftest import auth


@pytest.fixture(scope="module")
def sa_token(client) -> str:
    response = client.post("/api/v1/sa/auth/login", json={"username": "owner", "password": "Owner@12345"})
    assert response.status_code == 200, response.text
    return response.json()["data"]["access_token"]


ACHI_CSV = (
    "code,short_desc,long_desc,effective_date,inactive_date,replaced_by\n"
    "30473-00,Panendoscopy to duodenum,,2023-06-01,,\n"
    "30473-01,Panendoscopy with biopsy,,2023-06-01,,\n"
    "30478-99,Old retired procedure,,2021-01-01,2023-06-01,30473-01\n"
).encode("utf-8")


def _import(client, token: str, *, system: str, version: str, dry_run: bool,
            filename: str = "achi.csv", content: bytes = ACHI_CSV):
    return client.post(
        "/api/v1/sa/registry/import",
        headers=auth(token),
        data={"system": system, "version": version, "dry_run": "true" if dry_run else "false"},
        files={"file": (filename, content, "text/csv")},
    )


def test_registry_overview_lists_all_systems(client, sa_token):
    response = client.get("/api/v1/sa/registry", headers=auth(sa_token))
    assert response.status_code == 200, response.text
    systems = {row["system"]: row for row in response.json()["data"]["systems"]}
    assert set(systems) == {"ICD10AM", "ACHI", "SBS", "SFDA", "GMDN"}
    # عيّنة البذر تحمّل SBS وICD10AM — ACHI فارغ فلا تحقق له
    assert systems["SBS"]["enforced"] is True and systems["SBS"]["inactive"] >= 1
    assert systems["ICD10AM"]["enforced"] is True
    assert systems["ACHI"]["enforced"] is False and systems["ACHI"]["total"] == 0


def test_registry_rejected_for_facility_tokens(client, admin_token):
    assert client.get("/api/v1/sa/registry", headers=auth(admin_token)).status_code == 403


def test_import_dry_run_writes_nothing(client, sa_token):
    preview = _import(client, sa_token, system="ACHI", version="ACHI 10th ed.", dry_run=True)
    assert preview.status_code == 200, preview.text
    data = preview.json()["data"]
    assert data["dry_run"] is True and data["inserted"] == 3 and data["updated"] == 0

    after = client.get("/api/v1/sa/registry", headers=auth(sa_token)).json()["data"]["systems"]
    achi = next(row for row in after if row["system"] == "ACHI")
    assert achi["total"] == 0, "المعاينة لا تكتب شيئاً"


def test_import_publish_activates_validation(client, sa_token, doctor_token):
    published = _import(client, sa_token, system="ACHI", version="ACHI 10th ed.", dry_run=False)
    assert published.status_code == 200, published.text
    data = published.json()["data"]
    assert data["inserted"] == 3
    achi = next(row for row in data["systems"] if row["system"] == "ACHI")
    assert achi["enforced"] is True and achi["active"] == 2 and achi["inactive"] == 1
    assert achi["versions"] == ["ACHI 10th ed."]

    # النشر يسري فوراً: بحث الدكاترة يجد الكود، والملغى يظهر ببديله بعد النشط
    rows = client.get("/api/v1/codes/search", headers=auth(doctor_token),
                      params={"system": "ACHI", "q": "panendoscopy"}).json()["data"]
    assert [row["code"] for row in rows[:2]] == ["30473-00", "30473-01"]
    retired = client.get("/api/v1/codes/search", headers=auth(doctor_token),
                         params={"system": "ACHI", "q": "30478"}).json()["data"]
    assert retired[0]["is_active"] is False and retired[0]["replaced_by"] == "30473-01"

    # إعادة النشر بنفس الملف = تحديث لا ازدواج (idempotent)
    again = _import(client, sa_token, system="ACHI", version="ACHI 10th ed.", dry_run=False)
    assert again.status_code == 200
    assert again.json()["data"]["inserted"] == 0 and again.json()["data"]["updated"] == 3


def test_import_rejects_invalid_file_and_system(client, sa_token):
    broken = _import(client, sa_token, system="SBS", version="SBS V9",
                     dry_run=True, filename="junk.xlsx", content=b"not-an-xlsx")
    assert broken.status_code == 422
    assert broken.json()["error"]["code"] == "MDF-4225"

    wrong_system = _import(client, sa_token, system="ICD10CM", version="ICD-10-CM 2026", dry_run=True)
    assert wrong_system.status_code == 404, "ICD-10-CM الأمريكي ليس نظاماً معتمداً"


def test_registry_clear_stops_validation(client, sa_token):
    removed = client.delete("/api/v1/sa/registry/ACHI", headers=auth(sa_token))
    assert removed.status_code == 200, removed.text
    data = removed.json()["data"]
    assert data["removed"] == 3
    achi = next(row for row in data["systems"] if row["system"] == "ACHI")
    assert achi["enforced"] is False

    again = client.delete("/api/v1/sa/registry/ACHI", headers=auth(sa_token))
    assert again.status_code == 404
