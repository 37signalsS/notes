# Настройка Grafana с помощью Docker Compose

Этот документ описывает базовую настройку Grafana для визуализации метрик из Prometheus с использованием `docker-compose` и автоматического провиженинга источника данных.

## Структура проекта

Для запуска стека мониторинга (Prometheus + Grafana) рекомендуется следующая структура:

```
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

*   `docker-compose.yml`: Описывает сервисы `prometheus` и `grafana`.
*   `grafana/provisioning/datasources/datasources.yaml`: Файл для автоматической настройки источников данных в Grafana.

## Конфигурация Docker Compose

Добавим сервис `grafana` в `docker-compose.yml` к ранее созданному сервису `prometheus`.

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

  grafana:
    image: grafana/grafana
    container_name: ${PROJECT_NAME}-grafana
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning
    ports:
      - "3000:3000"
    restart: always
    depends_on:
      - prometheus

volumes:
  prom_data:

```

*   **`image: grafana/grafana`**: Используется официальный образ Grafana.
*   **`volumes`**: Пробрасывает локальный каталог `grafana/provisioning` в контейнер. Grafana автоматически подхватит конфигурационные файлы из этого каталога при старте.
*   **`ports`**: Публикует стандартный порт Grafana `3000`.
*   **`depends_on`**: Гарантирует, что `grafana` запустится после `prometheus`.

## Провиженинг источника данных

Чтобы Grafana автоматически подключилась к Prometheus, создадим файл `datasources.yaml`.

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

*   **`apiVersion: 1`**: Стандартный заголовок для файлов провиженинга Grafana.
*   **`datasources`**: Список источников данных для создания.
    *   **`name`**: Имя источника данных, которое будет отображаться в UI Grafana.
    *   **`type`**: Тип источника данных, в данном случае `prometheus`.
    *   **`url`**: Адрес сервера Prometheus. Так как оба сервиса находятся в одной Docker-сети, мы можем обращаться к Prometheus по имени сервиса (`prometheus`).
    *   **`isDefault: true`**: Делает этот источник данных основным.
    *   **`editable: true`**: Позволяет редактировать настройки источника данных через веб-интерфейс Grafana.

## Запуск

1.  Убедитесь, что у вас созданы все необходимые файлы и каталоги.
2.  Запустите стек командой в каталоге `monitoring/`:

```bash
docker-compose up -d
```

**Доступ:**
*   **Prometheus:** `http://localhost:9090`
*   **Grafana:** `http://localhost:3000`

При первом входе в Grafana используйте стандартные учетные данные:
*   **Логин:** `admin`
*   **Пароль:** `admin`

После входа Grafana предложит сменить пароль.

Чтобы проверить, что источник данных успешно подключился, перейдите в **Connections -> Data sources**. Вы должны увидеть `Prometheus` в списке. Нажав на него и затем на кнопку **Save & test**, вы можете убедиться, что соединение установлено корректно.

---
**Связанные темы:**
*   [[grafana_overview.md]]
*   [[grafana_provisioning.md]]
*   [[grafana_dashboards.md]]
*   [[../Prometheus/docker_compose_setup.md]]
*   [[../Loki/docker_compose_setup.md]]
