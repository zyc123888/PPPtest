"""安全生命周期回归测试（Task D5）：Webhook secret 掩码 + API Token 生命周期。"""

import time


def _create_project(client) -> int:
    resp = client.post("/projects", json={"name": f"通知项目_{time.time_ns()}", "base_url": "http://example.com"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_webhook_secret_is_masked_on_read_and_write(client) -> None:
    project_id = _create_project(client)
    secret = "super-secret-webhook-token-9f3a"

    updated = client.put(
        f"/projects/{project_id}/notification-setting",
        json={"enabled": True, "webhook_url": "https://example.com/hook", "secret": secret},
    )
    assert updated.status_code == 200, updated.text
    assert secret not in updated.text  # 写响应也不回明文

    read = client.get(f"/projects/{project_id}/notification-setting")
    assert read.status_code == 200
    body = read.json()
    assert body["secret_configured"] is True
    assert "secret" not in body  # 读响应只有 secret_configured 布尔，无 secret 字段
    assert secret not in read.text


def test_api_token_plaintext_only_present_on_creation(client) -> None:
    created = client.post("/api-tokens", json={"name": f"token_{time.time_ns()}"})
    assert created.status_code == 201, created.text
    created_body = created.json()
    assert created_body["token"].startswith("pt_")
    assert created_body["token_prefix"].endswith("****")

    listed = client.get("/api-tokens")
    assert listed.status_code == 200
    rows = listed.json()
    created_row = next(row for row in rows if row["id"] == created_body["id"])
    assert "token" not in created_row  # 列表只回掩码前缀
    assert created_row["token_prefix"].endswith("****")
    assert created_body["token"] not in listed.text


def test_deleted_api_token_is_immediately_invalid(client) -> None:
    created = client.post("/api-tokens", json={"name": f"token_{time.time_ns()}"})
    token = created.json()["token"]
    token_id = created.json()["id"]

    # 未删除时可用
    ok = client.get("/system/info", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200, ok.text

    deleted = client.delete(f"/api-tokens/{token_id}")
    assert deleted.status_code == 204

    # 删除后立即失效
    again = client.get("/system/info", headers={"Authorization": f"Bearer {token}"})
    assert again.status_code == 401, again.text

    # 列表不再包含该 Token
    listed = client.get("/api-tokens")
    assert listed.status_code == 200
    assert all(row["id"] != token_id for row in listed.json())
