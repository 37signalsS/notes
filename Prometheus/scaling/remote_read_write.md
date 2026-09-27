# Удаленное чтение и запись в Prometheus (Remote Read/Write)

Удаленное чтение и запись (Remote Read/Write, PRW) — это стандартный механизм Prometheus, позволяющий отправлять (push) и запрашивать (pull) метрики из внешних систем длительного хранения (LTS). Этот протокол решает фундаментальные проблемы локальной базы данных TSDB: ограничение дискового пространства, отсутствие горизонтального масштабирования и отсутствие встроенной высокой доступности.

## Определения

| Механизм | Описание |
|---|---|
| **`remote_write`** | Процесс, при котором Prometheus (или агент сбора) в реальном времени отправляет собранные метрики во внешнее хранилище. |
| **`remote_read`** | Метод запроса исторических данных из внешнего хранилища при выполнении PromQL-запросов, если этих данных нет в локальной TSDB. Используется редко, обычно Grafana подключается напрямую к LTS. |
| **WAL (Write-Ahead Log)** | Журнал предзаписи. Надежный буфер на диске, который `remote_write` использует для хранения данных перед отправкой по сети, гарантируя защиту от потерь при разрывах связи. |

## Базовые концепции

### Архитектура и защита данных (WAL)

Механизм `remote_write` спроектирован так, чтобы гарантировать доставку данных (at-least-once delivery) даже в нестабильных сетях.

1.  **Чтение с диска, а не из памяти:** Компонент `remote_write` не берет данные напрямую из оперативной памяти (Head Block). Он читает их из локального файла **[WAL](../../Databases/Concepts/write_ahead_log.md)**. Это гарантирует сохранность данных при перезагрузке сервера.
2.  **Буферизация (Backfill):** Если внешнее хранилище недоступно, Prometheus просто перестает продвигать указатель чтения WAL. Метрики продолжают копиться на локальном диске в рамках настроенного времени `retention`.
3.  **Восстановление:** При восстановлении связи `remote_write` начинает агрессивную отправку накопленных данных (backfilling), используя параллельные потоки (shards), чтобы догнать текущее время.

#### Взаимодействие с сегментами WAL и чекпоинтами

Для понимания поведения `remote_write` при сбоях необходимо знать внутреннюю структуру WAL:

- **Сегменты WAL:** Файлы фиксированного размера (по умолчанию 512 МБ). Каждый сегмент содержит записи с сэмплами и служебными событиями.
- **Чекпоинты (Checkpoints):** Периодические снимки Head-блока, ускоряющие восстановление. При создании чекпоинта старые сегменты WAL, данные из которых уже записаны в блоки, могут быть удалены.
- **Взаимодействие с remote_write:** Компонент читает из WAL только неподтвержденные (не отправленные в LTS) сэмплы. После успешной отправки WAL не изменяется — данные удаляются только после записи в постоянные блоки и прохождения retention.

#### Механизм backfill при восстановлении связи

При восстановлении связи после долгой недоступности LTS происходит следующее:

1. **Определение лага:** `remote_write` вычисляет разницу между последним отправленным временем и текущим временем.
2. **Активация шардов:** Увеличивается `max_shards` до настроенного максимума для ускорения отправки.
3. **Пауза перед отправкой:** По умолчанию Prometheus ждет `batch_send_deadline` перед отправкой первого батча, чтобы собрать достаточное количество сэмплов.
4. **Управление переполнением:** Если LTS не успевает обрабатывать данные, Prometheus замедляет чтение WAL, предотвращая переполнение очереди. Если очередь заполнена полностью — сэмплы отбрасываются (метрика `prometheus_remote_storage_dropped_samples_total`).

### Эволюция протокола: Remote Write 2.0 (Стандарт 2025–2026)

Начиная с версии Prometheus 3.0, спецификация **PRW 2.0** стала основным стандартом, радикально снижающим потребление ресурсов:

*   **Интернирование строк (String Interning):** В PRW 1.0 каждое имя метрики и лейбла передавалось текстом в каждом пакете. В PRW 2.0 используется словарь (symbol table). Строка отправляется один раз, а далее передается только ее числовой ID. Это **снижает объем исходящего Egress-трафика на 50–60%** и нагрузку на CPU хранилища (Mimir/VictoriaMetrics).
*   **Сжатие данных (Compression):** В дополнение к алгоритму `snappy` добавлена поддержка `zstd`, который обеспечивает лучший коэффициент сжатия при сопоставимой нагрузке на процессор.
*   **Метаданные и OTLP:** PRW 2.0 нативно передает типы метрик (Counter, Gauge, Histogram) и единицы измерения, что делает его полностью совместимым с форматом OpenTelemetry (OTLP) и поддержкой UTF-8.
*   **Created Timestamps:** Передача временных меток создания серии позволяет корректно обрабатывать сбросы счетчиков (counter resets) на стороне LTS, повышая точность функций `rate()` и `increase()`.

## Практические сценарии и параметры конфигурации

### Базовые параметры `remote_write`

| Параметр | Default | Описание |
|---|---|---|
| `url` | — | URL эндпоинта удалённого хранилища. |
| `remote_timeout` | `30s` | Таймаут одного HTTP-запроса записи. При медленной сети стоит увеличить. |
| `send_exemplars` | `false` | Включает отправку Exemplars (ссылки на трейсы) вместе с метриками. |
| `send_native_histograms` | `false` | Отправка высокоточных Native Histograms (экспериментально). |
| `write_relabel_configs` | — | Мощный инструмент фильтрации и модификации меток **до** их отправки в сеть. |
| `name` | (хэш) | Уникальное имя очереди в метриках (полезно при наличии нескольких `remote_write`). |

### Промetheus Agent Mode + Remote Write

**Prometheus Agent Mode** — это режим сбора метрик без локального TSDB (введен в v2.32.0, стабилизирован в v3.x). В этом режиме:

- Замена TSDB на облегченный WAL (только для исходящих данных).
- Потребление CPU/RAM на 30–40% ниже, чем в Server Mode.
- Отсутствие выполнения правил (recording/alerting) и тяжелых запросов.
- Все собранные метрики immediately отправляются через `remote_write`.

**Когда использовать Agent Mode:**
- Edge-кластеры с ограниченными ресурсами.
- Сценарии, где нужен только сбор и пересылка данных в центральный кластер.
- Миграция с устаревших агентов (например, Graphite/StatsD мостов).

**Пример конфигурации Agent Mode:**
```bash
prometheus \
  --enable-feature=agent \
  --storage.tsdb.path=/tmp/prometheus \
  --storage.tsdb.retention.time=24h \
  --remote-write.url=http://victoriametrics:8428/api/v1/write \
  --remote-write.queue-config.max-shards=50
```

> **Важно:** В Agent Mode локальный WAL хранится только 24 часа (по умолчанию). При недоступности LTS дольше этого окна данные будут потеряны. Для production увеличьте `--storage.tsdb.retention.time` в зависимости от допустимого downtime LTS.

### Фильтрация мусора (Relabeling)

Обязательная практика для снижения затрат на хранилище: не отправляйте в LTS мусорные или отладочные метрики.

```yaml
remote_write:
  - url: 'http://victoriametrics:8428/api/v1/write'
    write_relabel_configs:
      # Отбросить все метрики сборщика мусора Go
      - source_labels: [__name__]
        regex: '^go_gc_.*'
        action: drop
      # Удалить высококардинальные лейблы (эфемерные порты)
      - source_labels: [instance]
        regex: '(.*):[0-9]+'
        target_label: instance
        replacement: '$1'
      # Оставить только заданные метрики (опционально)
      - source_labels: [__name__]
        regex: 'up|node_cpu_seconds_total|node_memory_MemAvailable_bytes'
        action: keep
```

#### Лучшие практики relabeling для remote_write

1. **Фильтруйте на источнике:** Применяйте `metric_relabel_configs` на уровне scrape_config, чтобы ненужные метрики вообще не попадали в WAL.
2. **Держите конфиг под контролем версий:** Изменения в `write_relabel_configs` влияют на то, какие данные попадут в LTS. Без контроля версий возможна потеря исторических данных.
3. **Тестируйте правила:** Используйте `promtool` для проверки корректности relabeling перед применением в production:
   ```bash
   promtool test rules prometheus.yml
   ```

### Безопасность: Auth, TLS и mTLS

**Пример 1: Basic Auth и TLS**
```yaml
remote_write:
  - url: 'https://victoriametrics.example.com/api/v1/write'
    tls_config:
      ca_file: '/etc/prometheus/certs/ca.crt'
      cert_file: '/etc/prometheus/certs/client.crt'
      key_file: '/etc/prometheus/certs/client.key'
    basic_auth:
      username: 'prom-writer'
      password_file: '/etc/prometheus/secrets/vm-pass'
```

**Пример 2: Bearer Token (Self-hosted / Kubernetes)**
```yaml
remote_write:
  - url: 'https://thanos-receive.monitoring.svc:19291/api/v1/receive'
    bearer_token_file: '/var/run/secrets/kubernetes.io/serviceaccount/token'
```

**Пример 3: OAuth2 / OIDC с самохостенным IdP (Keycloak, Dex)**
Использование внутреннего OAuth2-провайдера без внешних облачных сервисов:
```yaml
remote_write:
  - url: 'https://lts.monitoring.internal/api/v1/push'
    oauth2:
      client_id: 'prometheus-sa'
      client_secret_file: '/etc/prometheus/secrets/oauth2-secret'
      token_url: 'https://keycloak.monitoring.internal/realms/internal/protocol/openid-connect/token'
      scopes:
        - 'remote_write'
```

**Пример 4: mTLS с сертификатами**
```yaml
remote_write:
  - url: 'https://mimir.monitoring.internal/api/v1/push'
    tls_config:
      ca_file: '/etc/prometheus/certs/ca.crt'
      cert_file: '/etc/prometheus/certs/client.crt'
      key_file: '/etc/prometheus/certs/client.key'
      server_name: 'mimir.monitoring.internal'
```

### Настройка в Prometheus Operator (CRD)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
spec:
  remoteWrite:
    - url: "http://victoria-metrics.monitoring.svc:8428/api/v1/write"
      sendExemplars: true
      queueConfig:
        maxShards: 100
      writeRelabelConfigs:
        - action: drop
          regex: "container_network_.*"
          sourceLabels: [__name__]
```

## Тюнинг и эксплуатация

### Настройка очереди отправки (`queue_config`)

Тюнинг очереди критически важен для высоконагруженных систем (>100k samples/s).

| Параметр | Default | SRE Тюнинг / Описание |
|---|---|---|
| `capacity` | `10000` | Размер буфера в сэмплах на каждый шард. Увеличьте при нестабильной сети. |
| `max_shards` | `200` | Максимальное число параллельных потоков. Для больших потоков: `1000–2000`. |
| `min_shards` | `1` | Минимальное число потоков. Для стабильной нагрузки: `min_shards == max_shards`. |
| `max_samples_per_send`| `500` | Максимум сэмплов в батче. Увеличение до `5000` снижает накладные расходы на HTTP. |
| `batch_send_deadline` | `5s` | Максимальное время ожидания перед отправкой неполного батча. |
| `min_backoff` | `30ms` | Начальная пауза при ретраях (ошибки 5xx). |
| `max_backoff` | `5s` | Максимальная пауза при ретраях. При лагах LTS увеличьте до `15s`. |

#### Внутренние механизмы очереди

Очередь `remote_write` работает по принципу **sharded queue**:

1. **WAL Reader:** Отдельный поток на каждый шард читает необработанные сэмплы из WAL.
2. **Валидация:** Сэмплы проходят через `write_relabel_configs`. Отброшенные сэмплы не попадают в очередь.
3. **Баткинг:** Сэмплы группируются в батчи размером `max_samples_per_send` или по времени `batch_send_deadline`.
4. **HTTP Client:** Каждый шард отправляет батч через HTTP. При ошибках 5xx или таймаутах выполняется ретрай с экспоненциальным backoff.
5. **WAL Advance:** После успешной отправки указатель чтения WAL продвигается. При ошибке указатель остается, и сэмплы будут повторно отправлены при следующей попытке (at-least-once).

**Мониторинг лага:**
- `prometheus_remote_storage_highest_timestamp_in_seconds`: время последнего скрейпа.
- `prometheus_remote_storage_queue_highest_sent_timestamp_seconds`: время последнего отправленного сэмпла.
- **Лаг** = разница между ними. Если растет — увеличивайте `max_shards`.
- `prometheus_remote_storage_dropped_samples_total`: критическая метрика потери данных.

### Диагностика и решение проблем

| Проблема | Причина | Решение |
|---|---|---|
| **Высокий лаг Remote Write** | Недостаточно `max_shards`, медленная сеть или перегрузка LTS | Увеличить `max_shards` и `capacity`; проверить задержку сети до LTS; убедиться, что LTS не в режиме read-only |
| **Дропнутые сэмплы** | Переполнение очереди, недоступность LTS или ошибки 4xx/5xx | Проверить `prometheus_remote_storage_dropped_samples_total`; увеличить `capacity` и `max_shards`; проверить логи LTS |
| **WAL заполняется при недоступности LTS** | Длительный downtime LTS превышает `retention` | Увеличить `retention` на время проведения ремонтных работ; использовать `retentionSize` вместо времени для защиты от переполнения |
| **Высокое потребление RAM** | Слишком много шардов (каждый держит буфер `capacity`) | Снизить `max_shards` и увеличить `capacity`; проверить утечки памяти Go |
| **Ошибки 429 (Too Many Requests)** | LTS троттлит Prometheus | Увеличить `batch_send_deadline` и `max_backoff`; согласовать лимиты с командой LTS |
| **Медленный старт после сбоя** | Большой объем данных в WAL для backfill | Включить `min_backoff: 30ms` и `max_backoff: 5s`; рассмотреть предварительное оповещение LTS оplanned downtime |
| **Сетевые таймауты при TLS** | Неправильная конфигурация сертификатов или большая латентность | Увеличить `remote_timeout` до `60s`; проверить срок действия сертификатов; использовать IP вместо DNS для снижения задержки |

### Параметры `remote_read`

Использование `remote_read` считается антипаттерном. Grafana должна обращаться в LTS напрямую.

| Параметр | Default | Описание |
|---|---|---|
| `url` | — | URL эндпоинта удалённого чтения. |
| `remote_timeout` | `1m` | Таймаут запроса. Может требовать увеличения до `2m-5m`. |
| `read_recent` | `false` | Если `true`, Prometheus запрашивает из сети даже свежие данные (игнорируя Head Block). |
| `required_matchers` | — | Фильтр для отправки запроса в сеть только при наличии определенных меток. |

## Планирование мощностей (Capacity Planning)

### Расчет размера WAL для remote_write

WAL в сценарии с remote_write служит буфером между сбором метрик и отправкой в LTS. Размер WAL напрямую влияет на время восстановления после сбоя и допустимый downtime LTS.

**Формула приблизительного размера WAL:**
```
WAL Size ≈ (samples_per_second × bytes_per_sample × retention_seconds) + overhead
```

Где:
- `samples_per_second`: пиковая скорость сбора.
- `bytes_per_sample`: ~0.5–2 байта на сэмпл (зависит от кардинальности и сжатия WAL в Prometheus v3).
- `retention_seconds`: время, на которое хватает буфера.
- `overhead`: ~10–20% на сегменты WAL и чекпоинты.

**Пример расчета:**
- 500k samples/s × 1 байт/сэмпл × 86400 сек (сутки) = ~43 ГБ WAL на сутки.
- Для допуска простоя LTS 48 часов: ~86 ГБ + overhead = 100 ГБ.

**Рекомендации:**
- Выделяйте WAL на отдельный быстрый диск (NVMe SSD). WAL критичен к латентности записи (каждый сэмпл требует `fsync`).
- Настройка `--storage.tsdb.retention.time` для Agent Mode: не менее 2× ожидаемого максимального downtime LTS.
- В Kubernetes используйте отдельный PVC для WAL с StorageClass на быстрых SSD.

### Параметры ядра Linux для remote_write

```bash
# /etc/sysctl.d/99-prometheus-remote-write.conf

# Увеличение открытых файлов (несколько тысяч HTTP-соединений)
fs.file-max = 1000000

# Оптимизация TCP для множества параллельных соединений
net.core.rmem_default = 262144
net.core.wmem_default = 262144
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_intvl = 75
net.ipv4.tcp_keepalive_probes = 9

# Оптимизация для SSD
vm.dirty_ratio = 20
vm.dirty_background_ratio = 10
```

Примените: `sysctl --system`

## Граничные случаи и ограничения

### At-Least-Once Delivery и дубликаты

Протокол `remote_write` гарантирует **at-least-once delivery**:
- При разрыве связи уже отправленные сэмплы могут быть повторно отправлены после восстановления.
- LTS-хранилище (VictoriaMetrics, Mimir) отвечает за идемпотентность: дубликаты определяются по комбинации `time_ms` + `fingerprint` (хэш имени метрики и лейблов).
- Prometheus не хранит состояние отправленных сэмплов — это ответственность LTS.

### Ограничения WAL при prolonged outage

Если LTS недоступен дольше `--storage.tsdb.retention.time`:
1. Prometheus продолжает накапливать данные в WAL до достижения лимита retention.
2. После превышения retention старые сегменты WAL удаляются.
3. Данные, содержащиеся в удаленных сегментах, **безвозвратно теряются**.
4. При восстановлении связи произойдет backfill только оставшихся данных.

**Рекомендация:** Настройте `retentionSize` вместо `retention` для Agent Mode, чтобы предотвратить переполнение диска:
```bash
--storage.tsdb.retention.size=200Gi
```

### Ограничения Prometheus 3.x (Agent Mode и OTLP)

- **Agent Mode не выполняет правила:** Recording и Alerting rules в этом режиме отсутствуют. Всю логику обработки переносите на LTS.
- **OTLP и deduplication:** Входящий OTLP-трафик не балансируется между репликами автоматически. Используйте внешний балансировщик (MetalLB, IPVS, Nginx).
- **Native Histograms в remote_write:** Поддержка `send_native_histograms` в v3 улучшилась, но не все LTS поддерживают полную совместимость. Проверьте документацию целевого хранилища.

## Дополнительная информация

### Поддерживаемые хранилища (2025–2026)

| Хранилище | Архитектура | Примечание |
|---|---|---|
| **Grafana Mimir** | Microservices | 100% совместимость, мульти-тенантность, PRW 2.0. |
| **VictoriaMetrics** | Cluster/Single | Экстремальная производительность, нативное сжатие. |
| **Thanos Receive** | Gateway | Шлюз для выгрузки блоков в S3/GCS. |
| **ClickHouse** | Columnar DB | Через адаптер. Идеально для петабайтных логов метрик. |
| **TimescaleDB** | PostgreSQL | SQL-интерфейс поверх временных рядов (через адаптер). |
| **OpenTelemetry Collector** | Gateway | Прием PRW и конвертация в OTLP для любых систем. |

### См. также
*   [Масштабирование: обзор](./overview.md)
*   [Внутреннее устройство TSDB](../concepts/tsdb.md)
*   [Thanos: архитектура](./thanos_overview.md)
