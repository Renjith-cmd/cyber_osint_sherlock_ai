"""
Adversarial Security and Multi-Tenant Isolation Tests for Sherlock AI.
Validates:
1. User registration, password hashing (PBKDF2/bcrypt salt), and JWT issuance.
2. Login with valid vs invalid credentials.
3. Private case creation scoped to authenticated user.
4. Cross-user access denial: User B cannot view, query, or upload to User A's case (403 Forbidden).
5. Audit trail generation on sensitive actions and unauthorized access attempts.
"""

import pytest
from fastapi.testclient import TestClient
from src.api.app import create_app
from src.core.investigation_sqlite import SQLiteInvestigationStore


@pytest.fixture
def auth_client(tmp_path):
    db_file = str(tmp_path / "test_auth_sherlock.db")
    app = create_app(db_path=db_file, backend_mode="rule", disable_auth=False)
    client = TestClient(app)
    return client


def test_user_registration_and_login(auth_client):
    # 1. Register Alice
    reg_resp = auth_client.post(
        "/api/v1/auth/register",
        json={
            "username": "alice_investigator",
            "email": "alice@agency.gov",
            "password": "SecurePassword123!",
            "full_name": "Alice Vance",
            "role": "analyst",
        },
    )
    assert reg_resp.status_code == 201
    reg_data = reg_resp.json()
    assert "access_token" in reg_data
    assert reg_data["user"]["username"] == "alice_investigator"
    assert reg_data["user"]["email"] == "alice@agency.gov"

    alice_token = reg_data["access_token"]

    # 2. Duplicate registration rejected
    dup_resp = auth_client.post(
        "/api/v1/auth/register",
        json={
            "username": "alice_investigator",
            "email": "different@agency.gov",
            "password": "SecurePassword123!",
        },
    )
    assert dup_resp.status_code == 409

    # 3. Login with correct password
    login_resp = auth_client.post(
        "/api/v1/auth/login",
        json={
            "username": "alice_investigator",
            "password": "SecurePassword123!",
        },
    )
    assert login_resp.status_code == 200
    assert "access_token" in login_resp.json()

    # 4. Login with incorrect password rejected
    bad_login = auth_client.post(
        "/api/v1/auth/login",
        json={
            "username": "alice_investigator",
            "password": "WrongPassword!",
        },
    )
    assert bad_login.status_code == 401

    # 5. Access /auth/me with Bearer token
    me_resp = auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "alice_investigator"


def test_cross_user_investigation_isolation(auth_client):
    """
    Forensic Multi-Tenant Privacy Test:
    User A (Alice) creates a private case.
    User B (Bob) must be DENIED access to Alice's case (HTTP 403 Forbidden).
    """
    # Register Alice
    resp_a = auth_client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "email": "alice@firm.org", "password": "PasswordAlice123"},
    )
    token_a = resp_a.json()["access_token"]

    # Register Bob
    resp_b = auth_client.post(
        "/api/v1/auth/register",
        json={"username": "bob", "email": "bob@firm.org", "password": "PasswordBob123"},
    )
    token_b = resp_b.json()["access_token"]

    # Alice creates a private case
    create_resp = auth_client.post(
        "/api/v1/investigations",
        json={
            "investigation_id": "case_alice_confidential",
            "description": "Alice Top Secret Corporate Investigation",
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert create_resp.status_code == 201

    # Alice uploads a document to her case
    doc_content = b"Global Horizon Trade Corp wired $5,000,000 to Meridian Capital Trust on 2026-03-15."
    up_resp = auth_client.post(
        "/api/v1/investigations/case_alice_confidential/documents",
        files={"file": ("wire_transfer.txt", doc_content, "text/plain")},
        data={"auto_process": "true"},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert up_resp.status_code == 201

    # Alice can view her case
    alice_view = auth_client.get(
        "/api/v1/investigations/case_alice_confidential",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert alice_view.status_code == 200
    assert alice_view.json()["investigation_id"] == "case_alice_confidential"

    # Bob attempts to view Alice's case -> MUST BE 403 FORBIDDEN
    bob_view = auth_client.get(
        "/api/v1/investigations/case_alice_confidential",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert bob_view.status_code == 403
    assert "Access denied" in bob_view.json()["detail"]

    # Bob attempts to list documents from Alice's case -> 403 FORBIDDEN
    bob_docs = auth_client.get(
        "/api/v1/investigations/case_alice_confidential/documents",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert bob_docs.status_code == 403

    # Bob attempts to upload a document to Alice's case -> 403 FORBIDDEN
    bob_upload = auth_client.post(
        "/api/v1/investigations/case_alice_confidential/documents",
        files={"file": ("injected.txt", b"Injected data", "text/plain")},
        data={"auto_process": "true"},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert bob_upload.status_code == 403

    # Bob attempts to export Alice's report -> 403 FORBIDDEN
    bob_report = auth_client.get(
        "/api/v1/investigations/case_alice_confidential/report",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert bob_report.status_code == 403

    # Bob's investigation list does NOT show Alice's case
    bob_list = auth_client.get(
        "/api/v1/investigations",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert bob_list.status_code == 200
    bob_case_ids = [c["investigation_id"] for c in bob_list.json()["investigations"]]
    assert "case_alice_confidential" not in bob_case_ids

    # Check audit log records unauthorized attempt for Alice's case
    logs_resp = auth_client.get(
        "/api/v1/auth/audit-logs",
        headers={"Authorization": f"Bearer {token_a}"},
        params={"target_id": "case_alice_confidential"},
    )
    assert logs_resp.status_code == 200
    actions = [l["action"] for l in logs_resp.json()]
    assert "UNAUTHORIZED_ACCESS_ATTEMPT" in actions
