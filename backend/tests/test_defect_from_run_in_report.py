import time


def test_report_shows_internal_defect_created_from_run(client) -> None:
    from app.core.database import SessionLocal
    from app.models import TestPlan, TestPlanRun, TestRun

    suffix = time.time_ns()
    project = client.post('/projects', json={'name': f'DefectReport_{suffix}', 'base_url': 'http://defect-report.test'})
    assert project.status_code == 201, project.text
    project_id = project.json()['id']
    case_id = None
    plan_id = None
    plan_run_id = None
    run_id = None
    defect_id = None
    try:
        case = client.post('/api-cases', json={
            'project_id': project_id, 'name': f'报告缺陷用例 {suffix}',
            'method': 'GET', 'path': '/health', 'expected_status': 200,
        })
        assert case.status_code == 201, case.text
        case_id = case.json()['id']

        with SessionLocal() as db:
            plan = TestPlan(project_id=project_id, name=f'缺陷报告计划 {suffix}')
            db.add(plan)
            db.flush()
            plan_run = TestPlanRun(plan_id=plan.id, project_id=project_id, status='FAILED', total_count=1, fail_count=1)
            db.add(plan_run)
            db.flush()
            run = TestRun(
                project_id=project_id, plan_run_id=plan_run.id,
                case_type='API', case_id=case_id, case_name=f'报告缺陷用例 {suffix}',
                status='FAILED', summary='断言失败：期望 200 实际 500',
            )
            db.add(run)
            db.commit()
            plan_id, plan_run_id, run_id = plan.id, plan_run.id, run.id

        created = client.post(f'/project-defects/from-run/{run_id}', json={'title': '登录超时', 'severity': 'P2'})
        assert created.status_code == 201, created.text
        defect_id = created.json()['id']

        report = client.get(f'/reports/{plan_run_id}')
        assert report.status_code == 200, report.text
        payload = report.json()
        internal_ids = {item['id'] for item in payload['internal_defects']}
        assert defect_id in internal_ids
        assert payload['internal_defects'][0]['title'] == '登录超时'
        assert defect_id not in {item['id'] for item in payload['defects']}, '内部缺陷不应出现在外部缺陷登记列表'

        listed = client.get(f'/projects/{project_id}/defects', params={'page': 1, 'page_size': 50})
        assert listed.status_code == 200, listed.text
        listed_ids = {item['id'] for item in listed.json()['items']}
        assert defect_id in listed_ids, '报告创建的项目缺陷应能在项目缺陷列表查到同一 ID'
    finally:
        if defect_id is not None:
            client.delete(f'/project-defects/{defect_id}')
        with SessionLocal() as db:
            if run_id is not None:
                run = db.get(TestRun, run_id)
                if run:
                    db.delete(run)
            if plan_run_id is not None:
                plan_run = db.get(TestPlanRun, plan_run_id)
                if plan_run:
                    db.delete(plan_run)
            if plan_id is not None:
                plan = db.get(TestPlan, plan_id)
                if plan:
                    db.delete(plan)
            db.commit()
        if case_id is not None:
            client.delete(f'/api-cases/{case_id}')
        client.delete(f'/projects/{project_id}')
