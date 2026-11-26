"""测试报告聚合统计与洞察领域逻辑。"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import schemas
from app.models import (
    Defect,
    DefectRecord,
    DefectRunLink,
    TestPlan,
    TestPlanRun,
    TestRun,
)


def _error_type_text(error_type: str) -> str:
    mapping = {
        "CONFIG": "预检失败",
        "ASSERTION": "断言失败",
        "SYSTEM": "系统异常",
        "TIMEOUT": "超时",
        "CANCELLED": "已取消",
    }
    return mapping.get(error_type, error_type)


def _summarize_failure_reasons(counts: dict[str, int]) -> list[str]:
    return [
        f"{_error_type_text(error_type)} {count}"
        for error_type, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _pass_rate(pass_count: int, total_count: int) -> float:
    if total_count <= 0:
        return 0.0
    return round((pass_count / total_count) * 100, 1)


def _collect_failure_reason_map(db: Session, plan_run_ids: list[int]) -> dict[int, dict[str, int]]:
    if not plan_run_ids:
        return {}
    rows = db.execute(
        select(TestRun.plan_run_id, TestRun.error_type, func.count(TestRun.id))
        .where(
            TestRun.plan_run_id.in_(plan_run_ids),
            TestRun.status != "SUCCESS",
            TestRun.error_type.is_not(None),
        )
        .group_by(TestRun.plan_run_id, TestRun.error_type)
    ).all()
    result: dict[int, dict[str, int]] = {}
    for plan_run_id, error_type, count in rows:
        bucket = result.setdefault(plan_run_id, {})
        bucket[error_type] = count
    return result


def _build_report_insights(
    runs: list[TestPlanRun],
    plans_by_id: dict[int, TestPlan | None],
    failure_reason_map: dict[int, dict[str, int]],
) -> schemas.ReportInsights:
    report_count = len(runs)
    success_count = sum(1 for run in runs if run.status == "SUCCESS")
    completed_runs = [run for run in runs if run.status in {"SUCCESS", "FAILED", "ERROR", "TIMEOUT"}]
    completed_count = len(completed_runs)
    failed_count = completed_count - success_count
    failed_case_count = sum(run.fail_count or 0 for run in runs)
    config_fail_count = sum(failure_reason_map.get(run.id, {}).get("CONFIG", 0) for run in runs)
    success_rate = round((success_count / completed_count) * 100, 1) if completed_count else 0.0
    average_pass_rate = round(
        sum(_pass_rate(run.pass_count or 0, run.total_count or 0) for run in completed_runs) / completed_count, 1
    ) if completed_count else 0.0
    duration_values = [run.duration_ms for run in runs if run.duration_ms is not None]
    average_duration_ms = int(sum(duration_values) / len(duration_values)) if duration_values else None

    overall_reason_counts: dict[str, int] = {}
    for counts in failure_reason_map.values():
        for error_type, count in counts.items():
            overall_reason_counts[error_type] = overall_reason_counts.get(error_type, 0) + count

    recent_trend = [
        schemas.ReportTrendPoint(
            plan_run_id=run.id,
            plan_id=run.plan_id,
            plan_name=plans_by_id.get(run.plan_id).name if plans_by_id.get(run.plan_id) else "-",
            status=run.status,
            error_type=run.error_type,
            pass_rate=_pass_rate(run.pass_count or 0, run.total_count or 0),
            fail_count=run.fail_count or 0,
            created_at=run.created_at,
            duration_ms=run.duration_ms,
        )
        for run in runs[:10]
    ]
    recent_window = completed_runs[:10]
    older_window = completed_runs[10:20]
    recent_success_rate = round(
        (sum(1 for run in recent_window if run.status == "SUCCESS") / len(recent_window)) * 100, 1
    ) if recent_window else success_rate
    older_success_rate = round(
        (sum(1 for run in older_window if run.status == "SUCCESS") / len(older_window)) * 100, 1
    ) if older_window else recent_success_rate
    success_rate_delta = round(recent_success_rate - older_success_rate, 1)

    runs_by_plan: dict[int, list[TestPlanRun]] = {}
    for run in runs:
        runs_by_plan.setdefault(run.plan_id, []).append(run)

    plan_histories: list[schemas.ReportPlanHistory] = []
    flaky_plan_count = 0
    for plan_id, plan_runs in runs_by_plan.items():
        ordered_runs = sorted(plan_runs, key=lambda item: item.id, reverse=True)
        latest = ordered_runs[0]
        latest_rate = _pass_rate(latest.pass_count or 0, latest.total_count or 0)
        previous_rate = _pass_rate(ordered_runs[1].pass_count or 0, ordered_runs[1].total_count or 0) if len(ordered_runs) > 1 else latest_rate
        avg_rate = round(
            sum(_pass_rate(item.pass_count or 0, item.total_count or 0) for item in ordered_runs) / len(ordered_runs), 1
        )
        history_duration_values = [item.duration_ms for item in ordered_runs if item.duration_ms is not None]
        reason_counts: dict[str, int] = {}
        for item in ordered_runs:
            for error_type, count in failure_reason_map.get(item.id, {}).items():
                reason_counts[error_type] = reason_counts.get(error_type, 0) + count
        status_set = {item.status for item in ordered_runs[:5]}
        if "SUCCESS" in status_set and any(status in {"FAILED", "ERROR", "TIMEOUT"} for status in status_set):
            flaky_plan_count += 1
        plan = plans_by_id.get(plan_id)
        plan_histories.append(
            schemas.ReportPlanHistory(
                plan_id=plan_id,
                plan_name=plan.name if plan else "-",
                latest_plan_run_id=latest.id,
                latest_status=latest.status,
                latest_error_type=latest.error_type,
                latest_created_at=latest.created_at,
                latest_pass_rate=latest_rate,
                average_pass_rate=avg_rate,
                pass_rate_delta=round(latest_rate - previous_rate, 1),
                latest_fail_count=latest.fail_count or 0,
                average_duration_ms=int(sum(history_duration_values) / len(history_duration_values))
                if history_duration_values
                else None,
                run_count=len(ordered_runs),
                failure_reason_counts=reason_counts,
                failure_reason_summary=_summarize_failure_reasons(reason_counts),
            )
        )
    plan_histories.sort(key=lambda item: (item.latest_created_at is None, item.latest_created_at), reverse=True)
    unstable_run_count = sum(
        1 for run in runs if (run.fail_count or 0) > 0 or run.error_type in {"CONFIG", "SYSTEM", "TIMEOUT"}
    )
    quality_score = round(
        max(
            0.0,
            min(
                100.0,
                success_rate * 0.45
                + average_pass_rate * 0.35
                + max(0.0, 100 - min((average_duration_ms or 0) / 50, 100)) * 0.1
                + max(0.0, 100 - min(config_fail_count * 5, 100)) * 0.1,
            ),
        ),
        1,
    )

    return schemas.ReportInsights(
        report_count=report_count,
        success_count=success_count,
        failed_count=failed_count,
        failed_case_count=failed_case_count,
        config_fail_count=config_fail_count,
        success_rate=success_rate,
        average_pass_rate=average_pass_rate,
        average_duration_ms=average_duration_ms,
        success_rate_delta=success_rate_delta,
        quality_score=quality_score,
        flaky_plan_count=flaky_plan_count,
        unstable_run_count=unstable_run_count,
        failure_reason_counts=overall_reason_counts,
        failure_reason_summary=_summarize_failure_reasons(overall_reason_counts),
        recent_trend=recent_trend,
        plan_histories=plan_histories[:8],
    )


def _serialize_plan_run(plan_run: TestPlanRun) -> schemas.TestPlanRunRead:
    payload = {
        field: getattr(plan_run, field)
        for field in schemas.TestPlanRunRead.model_fields.keys()
    }
    payload["retry_count"] = payload.get("retry_count") or 0
    return schemas.TestPlanRunRead(**payload)


def _assemble_report_detail(db: Session, plan_run: TestPlanRun) -> schemas.ReportDetail:
    plan_run_id = plan_run.id
    test_runs = list(
        db.scalars(select(TestRun).where(TestRun.plan_run_id == plan_run_id).order_by(TestRun.id.asc())).all()
    )
    recent_history_runs = list(
        db.scalars(
            select(TestPlanRun)
            .where(TestPlanRun.plan_id == plan_run.plan_id)
            .order_by(TestPlanRun.id.desc())
            .limit(5)
        ).all()
    )
    recent_history = [
        schemas.ReportHistoryItem(
            plan_run_id=item.id,
            status=item.status,
            error_type=item.error_type,
            created_at=item.created_at,
            duration_ms=item.duration_ms,
            pass_rate=_pass_rate(item.pass_count or 0, item.total_count or 0),
            fail_count=item.fail_count or 0,
        )
        for item in recent_history_runs
    ]
    defects = list(
        db.scalars(
            select(DefectRecord)
            .where(
                DefectRecord.project_id == plan_run.project_id,
                (DefectRecord.plan_run_id == plan_run.id) | (DefectRecord.run_id.in_([run.id for run in test_runs]) if test_runs else False),
            )
            .order_by(DefectRecord.id.desc())
        ).all()
    )
    run_ids = [run.id for run in test_runs]
    internal_defects = (
        list(
            db.scalars(
                select(Defect)
                .join(DefectRunLink, DefectRunLink.defect_id == Defect.id)
                .where(
                    Defect.project_id == plan_run.project_id,
                    DefectRunLink.test_run_id.in_(run_ids),
                )
                .order_by(Defect.id.desc())
                .distinct()
            ).all()
        )
        if run_ids
        else []
    )
    return schemas.ReportDetail(
        plan_run=_serialize_plan_run(plan_run),
        test_runs=test_runs,
        recent_history=recent_history,
        defects=defects,
        internal_defects=internal_defects,
    )


def _report_share_url(share_token: str | None) -> str:
    if not share_token:
        return ""
    return f"/shared-report/{share_token}"
