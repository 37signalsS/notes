# Запуск Docker в LXC контейнерах Proxmox

## Определения

**LXC (Linux Containers)** -- операционная системная виртуализация на уровне ядра Linux. Контейнер разделяет ядро с хостом, но имеет изолированные namespace (PID, network, mount, user). В отличие от Docker, LXC имитирует полноценную ОС с init-системой.

**Docker-in-LXC** -- запуск Docker runtime внутри LXC контейнера Proxmox. Позволяет использовать Docker Compose и экосистему контейнеров, сохраняя изоляцию на уровне Proxmox.

**Nesting** -- параметр LXC, разрешающий запуск контейнеров внутри контейнеров (Linux namespaces). Требуется для Docker-in-LXC.

**Privileged vs Unprivileged** --privileged LXC имеет root-доступ к namespace хоста (небезопасно). Unprivileged LXC映射 UID/GID через subuid/subgid (безопаснее).

**OverlayFS** -- filesystem для Docker storage driver. Позволяет эффективно хранить слои контейнеров. В LXC требуется ручная настройка.

## Теоретический блок

### LXC vs Docker в Proxmox

| Критерий | LXC | Docker |
|----------|-----|--------|
| Изоляция | Операционная система | Приложение |
| Ядро | Каждый контейнер может иметь своё ядро | Разделяет ядро с хостом |
| Init-система | systemd/openrc | Один процесс |
| Сетевые пространства | Полная изоляция | Полная изоляция |
| Производительность | Почти native | Почти native |
| Snapshot'ы | Да (ZFS/BTRFS) | Да ( через storage driver) |
| Использование в Proxmox | Нативная поддержка | Через nesting |

### Архитектура Docker-in-LXC

```
Proxmox Host (Kernel)
┌────────────────────────────────────────┐
│  LXC Container (unprivileged)         │
│  ┌──────────────────────────────────┐ │
│  │  Docker Daemon (dockerd)         │ │
│  │  ┌────────────┐ ┌────────────┐  │ │
│  │  │ Container A│ │ Container B│  │ │
│  │  │ (nginx)   │ │ (postgres) │  │ │
│  │  └────────────┘ └────────────┘  │ │
│  └──────────────────────────────────┘ │
│  Storage: OverlayFS on ZFS           │
│  Network: docker0 bridge → macvlan   │
└────────────────────────────────────────┘
```

## Практические сценарии

### 1. Создание LXC для Docker

```bash
# Создание privileged LXC (проще, но менее безопасно)
pct create 200 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst   --hostname docker-host   --memory 4096   --cores 2   --rootfs 32   --net0 name=eth0,bridge=vmbr0,ip=dhcp

# Настройка LXC для Docker
cat >> /etc/pve/lxc/200.conf << 'EOF'
# Docker-in-LXC настройки
features: nesting=1,keyctl=1
unprivileged: 0
EOF

# Применение изменений
pct reboot 200
```

### 2. Unprivileged LXC для Docker (безопаснее)

```bash
# Создание unprivileged LXC
pct create 201 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst   --hostname docker-secure   --memory 4096   --cores 2   --rootfs 32   --unprivileged 1   --net0 name=eth0,bridge=vmbr0,ip=dhcp

# Настройка nested namespaces
cat >> /etc/pve/lxc/201.conf << 'EOF'
features: nesting=1,keyctl=1
EOF

# Маппинг UID/GID для Docker inside unprivileged LXC
# На хосте:
echo "root:100000:65536" >> /etc/subuid
echo "root:100000:65536" >> /etc/subgid

# Внутри LXC (после входа):
pct enter 201

# Настройка subuid/subgid внутри контейнера
echo "dockremap:165536:65536" >> /etc/subuid
echo "dockremap:165536:65536" >> /etc/subgid

# Настройка Docker daemon
cat > /etc/docker/daemon.json << 'EOF'
{
  "storage-driver": "overlay2",
  "userns-remap": "default",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
EOF
```

### 3. Установка Docker в LXC

```bash
# Внутри LXC (Debian/Ubuntu)
apt update
apt install -y ca-certificates curl gnupg

# Добавление официального Docker репозитория
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list

apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Запуск
systemctl enable --now docker
docker run hello-world
```

### 4. Оптимизация storage driver

```bash
# Проверка текущего storage driver
docker info | grep "Storage Driver"

# Настройка OverlayFS (оптимально для LXC)
cat > /etc/docker/daemon.json << 'EOF'
{
  "storage-driver": "overlay2",
  "storage-opts": [
    "overlay2.override_kernel_check=true",
    "overlay2.size=20G"
  ]
}
EOF

systemctl restart docker

# Проверка
docker info | grep -A 5 "Storage Driver"
```

### 5. Сетевые настройки для Docker в LXC

```bash
# Bridged networking (по умолчанию)
# Docker使用 docker0 bridge внутри LXC
# LXC с macvlan для прямого доступа к сети

# Настройка macvlan в LXC
cat >> /etc/pve/lxc/200.conf << 'EOF'
# Дополнительный интерфейс для Docker
net1: name=docker0,bridge=vmbr0,ip=10.0.0.100/24,hwaddr=auto
EOF

# Внутри LXC -- настройка macvlan
ip link add docker-macvlan link eth1 type macvlan mode bridge
ip addr add 10.0.0.100/32 dev docker-macvlan
ip link set docker-macvlan up
ip route add 10.0.0.0/24 dev docker-macvlan

# Docker network с macvlan
docker network create -d macvlan   --subnet=10.0.0.0/24   --gateway=10.0.0.1   -o parent=docker-macvlan   proxynet
```

### 6. Docker Compose в LXC

```bash
# docker-compose.yml
cat > /opt/docker-compose/docker-compose.yml << 'EOF'
version: "3.8"
services:
  web:
    image: nginx:alpine
    ports:
      - "80:80"
    volumes:
      - ./html:/usr/share/nginx/html
    restart: unless-stopped
    networks:
      - frontend

  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: app
      POSTGRES_USER: app
      POSTGRES_PASSWORD: secret
    volumes:
      - db_data:/var/lib/postgresql/data
    restart: unless-stopped
    networks:
      - backend

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    networks:
      - backend

volumes:
  db_data:

networks:
  frontend:
  backend:
EOF

# Запуск
cd /opt/docker-compose
docker compose up -d

# Проверка
docker compose ps
docker compose logs -f
```

### 7. Мониторинг Docker в LXC

```bash
# Экспорт метрик Docker для Prometheus
docker run -d   --name cadvisor   --volume /:/rootfs:ro   --volume /var/run:/var/run:ro   --volume /sys:/sys:ro   --volume /var/lib/docker/:/var/lib/docker:ro   --publish 8080:8080   ghcr.io/google/cadvisor:v0.60.6

# Настройка scrape в Prometheus
# prometheus.yml
# scrape_configs:
#   - job_name: 'docker'
#     static_configs:
#       - targets: ['lxc-host:8080']

# Внутри LXC -- проверка метрик
curl http://localhost:8080/metrics
```

### 8. Бэкап Docker контейнеров в LXC

```bash
# Включение Docker в backup для vzdump
# /etc/vzdump.conf
backup: include-docker-containers: yes

# Или на уровне VM
# /etc/pve/vzdump.conf
backup: include-docker-containers: yes

# Ручной бэкап с Docker контейнерами
vzdump 200 --mode snapshot --storage local-zfs --compress zstd

# Восстановление -- Docker данные восстанавливаются автоматически
qmrestore /mnt/pbs-backup/vzdump-lxc-200-*.pxar 200
```

### 9. Автозапуск Docker сервисов

```bash
# systemd unit для автозапуска compose
cat > /etc/systemd/system/docker-compose.service << 'EOF'
[Unit]
Description=Docker Compose Application
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/docker-compose
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
EOF

systemctl enable docker-compose.service
```

### 10. Логирование Docker в LXC

```bash
# Настройка логирования в файлы
cat > /etc/docker/daemon.json << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3",
    "labels": "service",
    "env": "os,customer"
  }
}
EOF

# Просмотр логов
docker logs -f <container>
journalctl -u docker --since "1 hour ago"

# Интеграция с Fluentd/Fluent Bit
# см. proxmox_logging.md
```

## Диагностика и устранение неполадок

### Docker daemon не запускается в LXC

```bash
# Проверка nesting
pct config 200 | grep features
# → features: nesting=1

# Проверка systemd в LXC
systemctl status docker

# Проверка логов
journalctl -u docker --since "5 minutes ago"

# Типичные ошибки:
# - nesting=1 не включен
# - keyctl=1 не включен
# - cgroups v2 не настроен
```

### OverlayFS не работает

```bash
# Проверка поддержки ядра
cat /proc/filesystems | grep overlay

# В unprivileged LXC проверка subuid/subgid
cat /etc/subuid
cat /etc/subgid

# Проверка dockremap
id dockremap

# Проверка daemon.json
cat /etc/docker/daemon.json
```

### Сеть Docker не работает

```bash
# Проверка docker0
ip addr show docker0

# Проверка iptables
iptables -L -n -v

# Проверка DNS
cat /etc/resolv.conf

# Пересоздание docker0
ip link set docker0 down
ip link delete docker0
systemctl restart docker
```

## Лучшие практики

1. **Unprivileged LXC**: Всегда используйте unprivileged контейнеры для Docker. Нарушает принцип минимальных привилегий.

2. **Nesting**: Включайте `features: nesting=1` только для контейнеров с Docker. Для обычных LXC -- не нужно.

3. **Storage**: Используйте OverlayFS на ZFS. Не используйte `devicemapper` -- он ненадежен в LXC.

4. **Сеть**: Для production -- macvlan. Для dev/test -- стандартный docker0 bridge.

5. **Логирование**: Настройте `json-file` с `max-size` и `max-file`. Не храните логи бесконечно.

6. **Мониторинг**: Интегрируйте cAdvisor + Prometheus для метрик Docker. См. [Proxmox Monitoring](./proxmox_monitoring.md).

7. **Бэкапы**: Включите `include-docker-containers` в vzdump. Используйте volumes для данных.

8. **Безопасность**: Не запускайте привилегированные контейнеры (`--privileged`). Используйте `--cap-drop` и `--security-opt`.

9. **Ресурсы**: Ограничивайте CPU/RAM на уровне LXC, а не Docker. Proxmox видит только LXC контейнер.

10. **Обновления**: Обновляйте Docker и ядро регулярно. Проверяйте совместимость nesting с новыми версиями.

## Граничные случаи

- **Nested containers и Cgroups v2**: Proxmox 8+ по умолчанию использует cgroups v2. Docker в LXC может требовать `systemd.unified_cgroup_hierarchy=1` в cmdline ядра.

- **UID mapping и файлы**: В unprivileged LXC файлы, созданные Docker контейнерами, могут иметь "странные" UID на хосте. Используйте `pct mount` для доступа.

- **Docker Swarm и LXC**: Docker Swarm требует raft consensus. Не рекомендуется в LXC -- используйте Kubernetes (k3s) или standalone.

- **Docker Desktop**: Docker Desktop не работает в LXC (нет KVM). Используйте Docker Engine.

- **Проброс портов**: Порты Docker пробрасываются через LXC bridge. Убедитесь, что проксирующий сервер (nginx/HAProxy) знает IP LXC контейнера.

## Дополнительная информация

### Связанные темы

- [Docker (обзор)](../Linux/Virtualization/docker/docker.md)
- [Kubernetes с Docker](../Linux/Virtualization/kubernetes/kubernetes.md)
- [LXC и Proxmox](../Linux/Virtualization/containers/lxc/lxc.md)
- [Proxmox Networking](./proxmox_networking.md)
- [Proxmox Monitoring](./proxmox_monitoring.md)
