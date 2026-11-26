import time
import pytest


def test_copy_to_review_is_atomic_and_preserves_source(client, monkeypatch):
    from app.domain import cases as cases_domain
    project = client.post('/projects', json={'name': f'CopyPlan_{time.time_ns()}', 'base_url': 'http://plan.test'})
    assert project.status_code == 201, project.text
    project_id = project.json()['id']
    plans = []
    case_id = None
    try:
        case = client.post('/api-cases', json={'project_id': project_id, 'name': '复制测试', 'method': 'GET', 'path': '/health', 'expected_status': 200})
        assert case.status_code == 201, case.text
        case_id = case.json()['id']
        source = client.post('/test-plans', json={'project_id': project_id, 'name': '来源计划'})
        assert source.status_code == 201, source.text
        source_id = source.json()['id']
        plans.append(source_id)
        added = client.post(f'/test-plans/{source_id}/cases/batch', json={'items': [{'case_type': 'API', 'case_id': case_id}], 'allow_unapproved': True})
        assert added.status_code == 200, added.text
        source_items = client.get(f'/test-plans/{source_id}/cases').json()
        assert len(source_items) == 1
        before = client.get('/test-plans', params={'project_id': project_id}).json()
        failed = client.post(f'/test-plans/{source_id}/cases/copy-to-review', json={'item_ids': [source_items[0]['id'], 999999999]})
        assert failed.status_code == 404
        assert len(client.get('/test-plans', params={'project_id': project_id}).json()) == len(before)
        with monkeypatch.context() as scoped:
            def fail_snapshot(_case):
                raise RuntimeError('模拟快照写入失败')
            scoped.setattr(cases_domain, '_case_snapshot', fail_snapshot)
            with pytest.raises(RuntimeError, match='模拟快照写入失败'):
                client.post(f'/test-plans/{source_id}/cases/copy-to-review', json={'item_ids': [source_items[0]['id']]})
        assert len(client.get('/test-plans', params={'project_id': project_id}).json()) == len(before)
        assert len(client.get(f'/test-plans/{source_id}/cases').json()) == 1
        copied = client.post(f'/test-plans/{source_id}/cases/copy-to-review', json={'item_ids': [source_items[0]['id']]})
        assert copied.status_code == 201, copied.text
        plans.append(copied.json()['id'])
        assert len(client.get(f'/test-plans/{source_id}/cases').json()) == 1
        assert len(client.get(f'/test-plans/{plans[-1]}/cases').json()) == 1
    finally:
        for plan_id in reversed(plans):
            client.delete(f'/test-plans/{plan_id}')
        if case_id:
            client.delete(f'/api-cases/{case_id}')
        client.delete(f'/projects/{project_id}')
