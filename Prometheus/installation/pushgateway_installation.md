# Pushgateway Installation

## Definitions

**Pushgateway** — компонент Prometheus для приёма метрик от ephemeral и batch-задач. Принимает метрики по HTTP, хранит до скрейпинга Prometheus. Не является решением для долгосрочного хранения.

> **Общее руководство:** [Pushgateway](../pushgateway.md).

## Basic Concepts

### Актуальная версия

| Параметр | Значение |
|---|---|
| **Последняя стабильная версия** | `1.11.2` (2025-10-30) |
| **Репозиторий** | [prometheus/pushgateway](https://github.com/prometheus/pushgateway) |

### Когда использовать

**Рекомендуемые сценарии:**

* Batch-задачи (cron jobs), выполняющиеся реже интервала скрейпинга
* Эфемерные задачи, недоступные для scrape
* Сервисы за firewall

**Не рекомендуется:**

* Долгосрочное хранение метрик
* Замена pull-модели Prometheus
* Мониторинг долгоживущих сервисов

> **Анти-паттеры и подробности:** [Pushgateway — когда использовать](../pushgateway.md#когда-использовать).

## Practical Scenarios

### Установка из бинарных файлов (Linux)

**1. Создание пользователя:**

```bash
useradd --no-create-home --shell /bin/false pushgateway --comment "Pushgateway server user"
```

**2. Загрузка и установка:**

```bash
PUSHGATEWAY_VERSION="1.11.2"
cd /tmp
wget https://github.com/prometheus/pushgateway/releases/download/v${PUSHGATEWAY_VERSION}/pushgateway-${PUSHGATEWAY_VERSION}.linux-amd64.tar.gz
tar xvfz pushgateway-${PUSHGATEWAY_VERSION}.linux-amd64.tar.gz
cd pushgateway-${PUSHGATEWAY_VERSION}.linux-amd64
mv pushgateway /usr/local/bin/
```

**3. Создание файла с опциями запуска** (`/etc/sysconfig/pushgateway`):

```bash
cat <<EOF > /etc/sysconfig/pushgateway
OPTIONS="--web.listen-address=:9091 \
--web.telemetry-path=/metrics \
--persistence.file=/var/lib/pushgateway/metrics.store \
--persistence.interval=5m \
--log.level=info"
EOF
```

**4. Создание каталога для персистентности:**

```bash
mkdir -p /var/lib/pushgateway
chown pushgateway:pushgateway /var/lib/pushgateway
```

**5. Создание systemd-юнита** (`/etc/systemd/system/pushgateway.service`):

```bash
cat <<EOF > /etc/systemd/system/pushgateway.service
[Unit]
Description=Prometheus Pushgateway
Documentation=https://github.com/prometheus/pushgateway
After=network-online.target

[Service]
User=pushgateway
Group=pushgateway
EnvironmentFile=/etc/sysconfig/pushgateway
Restart=always
ExecStart=/usr/local/bin/pushgateway \$OPTIONS
ExecReload=/bin/kill -HUP \$MAINPID
TimeoutStopSec=20s
SendSIGKILL=no

[Install]
WantedBy=multi-user.target
EOF
```

**6. Запуск и проверка:**

```bash
systemctl daemon-reload
systemctl start pushgateway
systemctl enable pushgateway

# Проверка доступности
curl -s -o /dev/null -w "%{http_code}" http://localhost:9091/-/healthy
# Ожидаемый ответ: 200

# Проверка статуса
systemctl status pushgateway
```

### Установка через Docker

```bash
docker run -d \
  --name pushgateway \
  -p 9091:9091 \
  -v /var/lib/pushgateway:/data \
  prom/pushgateway:v1.11.2 \
  --persistence.file=/data/metrics.store \
  --persistence.interval=5m
```

### Отправка метрик от batch-задачи

```bash
#!/bin/bash
START=$(date +%s)

# ... выполнение задачи ...

END=$(date +%s)
DURATION=$((END - START))

cat <<EOF | curl --data-binary @- http://localhost:9091/metrics/job/backup/instance/db-server
# HELP backup_duration_seconds Duration of backup job
# TYPE backup_duration_seconds gauge
backup_duration_seconds $DURATION
# HELP backup_status Status of backup (1=success, 0=failure)
# TYPE backup_status gauge
backup_status 1
EOF
```

> **Принцип работы и группировка метрик:** [Pushgateway — Basic Concepts](../pushgateway.md#basic-concepts).

### Скрейпинг из Prometheus

```yaml
scrape_configs:
  - job_name: 'pushgateway'
    honor_labels: true  # Сохраняет лейблы job/instance из URL
    static_configs:
      - targets: ['localhost:9091']
```

> **Подробности настройки:** [Pushgateway — настройка Prometheus](../pushgateway.md#настройка-prometheus).

## Additional Information

### Рекомендации по безопасности

**Непривилегированный пользователь:**

```bash
useradd --no-create-home --shell /bin/false pushgateway
```

**Ограничение сетевого доступа:**

```bash
ufw allow from 10.0.0.0/8 to any port 9091
```

**TLS через обратный прокси (Nginx):**

```nginx
server {
    listen 443 ssl;
    server_name pushgateway.example.com;

    ssl_certificate /etc/ssl/certs/pushgateway.crt;
    ssl_certificate_key /etc/ssl/private/pushgateway.key;

    location / {
        proxy_pass http://localhost:9091;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Параметры запуска

| Параметр | По умолчанию | Описание |
|---|---|---|
| `--web.listen-address` | `:9091` | Адрес для веб-интерфейса |
| `--web.telemetry-path` | `/metrics` | Путь для метрик |
| `--web.enable-admin-api` | `false` | Включить admin API |
| `--web.enable-lifecycle` | `false` | Включить reload/shutdown API |
| `--persistence.file` | `` | Файл для персистентности |
| `--persistence.interval` | `5m` | Интервал сохранения |
| `--log.level` | `info` | Уровень логирования |

> **Полный список флагов:** [Pushgateway — параметры запуска](../pushgateway.md#параметры-запуска).

### API

**Отправка метрик (POST — добавление/обновление):**

```bash
curl -T metrics.txt http://localhost:9091/metrics/job/myjob/instance/instance1
```

**Замена метрик (PUT — полная замена группы):**

```bash
curl -X PUT -T metrics.txt http://localhost:9091/metrics/job/myjob/instance/instance1
```

**Удаление группы метрик:**

```bash
curl -X DELETE http://localhost:9091/metrics/job/myjob/instance/instance1
```

> **Подробное описание API и управление жизненным циклом:** [Pushgateway — HTTP API](../pushgateway.md#http-api).

### Устранение неполадок

**Pushgateway не запускается:**

```bash
journalctl -u pushgateway -f
ss -tnlp | grep 9091
ls -la /var/lib/pushgateway/
```

**Метрики не сохраняются:**

* Проверьте путь `--persistence.file` и права на запись
* Убедитесь, что `--persistence.interval` не слишком большой

**Метрики дублируются:**

* Pushgateway не удаляет метрики автоматически — используйте `DELETE` API перед завершением задачи
* Настройте TTL, если версия поддерживает
