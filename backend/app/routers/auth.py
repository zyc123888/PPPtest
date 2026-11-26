"""认证、API Token 与用户管理路由。"""

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
)
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas, services
from app.core.config import settings
from app.core.database import get_db
from app.models import ApiToken, ProjectMember, User
from app.deps.auth import (
    _serialize_user,
    auth_scheme,
    get_current_user,
    require_admin,
)

public_router = APIRouter(tags=["auth"])
protected_router = APIRouter(tags=["auth"])
users_router = APIRouter(tags=["users"])


@public_router.post("/auth/login", response_model=schemas.AuthLoginResponse, summary="用户登录")
def login(
    payload: schemas.AuthLoginRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
) -> schemas.AuthLoginResponse:
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"{client_ip}:{(payload.username or '').strip().lower()}"
    try:
        services.check_login_rate_limit(rate_key)
    except services.LoginRateLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    try:
        user = services.authenticate_user(db, payload.username, payload.password)
    except services.AccountDisabledError:
        raise HTTPException(status_code=403, detail="账号已停用，请联系管理员")
    if user is None:
        services.record_login_failure(rate_key)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    services.clear_login_failures(rate_key)
    token = services.issue_user_token(db, user)
    response.set_cookie(
        key="tp_browser_session",
        value=token,
        max_age=services.TOKEN_TTL_HOURS * 60 * 60,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path=settings.api_v1_prefix,
    )
    return schemas.AuthLoginResponse(token=token, user=_serialize_user(db, user))


@protected_router.post("/auth/logout", status_code=204, summary="退出登录")
def logout(
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
    db: Session = Depends(get_db),
) -> None:
    if credentials and credentials.credentials:
        services.revoke_user_token(db, credentials.credentials)
    response.delete_cookie(key="tp_browser_session", path=settings.api_v1_prefix, samesite="strict")


@protected_router.get("/auth/me", response_model=schemas.UserRead, summary="获取当前用户信息")
def get_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> schemas.UserRead:
    return _serialize_user(db, current_user)


@protected_router.post("/auth/change-password", status_code=204, summary="修改当前用户密码")
def change_password(
    payload: schemas.PasswordChangeRequest,
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    if not services.verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="原密码不正确")
    current_user.password_hash = services.hash_password(payload.new_password)
    db.commit()
    keep = credentials.credentials if credentials else None
    services.revoke_all_user_tokens(db, current_user.id, keep_token=keep)


@protected_router.get("/api-tokens", response_model=list[schemas.ApiTokenRead], summary="获取个人 API Token 列表")
def list_api_tokens(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[schemas.ApiTokenRead]:
    records = db.scalars(
        select(ApiToken).where(ApiToken.user_id == current_user.id).order_by(ApiToken.id.desc())
    ).all()
    return [
        schemas.ApiTokenRead(
            id=record.id,
            name=record.name,
            token_prefix=record.token[:8] + "****",
            expires_at=record.expires_at,
            last_used_at=record.last_used_at,
            created_at=record.created_at,
        )
        for record in records
    ]


@protected_router.post("/api-tokens", response_model=schemas.ApiTokenCreated, status_code=201, summary="创建 API Token")
def create_api_token(
    payload: schemas.ApiTokenCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> schemas.ApiTokenCreated:
    record = services.create_api_token(
        db, current_user, name=payload.name.strip(), expires_days=payload.expires_days
    )
    return schemas.ApiTokenCreated(
        id=record.id,
        name=record.name,
        token_prefix=record.token[:8] + "****",
        token=record.token,
        expires_at=record.expires_at,
        last_used_at=record.last_used_at,
        created_at=record.created_at,
    )


@protected_router.delete("/api-tokens/{token_id}", status_code=204, summary="吊销 API Token")
def delete_api_token(
    token_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    record = db.get(ApiToken, token_id)
    if record is None or record.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Token 不存在")
    db.delete(record)
    db.commit()


_VALID_USER_ROLES = {"admin", "tester", "viewer"}


_VALID_USER_STATUSES = {"ACTIVE", "DISABLED"}


def _validate_user_fields(role: str | None = None, status: str | None = None) -> None:
    if role is not None and role not in _VALID_USER_ROLES:
        raise HTTPException(status_code=422, detail="非法角色，仅支持 admin / tester / viewer")
    if status is not None and status not in _VALID_USER_STATUSES:
        raise HTTPException(status_code=422, detail="非法状态，仅支持 ACTIVE / DISABLED")


def _other_active_admin_exists(db: Session, exclude_user_id: int) -> bool:
    count = db.scalar(
        select(func.count())
        .select_from(User)
        .where(User.role == "admin", User.status == "ACTIVE", User.id != exclude_user_id)
    )
    return bool(count)


@users_router.get("/users", response_model=list[schemas.UserRead], dependencies=[Depends(require_admin)], summary="获取用户列表")
def list_users(db: Session = Depends(get_db)) -> list[User]:
    users = list(db.scalars(select(User).order_by(User.id.asc())).all())
    return [_serialize_user(db, user) for user in users]


@users_router.post("/users", response_model=schemas.UserRead, status_code=201, dependencies=[Depends(require_admin)], summary="创建用户")
def create_user(payload: schemas.UserCreate, db: Session = Depends(get_db)) -> User:
    data = payload.model_dump()
    _validate_user_fields(role=data.get("role"), status=data.get("status"))
    if db.scalar(select(User).where(User.username == data["username"])) is not None:
        raise HTTPException(status_code=400, detail="用户名已存在")
    password = data.pop("password")
    user = User(**data, password_hash=services.hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    workspace = services.ensure_default_workspace(db)
    services.ensure_workspace_member(db, workspace.id, user.id, "member")
    return _serialize_user(db, user)


@users_router.put("/users/{user_id}", response_model=schemas.UserRead, summary="更新用户信息或角色状态")
def update_user(
    user_id: int,
    payload: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    data = payload.model_dump(exclude_unset=True)
    _validate_user_fields(role=data.get("role"), status=data.get("status"))
    demoting = "role" in data and user.role == "admin" and data["role"] != "admin"
    disabling = "status" in data and user.status == "ACTIVE" and data["status"] == "DISABLED"
    if (demoting or disabling) and user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能停用或降级自己的账号")
    if (demoting or disabling) and user.role == "admin" and not _other_active_admin_exists(db, user.id):
        raise HTTPException(status_code=400, detail="至少保留一名启用的管理员")
    password = data.pop("password", None)
    if password:
        user.password_hash = services.hash_password(password)
    if "display_name" in data:
        user.display_name = data["display_name"]
    if "role" in data:
        user.role = data["role"]
    if "status" in data:
        user.status = data["status"]
    db.commit()
    db.refresh(user)
    if disabling:
        services.revoke_all_user_tokens(db, user.id)
    return _serialize_user(db, user)


@users_router.delete("/users/{user_id}", status_code=204, summary="删除用户")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    if user.role == "admin" and not _other_active_admin_exists(db, user.id):
        raise HTTPException(status_code=400, detail="至少保留一名启用的管理员")
    # 先将全库指向该用户的可空外键（created_by/updated_by 等审计字段）置空，
    # 避免数据库 RESTRICT 外键约束阻止删除；tokens/工作空间成员由级联删除处理
    for table in User.metadata.sorted_tables:
        for column in table.columns:
            if column.nullable and any(fk.column.table.name == "users" for fk in column.foreign_keys):
                db.execute(table.update().where(column == user.id).values({column.name: None}))
    db.execute(delete(ProjectMember).where(ProjectMember.user_id == user.id))
    db.delete(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该用户存在无法解除的关联数据，请先停用账号")
