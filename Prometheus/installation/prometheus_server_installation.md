# Установка Prometheus Server

## Определения

**Prometheus Server** — центральный компонент системы мониторинга, отвечающий за сбор (scraping) метрик, их хранение во встроенной базе данных временных рядов (TSDB), выполнение запросов на языке PromQL, а также обработку правил записи и оповещения (alerting).

> **См. также:** **[Архитектура Prometheus](../overview.md)**, **[Внутреннее устройство TSDB](../concepts/tsdb.md)**, **[Конфигурация](../configuration.md)**.

## Основные концепции

### Нововведения и изменения в Prometheus 3.x

Начиная с версии 3.0, архитектура сервера претерпела значительные изменения, направленные на производительность и совместимость с OpenTelemetry:
*   **Нативная поддержка OTLP**: Возможность принимать метрики напрямую от OpenTelemetry SDK/Collectors без промежуточных экспортеров через эндпоинты `/api/v1/otlp/v1/metrics`.
*   **Сжатие WAL (Write-Ahead Log)**: Новый механизм сжатия данных до их записи в блоки TSDB, что снижает нагрузку на дисковую подсистему.
*   **Поддержка UTF-8**: Имена метрик теперь могут содержать расширенный набор символов (соответствие OpenMetrics).
*   **Улучшенная диагностика**: Web UI включает расширенный раздел профилирования и анализа кардинальности «на лету».

### Безопасность и отказоустойчивость

*   **API Management**: Флаг `--web.enable-lifecycle` включает эндпоинты для управления состоянием (например, `/-/reload` для горячей перезагрузки конфигурации без перезапуска).
*   **Hardening (Укрепление)**: Рекомендуется запуск процесса с минимально возможными правами в ОС, используя механизмы изоляции `systemd`.

## Практические сценарии

### Сценарий 1: Установка из бинарных файлов (Linux/systemd)

Этот метод обеспечивает максимальный контроль над производительностью и рекомендуется для Production-сред.

**1. Подготовка системы:**
Создайте системного пользователя без домашней директории и прав входа, а также необходимые каталоги.
```bash
# Создание пользователя
sudo useradd --no-create-home --shell /bin/false prometheus

# Создание директорий для конфигурации и данных TSDB
sudo mkdir -p /etc/prometheus /var/lib/prometheus
```

**2. Загрузка и верификация (v3.13.2):**
```bash
PROMETHEUS_VERSION="3.13.2"
cd /tmp

# Загрузка архива и файла контрольных сумм
wget https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz
wget https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/sha256sums.txt

# Проверка целостности загруженного файла
sha256sum --check --ignore-missing sha256sums.txt
# → prometheus-3.13.2.linux-amd64.tar.gz: OK
```

**3. Размещение исполняемых и конфигурационных файлов:**
```bash
tar xvfz prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz
cd prometheus-${PROMETHEUS_VERSION}.linux-amd64

# Перемещение бинарных файлов в стандартный путь выполнения
sudo mv prometheus promtool /usr/local/bin/

# Копирование консольных библиотек и шаблонов (необходимы для Web UI)
sudo cp -r consoles console_libraries /etc/prometheus/
sudo cp prometheus.yml /etc/prometheus/

# Установка прав владения (рекурсивно для директории данных)
sudo chown -R prometheus:prometheus /etc/prometheus /var/lib/prometheus
sudo chown prometheus:prometheus /usr/local/bin/prometheus /usr/local/bin/promtool
# → Files placed and permissions updated
```

**4. Настройка systemd-сервиса с элементами Hardening:**
Создайте `/etc/systemd/system/prometheus.service`:
```ini
[Unit]
Description=Prometheus Server
Documentation=https://prometheus.io/docs/introduction/overview/
After=network-online.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/prometheus \
    --config.file=/etc/prometheus/prometheus.yml \
    --storage.tsdb.path=/var/lib/prometheus/ \
    --storage.tsdb.retention.time=15d \
    --storage.tsdb.wal-compression \
    --web.enable-lifecycle \
    --web.enable-otlp-receiver \
    --web.listen-address=:9090

# Ограничение прав процесса
Restart=always
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**5. Запуск:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now prometheus
# Проверка статуса
systemctl is-active prometheus
# → active
```

### Сценарий 2: Установка через Docker / Podman

Используйте официальный образ. Рекомендуется использовать конкретные теги версий вместо `latest`.

```bash
docker run -d \
  --name prometheus \
  -p 9090:9090 \
  -v /path/to/prometheus.yml:/etc/prometheus/prometheus.yml:ro \
  -v prometheus_data:/prometheus \
  prom/prometheus:v3.13.2 \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus \
  --storage.tsdb.wal-compression \
  --web.enable-lifecycle
# → Container started with ID ...
```

### Сценарий 3: Настройка безопасности (Native Basic Auth & TLS)

Использование встроенных механизмов защиты без внешнего прокси.

**1. Создание файла `web-config.yml`:**
```yaml
basic_auth_users:
  admin: "$2y$12$hN3qMZZP4zWlYhX.Q.W.Ze9rYgWJ9g2U1c2G5rX1b.x.x.x.x.x.x" # bcrypt hash

tls_server_config:
  cert_file: /etc/prometheus/certs/server.crt
  key_file: /etc/prometheus/certs/server.key
```

**2. Запуск:** Добавьте флаг `--web.config.file=/etc/prometheus/web-config.yml` в `ExecStart` или команду запуска контейнера.

## Дополнительная информация

### Использование promtool (Диагностика)

Инструмент `promtool` необходим для обслуживания и проверки системы:
*   **Валидация конфига**: `promtool check config /etc/prometheus/prometheus.yml` (# → SUCCESS).
*   **Анализ TSDB**: `promtool tsdb analyze /var/lib/prometheus/` (позволяет выявить метрики с наибольшей кардинальностью).
*   **Проверка правил**: `promtool check rules /etc/prometheus/alert_rules.yml`.

### Мониторинг самого сервера

Критически важно собирать метрики самого Prometheus для контроля здоровья TSDB.
```yaml
scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
```
**Ключевые метрики для алертинга:**
*   `prometheus_tsdb_head_series`: Количество активных временных рядов в памяти.
*   `prometheus_tsdb_storage_blocks_bytes`: Общий объем хранилища на диске.
*   `rate(prometheus_tsdb_head_samples_appended_total[5m])`: Скорость записи новых данных.

### Устранение неполадок

*   **Повреждение WAL (Write-Ahead Log)**: При ошибках `panic: runtime error: index out of range` на старте — проверьте целостность сегментов. В крайнем случае удалите содержимое директории `wal/` (приведет к потере последних 2-х часов данных, не записанных в блоки).
*   **Таймауты скрейпинга**: Проверьте метрику `up == 0`. Если таргет доступен, увеличьте `scrape_timeout` в конфигурации.
*   **Переполнение памяти**: Используйте раздел **Status -> TSDB Status** в Web UI для идентификации лейблов, вызывающих взрывной рост кардинальности.

### См. также
*   **[Конфигурация prometheus.yml](../configuration.md)**
*   **[Безопасность Prometheus](../security.md)**
*   **[Масштабирование и Remote Write](../scaling/overview.md)**
*   **[Внутреннее устройство TSDB](../concepts/tsdb.md)**
