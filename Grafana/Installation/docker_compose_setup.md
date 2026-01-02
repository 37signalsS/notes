# Настройка Grafana с помощью Docker Compose

## Определения

*   **Grafana**: Открытая платформа для аналитики и интерактивной визуализации, позволяющая получать данные из различных источников, таких как Prometheus, Loki, Graphite, InfluxDB и других.
*   **Docker Compose**: Инструмент для определения и запуска многоконтейнерных Docker-приложений. Он позволяет описывать всю инфраструктуру приложения в одном YAML-файле.
*   **Prometheus**: Система мониторинга с открытым исходным кодом, использующая модель pull для сбора метрик с целевых систем.
*   **Провиженинг (Provisioning)**: Процесс автоматической настройки ресурсов или сервисов. В контексте Grafana это означает автоматическое создание источников данных, дашбордов и других конфигураций при старте.

## Основные понятия

Для запуска стека мониторинга (Prometheus + Grafana) рекомендуется следующая структура проекта:

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

*   `docker-compose.yml`: Определяет сервисы `prometheus` и `grafana` и их взаимосвязи.
*   `grafana/provisioning/datasources/datasources.yaml`: Файл для автоматической настройки источников данных в Grafana.

**Конфигурация Docker Compose (`docker-compose.yml`):**

*   **`image`**: Указывает образ Docker для запуска контейнера (например, `grafana/grafana`).
*   **`container_name`**: Задает имя для контейнера.
*   **`command`**: Определяет команду, которая будет выполнена при старте контейнера.
*   **`volumes`**: Пробрасывает локальные каталоги или файлы внутрь контейнера, обеспечивая персистентность данных или доступ к конфигурационным файлам.
*   **`ports`**: Сопоставляет порты между хостовой машиной и контейнером, делая сервис доступным извне.
*   **`restart: always`**: Гарантирует автоматический перезапуск контейнера при его завершении.
*   **`depends_on`**: Определяет зависимости между сервисами, гарантируя, что один сервис запустится только после успешного старта другого.

**Провиженинг источника данных (`datasources.yaml`):**

*   **`apiVersion: 1`**: Стандартный заголовок для файлов провиженинга Grafana.
*   **`datasources`**: Корневой элемент, содержащий список источников данных.
    *   **`name`**: Имя источника данных, отображаемое в пользовательском интерфейсе Grafana.
    *   **`type`**: Тип подключаемого источника данных (например, `prometheus`).
    *   **`url`**: URL-адрес источника данных. В Docker Compose сервисы могут обращаться друг к другу по именам сервисов.
    *   **`isDefault: true`**: Делает этот источник данных основным в Grafana.
    *   **`editable: true`**: Позволяет редактировать настройки источника данных через веб-интерфейс Grafana.

## Практические сценарии

### Конфигурация Docker Compose

Добавьте сервис `grafana` в `docker-compose.yml` (предполагается, что сервис `prometheus` уже настроен):

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

### Провиженинг источника данных Prometheus

Создайте файл `datasources.yaml` для автоматического подключения Prometheus в Grafana:

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

### Запуск и доступ

1.  Убедитесь, что все необходимые файлы и каталоги созданы.
2.  Запустите стек командой в каталоге `monitoring/`:

    ```bash
    docker-compose up -d
    ```

**Доступ к сервисам:**

*   **Prometheus**: `http://localhost:9090`
*   **Grafana**: `http://localhost:3000`

### Начальный вход в Grafana

При первом входе используйте стандартные учетные данные:

*   **Логин**: `admin`
*   **Пароль**: `admin`

После входа Grafana предложит сменить пароль для повышения безопасности.

### Проверка подключения источника данных

1.  Перейдите в Grafana UI: **Connections -> Data sources**.
2.  Вы должны увидеть `Prometheus` в списке.
3.  Нажмите на него и затем на кнопку **Save & test**, чтобы убедиться в корректности соединения.

