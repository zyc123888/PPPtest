import time

import pytest


@pytest.mark.parametrize('kind', ['api', 'ui'])
def test_batch_patch_distinguishes_omitted_and_null(client, kind) -> None:
    project = client.post('/projects', json={
        'name': f'BatchPatch_{kind}_{time.time_ns()}',
        'base_url': 'http://batch-patch.test',
    })
    assert project.status_code == 201, project.text
    project_id = project.json()['id']
    case_id = None
    path = f'/{kind}-cases'
    try:
        payload = {
            'project_id': project_id,
            'name': f'BatchPatch_{kind}',
            'folder_path': '测试/目录',
            'tags_json': ['保留标签'],
        }
        if kind == 'api':
            payload.update(method='GET', path='/health', expected_status=200)
        else:
            payload.update(target_url='http://batch-patch.test', expect_text='ready', steps_json=[])
        created = client.post(path, json=payload)
        assert created.status_code == 201, created.text
        case_id = created.json()['id']

        updated = client.put(f'{path}/batch', json={'case_ids': [case_id], 'patch': {'priority': 'P1'}})
        assert updated.status_code == 200, updated.text
        current = client.get(f'{path}/{case_id}').json()
        assert current['folder_path'] == '测试/目录'
        assert current['tags_json'] == ['保留标签']

        cleared = client.put(f'{path}/batch', json={
            'case_ids': [case_id], 'patch': {'folder_path': None, 'tags_json': None},
        })
        assert cleared.status_code == 200, cleared.text
        current = client.get(f'{path}/{case_id}').json()
        assert current['folder_path'] is None
        assert current['tags_json'] is None
        assert current['priority'] == 'P1'
    finally:
        if case_id is not None:
            client.delete(f'{path}/{case_id}')
        client.delete(f'/projects/{project_id}')
