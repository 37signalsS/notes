# Настройка Grafana с помощью Docker Compose

## Определения

- **Grafana**: Открытая платформа для аналитики и интерактивной визуализации данных из различных источников ([Prometheus](../overview.md), [Loki](../../Loki/loki_overview.md), InfluxDB и др.).
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

1.  Убедитесь, что все необходимые файлы и каталоги (`prometheus/prometheus.yml`) созданы.
2.  Запустите стек из каталога `monitoring/`:
    ```bash
    docker-compose up -d
    ```
3.  **Доступ к сервисам:**
    - **Prometheus**: `http://localhost:9090`
    - **Grafana**: `http://localhost:3000`
4.  **Первый вход в Grafana:**
    - Логин: `admin`
    - Пароль: `admin`
    - *Система попросит сменить пароль при первом входе.*
5.  **Проверка источника данных:**
    - В Grafana перейдите в **Connections -> Data sources**.
    - Убедитесь, что `Prometheus` присутствует в списке.
    - Нажмите на него, а затем на **Save & test** для проверки соединения.

## Дополнительная информация

- **Безопасность**: Всегда меняйте пароль администратора по умолчанию при первом входе.
- **Production**: Для производственной среды рекомендуется использовать фиксированные версии образов (например, `grafana/grafana:10.4.2` вместо `grafana/grafana` или `grafana/grafana:latest`).
- **Расширение стека**:
    - Для сбора логов вы можете добавить в стек [Loki](../..//Loki/docker_compose_setup.md).
    - Для обеспечения отказоустойчивости изучите настройку [высокой доступности (HA)](../high_availability.md).

