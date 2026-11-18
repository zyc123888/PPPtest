import time

import pytest


@pytest.mark.parametrize('kind', ['api', 'ui', 'performance'])
def test_case_update_cannot_reassign_project(client, kind):
    projects = []
    case_id = None
    path = f'/{kind}-cases'
    try:
        for suffix in ('source', 'target'):
            response = client.post('/projects', json={'name': f'Guard_{suffix}_{time.time_ns()}', 'base_url': 'http://guard.test'})
            assert response.status_code == 201, response.text
            projects.append(response.json()['id'])
        payload = {'project_id': projects[0], 'name': f'项目保护_{kind}'}
        if kind == 'ui':
            payload.update(target_url='http://guard.test', expect_text='ready', steps_json=[])
        else:
            payload.update(method='GET', path='/health', expected_status=200)
        created = client.post(path, json=payload)
        assert created.status_code == 201, created.text
        case_id = created.json()['id']
        response = client.put(f'{path}/{case_id}', json={**payload, 'project_id': projects[1]})
        assert response.status_code == 400, response.text
        assert client.get(f'{path}/{case_id}').json()['project_id'] == projects[0]
    finally:
        if case_id is not None:
            client.delete(f'{path}/{case_id}')
        for project_id in reversed(projects):
            client.delete(f'/projects/{project_id}')
