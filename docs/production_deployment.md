# OmniTest GitHub 自动部署

## 目标架构

```text
master push
  -> Stack Tests
  -> Publish and Deploy
  -> GHCR images
  -> production server over SSH
  -> Docker Compose health check
  -> success or automatic rollback
```

GitHub 保存代码并运行 CI；生产服务器只拉取经过测试的镜像，不需要保存仓库源码。数据库、Redis、上传文件、报告和 Celery Beat 状态保存在 Docker named volumes 中。

## 发布的镜像

工作流会发布以下镜像，每次同时带 `latest` 和不可变的 `sha-<commit>` 标签：

- `ghcr.io/zyc123888/ppptest-backend`
- `ghcr.io/zyc123888/ppptest-worker`
- `ghcr.io/zyc123888/ppptest-frontend`

生产部署固定使用 `sha-<commit>`，不会因 `latest` 后续变化而漂移。

## 一、服务器要求

- 64 位 Linux 服务器
- Docker Engine
- Docker Compose v2，即 `docker compose version` 可用
- 建议至少 4 CPU、8 GB 内存；同时运行多个浏览器或可信生成任务时需要更高配置
- 开放对外 HTTP 端口，默认 `80`
- 服务器可访问 `ghcr.io`

生产 Compose 不开放 MariaDB、Redis 和后端端口。浏览器只访问前端，`/api` 由前端 Nginx 转发到后端。

## 二、首次初始化服务器

把 `deploy/` 目录传到服务器后执行：

```bash
sudo bash deploy/bootstrap-server.sh /opt/omnitest <部署用户>
sudo nano /opt/omnitest/.env.production
```

必须替换 `.env.production` 中的全部占位内容。生成 Fernet 密钥：

```bash
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

如果 GHCR 镜像不是公开包，需要在服务器执行一次登录：

```bash
docker login ghcr.io
```

登录账号使用 GitHub 用户名；Token 至少需要 `read:packages` 权限。凭据保存在服务器 Docker credential store 中，不写入仓库或部署工作流。

## 三、GitHub production Environment

在仓库中打开：

```text
Settings -> Environments -> New environment -> production
```

建议启用 Required reviewers，使生产部署在人工确认后才取得 SSH Secrets 并继续执行。

### Environment Secrets

| 名称 | 内容 |
|---|---|
| `DEPLOY_HOST` | 服务器 IP 或域名 |
| `DEPLOY_USER` | 具有 Docker 权限的部署用户 |
| `DEPLOY_PORT` | SSH 端口，通常为 `22` |
| `DEPLOY_SSH_KEY` | 专用部署私钥全文 |
| `DEPLOY_KNOWN_HOSTS` | 服务器经过可信渠道确认的 SSH host key |

不要在工作流中临时执行 `ssh-keyscan` 代替可信 host key。可以在可信网络中取得：

```bash
ssh-keyscan -p 22 your-server.example.com
```

核对服务器指纹后，再把整行结果保存为 `DEPLOY_KNOWN_HOSTS`。

### Repository Variables

在 `Settings -> Secrets and variables -> Actions -> Variables` 中设置。`PRODUCTION_DEPLOY_ENABLED` 必须是仓库变量，因为它用于决定是否创建部署 Job；SSH 凭据仍只放在 `production` Environment Secrets 中。

| 名称 | 示例 | 说明 |
|---|---|---|
| `PRODUCTION_DEPLOY_ENABLED` | `true` | 未设置为 `true` 时只发布镜像，不部署 |
| `PRODUCTION_URL` | `https://omnitest.example.com` | GitHub Deployment 页面展示的地址 |
| `DEPLOY_PATH` | `/opt/omnitest` | 服务器部署目录 |

## 四、自动发布流程

1. 代码合入 `master`。
2. `Stack Tests` 启动完整容器并运行后端与 E2E 测试。
3. 只有测试成功的 `master` 提交才触发镜像发布。
4. 发布 backend、worker、frontend 三个 GHCR 镜像。
5. `PRODUCTION_DEPLOY_ENABLED=true` 时进入 `production` Environment。
6. GitHub 通过 SSH 上传生产 Compose 和部署脚本。
7. 服务器拉取指定 SHA 镜像并启动服务。
8. 后端健康检查通过后记录本次成功版本。
9. 健康检查失败时自动恢复上一个成功镜像标签。

也可以在 Actions 页面手动运行 `Publish and Deploy`，用于重新发布当前 `master`。

## 五、服务器日常操作

```bash
cd /opt/omnitest

# 查看状态
docker compose --env-file .env.production -f compose.production.yml ps

# 查看日志
docker compose --env-file .env.production -f compose.production.yml logs -f --tail=200

# 手动部署指定提交
./deploy.sh sha-<full-git-commit>

# 仅重启服务，不升级镜像
docker compose --env-file .env.production -f compose.production.yml restart
```

不要执行 `docker compose down -v`，该命令会删除数据库和所有持久化数据。

## 六、备份要求

自动回滚只回滚应用镜像，不回滚数据库。上线前至少配置：

- MariaDB 每日备份
- `reports_data` 与 `uploads_data` 定期快照
- 异地保存 `APP_ENCRYPTION_KEY`
- 定期验证备份可恢复

数据库结构发生不兼容变更时，必须先备份数据库再部署。

## 七、HTTPS

当前生产 Compose 默认直接开放 HTTP 端口，便于首次验证。正式对公网使用时，应在服务器或云负载均衡上配置 HTTPS，并把 `.env.production` 的 `PUBLIC_URL` 改成最终 HTTPS 地址。

如果服务器已有 Nginx、Caddy 或云负载均衡，让它把公网域名反向代理到 OmniTest 的 `PUBLIC_HTTP_PORT` 即可。
