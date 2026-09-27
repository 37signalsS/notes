# Экспортеры Prometheus: Обзор

## Определения

**Экспортер (Exporter)** — специализированный программный компонент (агент), который собирает метрики из систем, не поддерживающих протокол Prometheus нативно, и транслирует их в формат, понятный серверу мониторинга. Экспортеры выступают в роли адаптеров между проприетарными или специфичными интерфейсами (JMX, SNMP, SQL) и HTTP-интерфейсом Prometheus.

**Нативная инструментация (Native Instrumentation)** — подход, при котором приложение или система самостоятельно реализует эндпоинт `/metrics`, исключая необходимость в стороннем агенте. Это предпочтительный метод, так как он уменьшает количество moving parts и повышает надежность (например, Kubernetes API Server, Angie, Traefik).

**Процесс экспозиции (Exposition)** — предоставление собранных метрик через HTTP-эндпоинт (обычно `/metrics`) для последующего сбора (scraping) сервером. В современных реалиях 2026 года экспозиция осуществляется в текстовом (OpenMetrics 2.0) или бинарном (Protobuf/OTLP) форматах.

**Collector (Коллектор)** — внутренний модуль экспортера или клиентской библиотеки, отвечающий за сбор группы связанных метрик. В Prometheus 3.0 коллекторы могут возвращать Native Histograms, что снижает кардинальность. Пример: `cpuCollector` в `node_exporter` или `fs_collector` в `cAdvisor`.

**См. также:** [Написание собственных экспортеров](./extensibility/custom_exporters.md), [Формат экспозиции](../../Prometheus/concepts/metric_types/exposition_format.md), [Расширяемость: концепции](./extensibility/concepts.md).

## Архитектура

### Схема взаимодействия

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Prometheus Server                            │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │  SD Manager  │───▶│  Scrape Pool │───▶│      TSDB            │  │
│  └──────────────┘    └──────┬───────┘    └──────────────────────┘  │
│                            │                                       │
│                   HTTP Pull (Pull-модель)                          │
└────────────────────────────┼───────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│    Target    │    │    Target    │    │    Target    │
│  node_exporter│    │  cAdvisor    │    │ Blackbox     │
│   :9100       │    │   :8080      │    │   :9115      │
└──────────────┘    └──────────────┘    └──────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   /proc,     │    │   cgroups,   │    │   Модули     │
│   /sys       │    │   Docker API │    │   probing    │
└──────────────┘    └──────────────┘    └──────────────┘
```

### Жизненный цикл одной метрики

1. **Discovery (Обнаружение):** Prometheus через SD Manager получает список целей от внешней системы (static_configs, kubernetes_sd, docker_sd).
2. **Relabeling (Прескрапинг):** Метки цели модифицируются (`relabel_configs`), фильтруются лишние `__meta_*`, формируется `__address__`.
3. **Scrape (Сбор):** HTTP GET на `http://<address>/metrics`. Prometheus передает заголовок `Accept` для согласования формата.
4. **Parsing (Парсинг):** Ответ экспортера парсится в соответствии с форматом (текстовый или бинарный). В Prometheus 3.0 поддерживается UTF-8.
5. **Relabeling (Постскрапинг):** `metric_relabel_configs` фильтруют отдельные временные ряды до записи в TSDB.
6. **Storage (Хранение):** Валидные серии записываются в TSDB с timestamp времени скрапинга.

## Основные концепции

### Принцип работы экспортера

Prometheus реализует **Pull-модель** сбора данных. Типовой цикл работы экспортера:

1.  **Запрос данных:** Экспортер опрашивает целевую систему (ядро ОС, БД, брокер сообщений, сетевое оборудование).
2.  **Трансформация:** Полученные данные (например, вывод `iostat`, результат SQL-запроса или SNMP-ответ) преобразуются в модель данных Prometheus.
3.  **Обслуживание:** Экспортер открывает HTTP-сервер. При поступлении запроса от Prometheus он отдаёт актуальный снимок (snapshot) метрик.

> **Важно:** Экспортер — это **stateless** (не сохраняющий состояние) компонент. Он не хранит историю метрик, эта задача полностью делегирована [TSDB Prometheus](../overview.md).

### Сравнение: отдельный экспортер vs нативная инструментация

| Характеристика | Отдельный экспортер | Нативная инструментация |
|:---|:---|:---|
| **Примеры** | `node_exporter`, `mysqld_exporter`, `cAdvisor` | Kubernetes API, Angie, RabbitMQ plugin |
| **Зависимости** | Требует установки, обновления и мониторинга отдельного процесса | Встроено в приложение/систему |
| **Надежность** | Дополнительный потенциальный point of failure | Отсутствует отдельный компонент |
| **Гибкость** | Можно использовать для любого ПО, даже без исходников | Требует поддержки в самом ПО |
| **Производительность** | Небольшой overhead на процесс и память | Минимальный overhead |
| **Безопасность** | Требует настройки TLS/Auth отдельно | Использует существующие механизмы приложения |
| **Версионирование** | Нужно отслеживать совместимость версий экспортера и цели | Обновляется вместе с приложением |

**Рекомендация:** При возможности используйте нативную инструментацию. Отдельные экспортеры оправданы для legacy-систем, проприетарного ПО или когда нет возможности изменить исходный код.

### Современные форматы экспозиции (2026)

С выходом Prometheus v3.0+ и развитием OpenTelemetry, количество и качество поддерживаемых форматов значительно выросло:

*   **OpenMetrics 2.0:** Основной текстовый стандарт. Нативно поддерживает **Exemplars** (связи с трассами), **Native Histograms** и расширенные имена в **UTF-8** (включая точки в именах).
*   **Protobuf (binary):** Используется для высокоэффективной передачи данных. Является предпочтительным при передаче больших объемов данных с нативными гистограммами, так как существенно снижает нагрузку на CPU при парсинге.
*   **OTLP (OpenTelemetry Protocol):** В 2026 году Prometheus поддерживает прямой прием OTLP метрик по gRPC или HTTP. Это позволяет современным приложениям, инструментированным OTel SDK, отправлять данные в Prometheus без использования выделенных экспортеров.
*   **Prometheus Text (0.0.4):** Устаревающий, но всё еще поддерживаемый формат для обратной совместимости.

### Типы реализации сбора

1.  **Отдельные экспортеры (Sidecar/Standalone):** Внешние процессы для систем без поддержки Prometheus (например, [node_exporter](./node_exporter.md)).
2.  **Нативная инструментация:** Когда приложение само реализует эндпоинт `/metrics` (например, [Angie](../../WebServers/Angie/angie_overview.md), Kubernetes). Это исключает лишнее звено и повышает надежность.
3.  **Pushgateway:** Промежуточный буфер для кратковременных задач (Cron jobs), которые завершаются быстрее, чем происходит цикл скрапинга. Подробнее: [Pushgateway](../pushgateway.md).
4.  **Textfile Collector:** Механизм сбора метрик из текстовых файлов, создаваемых простейшими скриптами. Подробнее: [Textfile Collector](./extensibility/textfile_collector.md).

### Service Discovery для экспортеров

Автоматическое обнаружение целей критично для масштабирования. Prometheus поддерживает несколько механизмов:

**Static (статический):** Явное перечисление целей в конфигурации. Подходит для малых инфраструктур.

```yaml
scrape_configs:
  - job_name: 'node_exporter'
    static_configs:
      - targets: ['192.168.1.10:9100', '192.168.1.11:9100']
        labels:
          env: 'production'
          region: 'eu-central'
```

**File SD (файловый):** Prometheus периодически читает YAML/JSON-файлы со списком целей. При изменении файлов конфигурация применяется автоматически без перезагрузки.

```yaml
scrape_configs:
  - job_name: 'file_sd'
    file_sd_configs:
      - files: ['/etc/prometheus/sd/*.yml']
        refresh_interval: 2m
```

Пример файла `/etc/prometheus/sd/hosts.yml`:
```yaml
- targets:
  - 'server1.example.com:9100'
  - 'server2.example.com:9100'
  labels:
    service: 'backend'
```

**Docker SD (Docker Engine API):** Обнаружение контейнеров через локальный или удаленный Docker Engine API. Подробнее: [Интеграция Docker с Prometheus](../../Docker/Docker_metrics/docker_prometheus_integration.md).

```yaml
scrape_configs:
  - job_name: 'docker'
    docker_sd_configs:
      - host: 'unix:///var/run/docker.sock'
        refresh_interval: 15s
    relabel_configs:
      - source_labels: [__meta_docker_container_name]
        regex: '/(.*)'
        target_label: container_name
      - source_labels: [__meta_docker_port_tcp]
        regex: '9100'
        action: keep
```

**Kubernetes SD (Kubernetes API):** Обнаружение Pod, Service, Endpoint, Node. Подробнее: [Service Discovery в Kubernetes](../../Prometheus/kubernetes/service_discovery.md).

```yaml
scrape_configs:
  - job_name: 'kubernetes-pods'
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        target_label: __metrics_path__
```

### Безопасность экспортеров

Экспортеры часто имеют доступ к критическим системным вызовам или данным БД. Рекомендуемые меры:

*   **TLS и Аутентификация:** Использование `exporter-toolkit` для настройки TLS и Basic Auth. Никогда не оставляйте эндпоинты открытыми в публичных сетях.
*   **Минимальные привилегии:** Запуск процесса от не-root пользователя с доступом только к необходимым ресурсам.
*   **Сетевая изоляция:** Ограничение доступа к порту экспортера на уровне Firewall (только для IP серверов мониторинга).

**Пример конфигурации `web-config.yml` (exporter-toolkit):**
```yaml
tls_server_config:
  cert_file: /etc/node_exporter/tls.crt
  key_file: /etc/node_exporter/tls.key
  client_auth_type: RequireAndVerifyClientCert
  client_ca_file: /etc/node_exporter/ca.crt

basic_auth_users:
  admin: "$2b$12$..."
```

**Запуск с защищенным эндпоинтом:**
```bash
./node_exporter --web.config.file=web-config.yml
```

### Кардинальность и производительность

Кардинальность — количество уникальных временных рядов в TSDB. Она напрямую влияет на потребление RAM и дискового пространства Prometheus.

**Факторы, влияющие на кардинальность:**
1.  **Количество целей (targets):** Каждый target добавляет базовую кардинальность.
2.  **Метрики на экспортер:** Node Exporter выдает ~1000+ метрик на хост.
3.  **Лейблы:** Каждая уникальная комбинация лейблов создает отдельный временной ряд.
4.  **Коллекторы:** Отключение ненужных коллекторов снижает кардинальность пропорционально.

**Ориентировочные лимиты на один инстанс Prometheus (2026):**
| Сценарий | Цели | Метрик на цель | Рядов | RAM Prometheus |
|:---|:---|:---|:---|:---|
| **Малый** | < 100 | < 500 | < 50 000 | 2–4 GB |
| **Средний** | 100–500 | 500–1000 | 50 000–500 000 | 8–16 GB |
| **Большой** | 500–2000 | 1000+ | 500 000–2 000 000 | 32–64 GB |
| **Enterprise** | > 2000 | 1000+ | > 2 000 000 | Требуется шардирование |

**Меры по снижению кардинальности:**
*   Отключайте неиспользуемые коллекторы через флаги запуска (`--no-collector.<name>`).
*   Используйте `metric_relabel_configs` для удаления не нужных метрик.
*   Избегайте высококардинальных лейблов (ID сессий, email, полные URL).
*   Используйте Native Histograms вместо классических — они создают в 3–5 раз меньше рядов.
*   Настройте `scrape_interval` 30–60s для инфраструктурных метриков.

## Практические сценарии

### Паттерн Multi-Target

Для таких экспортеров как [Blackbox](./blackbox/blackbox_exporter_overview.md) или SNMP Exporter используется схема, где один инстанс экспортера проверяет множество целей. Prometheus передает адрес цели в параметре запроса:

```yaml
# Пример конфигурации scrape для Blackbox
- job_name: 'blackbox'
  metrics_path: /probe
  params:
    module: [http_2xx]
  static_configs:
    - targets: ['example.com', 'google.com']
  relabel_configs:
    - source_labels: [__address__]
      target_label: __param_target
    - target_label: __address__
      replacement: 127.0.0.1:9115 # Адрес самого экспортера
```

### Выбор инструмента для мониторинга

| Система | Рекомендуемый инструмент | Особенности |
|:---|:---|:---|
| **Linux OS** | [node_exporter](./node_exporter.md) | Стандарт для железа и виртуальных машин. |
| **Контейнеры** | [cAdvisor](./cadvisor.md) | Мониторинг ресурсов на уровне cgroups. |
| **Базы данных** | `postgres_exporter` / `mysqld_exporter` | Требуют выделенного пользователя с правами на чтение системных таблиц. |
| **Веб-серверы** | [Angie](../../WebServers/Angie/angie_overview.md) / Nginx | Angie имеет нативную поддержку экспорта. |
| **Сетевые устройства** | `snmp_exporter` | Использует паттерн Multi-Target для опроса по SNMP. |
| **Удаленные проверки** | [blackbox_exporter](./blackbox/blackbox_exporter_overview.md) | Проверка доступности L4/L7 снаружи. |

### Конфигурация сбора метрик (Scrape Configs)

**Типовой шаблон для standalone-экспортера:**

```yaml
scrape_configs:
  - job_name: 'node_exporter'
    scrape_interval: 15s
    scrape_timeout: 10s
    static_configs:
      - targets: ['192.168.1.10:9100']
        labels:
          env: 'production'
          role: 'worker'
    relabel_configs:
      - source_labels: [__address__]
        target_label: instance
```

**Важные параметры:**
*   `scrape_interval` — частота сбора метрик. Рекомендуется 15–30s для инфраструктуры, 5–15s для критичных приложений.
*   `scrape_timeout` — таймаут одного запроса. Должен быть меньше `scrape_interval` минимум на 2–3 секунды.
*   `scheme` — `http` (по умолчанию) или `https`. Используйте HTTPS если экспортер настроен на TLS.
*   `metrics_path` — путь к эндпоинту метрик. По умолчанию `/metrics`.

### Валидация экспортеров

После развертывания экспортера выполните проверки:

**1. Проверка доступности эндпоинта `/metrics`:**
```bash
curl -s http://localhost:9100/metrics | head -n 20
# → # HELP node_cpu_seconds_total ...
# → # TYPE node_cpu_seconds_total counter
# → node_cpu_seconds_total{cpu="0",mode="idle"} 12345.67
```

**2. Проверка формата через promtool:**
```bash
curl -s http://localhost:9100/metrics | promtool check metrics
# → SUCCESS: 15 metric families found
```

**3. Проверка состояния targets в Prometheus:**
```bash
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.job=="node_exporter")'
# → {"target":"192.168.1.10:9100","health":"up",...}
```

**4. Проверка через PromQL:**
```promql
# Все инстансы node_exporter доступны
up{job="node_exporter"}

# Количество собранных метрик
count({__name__=~".+", job="node_exporter"})
```

### Алертинг на уровне экспортеров

Минимальные правила для контроля доступности самих экспортеров:

```yaml
groups:
  - name: exporter-availability
    rules:
      - alert: ExporterDown
        expr: up{job=~".+_exporter"} == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Экспортер {{ $labels.job }} на {{ $labels.instance }} недоступен"
          description: "HTTP-скрапинг завершается ошибкой более 5 минут."

      - alert: ExporterScrapeSlow
        expr: scrape_duration_seconds{job=~".+_exporter"} > 5
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Медленный скрапинг {{ $labels.job }}"
          description: "Время сбора метрик превышает 5 секунд: {{ $value }}s."
```

### Типичные проблемы и устранение неполадок

1.  **Ошибка `connection refused` при скрапинге**
    *   **Причина:** Экспортер не запущен, слушает на другом интерфейсе или порт закрыт фаерволлом.
    *   **Решение:** Проверьте процесс (`systemctl status node_exporter` или `docker ps`). Проверьте слушаемый порт (`ss -tlnp | grep 9100`). Проверьте фаерволл (`iptables -L -n` или `ufw status`).

2.  **Ошибка `context deadline exceeded` (timeout)**
    *   **Причина:** `scrape_timeout` меньше времени, необходимого экспортеру для сбора всех метрик.
    *   **Решение:** Увеличьте `scrape_timeout` в `prometheus.yml` или отключите ресурсоемкие коллекторы (`--no-collector.<name>`).

3.  **Кардинальность выросла после добавления экспортера**
    *   **Причина:** Высокое количество метрик с высококардинальными лейблами (например, `container_id` в Docker с динамическими ID).
    *   **Решение:** Используйте `metric_relabel_configs` для удаления лишних лейблов. Включите `--collector.<name>` вместо отключения всех и добавления отдельных.

4.  **Метрики отображаются как `stale` или NaN**
    *   **Причина:** Экспортер завершился без graceful shutdown или не передает stale markers.
    *   **Решение:** Перезапустите экспортер. Убедитесь, что он корректно обрабатывает SIGTERM и передает `NaN` перед выходом.

5.  **Символы UTF-8 в именах метрик отображаются как `_`**
    *   **Причина:** Prometheus v2.x не поддерживает UTF-8 без escaping. В v3.0 требуется заголовок `Accept: text/plain; version=1.0; escaping=allow-utf-8`.
    *   **Решение:** Обновите Prometheus до v3.0+ и настройте `scrape_protocols` в `scrape_configs`.

6.  **Таймаут TLS-рукопожатия (handshake failure)**
    *   **Причина:** Несовместимые версии TLS, устаревший сертификат или неправильный SNI.
    *   **Решение:** Укажите `server_name` в `tls_config` на стороне Prometheus. Проверьте срок действия сертификата (`openssl x509 -in tls.crt -noout -dates`).

7.  **Высокое потребление CPU на хосте с экспортером**
    *   **Причина:** Слишком частый скрапинг (интервал < 10s) или слишком много коллекторов с интенсивными syscalls.
    *   **Решение:** Увеличьте `scrape_interval` до 30–60s. Отключите тяжелые коллекторы. Используйте `nice` для снижения приоритета процесса.

8.  **Prometheus не видит метрики после обновления экспортера**
    *   **Причина:** Изменение имен метрик или формата экспозиции в новой версии экспортера.
    *   **Решение:** Проверьте release notes экспортера. Валидируйте вывод через `curl | promtool check metrics`. Обновите дашборды и алерты.

9.  **Метрики `up` равны 1, но данные отсутствуют в TSDB**
    *   **Причина:** Ошибка парсинга формата или `metric_relabel_configs` отбрасывает все метрики.
    *   **Решение:** Проверьте `promtool check metrics`. Временно отключите `metric_relabel_configs` для диагностики.

10. **Ошибка `permission denied` при доступе к `/proc` или `/sys`**
    *   **Причина:** Экспортер запущен от пользователя без прав на чтение системных файлов.
    *   **Решение:** Запускайте от выделенного пользователя с минимальными правами. Для `node_exporter` достаточно чтения `/proc` и `/sys` — root не требуется.

## Дополнительная информация

### Порты экспортеров

При разработке собственных решений необходимо придерживаться [официального списка портов Prometheus](https://github.com/prometheus/prometheus/wiki/Default-port-allocations), чтобы избежать конфликтов.

### Рекомендации по настройке

| Параметр | Рекомендация | Обоснование |
|:---|:---|:---|
| **scrape_interval** | 15–30 секунд | Меньше 15s создает избыточную нагрузку на Prometheus и экспортер. |
| **scrape_timeout** | 10 секунд (по умолчанию) | Должен быть меньше `scrape_interval`. |
| **Формат по умолчанию** | OpenMetrics 2.0 | Лучшая совместимость с v3.x, UTF-8, нативные гистограммы. |
| **gzip** | Обязателен для текстовых форматов | Снижает трафик в 3–10 раз. |
| **Stale markers** | Обязательны для graceful shutdown | Предотвращает ложные алерты. |

### См. также

*   [Типы метрик в Prometheus](../../Prometheus/concepts/metric_types/overview.md) — классификация и применение.
*   [Service Discovery и Relabeling](../../Prometheus/service_discovery_and_relabeling.md) — автоматизация поиска целей для сбора.
*   [Каталог других экспортеров](./other_exporters.md) — перечень для специфичных систем.
*   [Методология мониторинга](./monitoring_matrix.md) — матрица «Сервис → Метрики → Экспортер → Алерты».
