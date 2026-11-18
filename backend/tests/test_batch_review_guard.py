def test_batch_review_cannot_approve_own_draft(client):
    project_id = client.get('/projects').json()[0]['id']
    created = client.post('/ui-cases', json={
        'project_id': project_id, 'name': '批量评审权限测试',
        'target_url': 'http://review.test', 'expect_text': 'ready', 'steps_json': [],
    })
    assert created.status_code == 201, created.text
    case_id = created.json()['id']
    try:
        response = client.post('/cases/batch-review', json={
            'items': [{'case_type': 'UI', 'case_id': case_id}], 'review_status': 'APPROVED',
        })
        assert response.status_code == 403
        case = client.get(f'/ui-cases/{case_id}').json()
        assert case['review_status'] == 'DRAFT'
        assert case['reviewed_by'] is None
    finally:
        client.delete(f'/ui-cases/{case_id}')


def test_batch_review_validates_all_before_approving(client):
    import time
    from fastapi.testclient import TestClient

    project_id = client.get('/projects').json()[0]['id']
    username = f'reviewer_{time.time_ns()}'
    user = client.post('/users', json={'username': username, 'password': 'Review-test-2026', 'role': 'admin'})
    assert user.status_code == 201, user.text
    user_id = user.json()['id']
    cases = []
    try:
        for index in range(2):
            created = client.post('/ui-cases', json={
                'project_id': project_id, 'name': f'跨用户评审_{index}',
                'target_url': 'http://review.test', 'expect_text': 'ready', 'steps_json': [],
            })
            assert created.status_code == 201, created.text
            cases.append(created.json()['id'])
        assert client.post(f'/ui-cases/{cases[0]}/review/submit').status_code == 200
        with TestClient(client.app, base_url='http://testserver/api/v1') as reviewer:
            login = reviewer.post('/auth/login', json={'username': username, 'password': 'Review-test-2026'})
            assert login.status_code == 200, login.text
            headers = {'Authorization': f"Bearer {login.json()['token']}"}
            payload = {'items': [{'case_type': 'UI', 'case_id': case_id} for case_id in cases], 'review_status': 'APPROVED'}
            rejected = reviewer.post('/cases/batch-review', json=payload, headers=headers)
            assert rejected.status_code == 400
            assert client.get(f'/ui-cases/{cases[0]}').json()['review_status'] == 'IN_REVIEW'
            assert client.post(f'/ui-cases/{cases[1]}/review/submit').status_code == 200
            approved = reviewer.post('/cases/batch-review', json=payload, headers=headers)
            assert approved.status_code == 200, approved.text
        for case_id in cases:
            case = client.get(f'/ui-cases/{case_id}').json()
            assert case['review_status'] == 'APPROVED'
            assert case['reviewed_by'] == user_id
            assert case['reviewed_at'] is not None
    finally:
        for case_id in cases:
            client.delete(f'/ui-cases/{case_id}')
        client.delete(f'/users/{user_id}')


def test_project_viewer_cannot_review_even_with_global_tester_role(client, monkeypatch):
    import time
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from app import api
    from app.core.database import SessionLocal
    from app.models import ProjectMember

    project = client.post('/projects', json={'name': f'ReviewScope_{time.time_ns()}', 'base_url': 'http://review.test'}).json()
    username = f'viewer_{time.time_ns()}'
    user = client.post('/users', json={'username': username, 'password': 'Review-test-2026', 'role': 'tester'}).json()
    case_id = None
    try:
        with SessionLocal() as db:
            member = ProjectMember(project_id=project['id'], user_id=user['id'], role='viewer')
            db.add(member)
            db.commit()
            member_id = member.id
        created = client.post('/ui-cases', json={'project_id': project['id'], 'name': '权限范围评审', 'target_url': 'http://review.test', 'expect_text': 'ready'})
        assert created.status_code == 201, created.text
        case_id = created.json()['id']
        assert client.post(f'/ui-cases/{case_id}/review/submit').status_code == 200
        with TestClient(client.app, base_url='http://testserver/api/v1') as viewer:
            login = viewer.post('/auth/login', json={'username': username, 'password': 'Review-test-2026'})
            assert login.status_code == 200
            headers = {'Authorization': f"Bearer {login.json()['token']}"}
            assert viewer.put(f'/projects/{project["id"]}/members/{member_id}', json={'role': 'owner'}, headers=headers).status_code == 403
            assert viewer.post(f'/ui-cases/{case_id}/review/decide', json={'result': 'APPROVED'}, headers=headers).status_code == 403
            batch = viewer.post('/cases/batch-review', json={'items': [{'case_type': 'UI', 'case_id': case_id}], 'review_status': 'APPROVED'}, headers=headers)
            assert batch.status_code == 403
            assert viewer.post(f'/executions/ui/{case_id}/run', json={}, headers=headers).status_code == 403
            assert viewer.post('/executions/ui/batch-run', json={'case_ids': [case_id]}, headers=headers).status_code == 403
            with SessionLocal() as db:
                member = db.query(ProjectMember).filter_by(project_id=project['id'], user_id=user['id']).one()
                member.role = 'member'
                db.commit()
            monkeypatch.setattr(api, 'precheck_ui_case_execution', lambda *args, **kwargs: SimpleNamespace(is_valid=True))
            monkeypatch.setattr(api, '_dispatch_task_or_run_inline', lambda *args: ('test-task', False))
            run = viewer.post(f'/executions/ui/{case_id}/run', json={}, headers=headers)
            assert run.status_code == 200, run.text
        assert client.get(f'/ui-cases/{case_id}').json()['review_status'] == 'IN_REVIEW'
    finally:
        if case_id is not None:
            client.delete(f'/ui-cases/{case_id}')
        client.delete(f'/projects/{project["id"]}')
        client.delete(f'/users/{user["id"]}')
