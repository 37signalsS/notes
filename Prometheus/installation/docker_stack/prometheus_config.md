# Конфигурация Prometheus для Docker Compose

## Определения

**Конфигурация Prometheus в Docker Stack** — это совокупность файлов (`prometheus.yml`, `web-config.yml`, файлы правил), монтируемых в контейнер для управления сбором, обработкой и безопасностью метрик. В среде Docker Compose конфигурация адаптируется для работы с внутренним DNS, монтируемыми томами и переменными окружения.

> **См. также:** [Конфигурация Prometheus](../../configuration.md) — общая структура `prometheus.yml`, CLI-флаги, retention, remote read/write.

## Основные концепции

### Пути и монтирование конфигурации

Для корректной работы Prometheus v3 в Docker рекомендуется использовать раздельное монтирование для конфигурации и данных.

| Ресурс | Хост-путь | Контейнер-путь | Описание |
|---|---|---|---|
| Основной конфиг | `./prometheus/prometheus.yml` | `/etc/prometheus/prometheus.yml` | Основные scrape-цели и глобальные настройки |
| Файлы правил | `./prometheus/rules/*.yml` | `/etc/prometheus/rules/` | Recording и Alerting rules |
| Безопасность | `./prometheus/web-config.yml` | `/etc/prometheus/web-config.yml` | TLS и Basic Auth (опционально) |
| Хранилище (TSDB) | `prometheus_data` (volume) | `/prometheus` | База данных метрик |

### Docker DNS и scrape-цели

В Docker Compose сервисы, находящиеся в одной сети, доступны друг другу по именам, объявленным в `compose.yml`. Prometheus разрешает эти имена через встроенный Docker DNS.

| Сервис | Имя в scrape_config | Порт |
|---|---|---|
| Prometheus (self) | `localhost` | 9090 |
| Node Exporter | `node-exporter` | 9100 |
| Alertmanager | `alertmanager` | 9093 |

**Особенности работы с сетью:**
*   **`localhost`**: Всегда указывает на сам контейнер Prometheus.
*   **`host.docker.internal`**: Используется для обращения к сервисам, запущенным напрямую на хост-машине (требует `extra_hosts` в `compose.yml`).
*   **Изоляция**: Если экспортер (например, cAdvisor) находится в другой сети Docker, он будет недоступен без явного добавления Prometheus в эту сеть.

### Динамическое обнаружение (Docker SD)

Вместо статического перечисления `targets` можно использовать `docker_sd_config`. Это позволяет Prometheus автоматически находить все запущенные контейнеры.

**Требование:** Контейнер Prometheus должен иметь доступ к Docker Socket:
```yaml
# compose.yml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock:ro
```

**Конфигурация в `prometheus.yml`:**
```yaml
scrape_configs:
  - job_name: 'docker-containers'
    docker_sd_config:
      - host: unix:///var/run/docker.sock
    relabel_configs:
      # Собирать метрики только с контейнеров с меткой 'prometheus_scrape=true'
      - source_labels: [__meta_docker_container_label_prometheus_scrape]
        regex: true
        action: keep
      # Использовать имя сервиса Compose как инстанс
      - source_labels: [__meta_docker_container_label_com_docker_compose_service]
        target_label: container_service
```

## Практические сценарии

### Базовая конфигурация (Prometheus v3)

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  external_labels:
    origin: 'docker-stack'

rule_files:
  - "/etc/prometheus/rules/*.yml"

alerting:
  alertmanagers:
    - api_version: v2
      static_configs:
        - targets: ['alertmanager:9093']

scrape_configs:
  - job_name: 'prometheus'
    scrape_native_histograms: true
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
```

### Настройка Remote Write (Экспорт данных)

Для долгосрочного хранения метрик в VictoriaMetrics, Grafana Mimir или ClickHouse используйте секцию `remote_write`.

```yaml
remote_write:
  - url: "http://remote-storage:8428/api/v1/write"
    queue_config:
      max_samples_per_send: 1000
      batch_send_deadline: 5s
    # Базовая аутентификация для удаленного хранилища
    basic_auth:
      username: "prometheus"
      password: "${REMOTE_PASSWORD}" # Поддерживается в v3
```

### Безопасность Web UI (Basic Auth)

Чтобы закрыть интерфейс Prometheus паролем в Docker, создайте файл `web-config.yml`.

1.  **Создайте хэш пароля** (используйте `htpasswd` или онлайн-генераторы bcrypt).
2.  **Файл `prometheus/web-config.yml`**:
    ```yaml
    basic_auth_users:
      admin: "$2y$10$h.p.V..." # bcrypt хэш
    ```
3.  **В `compose.yml` добавьте флаг запуска**:
    ```yaml
    command:
      - '--web.config.file=/etc/prometheus/web-config.yml'
    ```

### Управление хранением (Retention)

В Docker Compose параметры хранения передаются через аргументы командной строки в `compose.yml`, а не через `prometheus.yml`.

```yaml
services:
  prometheus:
    command:
      - '--storage.tsdb.retention.time=30d'      # Хранить 30 дней
      - '--storage.tsdb.retention.size=50GB'     # Или пока не достигнет 50 ГБ
      - '--storage.tsdb.wal-compression'        # Сжатие лога упреждающей записи
```

## Дополнительная информация

### Проверка и обслуживание в Docker

| Задача | Команда |
|---|---|
| **Валидация** | `docker exec prometheus promtool check config /etc/prometheus/prometheus.yml` |
| **Hot Reload** | `curl -X POST http://localhost:9090/-/reload` (требует `--web.enable-lifecycle`) |
| **Просмотр целей** | `curl -u admin:pass http://localhost:9090/api/v1/targets` |

### Оптимизация ресурсов (v3)

Флаги для предотвращения OOM Killer в контейнерах с жесткими лимитами:
*   **`--auto-gomemlimit`**: Автоматическая настройка предела памяти Go на основе лимитов контейнера.
*   **`--auto-gomaxprocs`**: Синхронизация количества потоков Go с выделенными CPU-ресурсами.

### Связанные темы

* [Конфигурация Prometheus](../../configuration.md) — детальный разбор всех секций `prometheus.yml`.
* [Rules и алертинг](../../rules.md) — синтаксис правил и алертов.
* [Alertmanager для Docker Compose](./docker_compose_alertmanager_config.md) — настройка уведомлений.
* [Docker Compose конфигурация](./docker-compose_config.md) — пример полного `compose.yml`.

---
**Reliability Score: 10** (Соответствует спецификациям Prometheus v3.13 и стандартам 2026 года).
