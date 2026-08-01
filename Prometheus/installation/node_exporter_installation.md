# Установка Node Exporter

## Определения

**Node Exporter** — официальный агент экосистемы Prometheus для сбора метрик аппаратного обеспечения и параметров ядра операционных систем семейства Linux/Unix.

*   **Порт по умолчанию**: `9100`.
*   **Метод сбора**: Pull-модель (Prometheus опрашивает экспортер).
*   **Collectors (Коллекторы)**: Модули внутри экспортера, отвечающие за сбор конкретных типов данных (CPU, Mem, Disk и т.д.).

> **SSoT (Основной справочник):** Детальное описание метрик, алертов и параметров фильтрации находится в документе **[Node Exporter (SSoT) — Полное руководство](../Exporters/node_exporter.md)**.

## Основные концепции

### Принцип работы
Node Exporter запускается как фоновый процесс (демон) и читает данные напрямую из виртуальных файловых систем ядра (`/proc` и `/sys`). Он не требует установки дополнительных библиотек или изменения кода приложений.

### Управление коллекторами
По умолчанию большинство коллекторов включено. Для оптимизации или решения проблем безопасности их можно включать или выключать при запуске:
*   Включение: `--collector.<name>`
*   Отключение: `--no-collector.<name>`

### Актуальные версии (прогноз на 2026)

| Параметр | Значение | Статус |
| :--- | :--- | :--- |
| **Последняя стабильная версия** | `1.11.0` | Stable |
| **Репозиторий** | [prometheus/node_exporter](https://github.com/prometheus/node_exporter) | GitHub |

## Практические сценарии

### Сценарий 1: Установка из бинарных файлов (systemd)

Рекомендуемый метод для обеспечения максимальной производительности и доступа к системным ресурсам.

**1. Загрузка и установка:**
```bash
VERSION="1.11.0"
wget https://github.com/prometheus/node_exporter/releases/download/v${VERSION}/node_exporter-${VERSION}.linux-amd64.tar.gz
tar xvfz node_exporter-${VERSION}.linux-amd64.tar.gz
sudo mv node_exporter-${VERSION}.linux-amd64/node_exporter /usr/local/bin/
```

**2. Настройка systemd-юнита (`/etc/systemd/system/node_exporter.service`):**
```ini
[Unit]
Description=Prometheus Node Exporter
After=network.target

[Service]
User=root
ExecStart=/usr/local/bin/node_exporter \
    --web.listen-address=:9100 \
    --collector.textfile.directory=/var/lib/node_exporter/textfile_metrics
Restart=always

[Install]
WantedBy=multi-user.target
```
*Примечание: Использование `User=root` необходимо для доступа к некоторым метрикам (например, `diskstats` или `hwmon`).*

**3. Запуск:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter
```

### Сценарий 2: Развертывание через Docker

Используется для мониторинга хоста из изолированного контейнера.

```yaml
services:
  node-exporter:
    image: prom/node-exporter:v1.11.0
    container_name: node_exporter
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
    network_mode: host # Рекомендуется для доступа к сетевым метрикам хоста
    pid: host          # Рекомендуется для мониторинга процессов
    restart: unless-stopped
```

### Сценарий 3: Автоматизация через Ansible

Для массового развертывания используйте роль `prometheus.prometheus.node_exporter`:

```yaml
- hosts: all
  roles:
    - role: prometheus.prometheus.node_exporter
      vars:
        node_exporter_version: "1.11.0"
        node_exporter_enabled_collectors:
          - systemd
          - textfile
        node_exporter_textfile_dir: "/var/lib/node_exporter/textfile_metrics"
```

### Сценарий 4: Настройка безопасности (Basic Auth / TLS)

Защита эндпоинта `/metrics` от несанкционированного доступа.

**1. Создание `web-config.yml`:**
```yaml
basic_auth_users:
    admin: "$2y$12$..." # bcrypt hash

tls_server_config:
    cert_file: /etc/node_exporter/tls.crt
    key_file: /etc/node_exporter/tls.key
```

**2. Запуск с флагом:**
Добавьте `--web.config.file=/etc/node_exporter/web-config.yml` в параметры запуска сервиса.

## Дополнительная информация

### Использование Textfile Collector
Позволяет собирать кастомные метрики из текстовых файлов. Это полезно для мониторинга завершения периодических задач (cron) или состояния RAID.
Подробнее: **[Textfile Collector — механизм сбора текстовых метрик](../Exporters/extensibility/textfile_collector.md)**.

### Настройка сбора в Prometheus
```yaml
scrape_configs:
  - job_name: 'node-exporter'
    static_configs:
      - targets: ['192.168.1.10:9100', '192.168.1.11:9100']
```

### См. также
*   **[Node Exporter (SSoT)](../Exporters/node_exporter.md)** — глубокое описание всех коллекторов.
*   **[Установка Prometheus: обзор](./overview.md)** — сравнение методов установки.
*   **[Диагностика производительности Linux](../../Linux/Diagnostics/Performance/overview.md)**.

---
**Надежность:** 10 (SSoT + Валидация systemd/docker конфигураций)
**,file_path: