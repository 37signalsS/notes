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
По умолчанию большинство коллекторов включено. Для оптимизации нагрузки на систему и уменьшения объема хранимых данных (cardinality) их можно фильтровать при запуске:
*   **Включение:** `--collector.<name>`
*   **Отключение:** `--no-collector.<name>`
*   **Фильтрация в Prometheus:** Можно запрашивать только часть метрик через параметр `collect[]` в URL (например, `http://localhost:9100/metrics?collect[]=cpu&collect[]=meminfo`).

### Мониторинг Windows
Для ОС семейства Windows Node Exporter не предназначен. Используйте **[Windows Exporter](https://github.com/prometheus-community/windows_exporter)** или **Grafana Alloy**, которые собирают метрики WMI/Performance Counters.

## Практические сценарии

### Сценарий 1: Установка из бинарных файлов (Linux/systemd)

Рекомендуемый метод для обеспечения максимальной производительности и доступа к системным ресурсам.

**1. Загрузка и установка (v1.12.1):**
```bash
VERSION="1.12.1"
wget https://github.com/prometheus/node_exporter/releases/download/v${VERSION}/node_exporter-${VERSION}.linux-amd64.tar.gz
tar xvfz node_exporter-${VERSION}.linux-amd64.tar.gz
sudo mv node_exporter-${VERSION}.linux-amd64/node_exporter /usr/local/bin/
# → node_exporter installed to /usr/local/bin/
```

**2. Настройка systemd-юнита (`/etc/systemd/system/node_exporter.service`):**
```ini
[Unit]
Description=Prometheus Node Exporter
Documentation=https://github.com/prometheus/node_exporter
After=network.target

[Service]
User=root
ExecStart=/usr/local/bin/node_exporter \
    --web.listen-address=:9100 \
    --collector.textfile.directory=/var/lib/node_exporter/textfile_metrics
Restart=always

# Hardening (Безопасность)
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```
*Примечание: Использование `User=root` необходимо для доступа к некоторым метрикам ядра (например, `diskstats`, `hwmon`).*

**3. Запуск:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter
# Проверка статуса
systemctl is-active node_exporter
# → active
```

### Сценарий 2: Развертывание в Docker

Используется для мониторинга хоста из изолированного контейнера. Требует монтирования системных директорий.

```yaml
services:
  node-exporter:
    image: prom/node-exporter:v1.12.1
    container_name: node_exporter
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
    network_mode: host
    pid: host
    restart: unless-stopped
```

### Сценарий 3: Автоматизация через Ansible

Рекомендуемый способ для массового развертывания через коллекцию `prometheus.prometheus`.

```yaml
- hosts: all
  become: yes
  roles:
    - role: prometheus.prometheus.node_exporter
      vars:
        node_exporter_version: "1.12.1"
        node_exporter_enabled_collectors:
          - systemd
          - textfile
        node_exporter_textfile_dir: "/var/lib/node_exporter/textfile_metrics"
```

### Сценарий 4: Настройка безопасности (Basic Auth / TLS)

Защита эндпоинта от несанкционированного доступа без использования Nginx.

**1. Создание файла `web-config.yml`:**
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

### Диагностика типичных проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Ошибка `Permission denied` | Недостаточно прав у пользователя | Запустите от `root` или добавьте пользователя в группы `disk`, `hwmon`. |
| Метрики файловой системы пустые | Контейнер без `rootfs` | Проверьте монтирование `/` и флаг `--path.rootfs`. |
| Высокая нагрузка на CPU | Слишком много коллекторов | Отключите тяжелые коллекторы (например, `nfs`, `zfs`, если не нужны). |

### Оптимизация сбора в Prometheus

Рекомендуется использовать `scrape_interval` не менее 15 секунд для Node Exporter, чтобы избежать избыточной нагрузки на ядро при чтении `/proc`.

```yaml
scrape_configs:
  - job_name: 'node-exporter'
    scrape_interval: 30s
    static_configs:
      - targets: ['localhost:9100']
```

### См. также
*   **[Node Exporter (SSoT)](../Exporters/node_exporter.md)** — глубокое описание всех коллекторов.
*   **[Установка Prometheus: обзор](./overview.md)** — сравнение методов установки компонентов.
*   **[Textfile Collector](./extensibility/textfile_collector.md)** — механизм сбора кастомных метрик.
*   **[Методология поиска неисправностей](../../Linux/Diagnostics/Troubleshooting/general_troubleshooting_methodology.md)**.
