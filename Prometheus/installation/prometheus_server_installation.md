# Установка Prometheus Server

## Определения

**Prometheus Server** — центральный компонент системы мониторинга, отвечающий за:

* Сбор метрик (scraping) с целевых сервисов
* Хранение данных во встроенной TSDB (Time Series Database)
* Обработку запросов на языке PromQL
* Выполнение правил алертинга и записи (recording rules)

> **См. также:** [Архитектура Prometheus](./overview.md), [TSDB](../concepts/tsdb.md).

## Основные концепции

### Актуальная версия

| Параметр | Значение |
|---|---|
| **Последняя стабильная версия** | `3.10.0` |
| **Репозиторий** | [prometheus/prometheus](https://github.com/prometheus/prometheus) |

> **Важно:** Проверяйте [официальный репозиторий](https://github.com/prometheus/prometheus/releases) для получения последних версий.

### Ключевые изменения в версии 3.10.0

* **Docker:** Добавлен distroless-вариант образа (`-distroless`) с UID/GID 65532
* **PromQL:** Модификаторы `fill()` / `fill_left()` / `fill_right()` для бинарных операций
* **API:** Спецификация OpenAPI 3.2 по адресу `/api/v1/openapi.yaml`
* **Service Discovery:** Поддержка MSK Role для AWS
* **Производительность:** Улучшения в PromQL, OTLP-конвертации и TSDB

## Практические сценарии

### Установка из бинарных файлов (Linux)

**1. Создание пользователя:**

```bash
useradd --no-create-home --shell /bin/false prometheus --comment "Prometheus server user"
```

**2. Загрузка и установка:**

```bash
PROMETHEUS_VERSION="3.10.0"
cd /tmp
wget https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz
tar xvfz prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz
cd prometheus-${PROMETHEUS_VERSION}.linux-amd64
mv prometheus promtool /usr/local/bin/
```

**3. Настройка каталогов и конфигурации:**

```bash
mkdir -p /etc/prometheus
cp prometheus.yml /etc/prometheus/
chown -R prometheus:prometheus /etc/prometheus

mkdir -p /var/lib/prometheus
chown prometheus:prometheus /var/lib/prometheus
```

**4. Создание файла с опциями запуска** (`/etc/sysconfig/prometheus`):

```bash
cat <<EOF > /etc/sysconfig/prometheus
OPTIONS="--config.file=/etc/prometheus/prometheus.yml \
--storage.tsdb.path=/var/lib/prometheus/ \
--storage.tsdb.retention.time=15d \
--web.listen-address=:9090"
EOF
```

**5. Создание systemd-сервиса** (`/etc/systemd/system/prometheus.service`):

```bash
cat <<EOF > /etc/systemd/system/prometheus.service
[Unit]
Description=Prometheus Server
Documentation=https://github.com/prometheus/prometheus
After=network-online.target

[Service]
Restart=always
User=prometheus
Group=prometheus
EnvironmentFile=/etc/sysconfig/prometheus
ExecStart=/usr/local/bin/prometheus \$OPTIONS
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
systemctl start prometheus
systemctl enable prometheus

# Проверка доступности
curl -s -o /dev/null -w "%{http_code}" http://localhost:9090/graph
# Ожидаемый ответ: 200

# Проверка статуса
systemctl status prometheus
```

### Проверка конфигурации

Перед перезапуском всегда проверяйте синтаксис конфигурации:

```bash
promtool check config /etc/prometheus/prometheus.yml
```

> **См. также:** [promtool](../promtool_and_best_practices.md).

### Установка через Docker

```bash
docker run -d \
  --name prometheus \
  -p 9090:9090 \
  -v /etc/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml \
  -v prometheus-data:/prometheus \
  prom/prometheus:v3.10.0 \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus/ \
  --storage.tsdb.retention.time=15d
```

> **См. также:** [Docker Stack](./docker_stack/overview.md).

### Параметры запуска

| Параметр | По умолчанию | Описание |
|---|---|---|
| `--config.file` | `prometheus.yml` | Путь к файлу конфигурации |
| `--storage.tsdb.path` | `data/` | Путь к хранилищу данных |
| `--storage.tsdb.retention.time` | `15d` | Срок хранения данных |
| `--storage.tsdb.retention.size` | `0` | Макс. размер хранилища (0 = без ограничений) |
| `--web.listen-address` | `:9090` | Адрес для веб-интерфейса |
| `--web.console.templates` | `consoles/` | Путь к шаблонам консолей |
| `--web.console.libraries` | `console_libraries/` | Путь к библиотекам консолей |
| `--query.timeout` | `2m` | Таймаут выполнения запросов |
| `--log.level` | `info` | Уровень логирования |

> **См. также:** [Configuration](../configuration.md).

## Дополнительная информация

### Рекомендации по безопасности

**1. Запуск от непривилегированного пользователя:**

```bash
# Никогда не запускайте Prometheus от root
useradd --no-create-home --shell /bin/false prometheus
```

**2. Ограничение сетевого доступа:**

```bash
# Разрешите доступ только с доверенных IP
ufw allow from 10.0.0.0/8 to any port 9090
ufw allow from 192.168.1.0/24 to any port 9090
```

**3. TLS через обратный прокси (Nginx):**

```nginx
server {
    listen 443 ssl;
    server_name prometheus.example.com;

    ssl_certificate /etc/ssl/certs/prometheus.crt;
    ssl_certificate_key /etc/ssl/private/prometheus.key;

    location / {
        proxy_pass http://localhost:9090;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Мониторинг самого Prometheus (self-monitoring)

Prometheus автоматически собирает метрики о своей работе. Для добавления в конфигурацию:

```yaml
scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
```

**Ключевые метрики для отслеживания:**

* `prometheus_tsdb_storage_blocks_bytes` — размер TSDB на диске
* `prometheus_tsdb_head_series` — количество активных временных рядов
* `prometheus_http_requests_total` — HTTP-запросы к API
* `process_resident_memory_bytes` — потребление памяти
* `rate(prometheus_tsdb_head_samples_appended_total[5m])` — скорость записи

> **См. также:** [TSDB](../concepts/tsdb.md), [Rules](../rules.md).

### Устранение неполадок

**Prometheus не запускается:**

```bash
# Проверка логов
journalctl -u prometheus -f

# Проверка портов
ss -tnlp | grep 9090

# Проверка прав доступа
ls -la /var/lib/prometheus/
ls -la /etc/prometheus/
```

**Высокое потребление памяти:**

* Уменьшите `--storage.tsdb.retention.time`
* Проверьте кардинальность метрик: `count({__name__=~".+"})`
* Используйте [remote_write](../scaling/remote_read_write.md) для внешних хранилищ

> **См. также:** [Лейблы и кардинальность](../concepts/labels_and_cardinality.md).

### Связанные темы

* [Configuration](../configuration.md) — детальная настройка
* [TSDB](../concepts/tsdb.md) — устройство хранилища
* [PromQL](../concepts/promql.md) — язык запросов
* [Rules](../rules.md) — правила алертинга
* [Scaling](../scaling/overview.md) — масштабирование
* [Exporters](../Exporters/overview.md) — сбор метрик
