# Настройка Grafana с помощью Docker Compose

## Определения

- **Grafana**: Платформа для аналитики и визуализации. См. [Обзор Grafana](../grafana_overview.md).
- **Docker Compose**: Инструмент для определения и запуска многоконтейнерных Docker-приложений с помощью YAML-файла.
- **Prometheus**: Система мониторинга. См. [Обзор Prometheus](../../Prometheus/overview.md).
- **Провиженинг (Provisioning)**: Автоматическая конфигурация Grafana при старте. См. [Провиженинг Grafana](../grafana_provisioning.md).

### Параметры `docker-compose.yml`

| Параметр | Описание |
| :--- | :--- |
| **`image`** | Образ Docker для запуска контейнера |
| **`container_name`** | Имя контейнера |
| **`volumes`** | Монтирование локальных файлов или директорий в контейнер |
| **`ports`** | Проброс портов (хост:контейнер) |
| **`restart`** | Политика перезапуска (например, `unless-stopped`) |
| **`depends_on`** | Определение зависимостей между сервисами для порядка запуска |

### Параметры `datasources.yaml`

| Параметр | Описание |
| :--- | :--- |
| **`name`** | Имя источника данных в интерфейсе |
| **`type`** | Тип источника (prometheus, loki, и др.) |
| **`url`** | Адрес источника (в Docker Compose — имя сервиса) |
| **`isDefault`** | Флаг основного источника данных |
| **`editable`** | Разрешение редактирования через UI |

---

## Основные концепции

Использование Docker Compose позволяет развернуть полный стек мониторинга (Prometheus + Grafana) в виде изолированных контейнеров. Ключевым преимуществом является возможность декларативного описания всей инфраструктуры и её автоматической настройки через файлы провиженинга, что обеспечивает повторяемость среды и возможность версионирования конфигурации в Git.

Типовая структура проекта:

```text
monitoring/
├── docker-compose.yml
├── .env
├── prometheus/
│   └── prometheus.yml
└── grafana/
    └── provisioning/
        └── datasources/
            └── datasources.yaml
```

---

## Практические сценарии

### Сценарий 1: Конфигурация Docker Compose

Файл `docker-compose.yml` описывает сервисы `prometheus` и `grafana`, их связи и параметры хранения данных.

```yaml
# monitoring/docker-compose.yml

services:
  prometheus:
    image: prom/prometheus:v3.10.0
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
    image: grafana/grafana:12.4.2
    container_name: ${PROJECT_NAME:-monitoring}-grafana
    user: "472:472"
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD:-admin}
      - GF_SERVER_ROOT_URL=http://localhost:3000
      - GF_LOG_LEVEL=info
      - GF_LOG_MODE=console file
      - GF_LOG_FILE_LEVEL=info
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

**Особенности конфигурации:**

- Переменные `${PROJECT_NAME}` и `${GRAFANA_ADMIN_PASSWORD}` позволяют гибко настраивать окружение через `.env`.
- Health checks гарантируют, что Grafana начнет запуск только после того, как Prometheus станет доступен.
- Изолированная сеть `monitoring` предотвращает нежелательный доступ к сервисам извне.

### Сценарий 2: Провиженинг источника данных

Для автоматического подключения Prometheus необходимо создать файл в директории `provisioning/datasources/`. Полный перечень параметров и примеры для других СУБД см. в разделе **[Источники данных — Практические сценарии](../grafana_datasources.md#практические-сценарии)**.

```yaml
# monitoring/grafana/provisioning/datasources/datasources.yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    isDefault: true
```

### Сценарий 3: Запуск и проверка работоспособности

1. **Подготовка**: Убедитесь в наличии файла конфигурации Prometheus (`prometheus/prometheus.yml`).
2. **Запуск**: Выполните команду в директории проекта:

    ```bash
    docker compose up -d
    ```

3. **Проверка**:
    - Prometheus: `http://localhost:9090`
    - Grafana: `http://localhost:3000` (логин/пароль по умолчанию: `admin` / `admin`). Подробнее об управлении доступом см. [Управление пользователями и аутентификация](../grafana_user_management_and_authentication.md).
    - Статус источника: **Connections -> Data sources -> Prometheus -> Save & test**.

---

## Дополнительная информация

### Чек-лист безопасности (Security Checklist)

- Смените пароль администратора при первом входе.
- Используйте файл `.env` для хранения секретов, добавьте его в `.gitignore`.
- Запускайте контейнеры от непривилегированного пользователя (`user: "472:472"` для Grafana).
- Ограничивайте доступ к портам (например, `127.0.0.1:3000:3000`).
- Используйте reverse proxy (Nginx/Traefik) для настройки HTTPS.

### Устранение неполадок (Troubleshooting)

| Проблема | Решение |
| :--- | :--- |
| **Ошибка прав доступа к volumes** | `chmod -R 472:472 ./grafana` |
| **Grafana не видит Prometheus** | Проверьте, что оба сервиса находятся в одной сети `networks` |
| **Данные сбрасываются после перезапуска** | Проверьте наличие и корректность секции `volumes` для `grafana_data` |
| **Ошибка подключения к БД** | Проверьте логи: `docker compose logs -f grafana` |

### Полезные команды

```bash
# Просмотр логов в реальном времени
docker compose logs -f

# Проверка статуса контейнеров и healthcheck
docker compose ps

# Перезапуск стека с пересборкой (при изменении конфигов)
docker compose down && docker compose up -d

# Очистка неиспользуемых данных (volumes)
docker volume prune
```

**См. также:**

- [Высокая доступность Grafana](../high_availability.md)
- [Алертинг в Grafana](../alerting/concepts.md)
- [Loki в Docker Compose](../../Loki/Docker_Compose/index.md)
