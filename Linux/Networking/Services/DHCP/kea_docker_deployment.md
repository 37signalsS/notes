# Kea DHCP: Развертывание в контейнерах (Docker/Podman)

---

## Определения

**Containerized DHCP** — развертывание DHCP-сервера в контейнере (Docker/Podman) для изоляции, воспроизводимости и простоты управления. Подходит для dev/staging сред и специфичных production-сценариев (edge, IoT).

**Rootless containers** — контейнеры, запускаемые без root-привилегий. Для Kea требуют `--cap-add=NET_RAW` и `--net=host` для raw sockets.

**Persistent volume** — том для хранения данных, сохраняющихся после перезапуска контейнера (leases, конфигурация, логи).

---

## Основные концепции

### Архитектура Kea в контейнере

```
┌─────────────────────────────────────────────┐
│              Docker Host                     │
│  ┌─────────────────────────────────────┐    │
│  │         kea-dhcp4 container          │    │
│  │  ┌──────────┐  ┌────────────────┐   │    │
│  │  │ kea-dhcp4│  │ kea-ctrl-agent │   │    │
│  │  │ UDP 67   │  │ TCP 8000       │   │    │
│  │  └────┬─────┘  └───────┬────────┘   │    │
│  │       │                │            │    │
│  │  ┌────┴────────────────┴────────┐   │    │
│  │  │     Shared volumes           │   │    │
│  │  │  /etc/kea (config)           │   │    │
│  │  │  /var/lib/kea (leases)       │   │    │
│  │  │  /var/log/kea (logs)         │   │    │
│  │  └──────────────────────────────┘   │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
```

### Ограничения контейнерного DHCP

| Проблема | Решение |
|:--- |:--- |
| Raw sockets требуют root | `--cap-add=NET_RAW` или `--privileged` |
| DHCP слушает все интерфейсы | `--net=host` или `--network=promiscuous` |
| Персистентность leases | Volume mounts |
| systemd не доступен | Запуск через supervisord или отдельные контейнеры |
| Broadcast-пакеты | `--net=host` обязателен |

### Когда использовать контейнеры

| Сценарий | Рекомендация |
|:--- |:--- |
| Production (крупные сети) | Не рекомендуется — используйте bare-metal/VM |
| Dev/Staging среды | Рекомендуется |
| Edge/IoT (одиночные устройства) | Возможно с ограничениями |
| Тестирование конфигураций | Рекомендуется |
| CI/CD pipeline | Рекомендуется |

---

## Практические сценарии

### 1. Базовый Dockerfile

```dockerfile
# Dockerfile.kea-dhcp4
FROM debian:bookworm-slim

# Установка Kea
RUN apt-get update && apt-get install -y --no-install-recommends \
    kea-dhcp4-server \
    kea-ctrl-agent \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Создание директорий
RUN mkdir -p /etc/kea /var/lib/kea /var/log/kea && \
    chown -R kea:kea /var/lib/kea /var/log/kea

# Копирование конфигурации
COPY kea-dhcp4.conf /etc/kea/kea-dhcp4.conf
COPY kea-ctrl-agent.conf /etc/kea/kea-ctrl-agent.conf

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8000/ || exit 1

# Ports
EXPOSE 67/udp 68/udp 8000/tcp

# Запуск
CMD ["kea-dhcp4", "-c", "/etc/kea/kea-dhcp4.conf"]
```

### 2. Docker Compose (production-ready)

```yaml
# docker-compose.yml
version: '3.8'

services:
  kea-dhcp4:
    build:
      context: .
      dockerfile: Dockerfile.kea-dhcp4
    container_name: kea-dhcp4
    restart: unless-stopped
    network_mode: host  # Обязательно для DHCP
    cap_add:
      - NET_RAW
      - NET_ADMIN
    volumes:
      - ./config/kea-dhcp4.conf:/etc/kea/kea-dhcp4.conf:ro
      - ./config/kea-ctrl-agent.conf:/etc/kea/kea-ctrl-agent.conf:ro
      - kea-leases:/var/lib/kea
      - kea-logs:/var/log/kea
    environment:
      - TZ=Europe/Moscow
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8000/"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

  # Опционально: Prometheus exporter
  kea-exporter:
    image: prom/kea-exporter:latest
    container_name: kea-exporter
    restart: unless-stopped
    network_mode: host
    ports:
      - "9547:9547"
    environment:
      - KEA_URL=http://localhost:8000
    depends_on:
      - kea-dhcp4

volumes:
  kea-leases:
    driver: local
  kea-logs:
    driver: local
```

### 3. Конфигурация для контейнера

```json
// kea-dhcp4.conf
{
    "Dhcp4": {
        "interfaces-config": {
            "interfaces": ["eth0"],
            "dhcp-sockets": "raw"
        },
        "lease-database": {
            "type": "memfile",
            "persist": true,
            "name": "/var/lib/kea/kea-leases4.csv",
            "lfc-interval": 3600
        },
        "valid-lifetime": 86400,
        "renew-timer": 43200,
        "rebind-timer": 75600,
        "authoritative": true,
        "loggers": [
            {
                "name": "kea-dhcp4",
                "severity": "INFO",
                "output-options": [
                    {
                        "output": "stdout",
                        "pattern": "%-5p %m\n"
                    }
                ]
            }
        ],
        "subnet4": [
            {
                "id": 1,
                "subnet": "10.0.10.0/24",
                "pools": [
                    {
                        "pool": "10.0.10.100 - 10.0.10.200"
                    }
                ],
                "option-data": [
                    {"name": "routers", "data": "10.0.10.1"},
                    {"name": "domain-name-servers", "data": "10.0.0.10"},
                    {"name": "domain-name", "data": "corp.example.com"}
                ]
            }
        ]
    }
}
```

### 4. Podman (rootless)

```bash
# 1. Создание пользователя для Kea
sudo useradd -r -s /sbin/nologin kea

# 2. Создание директорий
sudo mkdir -p /var/lib/kea /var/log/kea /etc/kea
sudo chown kea:kea /var/lib/kea /var/log/kea

# 3. Запуск через Podman (rootless)
podman run -d \
  --name kea-dhcp4 \
  --network host \
  --cap-add NET_RAW \
  --cap-add NET_ADMIN \
  -v /etc/kea:/etc/kea:ro \
  -v /var/lib/kea:/var/lib/kea \
  -v /var/log/kea:/var/log/kea \
  localhost/kea-dhcp4:latest

# 4. systemd unit для Podman
# ~/.config/systemd/user/kea-dhcp4.service
[Unit]
Description=Kea DHCP4 Server (Podman)
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/podman run --rm \
  --network host \
  --cap-add NET_RAW \
  --cap-add NET_ADMIN \
  -v /etc/kea:/etc/kea:ro \
  -v /var/lib/kea:/var/lib/kea \
  -v /var/log/kea:/var/log/kea \
  localhost/kea-dhcp4:latest
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
# 5. Запуск
systemctl --user daemon-reload
systemctl --user enable --now kea-dhcp4
```

### 5. Kubernetes deployment

```yaml
# kea-dhcp4-deployment.yaml
apiVersion: apps/v1
kind: DaemonSet  # Один pod на каждый узел
metadata:
  name: kea-dhcp4
  namespace: network
spec:
  selector:
    matchLabels:
      app: kea-dhcp4
  template:
    metadata:
      labels:
        app: kea-dhcp4
    spec:
      hostNetwork: true  # Обязательно для DHCP
      containers:
        - name: kea-dhcp4
          image: registry.example.com/kea-dhcp4:2.6
          securityContext:
            capabilities:
              add:
                - NET_RAW
                - NET_ADMIN
          volumeMounts:
            - name: config
              mountPath: /etc/kea
              readOnly: true
            - name: leases
              mountPath: /var/lib/kea
            - name: logs
              mountPath: /var/log/kea
          ports:
            - containerPort: 67
              protocol: UDP
            - containerPort: 8000
              protocol: TCP
          livenessProbe:
            httpGet:
              path: /
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 30
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: 500m
              memory: 256Mi
      volumes:
        - name: config
          configMap:
            name: kea-config
        - name: leases
          hostPath:
            path: /var/lib/kea
            type: DirectoryOrCreate
        - name: logs
          emptyDir: {}
---
# ConfigMap с конфигурацией
apiVersion: v1
kind: ConfigMap
metadata:
  name: kea-config
  namespace: network
data:
  kea-dhcp4.conf: |
    {
        "Dhcp4": {
            "interfaces-config": {"interfaces": ["eth0"]},
            "lease-database": {"type": "memfile", "persist": true, "name": "/var/lib/kea/kea-leases4.csv"},
            "valid-lifetime": 86400,
            "subnet4": [{"id": 1, "subnet": "10.0.10.0/24", "pools": [{"pool": "10.0.10.100 - 10.0.10.200"}]}]
        }
    }
```

### 6. Тестирование контейнера

```bash
# 1. Сборка
docker build -t kea-dhcp4:latest -f Dockerfile.kea-dhcp4 .

# 2. Запуск
docker-compose up -d

# 3. Проверка статуса
docker-compose ps
docker logs kea-dhcp4 --tail 50

# 4. Проверка REST API
curl -s http://localhost:8000/ | jq

# 5. Тест выдачи адреса (на клиенте)
sudo dhclient -v eth0

# 6. Проверка leases
docker exec kea-dhcp4 cat /var/lib/kea/kea-leases4.csv

# 7. Мониторинг
curl -s -X POST http://localhost:8000/ \
  -d '{"command": "statistic-get-all"}' | jq
```

---

## Дополнительная информация

### Отладка контейнера

```bash
# Вход в контейнер
docker exec -it kea-dhcp4 bash

# Проверка процессов
docker exec kea-dhcp4 ps aux

# Проверка портов
docker exec kea-dhcp4 ss -nlup

# Проверка логов Kea
docker exec kea-dhcp4 tail -f /var/log/kea/kea-dhcp4.log

# Статистика памяти
docker stats kea-dhcp4
```

### Связанные разделы

- **[Kea DHCP: Архитектура и настройка](./kea_dhcp_overview.md)** — полный обзор.
- **[Kea DHCP: Production Operations](./kea_production_operations.md)** — day-2 ops.
- **[Kea DHCP: Управление через Ansible](./kea_ansible_management.md)** — IaC.
- **[Docker: Обзор](../../../../Docker/Docker.md)** — основы Docker.
- **[Kea DHCP Documentation](https://kea.readthedocs.io/)** — официальная документация.
