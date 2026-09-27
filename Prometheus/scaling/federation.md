# Федерация Prometheus

Федерация — это механизм, позволяющий одному серверу Prometheus (вышестоящему) собирать выбранные временные ряды с другого сервера Prometheus (нижестоящего). Это иерархический подход к масштабированию, предназначенный для агрегации данных из множества независимых источников.

## Определения

*   **Федерация (Federation):** Процесс сбора данных «сервер-сервер», где вышестоящий инстанс выступает в роли скрейпера для нижестоящего.
*   **Нижестоящий сервер (Leaf):** Источник данных, обслуживающий конкретный сегмент инфраструктуры (кластер, дата-центр). Ранее использовался термин Slave.
*   **Вышестоящий сервер (Master):** Точка агрегации, предоставляющая глобальный обзор (Global View) или расчет SLO на основе данных из Leaf-узлов. Ранее использовался термин Master.
*   **Эндпоинт `/federate`:** Системный эндпоинт, возвращающий не текущие метрики процесса, а содержимое TSDB нижестоящего сервера, отфильтрованное по селекторам.
*   **Instant Vector:** Формат данных, передаваемый по федерации — только последние значения (last samples) для каждого временного ряда.
*   **External Labels:** Набор меток, добавляемых к данным нижестоящего сервера на стороне вышестоящего, позволяющих различать идентичные метрики из разных источников.

## Базовые концепции

### Принцип работы и форматы данных

Вышестоящий сервер запрашивает данные по HTTP. В параметре URL `match[]` передаются PromQL-селекторы. Нижестоящий сервер находит соответствующие ряды в своей памяти или на диске и отдает их в текстовом формате.

**Технические особенности реализации:**
- **Instant Vector Only:** Передаются только последние значения (last samples). Федерация — это не синхронизация баз данных, а скрейпинг текущего состояния.
- **`honor_labels: true`:** Обязательная настройка. Без неё Master-сервер заменит оригинальные лейблы `job` и `instance` нижестоящего сервера своими собственными (обычно `job="federated"`), что приведет к потере контекста.
- **External Labels:** На нижестоящем сервере должны быть настроены уникальные `external_labels` (например, `cluster: dc1`), чтобы Master-сервер мог различать идентичные метрики из разных источников.

### Типы федерации

1.  **Иерархическая (Hierarchical Federation):**
    *   **Структура:** Древовидная (Leaf -> Regional -> Global).
    *   **Цель:** Масштабирование по количеству таргетов. Каждый уровень выше собирает всё менее детальные, но более агрегированные данные.
2.  **Межсервисная (Cross-service Federation):**
    *   **Структура:** Плоская.
    *   **Цель:** Обмен специфичными метриками между функциональными командами (например, команда БД забирает метрики сети для корреляции задержек).

### Количественные пороги и ограничения

Решение о применении федерации должно приниматься на основе метрик. Федерация подходит только для ограниченного объема данных.

| Показатель | Комфортная зона | Предупреждение | Критический режим | Рекомендация |
|---|---|---|---|---|
| **Количество Leaf-серверов на одном Master** | < 50 | 50–200 | > 200 | При >200 перейти на Remote Write + LTS |
| **Активные серии на одном Leaf** | < 2M | 2M–5M | > 5M | Увеличить RAM, добавить recording rules, уменьшить `match[]` |
| **Скорость запросов к `/federate`** | < 1 запрос/сек на Leaf | 1–5 запросов/сек | > 5 запросов/сек | Увеличить интервал скрейпинга Master, добавить кэширование |
| **Размер ответа `/federate`** | < 10 MB | 10–50 MB | > 50 MB | Уменьшить количество селекторов в `match[]`, добавить recording rules |
| **Задержка данных (lag)** | < 30с | 30с–2м | > 2м | Уменьшить `scrape_interval` на Master или перейти на Push-модель |

**Ключевые метрики для мониторинга здоровья федерации:**
```promql
# Процент dropped samples в Remote Write (если используется одновременно)
rate(prometheus_remote_storage_dropped_samples_total[5m])
  / sum(rate(prometheus_remote_storage_samples_total[5m])) * 100

# Задержка отправки данных в LTS (секунды)
prometheus_remote_storage_highest_timestamp_in_seconds
  - prometheus_remote_storage_queue_highest_sent_timestamp_seconds

# Активные серии на Leaf
prometheus_tsdb_head_series

# Размер WAL на Leaf
prometheus_tsdb_wal_size_bytes
```

### Внутренние механизмы `/federate` и их влияние на производительность

Эндпоинт `/federate` не возвращает данные напрямую из WAL. Prometheus должен:
1. Применить PromQL-селекторы к индексу TSDB.
2. Прочитать соответствующие чанки (chunks) с диска или из memory-mapped файлов.
3. Сформировать текстовый ответ (text exposition format) в оперативной памяти.
4. Сжать и отдать по HTTP.

Это делает запрос ресурсоемким:
- **CPU:** regex-матчинг и сериализация тысяч рядов.
- **Memory:** формирование полного ответа в буфере. При большом объеме метрик возможен OOM.
- **Disk I/O:** чтение нерелевантных чанков, если индексы фрагментированы.

**Связь с записью данных (ingestion):** Пока `/federate` активен, процесс Compaction не может удалять старые чанки, что приводит к росту WAL и увеличению лагов записи.

### Матрица выбора: Федерация vs альтернативы

| Условие | Рекомендуемое решение | Почему |
|---|---|---|
| < 50 Leaf-серверов, air-gapped сети | Федерация | Не требует исходящего доступа из Leaf |
| > 50 Leaf-серверов, высокая частота обновления | Remote Write 2.0 + LTS | Пропускная способность Push выше |
| Нужна история данных, а не только последние значения | Thanos / VictoriaMetrics Cluster | Федерация передает только Instant Vector |
| Год+ retention, глобальный обзор | Thanos Receive + Sidecar | Объектное хранилище + downsampling |
| Высокая кардинальность, миллионы серий на Leaf | Sharding + Remote Write | Федерация не справляется с нагрузкой на Leaf |

## Практические сценарии

### Сценарий 1: Базовая конфигурация (Bare-metal/VM)

**Шаг 1. Настройка нижестоящего сервера (Leaf)**
```yaml
# prometheus.yml на Leaf-сервере
global:
  scrape_interval: 15s
  external_labels:
    cluster: 'production-dc1'

scrape_configs:
  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']
```

**Шаг 2. Настройка вышестоящего сервера (Master)**
```yaml
# prometheus.yml на Master-сервере
scrape_configs:
  - job_name: 'federate-dc1'
    scrape_interval: 1m
    honor_labels: true
    metrics_path: '/federate'
    params:
      'match[]':
        - '{job="node"}'                # Собираем данные node_exporter
        - '{__name__=~"job:.*"}'        # Собираем результаты recording rules
    static_configs:
      - targets: ['leaf-dc1-ip:9090']
```

**Шаг 3. Валидация:**
```bash
# Проверка доступности /federate
curl -s http://leaf-dc1-ip:9090/federate | head -n 5

# Проверка на Master-сервере (должны появиться метрики)
curl -s 'http://master:9090/api/v1/query?query=up{cluster="production-dc1"}' | jq .
```

### Сценарий 2: Использование в изолированных (Air-gapped) сетях

Федерация остается безальтернативным методом в сетях с жесткой политикой безопасности:
- **Условие:** Фаервол запрещает исходящий трафик из защищенного сегмента (Push / Remote Write запрещены), но разрешает входящий Pull-запрос из доверенного сегмента мониторинга.
- **Реализация:** Вышестоящий сервер "затягивает" данные через однонаправленное соединение, выполняя роль шлюза для метрик.

**Расширенная конфигурация для air-gapped сети:**
```yaml
# На Master-сервере (в доверенном сегменте)
scrape_configs:
  - job_name: 'federate-secure-dmz'
    honor_labels: true
    metrics_path: '/federate'
    params:
      'match[]':
        - '{job="node"}'
        - '{__name__=~"up|node_cpu_seconds_total"}'
    static_configs:
      - targets: ['10.0.5.10:9090']  # IP Leaf в DMZ
    scrape_interval: 2m
    scrape_timeout: 30s
```

**Шаги развертывания:**
1. Настроить статическую запись маршрута или NAT на фаерволе для разрешения входящих TCP-соединений от IP Master-сервера к порту 9090 на Leaf.
2. Отключить на Leaf все Remote Write-очереди, чтобы избежать утечки трафика.
3. Настроить `external_labels` на Leaf для идентификации источника данных.

### Сценарий 3: Настройка в Prometheus Operator (Kubernetes)

В Operator федерация реализуется через `additionalScrapeConfigs`:

```yaml
# prometheus-additional.yaml
- job_name: 'federate-remote-cluster'
  honor_labels: true
  metrics_path: '/federate'
  params:
    'match[]':
      - '{cluster="remote-k8s"}'
  static_configs:
    - targets: ['prometheus-operated.remote-namespace.svc:9090']
```

Применение:
```bash
kubectl create configmap prometheus-additional-scrape-configs \
  --from-file=prometheus-additional.yaml -n monitoring

kubectl patch prometheus main -n monitoring --type='json' -p='[
  {
    "op": "replace",
    "path": "/spec/additionalScrapeConfigs",
    "value": [{"name": "prometheus-additional-scrape-configs", "key": "prometheus-additional.yaml"}]
  }
]'
```

### Сценарий 4: Capacity Planning для федеративной архитектуры

Пошаговая оценка необходимости поддержания или миграции с федерации.

**Шаг 1. Оценка количества Leaf-серверов:**
```bash
# Подсчет Leaf-серверов на одном Master
curl -s http://master:9090/api/v1/targets | jq '.data.activeTargets[] | select(.job | startswith("federate")) | .instance' | wc -l
```

**Шаг 2. Оценка размера ответа `/federate`:**
```bash
# Примерный объем данных с одного Leaf
curl -s -G http://leaf:9090/federate \
  --data-urlencode 'match[]={job="node"}' \
  -H "Accept-Encoding: gzip" | \
  wc -c
```

**Шаг 3. Прогноз роста:**
Если количество Leaf > 50 или размер ответа > 10 MB, планируйте переход на Remote Write 2.0 с Thanos/Mimir/VictoriaMetrics.

### Сценарий 5: Миграция с федерации на Remote Write 2.0

Поэтапный переход без простояя мониторинга.

**Этап 1. Включение Remote Write параллельно с федерацией:**
```yaml
# На каждом Leaf-сервере
remote_write:
  - url: 'http://thanos-receive:19291/api/v1/receive'
    name: 'thanos-primary'
    queue_config:
      max_shards: 50
  - url: 'http://vmagent:8429/api/v1/write'
    name: 'vm-backup'
    write_relabel_configs:
      - source_labels: [__name__]
        regex: 'up|node_cpu_seconds_total|node_memory_MemAvailable_bytes'
        action: keep
```

**Этап 2. Валидация целостности данных:**
Сравнить количество рядов в Grafana между источником федерации и новым LTS.

**Этап 3. Переключение Master-сервера:**
Заменить scrape-задачи федерации на запросы к LTS (Thanos Query / VictoriaMetrics).

**Этап 4. Отключение `/federate` на Leaf:**
Удалить `external_labels` и конфигурацию федерации после подтверждения работоспособности Push-архитектуры.

## Безопасность эндпоинта `/federate`

Эндпоинт `/federate` позволяет выгрузить практически всю TSDB сервера, поэтому его защита обязательна.

### Вариант 1: Встроенная аутентификация (v2.24+)

Настройка в `web.yml` нижестоящего сервера:
```yaml
basic_auth_users:
  admin: "$2b$12$hN3qMCEuBuidN31..." # Хэш пароля
```
Запуск Prometheus с флагом `--web.config.file=web.yml`.

На вышестоящем сервере:
```yaml
scrape_configs:
  - job_name: 'federate'
    basic_auth:
      username: admin
      password: yourpassword
    ...
```

### Вариант 2: TLS и mTLS

Использование клиентских сертификатов для взаимной аутентификации:

```yaml
# На Leaf-сервере
tls_server_config:
  cert_file: "/etc/prometheus/tls/server.crt"
  key_file: "/etc/prometheus/tls/server.key"
  client_ca_file: "/etc/prometheus/tls/ca.crt"

# На Master-сервере
scrape_configs:
  - job_name: 'federate-mtls'
    honor_labels: true
    metrics_path: '/federate'
    tls_config:
      ca_file: "/etc/prometheus/tls/ca.crt"
      cert_file: "/etc/prometheus/tls/client.crt"
      key_file: "/etc/prometheus/tls/client.key"
    static_configs:
      - targets: ['leaf-dc1:9090']
```

### Вариант 3: Nginx Reverse Proxy

Ограничение доступа по IP-адресам вышестоящих серверов:
```nginx
location /federate {
    allow 192.168.1.10; # IP Master-сервера
    deny all;
    proxy_pass http://localhost:9090/federate;
}
```

### Вариант 4: Корпоративный OIDC / OAuth2 Proxy

Для сред с централизованной аутентификацией (без публичных облаков):
```nginx
location /federate {
    auth_request /oauth2/auth;
    auth_request_set $user $upstream_http_x_auth_request_user;
    proxy_pass http://localhost:9090/federate;
}
```

## Производительность и ограничения

### Нагрузка на ресурсы

Запрос к `/federate` — тяжелая операция для Leaf-сервера:
- **CPU:** Выполнение regex-матчинга тысяч рядов.
- **Memory:** Формирование текстового ответа в памяти. Большой объем метрик может вызвать OOM.
- **Network:** Обязательно используйте сжатие (`Accept-Encoding: gzip`).

### Сравнение с Remote Write 2.0

| Характеристика | Федерация (Pull) | Remote Write (Push) |
|---|---|---|
| **Нагрузка на Leaf** | Высокая (при запросе) | Равномерная (постоянная) |
| **Сетевой поток** | Входящий (Pull) | Исходящий (Push) |
| **Актуальность** | Зависит от интервала Master | Реальное время |
| **Пропускная способность** | Низкая (текстовый формат) | Высокая (бинарный OTLP/Protobuf) |
| **Передача истории** | Только Instant Vector | Полная история (с WAL backfill) |
| **Сжатие** | gzip | zstd, snappy, Arrow |
| **Сетевая топология** | Master тянет из Leaf | Leaf пушит в LTS |

### Тюнинг производительности

1.  **Сжатие gzip:** Настройте `Accept-Encoding: gzip` на Master-сервере и поддержку сжатия на Leaf. Это снижает трафик в 3–5 раз.
2.  **Ограничение размера ответа:** В Nginx добавьте `client_max_body_size` и `proxy_read_timeout`.
3.  **Увеличение интервала скрейпинга:** Для статических данных используйте `scrape_interval: 2m` или `5m` на Master-сервере.
4.  **Recording Rules на Leaf:** Создавайте агрегаты на уровне Leaf, чтобы Master запрашивал меньше рядов.
5.  **Параллелизм:** Prometheus использует один воркер на запрос. Для параллельных запросов к нескольким Leaf используйте несколько scrape_configs с одним `job_name` или балансировщик.

### Антипаттерны

- **Сбор всех метрик (`match[]={__name__=~".+"}`)**: Гарантированная перегрузка Leaf-сервера.
- **Отсутствие Recording Rules**: Сбор сырых данных вместо агрегатов на Master-уровне забивает сеть.
- **Глубокая иерархия**: Больше 3 уровней федерации создают задержку данных (lag) более 2-3 минут.
- **Отсутствие сжатия:** Текстовый формат без gzip в 5–10 раз увеличивает нагрузку на сеть.
- **Слишком частый опрос:** Интервал < 30с не дает Leaf-серверу завершить Compaction и приводит к скачкам на графиках.

## Диагностика и решение проблем

| Проблема | Причина | Решение |
|---|---|---|
| **Leaf недоступен для федерации** | Фаервол блокирует входящие запросы от Master | Разрешить трафик от IP Master на порт 9090; проверить `iptables -L -n` |
| **Высокое потребление RAM на Leaf** | Слишком широкий `match[]` или regex-матринг | Добавить recording rules, сузить селекторы, включить gzip |
| **Данные не обновляются на Master** | Не настроены `external_labels` или сбой DNS | Проверить `honor_labels: true`, добавить `external_labels` на Leaf, проверить resolv.conf |
| **Дубликаты рядов на графиках** | Отсутствие `honor_labels: true` | Добавить `honor_labels: true` в конфигурацию Master |
| **Высокая задержка (lag) > 5 минут** | Глубокая иерархия (>3 уровней) или медленная сеть | Уменьшить количество уровней, увеличить интервал скрейпинга, перейти на Remote Write |
| **Ошибки 500/504 на `/federate`** | OOM или таймаут чтения TSDB | Увеличить `--query.lookback-delta`, проверить размер WAL, добавить RAM |
| **Утечка кардинальности при федерации** | Добавление новых лейблов на Master вместо Leaf | Перенести `relabel_configs` на Leaf, на Master только `honor_labels` и `external_labels` |
| **Федерация "забивает" сеть** | Отсутствие gzip или передача сырых данных | Включить `Accept-Encoding: gzip`, добавить recording rules на Leaf |

## Граничные случаи и ограничения

### Версия Prometheus 3.x и UTF-8
- Начиная с Prometheus 3.0, `/federate` поддерживает UTF-8 в именах метрик. Старые клиенты или прокси могут требовать escaping не-ASCII символов.
- `honor_labels` остаётся обязательным параметром; его отсутствие в конфигурации приводит к предупреждению в логах.

### Ограничения формата Instant Vector
- Федерация передает только последние значения (last samples). Для анализа трендов используйте recording rules на Master-уровне.
- Исторические данные не доступны через федерацию. Для долгосрочного хранения используйте Thanos или Remote Write.

### Глубокая иерархия (3+ уровня)
- Каждый уровень добавляет задержку, равную `scrape_interval` Master + время обработки.
- При >3 уровнях задержка данных превышает 2–3 минуты, что делает систему непригодной для оперативного алертинга.
- Рекомендация: не более 2 уровней (Leaf -> Regional -> Global), на Global уровне используйте LTS вместо третьей федерации.

### WAL и Compaction под нагрузкой федерации
- Активные запросы к `/federate` удерживают мьютекс на Head Block, что замедляет запись новых данных.
- При высокой частоте федерации (>1 запрос/сек на Leaf) WAL может вырасти до размера retention, что приведет к длинному запуску при рестарте.
- Решение: снизить частоту запросов или перейти на Remote Write.

### Согласованность external_labels
- При смене `external_labels` без очистки данных на Master-уровне возможны "разрывы" на графиках.
- Всегда делайте бэкап данных Master перед изменением `external_labels` на Leaf.

### Сетевые ограничения
- Федерация работает только по HTTP/HTTPS. Для сетей за NAT используйте reverse proxy или VPN.
- При использовании IPv6 убедитесь, что все узлы корректно разрешают DNS-имена Leaf-серверов.

## Дополнительная информация

### Лучшие практики (2025–2026)

1.  **Ограничивайте количество Leaf на одном Master:** Оптимально < 50. При большем количестве используйте Regional-уровень с Thanos Query.
2.  **Используйте Recording Rules на Leaf:** Создавайте агрегаты (сумма, среднее, перцентили) на стороне Leaf, чтобы Master запрашивал меньше рядов.
3.  **Включайте gzip на всех уровнях:** На Leaf (Nginx) и на Master (`Accept-Encoding: gzip`).
4.  **Не передавайте сырые данные через федерацию:** На Master-уровне собирайте только агрегаты и ключевые метрики (up, instance health).
5.  **Мониторьте здоровье федерации:** Отслеживайте задержку запросов, dropped samples и размер ответов `/federate`.

### Мониторинг федеративной архитектуры

```promql
# Количество активных Leaf-серверов
count by (job) (up{job=~"federate-.*"})

# Задержка данных с Leaf (разница между временем последнего скрейпа и текущим)
time() - max by (instance) (prometheus_remote_storage_highest_timestamp_in_seconds)

# Размер очереди Remote Write на Leaf (если используется параллельно)
prometheus_remote_storage_queue_capacity - prometheus_remote_storage_queue_samples
```

### См. также
*   [Масштабирование: обзор](./overview.md)
*   [Prometheus Remote Read/Write](./remote_read_write.md)
*   [Thanos: обзор](./thanos_overview.md)
*   [Prometheus Operator: HA](../kubernetes/operator/high_availability.md)
*   [Метки и кардинальность](../concepts/labels_and_cardinality.md)
*   [Стратегии сбора метрик](../../Concepts/Observability_and_Monitoring/metrics_collection_strategies.md)
