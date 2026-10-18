# Запуск Docker в LXC-контейнерах Proxmox VE

**Актуально для:** Proxmox VE 8.x / 9.x, LXC (PCT) с nesting, Docker Engine 29.x

## Определения

**LXC (Linux Containers)** — системная виртуализация: контейнер разделяет ядро хоста, имеет собственный namespace (PID, network, mount, user, UTS, IPC, cgroup) и полноценную init-систему (systemd). В Proxmox управляется `pct` и Web UI.

**Docker-in-LXC** — запуск Docker Engine (контейнерного рантайма приложений) **внутри** LXC-гостя Proxmox. Три уровня (LXC → dockerd → docker-контейнеры) используют **одно ядро** хоста; изоляция складывается пересечением, а не суммированием.

**Nesting** — feature PCT (`nesting=1`): отдаёт в контейнер procfs/sysfs (и вложенные cgroup namespace), без чего inner dockerd не может создавать namespaces. Не «режим Docker», а механизм вложенного запуска (systemd внутри LXC тоже полагается на nesting).

**Keyctl** — feature PCT (`keyctl=1`), только для unprivileged: разрешает `keyctl()`; без него unprivileged-контейнеры видят syscall как несуществующий, и Docker не стартует (документация pct.conf: «required to use docker inside a container»).

**Privileged / Unprivileged LXC** — privileged: root в контейнере ≈ root на хосте (взрывная сила при escape). Unprivileged: UID/GID маппятся через user namespace (по умолчанию `0–65535` → `100000–165535`); Docker-контейнер root внутри LXC — host UID 100000.

**AppArmor в LXC** — профиль ограничивает опасные syscalls (mount и др.); для Docker в unprivileged часто требуется `lxc.apparmor.profile: unconfined` (официально — не рекомендуется для production).

**OverlayFS / overlay2** — storage driver Docker по умолчанию; в LXC работает «из коробки» на современных ядрах (cgroup v2, PVE 9 — только v2).

## Теоретический блок

### LXC vs Docker: слои, а не конкуренция

| Критерий | LXC (PCT) | Docker в LXC |
| --- | --- | --- |
| Изоляция | ОС-контейнер: namespaces + cgroups + AppArmor | Контейнер приложения поверх dockerd |
| Ядро | Всегда ядро хоста PVE («своё ядро» — только у KVM-VM) | То же ядро (3-й уровень nesting) |
| Init | systemd / openrc внутри гостя | Один процесс (entrypoint) |
| Управление в PVE | Нативно: `pct`, snapshots, vzdump, HA | Только внутри гостя: Docker/Compose |
| Snapshot PVE | Да (ZFS/BTRFS/LVM — зависит от storage) | Не видит внутренности Docker-слоёв |
| Ресурсы | Лимиты LXC (cgroup v2) на весь LXC, включая все docker-контейнеры | Лимиты контейнеров — внутри этих лимитов |

**Когда LXC+Docker уместен:** homelab, CI-стенды, несколько compose-стеков на одном узле, миграция «сервер с Docker» → PVE без полной VM.  
**Когда нужна KVM-VM с Docker:** незнакомые tenants, требования ядерной изоляции, need custom kernel modules, production с жёстким security-обзором. PVE-документация и форум последовательно рекомендуют VM как более предсказуемый путь для Docker.

### Архитектура Docker-in-LXC (unprivileged)

```text
Proxmox Host (Kernel, cgroup v2)
├── LXC unprivileged (uid_map: 0→100000)
│   ├── nesting=1, keyctl=1, AppArmor (иногда unconfined)
│   ├── dockerd (+ containerd)
│   ├── container A (nginx)
│   └── container B (postgres)   ← root = host UID 100000
└── rootfs LXC: overlay2 /var/lib/docker (ext4 на ZFS/LVM)
```

Escape из docker-контейнера упирается в ядро и в политику LXC; с nesting surface ядра шире (procfs/sysfs), уровень привилегий — ниже, чем у Docker на bare metal.

### Что PVE требует от конфигурации LXC для Docker

| Параметр | Unprivileged | Privileged | Комментарий |
| --- | --- | --- | --- |
| `features: nesting=1` | Обязателен | Обязателен | procfs/sysfs для inner namespaces |
| `features: keyctl=1` | **Обязателен** (док. PCT) | Не нужен | Иначе dockerd падает на unprivileged |
| `lxc.apparmor.profile: unconfined` | Часто обязателен | Часто обязателен | Ограничение: не recommended for production |
| `lxc.cgroup2.devices.allow: a` | По необходимости | — | Устройства для runc (в т.ч. fuse) |
| `lxc.mount.auto: proc:rw sys:rw` | Иногда вручную поверх nesting | — | Не путать с nesting; nesting уже отдаёт views |
| cgroups | Только v2 (PVE 9; в 8 — v2 по умолчанию) | То же | `systemd.unified_cgroup_hierarchy=1` в cmdline **не нужен** на PVE 8/9 |

**Userns-remap Docker (`userns-remap`) внутри unprivileged LXC** — двойной remap (LXC + dockerd) на практике ломает права томов и bind-mount’ов без заметной выгоды: LXC уже не даёт host-root. Ремап dockerd оставьте для Docker **на KVM-VM или bare metal**; в LXC полагайтесь на маппинг PCT.

## Практические сценарии

### 1. Unprivileged LXC + nesting/keyctl (рекомендуемый каркас)

```bash
# Шаблон (версию см. в свой локальный список: pveam list local)
pveam download local debian-12-standard_12.7-1_amd64.tar.zst
# → Downloaded debian-12-standard_12.7-1_amd64.tar.zst ...

pct create 200 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname docker-host \
  --memory 4096 \
  --swap 1024 \
  --cores 2 \
  --rootfs local-lvm:32 \
  --unprivileged 1 \
  --onboot 1 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp,firewall=1

# AppArmor unconfined — часто нужен для dockerd (см. «Безопасность»)
pct set 200 --features nesting=1,keyctl=1
cat >> /etc/pve/lxc/200.conf << 'EOF'
lxc.apparmor.profile: unconfined
EOF

pct reboot 200
pct status 200
# → status: running
```

Проверка после старта:

```bash
pct exec 200 -- cat /proc/filesystems | grep -c overlay
# → 1
pct exec 200 -- stat -fc %T /sys/fs/cgroup
# → cgroup2fs
pct config 200 | grep -E '^(unprivileged|features):'
# → unprivileged: 1
# → features: nesting=1,keyctl=1
```

### 2. Privileged LXC (только когда обязателен)

```bash
pct create 201 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname docker-priv \
  --memory 4096 --cores 2 --rootfs local-lvm:32 \
  --unprivileged 0 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp

pct set 201 --features nesting=1
# keyctl для privileged не требуется; AppArmor-разблокировка — как в сценарии 1
```

Используйте, только если unprivileged физически невозможен (часть bind-mount/NFS/FUSE-кейсов). escape из privileged ≈ root на узле.

### 3. Установка Docker Engine (официальный репозиторий)

```bash
pct enter 200   # или pct exec 200 --

apt update && apt install -y ca-certificates curl

# Debian (inside LXC)
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg \
  | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list

apt update
apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

systemctl enable --now docker
docker run --rm hello-world
# → Hello from Docker! ...
```

Для Ubuntu внутри LXC — тот же рецепт с `download.docker.com/linux/ubuntu`. Альтернатива `curl -fsSL https://get.docker.com | sh` — быстрее для стенда, хуже аудируемости production.

### 4. daemon.json: логи и storage driver

```bash
mkdir -p /etc/docker
cat > /etc/docker/daemon.json << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "storage-driver": "overlay2"
}
EOF

# Синтаксис
python3 -m json.tool /etc/docker/daemon.json >/dev/null && echo OK
# → OK

systemctl restart docker
docker info --format '{{.Driver}} {{.LoggingDriver}}'
# → overlay2 json-file
```

Не задавайте `overlay2.size` без XFS+pquota на backing-FS; `override_kernel_check` на PVE 8/9 избыточен. Полный референс — [daemon.json](../Docker/docker_daemon_config.md).

### 5. Docker Compose: стек и автозапуск

```bash
mkdir -p /opt/app && cd /opt/app
cat > compose.yaml << 'EOF'
services:
  web:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./html:/usr/share/nginx/html:ro
    restart: unless-stopped
    networks: [frontend]

  db:
    image: postgres:17-alpine
    environment:
      POSTGRES_DB: app
      POSTGRES_USER: app
      POSTGRES_PASSWORD_FILE: /run/secrets/pg_password
    secrets:
      - pg_password
    volumes:
      - db_data:/var/lib/postgresql/data
    restart: unless-stopped
    networks: [backend]

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    networks: [backend]

volumes:
  db_data:

secrets:
  pg_password:
    file: ./secrets/pg_password

networks:
  frontend:
  backend:
EOF

mkdir -p html secrets
echo '<h1>PVE Docker-in-LXC</h1>' > html/index.html
# Пароль — из vault/Ansible, не в git; для стенда:
printf 'change-me' > secrets/pg_password
chmod 600 secrets/pg_password

docker compose up -d
docker compose ps
# → NAME ... STATUS ... (Up)
```

Автозапуск при старте LXC: достаточно `restart: unless-stopped` у сервисов + `systemctl enable docker` внутри гостя и `onboot=1` у LXC на узле. Отдельный oneshot-unit для compose — по желанию:

```bash
cat > /etc/systemd/system/app-compose.service << 'EOF'
[Unit]
Description=Docker Compose application
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/app
ExecStart=/usr/bin/docker compose up -d --remove-orphans
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload && systemctl enable --now app-compose.service
```

Подробности Compose V2 — [Docker Compose](../Docker/Docker_compose/).

### 6. Сеть: bridge внутри LXC, macvlan, проброс портов

По умолчанию docker0 живёт **внутри** LXC; хост PVE видит только eth0 контейнера. Порты контейнеров публикуются на IP LXC (DNAT docker’ом внутри LXC).

```bash
# Быстрая проверка доступности с хоста
pct exec 200 -- ip -4 addr show docker0 | grep inet
# → inet 172.17.0.1/16 ...
curl -sS http://$(pct exec 200 -- hostname -I | awk '{print $1}')/ | head -1
# → <h1>PVE Docker-in-LXC</h1>
```

Прямой L2-доступ к VLAN — вторым интерфейсом LXC (не путать имя veth в PCT с bridge’ом Docker):

```bash
# net1 = veth внутри LXC; bridge хоста — vmbr0 с tag
pct set 200 --net1 name=eth1,bridge=vmbr0,tag=20,ip=10.0.20.10/24,gw=10.0.20.1

pct exec 200 -- ip link add macvlan0 link eth1 type macvlan mode bridge
pct exec 200 -- ip addr add 10.0.20.11/32 dev macvlan0
pct exec 200 -- ip link set macvlan0 up
pct exec 200 -- ip route add default via 10.0.20.1

docker network create -d macvlan \
  --subnet=10.0.20.0/24 --gateway=10.0.20.1 \
  -o parent=eth1 proxynet
```

Рекомендация: для большинства стеков достаточно bridge + публикации портов + reverse-proxy на отдельном LXC/VM. VLAN/macvlan — когда нужен внешний IP у контейнера. Firewall PVE на `net0/net1` — [Firewall](./proxmox_firewall_advanced.md), [Networking](./proxmox_networking.md).

### 7. Лимиты ресурсов (cgroup v2) на уровне LXC

Docker-контейнеры **не видны** в PVE; ресурсы задают для LXC целиком:

```bash
pct set 200 --memory 4096 --swap 1024 --cores 2 --cpulimit 0
pct config 200 | grep -E '^(memory|cores|swap):'
```

Внутри LXC — `deploy.resources` в Compose или `docker run --memory` / `--cpus`, но потолок остаётся у LXC. Мониторинг узла — [Monitoring](./proxmox_monitoring.md).

### 8. Бэкап LXC с Docker: что реально в архиве

Волшебной опции `include-docker-containers` **нет** — `vzdump` архивирует rootfs контейнера целиком.

| Что | Входит в vzdump |
| --- | --- |
| `/var/lib/docker` на rootfs | Да (если rootfs — файловая система контейнера) |
| Docker volumes (named) на rootfs | Да |
| Bind-mount’ы наружу | **Никогда** (PVE не управляет их содержимым) |
| Доп. mount points `mpX` | По умолчанию **нет**; включается флагом Backup у тома (GUI) / `backup=1` |
| Состояние «running» демона | Архив ФС; после restore нужно `systemctl start docker` |

```bash
# Том с кешем образов — отдельно, без включения в backup (эфемерно)
pct set 200 --mp0 volume=local-lvm:vm-200-disk-1,mp=/var/lib/docker,backup=0

# Ручной бэкап (snapshot требует snapshot-capable storage)
vzdump 200 --mode snapshot --storage local --compress zstd
# → INFO: Starting new Backup job ...
# → INFO: Finished Backup of CT 200 ...

vzdump 200 --mode stop --storage local --compress zstd   # fallback без snapshots
```

Восстановление контейнера — **`pct restore`**, не `qmrestore` (та команда только для QEMU VM):

```bash
pvesm extractconfig /var/lib/vz/dump/vzdump-lxc-200-*.vma.zst 2>/dev/null | head
# или без распаковки — просто:

pct restore 200 /var/lib/vz/dump/vzdump-lxc-200-2026_10_18-03_00_00.tar.zst \
  --storage local
# Advanced mode (rootfs задан явно — архивные mpX игнорируются):
pct restore 210 /path/vzdump-lxc-200-*.tar.zst \
  --rootfs local-lvm:32 --storage local
```

Политики хранения — [Storage](./proxmox_storage.md), PBS — [Backup Server](./proxmox_backup_server.md), разбор упавших job — [Logging](./proxmox_logging.md).

### 9. Мониторинг Docker внутри LXC

PVE скрейпит сам LXC (node_exporter/PVE exporter), но **не** метрики docker-контейнеров. cAdvisor запускают внутри того же LXC:

```bash
docker run -d --name cadvisor --restart unless-stopped \
  --volume /:/rootfs:ro \
  --volume /var/run:/var/run:ro \
  --volume /sys:/sys:ro \
  --volume /var/lib/docker/:/var/lib/docker:ro \
  --publish 127.0.0.1:8080:8080 \
  ghcr.io/google/cadvisor:v0.60.6

curl -sS http://127.0.0.1:8080/metrics | head -3
# → # HELP container_cpu_usage_seconds_total ...
```

Scrape и алерты: [cAdvisor (SSoT)](../Docker/Docker_metrics/docker_cadvisor_deployment.md), [Prometheus-интеграция Docker](../Docker/Docker_metrics/docker_prometheus_integration.md), [Proxmox Monitoring](./proxmox_monitoring.md). Не светите 8080 наружу — только localhost/внутренний VLAN + firewall.

### 10. Логирование

```bash
# rotation — в daemon.json (сценарий 4); проверка:
ls -lh /var/lib/docker/containers/*/*-json.log
journalctl -u docker --since '1 hour ago'

docker compose logs -f web
```

Вывод в journald/syslog и централизация — [Docker Logs](../Docker/Docker_logs/), [Proxmox Logging](./proxmox_logging.md).

## Диагностика и устранение неполадок

### dockerd не стартует

```bash
pct config 200 | grep -E 'features|apparmor|unprivileged'
# → features: nesting=1,keyctl=1
# → lxc.apparmor.profile: unconfined
# → unprivileged: 1

pct exec 200 -- journalctl -u docker -e --no-pager | tail -40
```

| Симптом | Причина | Действие |
| --- | --- | --- |
| `Failed to mount overlayfs` / no overlay | Nesting/sysfs | `features: nesting=1`; перезапуск LXC |
| `keyctl: Permission denied` / syscall missing | Нет `keyctl=1` на unprivileged | `pct set CT --features nesting=1,keyctl=1` |
| AppArmor denial в dmesg хоста | Профиль LXC | `lxc.apparmor.profile: unconfined` (осознанный trade-off) |
| cgroup v1/v2 конфликт | Старый рецепт cmdline | На PVE 8/9 unified v2 — cmdline-флаг не нужен |

**Важно:** `pct set --features …` **заменяет** весь список, не добавляет флаги. Всегда перечисляйте `nesting=1,keyctl=1` одной строкой.

### Overlay2 / права томов

```bash
pct exec 200 -- docker info | grep -iE 'storage|root dir'
pct exec 200 -- df -h /var/lib/docker
pct enter 200 -- id
# На хосте: «чужие» UID — ожидание для unprivileged
pct mount 200
ls -ln /var/lib/lxc/200/rootfs/var/lib/docker | head
```

Если rootfs LXC — ZFS dataset, overlay2 работает, но для тяжёлой сборки/IO часто выносят `/var/lib/docker` на ext4-том (mpX) или KVM-VM.

### Сеть/публикация портов

```bash
pct exec 200 -- ss -lntup | grep -E 'docker|:80'
iptables -t nat -L -n | head    # на хосте — если ждёте DNAT наружу, помните: docker0 в namespace LXC
pct exec 200 -- iptables -t nat -L DOCKER -n
```

Порты наружу: либо reverse-proxy на IP LXC, либо macvlan/проброс на уровне PVE (port forward/SDN) — [Networking](./proxmox_networking.md).

### Бэкап/restore: exit code 23, rsync, ACL

Типичен на ZFS при snapshot/suspend и posixacl. Выносите `--tmpdir` на FS без проблемных ACL или используйте `--mode stop` для критичных гостей. Bind-mount’ы бэкапируйте отдельно (`proxmox-backup-client` на хосте, NFS-side snapshots и т.п.).

## Лучшие практики

1. **Unprivileged + nesting/keyctl** — базовый профиль; privileged — исключение с обоснованием.
2. **AppArmor unconfined** — документируйте компромисс; для незнакомых workload предпочитайте KVM-VM.
3. **Лимиты** — RAM/CPU/swap на LXC; не полагайтесь только на `--memory` docker.
4. **Backup** — `/var/lib/docker` эфемерен: `backup=0` на mp с кешем образов; данные — volumes + приложение-бэкапы; тестовый `pct restore` вменяемости.
5. **Секреты** — не в compose-файлах в git; file-secrets/Ansible vault, mode 600.
6. **Обновления** — apt внутри LXC + ядро/PVE на узле ([Updates](./proxmox_updates.md)); перезапуск LXC после kernel-upgrade в плане работ.
7. **Сеть** — bridge по умолчанию; firewall=1 на NIC; 8080 cAdvisor — только localhost.
8. **Логи** — json-file max-size/max-file всегда; иначе rootfs переполнится.
9. **Swarm/K8s в LXC** — не начинайте: raft/контроллеры чувствительны к nesting; k3s/K8s — в VM ([Kubernetes](../Kubernetes/kubernetes_overview.md)).
10. **Когда сомневаетесь — VM.** Docker-in-LXC — инструмент компромисса, не «лучший практик по умолчанию» для PVE.

## Граничные случаи

- **cgroups:** PVE 9 — только unified v2; cgroup v1 убран. Рецепты «включить unified hierarchy в cmdline» для PVE 8/9 не нужны.
- **Docker Desktop** — не ставится в LXC (нет своего KVM); только Docker Engine.
- **FUSE / fuse-overlayfs** — в unprivileged требует `features: fuse=1` и/или AppArmor/device access; стандартный overlay2 на PVE 8/9 предпочтительнее.
- **Userns-remap Docker** — не комбинируйте с unprivileged LXC без явной инженерной задачи.
- **Live migration LXC** — возможна при compatible storage; внутри — состояния dockerd не мигрируют, сервисы стартуют на целевом узле.
- **PID 1 / zombies** — если гаснет systemd-стек, проверяйте, что entrypoint compose-контейнеров не «ядовитый» для init LXC.
- **ZFS + snapshot vzdump** — иногда ACL/tmpdir (exit 23); см. диагностику.

## Дополнительная информация

### Связанные темы

- [LXC — обзор](../Linux/Virtualization/lxc_overview.md)
- [Продвинутый LXC в Proxmox](./proxmox_lxc_advanced.md)
- [Docker — обзор](../Docker/docker_overview.md)
- [daemon.json](../Docker/docker_daemon_config.md)
- [Установка Docker](../Docker/docker_install_ubuntu.md)
- [Docker Compose](../Docker/Docker_compose/)
- [cAdvisor](../Docker/Docker_metrics/docker_cadvisor_deployment.md)
- [Docker-in-Docker (CI) — другой контекст](../Docker/docker-in-docker.md)
- [Обзор Proxmox VE](./proxmox_overview.md)
- [Networking](./proxmox_networking.md) · [Firewall](./proxmox_firewall_advanced.md)
- [Monitoring](./proxmox_monitoring.md) · [Logging](./proxmox_logging.md)
- [Storage](./proxmox_storage.md) · [Backup Server](./proxmox_backup_server.md)
- [Updates](./proxmox_updates.md) · [Security](./proxmox_security.md)
- [Kubernetes](../Kubernetes/kubernetes_overview.md)
