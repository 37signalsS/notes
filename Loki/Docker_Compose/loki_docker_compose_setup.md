# Практическая настройка Loki в Docker Compose

## Определения

**Loki** — горизонтально масштабируемая система агрегации логов от Grafana Labs, которая индексирует только метаданные (метки), а не полный текст логов. Подробная архитектура: [loki_overview.md](../loki_overview.md).

**Docker Compose** — инструмент для определения и запуска многоконтейнерных Docker-приложений с помощью YAML-файлов.

**UI (User Interface)** — пользовательский интерфейс (например, веб-интерфейс Grafana) для визуализации и анализа данных.

**URL (Uniform Resource Locator)** — унифицированный указатель ресурса, используемый для адресации сервисов в сети.

## Основные концепции

Для полноценного сбора логов в Docker с использованием Loki требуется три основных компонента. Информация актуальна на **июль 2026 года**.

| Компонент | Назначение | Актуальная версия | Примечание |
| :--- | :--- | :--- | :--- |
| **Loki** | Сервер для приема, хранения и индексации логов | `3.7.4` | Основной бэкенд системы |
| **Grafana Alloy** | Универсальный агент для сбора телеметрии | `1.18.0` | **Рекомендуемый агент** (замена Promtail) |
| **Grafana** | Визуализация и запросы (LogQL) | `13.1.1` | Единый UI для мониторинга |
| **Promtail** | Агент для сбора логов (Legacy) | — | **Удален** в Loki 3.7.3. Только для старых систем |

> **Важно:** С июля 2026 года Promtail официально удален из состава Loki. Для всех новых развертываний необходимо использовать **Grafana Alloy**. Подробнее см. [Grafana Alloy](../../Grafana/grafana_alloy_overview.md).

## Практические сценарии

### Конфигурация Docker Compose

Ниже приведен современный пример `compose.yml` (формат Compose Spec, версия не указывается) для развертывания стека логирования.

```yaml
# monitoring/compose.yml

services:
  loki:
    image: grafana/loki:3.7.4
    container_name: monitoring-loki
    ports:
      - "3100:3100"
    command: -config.file=/etc/loki/local-config.yaml
    volumes:
      - loki_data:/loki
    restart: always
    networks:
      - monitoring

  alloy:
    image: grafana/alloy:v1.18.0
    container_name: monitoring-alloy
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./alloy/config.alloy:/etc/alloy/config.alloy:ro
      - alloy_data:/var/lib/alloy
    command: run --storage.path=/var/lib/alloy /etc/alloy/config.alloy
    ports:
      - "12345:12345" # UI Alloy для отладки
    restart: always
    networks:
      - monitoring
    depends_on:
      - loki

  grafana:
    image: grafana/grafana:13.1.1
    container_name: monitoring-grafana
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin
    restart: always
    networks:
      - monitoring
    depends_on:
      - loki

volumes:
  loki_data:
  alloy_data:
  grafana_data:

networks:
  monitoring:
    driver: bridge
```

### Ключевые параметры развертывания

| Параметр | Описание |
| :--- | :--- |
| **`image: grafana/loki:3.7.4`** | Стабильная версия Loki с новым движком запросов |
| **`/var/run/docker.sock`** | Позволяет Alloy обнаруживать контейнеры и читать их логи |
| **`alloy_data:/var/lib/alloy`** | Хранение positions-файлов (чтобы не читать логи заново при перезапуске) |
| **`./grafana/provisioning`** | Автоматическое добавление источника данных Loki при старте |

### Конфигурация источников данных Grafana

Для автоматической настройки Loki в Grafana создайте файл провиженинга.

```yaml
# monitoring/grafana/provisioning/datasources/datasources.yaml

apiVersion: 1

datasources:
  - name: Loki
    type: loki
    url: http://loki:3100
    access: proxy
    basicAuth: false
    editable: false
    version: 1
    isDefault: true
```

### Конфигурация Grafana Alloy (рекомендуется)

Современный способ сбора логов Docker в Alloy использует компоненты `discovery.docker` и `loki.source.docker`.

```alloy
// monitoring/alloy/config.alloy

// 1. Обнаружение контейнеров Docker
discovery.docker "containers" {
  host = "unix:///var/run/docker.sock"
}

// 2. Очистка и преобразование меток (Relabeling)
discovery.relabel "docker_logs" {
  targets = discovery.docker.containers.targets

  // Извлекаем имя контейнера (убираем начальный слэш)
  rule {
    source_labels = ["__meta_docker_container_name"]
    regex         = "/(.*)"
    target_label  = "container"
  }

  // Оставляем имя образа
  rule {
    source_labels = ["__meta_docker_container_image"]
    target_label  = "image"
  }
}

// 3. Сбор логов из обнаруженных контейнеров
loki.source.docker "local_docker" {
  host       = "unix:///var/run/docker.sock"
  targets    = discovery.relabel.docker_logs.output
  forward_to = [loki.write.local_loki.receiver]
}

// 4. Отправка логов в Loki
loki.write "local_loki" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

### Конфигурация Promtail (legacy)

Если вы используете версию Loki ниже 3.7.3, вы можете использовать Promtail. **Для новых систем используйте Alloy.**

```yaml
# monitoring/promtail/config.yml legacy example
server:
  http_listen_port: 9080

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://loki:3100/loki/api/v1/push

scrape_configs:
  - job_name: containers
    static_configs:
      - targets: [localhost]
        labels:
          job: container_logs
          __path__: /var/lib/docker/containers/*/*-json.log
```

### Запуск и проверка системы

1. Создание структуры директорий:

```bash
mkdir -p monitoring/grafana/provisioning/datasources
mkdir -p monitoring/alloy
```

2. Размещение файлов конфигурации:
   - `monitoring/compose.yml`
   - `monitoring/grafana/provisioning/datasources/datasources.yaml`
   - `monitoring/alloy/config.alloy`

3. Запуск стека:

```bash
cd monitoring
docker compose up -d
```

4. Проверка статуса:

```bash
docker compose ps
```

5. Проверка в Grafana: откройте `http://localhost:3000` (admin/admin), перейдите в **Explore**, выберите источник **Loki** и выполните запрос `{container=~".+"}`.

### Поиск и устранение неисправностей

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Логи не появляются** | Нет доступа к `docker.sock` | Проверьте права доступа и монтирование сокета в Alloy |
| **404 Not Found в Alloy** | Неверный URL API Loki | Проверьте `url` в `loki.write`. Должен быть `/loki/api/v1/push` |
| **Высокая нагрузка на CPU** | Слишком много мелких логов | Настройте батчинг (batching) в `loki.write` |
| **Пустой список контейнеров** | Ошибка discovery | Откройте UI Alloy на порту 12345 и проверьте граф компонентов |

## Дополнительная информация

* **Обзор архитектуры:** [loki_overview.md](../loki_overview.md)
* **Развертывание в Kubernetes:** [loki_installation.md](../loki_stack_setup/loki_installation.md)
* **Подробно об Alloy:** [Grafana Alloy](../../Grafana/grafana_alloy_overview.md)
* **Официальная документация:** [Grafana Loki Docs](https://grafana.com/docs/loki/latest/)

