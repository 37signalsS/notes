# Установка Pushgateway

## Определения

**Pushgateway** — это приемник метрик для ephemeral и batch-задач:

* Принимает метрики от кратковременных задач (cron, batch jobs)
* Хранит метрики до момента скрейпинга Prometheus
* Не является решением для долгосрочного хранения

> **См. также:** [Pushgateway](../pushgateway.md), [Exporters](../Exporters/overview.md).

## Основные концепции

### Актуальная версия

| Параметр | Значение |
|---|---|
| **Последняя стабильная версия** | `1.11.2` |
| **Репозиторий** | [prometheus/pushgateway](https://github.com/prometheus/pushgateway) |

> **Важно:** Проверяйте [официальный репозиторий](https://github.com/prometheus/pushgateway/releases) для получения последних версий.

### Когда использовать Pushgateway

**Рекомендуемые сценарии:**

* Batch-задачи (cron jobs), которые выполняются реже интервала скрейпинга
* Эфемерные задачи, которые не могут быть доступны для scrape
* Сервисы за firewall, которые не могут быть доступны из Prometheus

**Не рекомендуется для:**

* Долгосрочного хранения метрик
* Замены pull-модели Prometheus
* Мониторинга долгоживущих сервисов

> **См. также:** [Pushgateway — когда использовать](../pushgateway.md).

## Практические сценарии

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

**4. Создание каталога для хранения метрик:**

```bash
mkdir -p /var/lib/pushgateway
chown pushgateway:pushgateway /var/lib/pushgateway
```

**5. Создание systemd-сервиса** (`/etc/systemd/system/pushgateway.service`):

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

### Пример использования: batch job

**Bash-скрипт отправляет метрики в Pushgateway:**

```bash
#!/bin/bash

# Начало задачи
START=$(date +%s)

# Выполнение работы
# ... ваша логика ...

# Конец задачи
END=$(date +%s)
DURATION=$((END - START))

# Отправка метрик
cat <<EOF | curl --data-binary @- http://localhost:9091/metrics/job/backup/instance/db-server
# HELP backup_duration_seconds Duration of backup job
# TYPE backup_duration_seconds gauge
backup_duration_seconds $DURATION
# HELP backup_status Status of backup (1=success, 0=failure)
# TYPE backup_status gauge
backup_status 1
EOF
```

**Конфигурация Prometheus для скрейпинга Pushgateway:**

```yaml
scrape_configs:
  - job_name: 'pushgateway'
    static_configs:
      - targets: ['localhost:9091']
    honor_labels: true  # Важно: сохраняет лейблы из push
```

> **Важно:** `honor_labels: true` сохраняет лейблы, отправленные вместе с метриками.

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

## Дополнительная информация

### Рекомендации по безопасности

**1. Запуск от непривилегированного пользователя:**

```bash
useradd --no-create-home --shell /bin/false pushgateway
```

**2. Ограничение сетевого доступа:**

```bash
# Разрешите доступ только с доверенных IP
ufw allow from 10.0.0.0/8 to any port 9091
```

**3. TLS через обратный прокси (Nginx):**

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

### API Pushgateway

**Отправка метрик (PUSH):**

```bash
curl -T metrics.txt http://localhost:9091/metrics/job/myjob/instance/instance1
```

**Замена метрик (PUT):**

```bash
curl -X PUT -T metrics.txt http://localhost:9091/metrics/job/myjob/instance/instance1
```

**Удаление метрик группы:**

```bash
curl -X DELETE http://localhost:9091/metrics/job/myjob/instance/instance1
```

**Удаление всех метрик для job:**

```bash
curl -X DELETE http://localhost:9091/metrics/job/myjob
```

> **См. также:** [Pushgateway API](../pushgateway.md).

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

> **См. также:** [Docker Stack](./docker_stack/overview.md).

### Устранение неполадок

**Pushgateway не запускается:**

```bash
# Проверка логов
journalctl -u pushgateway -f

# Проверка портов
ss -tnlp | grep 9091

# Проверка прав доступа
ls -la /var/lib/pushgateway/
```

**Метрики не сохраняются:**

* Проверьте `--persistence.file` путь
* Убедитесь, что есть права на запись
* Проверьте `--persistence.interval`

**Метрики дублируются:**

* Pushgateway не удаляет старые метрики автоматически
* Используйте `DELETE` API для очистки
* Настройте TTL для метрик (если поддерживается)

### Связанные темы

* [Pushgateway](../pushgateway.md) — полное руководство
* [Exporters](../Exporters/overview.md) — обзор экспортёров
* [Configuration](../configuration.md) — настройка Prometheus
* [Extensibility](../Exporters/extensibility/custom_exporters.md) — создание метрик
