# Настройка Loki с помощью Docker Compose

## Определения

**[Loki](loki_overview.md)** — это система агрегации логов, разработанная Grafana Labs. Она индексирует только метаданные (метки), а не полный текст логов, что делает ее экономичной и быстрой для большинства задач мониторинга.

## Практические сценарии

### 1. Конфигурация Docker Compose

Добавим сервис `loki` в основной файл `docker-compose.yml` вашего стека мониторинга.

```yaml
# monitoring/docker-compose.yml

services:
  prometheus:
    # ... (конфигурация Prometheus)

  grafana:
    # ... (конфигурация Grafana)

  loki:
    image: grafana/loki
    container_name: ${PROJECT_NAME}-loki
    ports:
      - "3100:3100"
    restart: always

volumes:
  prom_data:
```

- **`image: grafana/loki`**: Используется официальный образ Loki.
- **`ports`**: Публикует стандартный порт Loki `3100`, который используется для приема логов и для запросов от Grafana.
- В этой базовой конфигурации не используются персистентные вольюмы для Loki, что означает, что логи будут теряться при перезапуске контейнера. Для production-окружения необходимо настроить [хранилище в Loki](loki_overview.md#конфигурация).

### 2. Интеграция с Grafana

Чтобы Grafana могла запрашивать логи из Loki, необходимо добавить Loki как еще один источник данных. Это можно сделать через провиженинг, дополнив файл `datasources.yaml`.

```yaml
# monitoring/grafana/provisioning/datasources/datasources.yaml

apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    isDefault: true
    editable: true

  - name: Loki
    type: loki
    url: http://loki:3100
    access: proxy
    basicAuth: false
    editable: false
    version: 1
```

- Добавлена вторая запись в список `datasources`.
- **`type: loki`**: Указывает на тип источника данных.
- **`url: http://loki:3100`**: Адрес сервера Loki, доступный из Grafana по имени сервиса в Docker-сети.
- **`access: proxy`**: Рекомендуемый режим доступа, при котором запросы к источнику данных идут через бэкенд Grafana, а не напрямую из браузера.
- **`editable: false`**: Запрещает редактирование источника данных через UI, так как он управляется кодом.

### 3. Запуск и проверка

1.  Обновите `docker-compose.yml` и `grafana/provisioning/datasources/datasources.yaml`.
2.  Перезапустите стек мониторинга:

    ```bash
    # Сначала остановим и удалим старые контейнеры
    docker-compose down

    # Запускаем обновленную конфигурацию
    docker-compose up -d
    ```

3.  Войдите в Grafana (`http://localhost:3000`).
4.  Перейдите в **Connections -> Data sources**. Теперь в списке должны быть и `Prometheus`, и `Loki`.
5.  Чтобы проверить работу Loki, откройте вкладку **Explore**, выберите в выпадающем списке источник данных `Loki`. Если все настроено правильно, вы сможете выполнять запросы на языке [LogQL](loki_overview.md#язык-запросов-logql). На начальном этапе, пока логи не поступают, вы можете просто проверить доступность, выполнив запрос `{}`.