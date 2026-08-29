# 从 MiAir / OpenXiaoCast 迁移到 CastFabric

## 兼容保证

CastFabric 0.10 采用增量迁移，不会主动删除以下内容：

- `/app/conf/config.json` 及 `.mi.token`；
- `mi_did`、`speakers`、`miplay_name` 等旧配置字段；
- 已保存的虚拟 DLNA UDN；
- `miair`、`openxiaocast` 和 `openxiaocast-miplay` 命令；
- `miair` Python 导入包和 `miair.app.MiAir` 类名。

首次加载旧配置时，程序会根据缓存的实体设备 `device_id` 和本地 DLNA location
生成通用 `targets` 记录。旧的默认名称 `OpenXiaoCast`/`MiAir` 会迁移为
`CastFabric`；用户明确设置的其他名称会继续作为设备前缀。

## Docker 迁移

新默认值是：

- 镜像：`ghcr.io/wangerzi/castfabric:latest`
- 容器：`castfabric`
- Compose 服务：`castfabric`
- 容器内配置目录：仍为 `/app/conf`

迁移前先确认旧容器实际使用的宿主机配置目录：

```bash
docker inspect miair --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
docker inspect openxiaocast --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

将同一个宿主机目录设置为 `CASTFABRIC_CONFIG_DIR`，再启动新容器。例如：

```dotenv
CASTFABRIC_CONFIG_DIR=/opt/miair_conf
CASTFABRIC_HOSTNAME=192.168.133.5
```

```bash
docker compose pull
docker compose up -d
```

确认 `http://宿主机IP:8300/api/status` 正常、手机能发现
`CastFabric · <目标>` 并完成播放后，再停止旧容器。不要让新旧容器同时绑定
8200/8300/8899 端口。

## 回滚

迁移版本保留旧字段，因此回滚只需要让旧镜像重新挂载原配置目录。CastFabric 新增的
`targets`、`default_target_id` 和 `device_name_prefix` 会被旧版本忽略。回滚前停止
CastFabric 容器，避免局域网广播和 host-network 端口冲突。

## 小米云扩展

标准 DLNA 音箱不再需要小米账号。只有目标没有原生 DLNA，且确实需要 MiNA 云控制
回退时，才在 Web 的“小米扩展”中主动启用并保存 Cookie。旧配置中的 Cookie 不会
自动启用扩展。token 过期不应影响标准目标扫描、虚拟 DLNA、AirPlay 或 MiPlay 的发现。
