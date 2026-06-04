# Установка Pushgateway

## Определение

**Pushgateway** — компонент экосистемы Prometheus, предназначенный для приёма метрик от кратковременных (ephemeral) и пакетных (batch) задач. Он принимает данные по HTTP и хранит их до момента сбора сервером мониторинга.

> **Общее руководство по использованию:** [Pushgateway](../pushgateway.md).

## Основные концепции

### Актуальная версия

| Параметр | Значение |
|---|---|
| **Последняя стабильная версия** | `1.11.2` (2025-10-30) |
| **Репозиторий** | [prometheus/pushgateway](https://github.com/prometheus/pushgateway) |

> **Когда использовать:** подробный разбор сценариев и антипаттернов приведен в разделе [Pushgateway — когда использовать](../pushgateway.md#когда-использовать).

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

**3. Настройка параметров запуска** (`/etc/sysconfig/pushgateway`):

```bash
cat <<EOF > /etc/sysconfig/pushgateway
OPTIONS="--web.listen-address=:9091 \
--persistence.file=/var/lib/pushgateway/metrics.store \
--persistence.interval=5m"
EOF
```

**4. Подготовка каталогов:**

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

[Install]
WantedBy=multi-user.target
EOF
```

**6. Запуск сервиса:**

```bash
systemctl daemon-reload
systemctl start pushgateway
systemctl enable pushgateway

# Проверка работоспособности
curl -s -o /dev/null -w "%{http_code}" http://localhost:9091/-/healthy
```

### Развёртывание через Docker

```bash
docker run -d \
  --name pushgateway \
  -p 9091:9091 \
  -v /var/lib/pushgateway:/data \
  prom/pushgateway:v1.11.2 \
  --persistence.file=/data/metrics.store \
  --persistence.interval=5m
```

### Настройка сбора в Prometheus

Добавьте следующее задание в `scrape_configs`:

```yaml
scrape_configs:
  - job_name: 'pushgateway'
    honor_labels: true
    static_configs:
      - targets: ['localhost:9091']
```

## Дополнительная информация

### Безопасность и защита доступа

**Ограничение сетевого доступа:**
Рекомендуется разрешать доступ к порту 9091 только с доверенных IP-адресов.

```bash
ufw allow from 10.0.0.0/8 to any port 9091
```

**Настройка TLS (Nginx Reverse Proxy):**

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

### Краткая справка по API

Для полноценного управления используйте [Pushgateway HTTP API](../pushgateway.md#http-api).

- **Отправка:** `curl --data-binary @- http://localhost:9091/metrics/job/my_job`
- **Удаление:** `curl -X DELETE http://localhost:9091/metrics/job/my_job`

### Устранение неполадок

| Проблема | Решение |
|---|---|
| Сервис не запускается | Проверьте логи: `journalctl -u pushgateway -f` |
| Ошибки записи данных | Проверьте права на директорию `/var/lib/pushgateway` |
| Порт занят | Проверьте активность порта: `ss -tnlp | grep 9091` |
| Метрики исчезают после рестарта | Убедитесь, что настроен флаг `--persistence.file` |

> **См. также:** [Устранение неполадок в Prometheus](../overview.md#устранение-неполадок).
