# Установка Node Exporter

## Определения

**Node Exporter** — экспортер для сбора метрик с аппаратного и программного обеспечения хостовой системы:
* CPU, память, диск, сеть
* Системные метрики (процессы, пользователи, boot time)
* Метрики файловой системы
* Сетевые интерфейсы и соединения

> **См. также:** [Node Exporter](../Exporters/node_exporter.md), [Exporters overview](../Exporters/overview.md).

## Основные концепции

### Актуальная версия

| Параметр | Значение |
|---|---|
| **Последняя стабильная версия** | `1.10.2` |
| **Дата выпуска** | Октябрь 2025 |
| **Репозиторий** | [prometheus/node_exporter](https://github.com/prometheus/node_exporter) |

### Архитектура

Node Exporter работает по принципу pull-модели:
1. Экспортер собирает метрики с хоста
2. Предоставляет их по HTTP на порту 9100
3. Prometheus опрашивает эндпоинт `/metrics`
4. Метрики сохраняются в TSDB

> **См. также:** [TSDB](../concepts/tsdb.md).

## Практические сценарии

### Установка из бинарных файлов (Linux)

**1. Загрузка и установка:**

```bash
NODE_EXPORTER_VERSION="1.10.2"
cd /tmp
wget https://github.com/prometheus/node_exporter/releases/download/v${NODE_EXPORTER_VERSION}/node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
tar xvfz node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64.tar.gz
mv node_exporter-${NODE_EXPORTER_VERSION}.linux-amd64/node_exporter /usr/local/bin/
```

**2. Создание файла с опциями запуска** (`/etc/sysconfig/node_exporter`):

```bash
cat <<EOF > /etc/sysconfig/node_exporter
OPTIONS="--web.listen-address=:9100 \
--log.level=info"
EOF
```

> **Примечание:** Для сбора всех метрик `node_exporter` рекомендуется запускать от `root`.

**3. Создание systemd-сервиса** (`/etc/systemd/system/node_exporter.service`):

```bash
cat <<EOF > /etc/systemd/system/node_exporter.service
[Unit]
Description=Prometheus Node exporter for machine metrics
Documentation=https://github.com/prometheus/node_exporter
After=network-online.target

[Service]
Restart=always
User=root
EnvironmentFile=/etc/sysconfig/node_exporter
ExecStart=/usr/local/bin/node_exporter \$OPTIONS
ExecReload=/bin/kill -HUP \$MAINPID
TimeoutStopSec=20s
SendSIGKILL=no

[Install]
WantedBy=multi-user.target
EOF
```

**4. Запуск и проверка:**

```bash
systemctl daemon-reload
systemctl start node_exporter
systemctl enable node_exporter

# Проверка доступности
curl -s -o /dev/null -w "%{http_code}" http://localhost:9100/metrics
# Ожидаемый ответ: 200

# Проверка статуса
systemctl status node_exporter
```

### Интеграция с Prometheus

**Добавьте в `prometheus.yml`:**

```yaml
scrape_configs:
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['localhost:9100']
        labels:
          instance: 'my-server'
          environment: 'production'
```

**Для нескольких хостов:**

```yaml
scrape_configs:
  - job_name: 'node-exporter'
    static_configs:
      - targets:
          - 'server1.example.com:9100'
          - 'server2.example.com:9100'
          - 'server3.example.com:9100'
```

> **См. также:** [Configuration](../configuration.md).

### Коллекторы

Node Exporter использует коллекторы для сбора метрик по категориям.

**Включенные по умолчанию:**

* `cpu` — метрики процессора
* `diskstats` — статистика дисков
* `filesystem` — файловые системы
* `loadavg` — средняя загрузка
* `meminfo` — информация о памяти
* `netdev` — сетевые устройства
* `stat` — системная статистика
* `time` — системное время

**Опциональные коллекторы:**

```bash
OPTIONS="--web.listen-address=:9100 \
--collector.systemd \
--collector.processes \
--collector.logind \
--collector.docker"
```

**Полный список коллекторов:**

```bash
node_exporter --help | grep collector
```

> **См. также:** [Node Exporter — коллекторы](../Exporters/node_exporter.md#коллекторы).

### Параметры запуска

| Параметр | По умолчанию | Описание |
|---|---|---|
| `--web.listen-address` | `:9100` | Адрес для веб-интерфейса |
| `--web.telemetry-path` | `/metrics` | Путь для метрик |
| `--collector.<name>` | varies | Включить/выключить коллектор |
| `--path.procfs` | `/proc` | Путь к procfs |
| `--path.sysfs` | `/sys` | Путь к sysfs |
| `--path.rootfs` | `/` | Путь к rootfs |
| `--log.level` | `info` | Уровень логирования |

## Дополнительная информация

### Рекомендации по безопасности

**1. Ограничение сетевого доступа:**

```bash
# Разрешите доступ только с доверенных IP
ufw allow from 10.0.0.0/8 to any port 9100
ufw allow from 192.168.1.0/24 to any port 9100
```

**2. TLS через reverse proxy:**

```nginx
server {
    listen 443 ssl;
    server_name node-exporter.example.com;

    ssl_certificate /etc/ssl/certs/node-exporter.crt;
    ssl_certificate_key /etc/ssl/private/node-exporter.key;

    location / {
        proxy_pass http://localhost:9100;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

**3. Запуск в контейнере (ограничение прав):**

```bash
docker run -d \
  --name node-exporter \
  --pid=host \
  --net=host \
  --volume=/:/rootfs:ro \
  --volume=/proc:/proc:ro \
  --volume=/sys:/sys:ro \
  prom/node-exporter:v1.10.2 \
  --path.rootfs=/rootfs
```

### Установка через Docker

```bash
docker run -d \
  --name node-exporter \
  --pid=host \
  --net=host \
  -p 9100:9100 \
  --volume=/:/rootfs:ro \
  --volume=/proc:/proc:ro \
  --volume=/sys:/sys:ro \
  prom/node-exporter:v1.10.2 \
  --path.rootfs=/rootfs
```

> **Примечание:** Требуются права `--pid=host` и `--net=host` для доступа к хост-метрикам.

### Отключение коллекторов

Для отключения неиспользуемых коллекторов (уменьшение кардинальности):

```bash
OPTIONS="--web.listen-address=:9100 \
--no-collector.arp \
--no-collector.bonding \
--no-collector.infiniband \
--no-collector.ipvs"
```

> **См. также:** [Лейблы и кардинальность](../concepts/labels_and_cardinality.md).

### Устранение неполадок

**Node Exporter не запускается:**

```bash
# Проверка логов
journalctl -u node_exporter -f

# Проверка портов
ss -tnlp | grep 9100

# Проверка прав доступа
ls -la /proc /sys
```

**Метрики не собираются:**

* Проверьте доступность порта 9100
* Убедитесь, что Prometheus может достичь хоста
* Проверьте логи на ошибки

**Недостаточно метрик:**

* Проверьте включенные коллекторы
* Убедитесь, что у процесса есть права доступа
* Проверьте пути к procfs/sysfs

### Связанные темы

* [Node Exporter](../Exporters/node_exporter.md) — полное руководство
* [Exporters overview](../Exporters/overview.md) — обзор экспортёров
* [Prometheus Server](./prometheus_server_installation.md) — интеграция
* [Configuration](../configuration.md) — настройка Prometheus
* [Docker Stack](./docker_stack/overview.md) — установка в Docker
