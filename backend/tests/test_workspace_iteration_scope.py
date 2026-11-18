import time


def test_iteration_assignment_requires_same_project_and_allows_clear(client):
    projects = []
    entities = []
    iterations = []
    try:
        for label in ('A', 'B'):
            response = client.post('/projects', json={'name': f'IterationScope_{label}_{time.time_ns()}', 'base_url': 'http://scope.test'})
            assert response.status_code == 201, response.text
            projects.append(response.json()['id'])
            iteration = client.post(f'/projects/{projects[-1]}/iterations', json={'name': f'迭代 {label}'})
            assert iteration.status_code == 201, iteration.text
            iterations.append(iteration.json()['id'])
        for plural, singular in [('requirements', 'requirements'), ('tasks', 'tasks')]:
            rejected = client.post(f'/projects/{projects[0]}/{plural}', json={'title': '范围测试', 'iteration_id': iterations[1]})
            assert rejected.status_code == 400
            created = client.post(f'/projects/{projects[0]}/{plural}', json={'title': '范围测试', 'iteration_id': iterations[0]})
            assert created.status_code == 201, created.text
            entity_id = created.json()['id']
            entities.append((singular, entity_id))
            rejected = client.put(f'/{singular}/{entity_id}', json={'iteration_id': iterations[1]})
            assert rejected.status_code == 400
            cleared = client.put(f'/{singular}/{entity_id}', json={'iteration_id': None})
            assert cleared.status_code == 200, cleared.text
            assert cleared.json()['iteration_id'] is None
    finally:
        for kind, entity_id in entities:
            client.delete(f'/{kind}/{entity_id}')
        for iteration_id in iterations:
            client.delete(f'/iterations/{iteration_id}')
        for project_id in projects:
            client.delete(f'/projects/{project_id}')
