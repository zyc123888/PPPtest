import time
from fastapi.testclient import TestClient


def test_manager_cannot_grant_owner_and_last_owner_is_protected(client):
    project = client.post('/projects', json={'name': f'MemberGuard_{time.time_ns()}', 'base_url': 'http://guard.test'}).json()
    users = []
    try:
        for label in ('owner', 'manager', 'other'):
            username = f'{label}_{time.time_ns()}'
            response = client.post('/users', json={'username': username, 'password': 'Guard-test-2026', 'role': 'tester'})
            assert response.status_code == 201, response.text
            users.append(response.json())
        owner = client.post(f'/projects/{project["id"]}/members', json={'user_id': users[0]['id'], 'role': 'owner'})
        assert owner.status_code == 201, owner.text
        manager = client.post(f'/projects/{project["id"]}/members', json={'user_id': users[1]['id'], 'role': 'manager'})
        assert manager.status_code == 201, manager.text
        assert client.put(f'/projects/{project["id"]}/members/{owner.json()["id"]}', json={'role': 'member'}).status_code == 400
        assert client.delete(f'/projects/{project["id"]}/members/{owner.json()["id"]}').status_code == 400
        assert client.post(f'/projects/{project["id"]}/members', json={'user_id': users[2]['id'], 'role': 'invalid'}).status_code == 400
        with TestClient(client.app, base_url='http://testserver/api/v1') as manager_client:
            login = manager_client.post('/auth/login', json={'username': users[1]['username'], 'password': 'Guard-test-2026'})
            headers = {'Authorization': f"Bearer {login.json()['token']}"}
            response = manager_client.post(f'/projects/{project["id"]}/members', json={'user_id': users[2]['id'], 'role': 'owner'}, headers=headers)
            assert response.status_code == 403
    finally:
        client.delete(f'/projects/{project["id"]}')
        for user in users:
            client.delete(f'/users/{user["id"]}')
