# Настройка Prometheus с помощью Docker Compose

Этот документ описывает базовую настройку сервера Prometheus с использованием `docker-compose`.

## Структура проекта

Для запуска мониторинга рекомендуется создать следующую структуру каталогов:

```
monitoring/
├── docker-compose.yml
├── .env
└── prometheus/
    └── prometheus.yml
```

*   `docker-compose.yml`: Основной файл, описывающий сервис Prometheus.
*   `.env`: Файл с переменными окружения (например, имя проекта).
*   `prometheus/prometheus.yml`: Файл конфигурации Prometheus.

## Конфигурация Docker Compose

Ниже приведен пример секции `prometheus` для файла `docker-compose.yml`.

```yaml
# monitoring/docker-compose.yml

services:
  prometheus:
    image: prom/prometheus
    container_name: ${PROJECT_NAME}-prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
    volumes:
      - ./prometheus:/etc/prometheus
      - prom_data:/prometheus
    ports:
      - "9090:9090"
    restart: always

volumes:
  prom_data:
```

*   **`image: prom/prometheus`**: Используется официальный образ Prometheus.
*   **`command`**: Переопределяет команду по умолчанию, указывая путь к файлу конфигурации внутри контейнера.
*   **`volumes`**:
    *   `./prometheus:/etc/prometheus`: Пробрасывает локальный каталог с конфигурацией `prometheus.yml` внутрь контейнера.
    *   `prom_data:/prometheus`: Используется именованный том Docker для сохранения данных временных рядов (метрик) между перезапусками контейнера.
*   **`ports`**: Публикует стандартный порт Prometheus `9090`.

## Файл переменных окружения

Файл `.env` помогает задавать общие переменные для всего проекта.

```ini
# monitoring/.env
PROJECT_NAME=my_monitoring
```

## Конфигурация Prometheus

Файл `prometheus.yml` содержит настройки для сбора метрик. Начнем с конфигурации, где Prometheus мониторит сам себя.

```yaml
# monitoring/prometheus/prometheus.yml

global:
  scrape_interval: 15s # Интервал сбора метрик по умолчанию
  evaluation_interval: 15s
  scrape_timeout: 10s

scrape_configs:
  - job_name: 'prometheus'
    # Мониторим сами себя
    static_configs:
      - targets: ['localhost:9090']
```

*   **`global`**: Глобальные настройки. `scrape_interval` определяет, как часто Prometheus будет опрашивать цели (targets).
*   **`scrape_configs`**: Секция для определения "заданий" (jobs) по сбору метрик.
*   **`job_name: 'prometheus'`**: Имя задания.
*   **`static_configs`**: Позволяет статически определить список целей для сбора метрик. В данном случае это сам Prometheus, доступный внутри Docker-сети по имени сервиса и порту.

## Запуск

Для запуска сервера Prometheus выполните команду в каталоге `monitoring/`:

```bash
docker-compose up -d
```

После запуска веб-интерфейс Prometheus будет доступен по адресу `http://localhost:9090`. В разделе **Status -> Targets** вы должны увидеть эндпоинт `prometheus` со статусом `UP`.

---
**Связанные темы:**
*   [[overview.md]]
*   [[../Grafana/docker_compose_setup.md]]
*   [[exporters_setup_guide.md]]
