# Alertmanager Installation

## Definitions

**Alertmanager** — компонент экосистемы Prometheus для обработки оповещений: дедупликация, группировка, подавление и маршрутизация. Полное руководство — [Alertmanager](../alertmanager.md).

> **См. также:** [Alertmanager](../alertmanager.md), [Rules](../rules.md), [Prometheus Server installation](./prometheus_server_installation.md).

## Basic Concepts

### Актуальная версия

| Параметр | Значение |
|---|---|
| **Последняя стабильная версия** | `0.32.0` (апрель 2026) |
| **Репозиторий** | [prometheus/alertmanager](https://github.com/prometheus/alertmanager) |

> **Важно:** Проверяйте [официальный репозиторий](https://github.com/prometheus/alertmanager/releases) для получения последних версий.

### Ключевые изменения в версии 0.32.0

* Улучшенная обработка дедупликации алертов
* Поддержка новых receiver-типов
* Исправления безопасности и производительности

### Параметры запуска

| Параметр | По умолчанию | Описание |
|---|---|---|
| `--config.file` | `alertmanager.yml` | Путь к файлу конфигурации |
| `--storage.path` | `data/` | Путь к хранилищу данных |
| `--web.listen-address` | `:9093` | Адрес для веб-интерфейса |
| `--web.external-url` | `` | Внешний URL для ссылок |
| `--web.route-prefix` | `/` | Префикс маршрута |
| `--cluster.listen-address` | `:9094` | Адрес для кластеризации |
| `--cluster.peers` | `` | Список пиров для кластера |
| `--log.level` | `info` | Уровень логирования |

## Practical Scenarios

### Установка из бинарных файлов (Linux)

**1. Создание пользователя:**

```bash
useradd --no-create-home --shell /bin/false alertmanager --comment "User to run Alertmanager"
```

**2. Загрузка и установка:**

```bash
ALERTMANAGER_VERSION="0.31.0"
cd /tmp
wget https://github.com/prometheus/alertmanager/releases/download/v${ALERTMANAGER_VERSION}/alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz
tar xvfz alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz
cd alertmanager-${ALERTMANAGER_VERSION}.linux-amd64
mv alertmanager amtool /usr/local/bin/
```

**3. Настройка каталогов и конфигурации:**

```bash
mkdir -p /etc/alertmanager
cp alertmanager.yml /etc/alertmanager/alertmanager.yml
chown -R alertmanager:alertmanager /etc/alertmanager

mkdir -p /var/lib/alertmanager
chown alertmanager:alertmanager /var/lib/alertmanager
```

**4. Создание файла с опциями запуска** (`/etc/sysconfig/alertmanager`):

```bash
cat <<EOF > /etc/sysconfig/alertmanager
OPTIONS="--config.file=/etc/alertmanager/alertmanager.yml \
--storage.path=/var/lib/alertmanager/ \
--web.listen-address=:9093 \
--cluster.listen-address="
EOF
```

> **Примечание:** Пустой `--cluster.listen-address=` отключает кластеризацию для одиночного инстанса.

**5. Создание systemd-сервиса** (`/etc/systemd/system/alertmanager.service`):

```bash
cat <<EOF > /etc/systemd/system/alertmanager.service
[Unit]
Description=Prometheus Alertmanager
Documentation=https://prometheus.io/docs/alerting/latest/alertmanager/
After=network-online.target

[Service]
User=alertmanager
Group=alertmanager
Restart=always
EnvironmentFile=/etc/sysconfig/alertmanager
ExecStart=/usr/local/bin/alertmanager \$OPTIONS
ExecReload=/bin/kill -HUP \$MAINPID
TimeoutStopSec=20s

[Install]
WantedBy=multi-user.target
EOF
```

**6. Запуск и проверка:**

```bash
systemctl daemon-reload
systemctl start alertmanager
systemctl enable alertmanager

# Проверка доступности
curl -s -o /dev/null -w "%{http_code}" http://localhost:9093
# Ожидаемый ответ: 200

# Проверка статуса
systemctl status alertmanager
```

### Проверка конфигурации

Перед применением изменений проверяйте синтаксис:

```bash
amtool check-config /etc/alertmanager/alertmanager.yml
```

### Минимальная конфигурация

**Базовый `/etc/alertmanager/alertmanager.yml`:**

```yaml
global:
  resolve_timeout: 5m
  smtp_smarthost: 'smtp.example.com:587'
  smtp_from: 'alertmanager@example.com'

route:
  group_by: ['alertname', 'job']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 12h
  receiver: 'default-receiver'

receivers:
  - name: 'default-receiver'
    email_configs:
      - to: 'team@example.com'
        send_resolved: true

inhibit_rules:
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['alertname', 'instance']
```

> **См. также:** [Alertmanager — полная конфигурация](../alertmanager.md).

### Установка через Docker

```bash
docker run -d \
  --name alertmanager \
  -p 9093:9093 \
  -v /etc/alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml \
  -v alertmanager-data:/alertmanager \
  prom/alertmanager:v0.32.0 \
  --config.file=/etc/alertmanager/alertmanager.yml \
  --storage.path=/alertmanager
```

> **См. также:** [Docker Stack](./docker_stack/overview.md).

## Additional Information

### Security Recommendations

**1. Запуск от непривилегированного пользователя:**

```bash
useradd --no-create-home --shell /bin/false alertmanager
```

**2. Ограничение сетевого доступа:**

```bash
# Разрешите доступ только с доверенных IP
ufw allow from 10.0.0.0/8 to any port 9093
```

**3. TLS через обратный прокси (Nginx):**

```nginx
server {
    listen 443 ssl;
    server_name alertmanager.example.com;

    ssl_certificate /etc/ssl/certs/alertmanager.crt;
    ssl_certificate_key /etc/ssl/private/alertmanager.key;

    location / {
        proxy_pass http://localhost:9093;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Alertmanager Clustering

Для высокой доступности разверните несколько инстансов в режиме кластера:

```bash
# Инстанс 1
--cluster.listen-address=:9094 \
--cluster.peers=alertmanager-1:9094,alertmanager-2:9094

# Инстанс 2
--cluster.listen-address=:9094 \
--cluster.peers=alertmanager-1:9094,alertmanager-2:9094
```

> **См. также:** [Alertmanager HA](../alertmanager.md#кластеризация).

### Prometheus Integration

**Добавьте в `prometheus.yml`:**

```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - 'localhost:9093'
```

### Troubleshooting

**Alertmanager не запускается:**

```bash
# Проверка логов
journalctl -u alertmanager -f

# Проверка портов
ss -tnlp | grep 9093

# Проверка конфигурации
amtool check-config /etc/alertmanager/alertmanager.yml
```

**Алерты не отправляются:**

* Проверьте маршрут в конфигурации
* Убедитесь, что receiver настроен правильно
* Проверьте логи на ошибки отправки

> **См. также:** [Rules и алертинг](../rules.md).
