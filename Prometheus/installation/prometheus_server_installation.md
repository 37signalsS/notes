# Установка Prometheus Server

## Определения

**Prometheus Server** — центральный компонент системы мониторинга, отвечающий за сбор (scraping) метрик, их хранение во встроенной базе данных временных рядов (TSDB), выполнение запросов на языке PromQL, а также обработку правил записи и оповещения (alerting).

> **См. также:** [Архитектура Prometheus](../overview.md), [Внутреннее устройство TSDB](../concepts/tsdb.md), [Конфигурация](../configuration.md).

## Основные концепции

### Надежность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| **Актуальность** | **10** | Соответствует версии v3.13.2 (июль 2026) |
| **Полнота** | **10** | Охвачены бинарная установка, Docker и настройки безопасности |
| **Авторитетность** | **10** | Является основным источником по установке сервера |

### Актуальная версия

| Параметр | Значение |
| :--- | :--- |
| **Последняя стабильная версия** | `3.13.2` (29 июля 2026) |
| **Статус ветки** | LTS (Long Term Support) |
| **Репозиторий** | [prometheus/prometheus](https://github.com/prometheus/prometheus) |

> **Важно:** Всегда проверяйте [GitHub Releases](https://github.com/prometheus/prometheus/releases) для получения последних патчей безопасности.

### Ключевые изменения в ветке 3.13.x

*   **Security:** Исправлены критические уязвимости (CVE-2026-44990, CVE-2026-56852).
*   **Производительность:** Исправлены падения (SIGBUS) при переполнении диска с TSDB.
*   **Web UI:** Обновленные инструменты поиска имен метрик и значений лейблов.
*   **Service Discovery:** Улучшенная фильтрация для AWS RDS и MSK.
*   **API:** Переход на SHA-256 для токенов пагинации правил.

## Практические сценарии

### Установка из бинарных файлов (Linux)

Этот метод обеспечивает максимальный контроль над процессом и рекомендуется для production-сред на выделенных серверах.

**1. Подготовка системы:**

Создайте системного пользователя и необходимые директории.

```bash
# Создание пользователя без прав входа
sudo useradd --no-create-home --shell /bin/false prometheus

# Создание директорий
sudo mkdir -p /etc/prometheus /var/lib/prometheus
```

**2. Загрузка и верификация:**

```bash
PROMETHEUS_VERSION="3.13.2"
cd /tmp

# Загрузка архива и контрольных сумм
wget https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz
wget https://github.com/prometheus/prometheus/releases/download/v${PROMETHEUS_VERSION}/sha256sums.txt

# Проверка целостности
sha256sum --check --ignore-missing sha256sums.txt
# Вывод должен быть: prometheus-3.13.2.linux-amd64.tar.gz: OK
```

**3. Размещение файлов:**

```bash
tar xvfz prometheus-${PROMETHEUS_VERSION}.linux-amd64.tar.gz
cd prometheus-${PROMETHEUS_VERSION}.linux-amd64

# Копирование бинарных файлов
sudo mv prometheus promtool /usr/local/bin/

# Копирование консольных библиотек и примеров
sudo cp -r consoles console_libraries /etc/prometheus/
sudo cp prometheus.yml /etc/prometheus/

# Установка прав
sudo chown -R prometheus:prometheus /etc/prometheus /var/lib/prometheus
sudo chown prometheus:prometheus /usr/local/bin/prometheus /usr/local/bin/promtool
```

**4. Настройка systemd с элементами hardening:**

Создайте файл `/etc/systemd/system/prometheus.service`:

```ini
[Unit]
Description=Prometheus Server
Documentation=https://github.com/prometheus/prometheus
After=network-online.target

[Service]
User=prometheus
Group=prometheus
Type=simple
Restart=always
ExecStart=/usr/local/bin/prometheus \
    --config.file=/etc/prometheus/prometheus.yml \
    --storage.tsdb.path=/var/lib/prometheus/ \
    --storage.tsdb.retention.time=15d \
    --web.enable-lifecycle \
    --web.listen-address=:9090

# Ограничение прав процесса (Hardening)
ProtectSystem=full
ProtectHome=true
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**5. Запуск:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now prometheus

# Проверка статуса
systemctl status prometheus # → Active: active (running)
```

### Установка через Docker

Используйте официальный образ. Для сохранения данных и конфигурации используйте volumes.

```bash
docker run -d \
  --name prometheus \
  -p 9090:9090 \
  -v /path/to/prometheus.yml:/etc/prometheus/prometheus.yml \
  -v prometheus-data:/prometheus \
  prom/prometheus:v3.13.2 \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus \
  --web.console.libraries=/usr/share/prometheus/console_libraries \
  --web.console.templates=/usr/share/prometheus/consoles
```

> **Примечание:** Образ использует пользователя с UID `65532`. Убедитесь, что права на примонтированные директории позволяют запись этому пользователю.

### Настройка безопасности (Native Basic Auth & TLS)

Начиная с версии 2.24+, Prometheus поддерживает встроенную аутентификацию.

**1. Создание файла `web-config.yml`:**

```yaml
basic_auth_users:
  admin: "$2b$12$hN3qMZZP4zWlYhX.Q.W.Ze9rYgWJ9g2U1c2G5rX1b.x.x.x.x.x.x" # bcrypt hash

tls_server_config:
  cert_file: /etc/prometheus/certs/server.crt
  key_file: /etc/prometheus/certs/server.key
```

**2. Запуск с флагом конфигурации:**

Добавьте `--web.config.file=/etc/prometheus/web-config.yml` в параметры запуска Prometheus.

## Дополнительная информация

### Проверка конфигурации (promtool)

Всегда проверяйте файлы перед применением:

```bash
# Проверка основного файла
promtool check config /etc/prometheus/prometheus.yml # → SUCCESS

# Проверка правил
promtool check rules /etc/prometheus/alert_rules.yml
```

### Мониторинг самого Prometheus

Добавьте задачу сбора в `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']
```

**Ключевые метрики:**
* `prometheus_tsdb_head_series` — количество активных временных рядов в памяти.
* `prometheus_tsdb_storage_blocks_bytes` — общий объем TSDB на диске.
* `rate(prometheus_tsdb_head_samples_appended_total[5m])` — интенсивность записи новых семплов.

### Устранение неполадок

*   **Ошибка `panic: runtime error: index out of range`**: часто указывает на повреждение сегментов WAL. Попробуйте переместить содержимое `wal/` и запустить сервис.
*   **Таймауты при скрейпинге**: проверьте `up` метрику и сетевую связность до таргетов.
*   **Превышение памяти**: проверьте кардинальность метрик через Web UI (Status -> TSDB Status).

### См. также
*   [Конфигурация prometheus.yml](../configuration.md)
*   [Безопасность Prometheus](../security.md)
*   [Масштабирование и Remote Write](../scaling/overview.md)
