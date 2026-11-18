import time


def test_trace_marks_success_plus_unexecuted_case_partial(client) -> None:
    from app.core.database import SessionLocal
    from app.models import TestRun

    project = client.post('/projects', json={'name': f'TraceTest_{time.time_ns()}', 'base_url': 'http://trace.test'})
    assert project.status_code == 201, project.text
    project_id = project.json()['id']
    requirement_id = None
    case_ids = []
    run_id = None
    try:
        requirement = client.post(f'/projects/{project_id}/requirements', json={'title': '追溯覆盖测试'})
        assert requirement.status_code == 201, requirement.text
        requirement_id = requirement.json()['id']
        for index in range(2):
            case = client.post('/api-cases', json={
                'project_id': project_id, 'name': f'追溯用例 {index}',
                'method': 'GET', 'path': '/health', 'expected_status': 200,
            })
            assert case.status_code == 201, case.text
            case_id = case.json()['id']
            case_ids.append(case_id)
            linked = client.post(f'/requirements/{requirement_id}/cases', json={'case_type': 'API', 'case_id': case_id})
            assert linked.status_code in (200, 201), linked.text
        with SessionLocal() as db:
            run = TestRun(project_id=project_id, case_type='API', case_id=case_ids[0], case_name='追溯用例 0', status='SUCCESS')
            db.add(run)
            db.commit()
            db.refresh(run)
            run_id = run.id

        response = client.get(f'/projects/{project_id}/trace')
        assert response.status_code == 200, response.text
        row = next(item for item in response.json()['rows'] if item['requirement_id'] == requirement_id)
        assert (row['linked_case_count'], row['executed_case_count'], row['passed_case_count']) == (2, 1, 1)
        assert row['coverage'] == 'PARTIAL'
    finally:
        if run_id is not None:
            with SessionLocal() as db:
                run = db.get(TestRun, run_id)
                if run:
                    db.delete(run)
                    db.commit()
        if requirement_id is not None:
            client.delete(f'/requirements/{requirement_id}')
        for case_id in case_ids:
            client.delete(f'/api-cases/{case_id}')
        client.delete(f'/projects/{project_id}')
