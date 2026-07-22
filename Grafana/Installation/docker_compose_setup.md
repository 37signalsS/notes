# Настройка Grafana с помощью Docker Compose

## Определения

- **Grafana**: Платформа для аналитики и визуализации. См. [Обзор Grafana](../grafana_overview.md).
- **Docker Compose**: Инструмент для определения и запуска многоконтейнерных Docker-приложений с помощью YAML-файла.
- **Prometheus**: Система мониторинга. См. [Обзор Prometheus](../../Prometheus/overview.md).
- **Провиженинг (Provisioning)**: Автоматическая конфигурация Grafana при старте (источники данных, дашборды, плагины). См. [Провиженинг Grafana](../grafana_provisioning.md).

### Параметры `docker-compose.yml`

| Параметр | Описание |
| :--- | :--- |
| **`image`** | Образ Docker для запуска контейнера |
| **`container_name`** | Имя контейнера |
| **`volumes`** | Монтирование локальных файлов или директорий в контейнер |
| **`ports`** | Проброс портов (хост:контейнер) |
| **`restart`** | Политика перезапуска (например, `unless-stopped`) |
| **`depends_on`** | Определение зависимостей между сервисами для порядка запуска |
| **`user`** | Запуск процесса от имени конкретного UID/GID (важно для прав на volumes) |

### Параметры `datasources.yaml`

| Параметр | Описание |
| :--- | :--- |
| **`name`** | Имя источника данных в интерфейсе |
| **`type`** | Тип источника (prometheus, loki, и др.) |
| **`url`** | Адрес источника (в Docker Compose — имя сервиса и порт) |
| **`isDefault`** | Флаг основного источника данных |
| **`editable`** | Разрешение редактирования через UI |

---

## Основные концепции

Использование Docker Compose позволяет развернуть полный стек мониторинга в виде изолированных контейнеров. Ключевым преимуществом является возможность декларативного описания всей инфраструктуры и её автоматической настройки через файлы провиженинга.

### Структура проекта

Для корректной работы рекомендуется придерживаться следующей структуры директорий:

```text
monitoring/
├── docker-compose.yml
├── .env                     # Секреты и переменные окружения
├── prometheus/
│   └── prometheus.yml       # Конфигурация сбора метрик
└── grafana/
    └── provisioning/
        ├── datasources/
        │   └── datasources.yaml
        └── dashboards/
            ├── dashboards.yaml  # Описание путей к дашбордам
            └── default/         # Папка с JSON-файлами дашбордов
                └── node-exporter.json
```

---

## Практические сценарии

### Сценарий 1: Конфигурация Docker Compose

Файл `docker-compose.yml` описывает сервисы `prometheus` и `grafana`, их связи и параметры хранения данных.

```yaml
# monitoring/docker-compose.yml

services:
  prometheus:
    image: prom/prometheus:v3.13.1
    container_name: ${PROJECT_NAME:-monitoring}-prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=15d'
    volumes:
      - ./prometheus:/etc/prometheus
      - prom_data:/prometheus
    ports:
      - "9090:9090"
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:9090/-/healthy"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - monitoring

  grafana:
    image: grafana/grafana:13.1.1
    container_name: ${PROJECT_NAME:-monitoring}-grafana
    user: "472:472" # UID/GID по умолчанию для пользователя grafana
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:-admin}
      - GF_SERVER_ROOT_URL=http://localhost:3000
      - GF_INSTALL_PLUGINS=${GRAFANA_PLUGINS:-} # Список плагинов через запятую
      - GF_LOG_LEVEL=info
      - GF_LOG_MODE=console file
    ports:
      - "3000:3000"
    restart: unless-stopped
    depends_on:
      prometheus:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "wget -q --spider http://localhost:3000/api/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - monitoring

volumes:
  prom_data:
  grafana_data:

networks:
  monitoring:
    driver: bridge
```

### Сценарий 2: Провиженинг источника данных

Создайте файл `grafana/provisioning/datasources/datasources.yaml`. При использовании Docker Compose в поле `url` указывается имя сервиса из `docker-compose.yml`.

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    isDefault: true
    access: proxy
    editable: false
```

### Сценарий 3: Провиженинг дашбордов

Для автоматической загрузки дашбордов необходимо создать описание провайдера в `grafana/provisioning/dashboards/dashboards.yaml`:

```yaml
apiVersion: 1
providers:
  - name: 'Default'
    orgId: 1
    folder: ''
    type: file
    disableDeletion: false
    editable: true
    options:
      path: /etc/grafana/provisioning/dashboards/default
```

JSON-файлы дашбордов (например, скачанные с [grafana.com/dashboards](https://grafana.com/grafana/dashboards/)) следует поместить в директорию `grafana/provisioning/dashboards/default/`.

### Сценарий 4: Конфигурация вспомогательных файлов

Для работы сценария 1 необходимы файлы `.env` и `prometheus/prometheus.yml`.

**Пример `.env`:**
```ini
PROJECT_NAME=my-stack
GRAFANA_ADMIN_PASSWORD=secure_password_123
GRAFANA_PLUGINS=grafana-clock-panel,grafana-simple-json-datasource
```

**Пример `prometheus/prometheus.yml`:**
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
```

### Сценарий 5: Запуск и проверка работоспособности

1. **Запуск**: Выполните команду в директории проекта:
    ```bash
    docker compose up -d
    ```

2. **Проверка**:
    - Prometheus: `http://localhost:9090`
    - Grafana: `http://localhost:3000` (логин/пароль: `admin` / `${GRAFANA_ADMIN_PASSWORD}`).
    - Проверка плагинов: **Administration -> Plugins**.
    - Проверка дашбордов: **Dashboards -> Browse**.

---

## Дополнительная информация

### Чек-лист безопасности

- **Смена пароля**: Обязательно используйте `${GRAFANA_ADMIN_PASSWORD}` в `.env`, не оставляйте `admin` по умолчанию.
- **Права доступа**: Флаг `user: "472:472"` гарантирует запуск от имени непривилегированного пользователя.
- **Сетевая изоляция**: Используйте внутренние сети Docker (`networks`), пробрасывайте на хост только порт Grafana (`3000`).
- **Секреты**: Никогда не коммитьте `.env` в публичные репозитории. Используйте `.gitignore`.
- **HTTPS**: В промышленной эксплуатации всегда используйте reverse proxy (Nginx, Traefik, Caddy) для терминации SSL.

### Устранение неполадок

| Проблема | Решение |
| :--- | :--- |
| **Ошибка прав доступа (Permission Denied)** | Выполните `chown -R 472:472 ./grafana` на хосте, чтобы контейнер мог писать в bind mounts. |
| **Grafana не видит Prometheus** | Проверьте `url` в `datasources.yaml`. Должно быть `http://prometheus:9090` (имя сервиса). |
| **Плагины не устанавливаются** | Убедитесь, что у контейнера Grafana есть доступ в интернет для скачивания плагинов. |
| **Дашборды не появляются** | Проверьте путь в `dashboards.yaml`. Он должен указывать на путь *внутри* контейнера. |

### Полезные команды

```bash
# Просмотр логов в реальном времени
docker compose logs -f

# Проверка статуса контейнеров и healthcheck
docker compose ps

# Принудительное пересоздание контейнеров
docker compose up -d --force-recreate

# Очистка всех данных (осторожно!)
docker compose down -v
```

**См. также:**

- [Высокая доступность Grafana](../high_availability.md)
- [Алертинг в Grafana](../alerting/concepts.md)
- [Loki в Docker Compose](../../Loki/Docker_Compose/loki_docker_compose_setup.md)
- [Провиженинг Grafana (подробно)](../grafana_provisioning.md)
- [Полный стек мониторинга (Prometheus + Alertmanager + Exporters)](../../Prometheus/installation/docker_stack/docker-compose_config.md)
