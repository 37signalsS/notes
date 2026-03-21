# Настройка Grafana с помощью Docker Compose

> **Навигация:**
>
> - [Обзор Grafana](../grafana_overview.md) — основная информация о платформе
> - [Провиженинг](../grafana_provisioning.md) — управление конфигурацией как код
> - [Источники данных](../grafana_datasources.md) — подключение систем мониторинга
> - [Установка через Helm](./grafana_helm_installation.md) — для Kubernetes

## Определения

- **Grafana**: Открытая платформа для аналитики и интерактивной визуализации данных из различных источников ([Prometheus](./overview.md), [Loki](../../Loki/loki_overview.md), InfluxDB и др.).
- **Docker Compose**: Инструмент для определения и запуска многоконтейнерных Docker-приложений с помощью одного YAML-файла.
- **Prometheus**: Система мониторинга и сбора метрик с открытым исходным кодом.
- **Провиженинг (Provisioning)**: Процесс автоматической конфигурации Grafana при запуске. Позволяет декларировать в файлах источники данных, дашборды и другие настройки.

- **Ключи `docker-compose.yml`**:
  - `image`: Образ Docker для запуска контейнера.
  - `container_name`: Имя контейнера.
  - `volumes`: Проброс локальных файлов или папок в контейнер для конфигурации или хранения данных.
  - `ports`: Сопоставление портов хоста и контейнера.
  - `restart: always`: Автоматический перезапуск контейнера при сбоях.
  - `depends_on`: Определение зависимостей между сервисами, гарантирующее правильный порядок их запуска.

- **Ключи `datasources.yaml`**:
  - `name`: Имя источника данных в интерфейсе Grafana.
  - `type`: Тип источника (например, `prometheus`, `loki`).
  - `url`: Адрес источника данных. В Docker Compose сервисы доступны по именам.
  - `isDefault`: Указывает, является ли источник данных основным.
  - `editable`: Разрешает или запрещает редактирование источника данных через веб-интерфейс.

## Основные понятия

Ключевая идея — запуск стека мониторинга (Prometheus + Grafana) как набора изолированных контейнеров, управляемых через `docker-compose.yml`. Grafana настраивается автоматически при старте с помощью файлов провиженинга, что позволяет версионировать конфигурацию и упрощает развертывание.

Для этого используется следующая структура проекта:

```
monitoring/
├── docker-compose.yml
├── .env # (опционально, для переменных вроде ${PROJECT_NAME})
├── prometheus/
│   └── prometheus.yml
└── grafana/
    └── provisioning/
        └── datasources/
            └── datasources.yaml
```

- `docker-compose.yml`: Определяет сервисы `prometheus` и `grafana`.
- `grafana/provisioning/datasources/datasources.yaml`: Файл для автоматического подключения источников данных в Grafana.

## Практические сценарии

### Шаг 1: Конфигурация Docker Compose

Создайте файл `docker-compose.yml` со следующим содержимым. Он описывает два сервиса: `prometheus` и `grafana`.

```yaml
# monitoring/docker-compose.yml

services:
  prometheus:
    image: prom/prometheus:v3.0.0
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
    image: grafana/grafana:11.4.0
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
    # Ограничение ресурсов (опционально)
    # deploy:
    #   resources:
    #     limits:
    #       cpus: '0.5'
    #       memory: 512M

volumes:
  prom_data:
  grafana_data:

networks:
  monitoring:
    driver: bridge
```

> **Примечания:**
>
> - `${PROJECT_NAME:-monitoring}` — использует значение переменной или `monitoring` по умолчанию
> - `${GRAFANA_ADMIN_PASSWORD:-admin}` — пароль из переменной окружения или `admin` по умолчанию
> - **Health checks** обеспечивают проверку работоспособности сервисов
> - **Сеть `monitoring`** изолирует трафик мониторинга

### Шаг 2: Провиженинг источника данных

Создайте файл `datasources.yaml`, чтобы Grafana автоматически подключилась к Prometheus при старте.

```yaml
# monitoring/grafana/provisioning/datasources/datasources.yaml

apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090 # URL к Prometheus внутри Docker-сети
    isDefault: true
    editable: true
```

### Шаг 3: Запуск и проверка

1. Убедитесь, что все необходимые файлы и каталоги (`prometheus/prometheus.yml`) созданы.
2. Запустите стек из каталога `monitoring/`:

    ```bash
    docker-compose up -d
    ```

3. **Доступ к сервисам:**
    - **Prometheus**: `http://localhost:9090`
    - **Grafana**: `http://localhost:3000`
4. **Первый вход в Grafana:**
    - Логин: `admin`
    - Пароль: `admin`
    - *Система попросит сменить пароль при первом входе.*
5. **Проверка источника данных:**
    - В Grafana перейдите в **Connections -> Data sources**.
    - Убедитесь, что `Prometheus` присутствует в списке.
    - Нажмите на него, а затем на **Save & test** для проверки соединения.

## Дополнительная информация

### Security Checklist

- [ ] **Смените пароль администратора** при первом входе
- [ ] **Используйте переменные окружения** для чувствительных данных (`.env` файл)
- [ ] **Запускайте от непривилегированного пользователя** (`user: "472:472"`)
- [ ] **Ограничьте доступ к портам** через firewall или binding на localhost
- [ ] **Включите HTTPS** для production (reverse proxy с SSL)
- [ ] **Настройте аутентификацию** через OAuth/LDAP (см. [управление пользователями](../grafana_user_management_and_authentication.md))

### Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Контейнер не запускается** | Ошибка прав доступа к volumes | `chmod -R 472:472 ./grafana` |
| **Нет связи с Prometheus** | Сервисы в разных сетях | Проверьте `networks` в docker-compose.yml |
| **Datasource не работает** | Неправильный URL | Используйте `http://prometheus:9090` (имя сервиса) |
| **Grafana теряет данные** | Нет persistent volume | Проверьте `grafana_data` volume |
| **Высокое потребление памяти** | Много дашбордов/запросов | Увеличьте лимиты памяти или оптимизируйте запросы |

**Полезные команды:**

```bash
# Просмотр логов
docker compose logs -f grafana
docker compose logs -f prometheus

# Проверка статуса
docker compose ps

# Перезапуск сервиса
docker compose restart grafana

# Полная пересборка
docker compose down && docker compose up -d

# Проверка health
curl http://localhost:3000/api/health
curl http://localhost:9090/-/healthy
```

### Production Recommendations

- **Безопасность**: Всегда меняйте пароль администратора по умолчанию при первом входе.
- **Version pinning**: Для производственной среды используйте фиксированные версии образов (например, `grafana/grafana:11.4.0` вместо `grafana/grafana` или `grafana/grafana:latest`).
- **Backup**: Настройте регулярный бэкап директории `/var/lib/grafana` (дашборды, БД) и файлов провиженинга.
- **Monitoring**: Разверните мониторинг для самой Grafana (метрики, логи).
- **High Availability**: Для HA-конфигурации используйте внешнюю БД (PostgreSQL/MySQL) и балансировщик. См. [Высокая доступность](../high_availability.md).

### Расширение стека

- **Сбор логов**: Добавьте [Loki](../../Loki/Docker_Compose/index.md) для агрегации логов.
- **Трассировки**: Добавьте [Tempo](../../Tempo/index.md) для распределенных трассировок.
- **Отказоустойчивость**: Изучите настройку [высокой доступности (HA)](../high_availability.md).
- **Алертинг**: Настройте [оповещения](../alerting/concepts.md) для уведомления об инцидентах.
