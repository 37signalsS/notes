# Устранение неполадок Prometheus

## Определения

**Troubleshooting Prometheus** — систематическая методология диагностики и устранения проблем, связанных со сбором, хранением, запросами и оповещениями метрик. Включает анализ симптомов, проверку гипотез и применение решений для восстановления работоспособности системы мониторинга.

> **См. также:** [Безопасность Prometheus](./security.md), [TSDB](./concepts/tsdb.md), [Capacity Planning](./installation/capacity_planning.md), [Масштабирование](./scaling/overview.md).

## Основные концепции

### Методология диагностики

Подход к устранению неполадок строится по алгоритму: **Симптом -> Гипотеза -> Диагностика -> Решение -> Верификация**.

| Этап | Действие | Инструменты |
| :--- | :--- | :--- |
| **1. Симптом** | Определить, что именно не работает | Метрики самого Prometheus, логи, Grafana |
| **2. Гипотеза** | Предположить причину на основе симптома | Знание архитектуры TSDB, сети, конфигурации |
| **3. Диагностика** | Проверить гипотезу через конкретные команды | `promtool`, `curl`, `ss`, `df`, `journalctl` |
| **4. Решение** | Применить исправление | Редактирование конфигурации, перезапуск, тюнинг |
| **5. Верификация** | Убедиться, что проблема решена | Повторная проверка метрик и логов |

### Ключевые диагностические эндпоинты

```bash
# Базовая проверка здоровья
curl -s http://localhost:9090/-/healthy   # -> Prometheus Server is Healthy.
curl -s http://localhost:9090/-/ready     # -> Prometheus Server is Ready.

# Статус TSDB (топ метрик по кардинальности)
curl -s http://localhost:9090/api/v1/status/tsdb | jq .

# Список флагов запуска
curl -s http://localhost:9090/api/v1/status/flags | jq .

# Текущая конфигурация
curl -s http://localhost:9090/api/v1/status/config | jq .

# Активные цели скрейпинга
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health}'

# Загруженные правила
curl -s http://localhost:9090/api/v1/rules | jq '.data.groups[] | {name: .name, rules: (.rules | length)}'

# Активные алерты
curl -s http://localhost:9090/api/v1/alerts | jq '.data.alerts[] | {alertname: .labels.alertname, state: .state}'
```

### Матрица симптомов

| Симптом | Вероятные причины | Приоритет диагностики |
| :--- | :--- | :--- |
| `up == 0` | Target недоступен, scrape_timeout, сеть | Средний |
| Prometheus не запускается | Ошибка конфигурации, повреждение WAL, нехватка диска | Высокий |
| OOM Kill | Взрыв кардинальности, тяжёлые PromQL-запросы | Критический |
| Медленные запросы | Высокая кардинальность, отсутствие recording rules, regex в селекторах | Средний |
| Нет данных за период | Scrape gaps, retention, компакция | Средний |
| Диск заполняется | Рост cardinality, отсутствие retention, WAL без компакции | Высокий |
| Remote Write fails | Очередь переполнена, LTS недоступен, сеть | Высокий |
| Алерты не приходят | Alertmanager недоступен, ошибка маршрутизации, inhibit | Средний |

## Практические сценарии

### Сценарий 1: Prometheus не запускается

**Симптом:** `systemctl status prometheus` показывает `failed`, процесс завершается сразу после старта.

**Диагностика:**

```bash
# 1. Проверка логов (причина ошибки)
journalctl -u prometheus -n 100 --no-pager
# -> Типичные ошибки:
#   "error parsing config yaml" - ошибка в prometheus.yml
#   "WAL corruption" - повреждение WAL
#   "no space left on device" - заполнен диск

# 2. Валидация конфигурации
promtool check config /etc/prometheus/prometheus.yml
# -> SUCCESS или описание ошибки

# 3. Проверка прав на файлы
ls -la /etc/prometheus/prometheus.yml
ls -la /var/lib/prometheus/
# -> Владелец должен быть prometheus:prometheus

# 4. Проверка порта
ss -tlnp | grep 9090
# -> Если порт занят - другой процесс или не перезапущен старый
```

**Решения:**

| Причина | Решение |
| :--- | :--- |
| Ошибка в `prometheus.yml` | Исправить синтаксис, выполнить `promtool check config` |
| Повреждение WAL | Удалить содержимое `wal/` (потеря до 2 часов данных) |
| Нехватка диска | Очистить старые блоки, уменьшить retention, расширить диск |
| Порт занят | Найти процесс: `ss -tlnp \| grep 9090`, остановить конфликтующий сервис |
| Права доступа | `chown -R prometheus:prometheus /etc/prometheus /var/lib/prometheus` |

```bash
# Восстановление после повреждения WAL (крайний случай)
systemctl stop prometheus
rm -rf /var/lib/prometheus/wal/*
systemctl start prometheus
# -> Потеря данных за последние 2 часа
```

### Сценарий 2: OOM Kill (нехватка памяти)

**Симптом:** Процесс Prometheus убит ядром Linux, в `dmesg` или `journalctl` видно `Out of memory: Kill process`.

**Диагностика:**

```bash
# 1. Проверка потребления памяти
curl -s 'http://localhost:9090/api/v1/query?query=process_resident_memory_bytes' | jq '.data.result[0].value[1]'

# 2. Проверка количества активных серий
curl -s 'http://localhost:9090/api/v1/query?query=prometheus_tsdb_head_series' | jq '.data.result[0].value[1]'
# -> Если > 1M - вероятная причина

# 3. Поиск метрики с высокой кардинальностью
curl -s 'http://localhost:9090/api/v1/status/tsdb' | jq '.data.seriesCountByMetricName[:10]'

# 4. Проверка GOMEMLIMIT (в контейнерах)
echo $GOMEMLIMIT
# -> Должен быть установлен на 85-90% от limits.memory
```

**Решения:**

| Причина | Решение |
| :--- | :--- |
| Взрыв кардинальности | Удалить высококардинальные метки через `metric_relabel_configs` |
| Тяжёлые PromQL-запросы | Добавить `--query.max-samples=50000000`, оптимизировать запросы |
| Недостаточно RAM | Увеличить `limits.memory` (K8s) или выделить больше RAM (bare-metal) |
| GOMEMLIMIT не установлен | Установить `GOMEMLIMIT` на 85-90% от лимита памяти |
| Native Histograms отключены | Включить для снижения количества рядов (до 40% экономии) |

```yaml
# Устранение высококардинальных меток
scrape_configs:
  - job_name: 'problematic-app'
    metric_relabel_configs:
      - source_labels: [request_id]
        regex: '.+'
        action: labeldrop
      - source_labels: [session_id]
        regex: '.+'
        action: labeldrop
```

### Сценарий 3: Медленные PromQL-запросы

**Симптом:** Grafana таймаутится, запросы в Web UI висят дольше 30 секунд.

**Диагностика:**

```bash
# 1. Проверка длительности запросов
curl -s 'http://localhost:9090/api/v1/query?query=prometheus_engine_query_duration_seconds' | jq '.data.result[] | {quantile: .metric.quantile, value: .value[1]}'

# 2. Проверка количества активных серий
curl -s 'http://localhost:9090/api/v1/query?query=prometheus_tsdb_head_series' | jq '.data.result[0].value[1]'

# 3. Анализ конкретного запроса через explain (v3.13+)
curl -G 'http://localhost:9090/api/v1/query' \
  --data-urlencode 'query=sum(rate(http_requests_total[5m])) by (job)' \
  --data-urlencode 'explain=true' | jq '.data.explanation'

# 4. Проверка recording rules
curl -s 'http://localhost:9090/api/v1/rules' | jq '.data.groups[].rules[] | select(.type=="recording") | .name'
```

**Типичные причины и решения:**

| Причина | Пример | Решение |
| :--- | :--- | :--- |
| Regex в селекторах | `job=~".*api.*"` | Заменить на точное совпадение: `job="api-server"` |
| Широкий временной диапазон | `rate(...[24h])` | Использовать recording rules для предвычисления |
| Высокая кардинальность в `by()` | `sum by (user_id)` | Агрегировать по `job` или `instance` |
| Отсутствие recording rules | Сложные агрегации на лету | Создать recording rules для тяжёлых запросов |
| Маленький `step` | `step=15s` за 7 дней | Увеличить `step` до `1h` для длинных диапазонов |

```yaml
# Recording rules для ускорения тяжёлых запросов
groups:
  - name: accelerated_rules
    interval: 30s
    rules:
      - record: job:http_requests:rate5m
        expr: sum(rate(http_requests_total[5m])) by (job)

      - record: job:http_errors:ratio5m
        expr: sum(rate(http_requests_total{code=~"5.."}[5m])) by (job)
          / job:http_requests:rate5m
```

### Сценарий 4: `up == 0` - Target недоступен

**Симптом:** Цель показывает `health: down` в `/api/v1/targets`, метрики не поступают.

**Диагностика:**

```bash
# 1. Проверка конкретной цели
curl -s 'http://localhost:9090/api/v1/targets' | jq '.data.activeTargets[] | select(.health=="down") | {instance: .labels.instance, lastError: .lastError}'

# 2. Проверка доступности target из Prometheus
curl -v http://<target>:9100/metrics 2>&1 | head -20

# 3. Проверка scrape_timeout
curl -s 'http://localhost:9090/api/v1/status/flags' | jq '.data["scrape.timeout"]'

# 4. Проверка последних ошибок скрейпинга
curl -s 'http://localhost:9090/api/v1/targets' | jq '.data.activeTargets[] | select(.health=="down") | {instance: .labels.instance, lastScrape: .lastScrape, lastError: .lastError}'
```

**Решения:**

| `lastError` | Причина | Решение |
| :--- | :--- | :--- |
| `context deadline exceeded` | Target не отвечает или scrape_timeout слишком мал | Увеличить `scrape_timeout`, проверить сеть |
| `connection refused` | Target не слушает порт | Проверить: `ss -tlnp \| grep 9100` |
| `no such host` | DNS не резолвится | Проверить DNS: `nslookup <hostname>` |
| `HTTP status 403` | Forbidden - нет доступа | Проверить Basic Auth / firewall |
| `HTTP status 502` | Bad Gateway - прокси вернул ошибку | Проверить reverse proxy |
| `text format parsing error` | Невалидный формат метрик | Проверить `/metrics` на target вручную |

### Сценарий 5: Диск заполняется

**Симптом:** `df -h` показывает высокое использование диска.

**Диагностика:**

```bash
# 1. Проверка размера TSDB
du -sh /var/lib/prometheus/
du -sh /var/lib/prometheus/wal/
du -sh /var/lib/prometheus/chunks_head/

# 2. Количество блоков на диске
ls -la /var/lib/prometheus/ | grep "^d" | wc -l

# 3. Проверка retention
curl -s 'http://localhost:9090/api/v1/status/flags' | jq '.data["storage.tsdb.retention.time"]'

# 4. Проверка размера WAL
curl -s 'http://localhost:9090/api/v1/query?query=prometheus_tsdb_wal_size_bytes' | jq '.data.result[0].value[1]'
```

**Решения:**

| Причина | Решение |
| :--- | :--- |
| Retention слишком длинный | Уменьшить `--storage.tsdb.retention.time` (30d -> 15d) |
| WAL не компактируется | Проверить `prometheus_tsdb_compaction_delay_seconds`, увеличить CPU |
| Метрики-призраки | Удалить через `DELETE /api/v1/admin/tsdb/delete_series` |
| WAL растёт из-за remote_write | Проверить доступность LTS, увеличить `max_shards` |
| `retention.size` не настроен | Добавить `--storage.tsdb.retention.size=50GB` |

```bash
# Очистка "мертвых" метрик (пометка на удаление)
curl -X POST -d '{"match[]":"old_unused_metric"}' \
  http://localhost:9090/api/v1/admin/tsdb/delete_series
# Физическое удаление произойдет при следующей компакции
```

### Сценарий 6: Remote Write не работает

**Симптом:** `prometheus_remote_storage_dropped_samples_total` растёт, данные не доходят до LTS.

**Диагностика:**

```bash
# 1. Проверка dropped samples
curl -s 'http://localhost:9090/api/v1/query?query=rate(prometheus_remote_storage_dropped_samples_total[5m])' | jq '.data.result[0].value[1]'

# 2. Проверка задержки отправки
curl -s 'http://localhost:9090/api/v1/query?query=prometheus_remote_storage_highest_timestamp_in_seconds - prometheus_remote_storage_queue_highest_sent_timestamp_seconds' | jq '.data.result[0].value[1]'

# 3. Проверка доступности LTS
curl -v http://<lts-host>:8428/api/v1/write 2>&1 | head -10
```

**Решения:**

| Причина | Решение |
| :--- | :--- |
| LTS недоступен | Проверить сеть, DNS, firewall до LTS-сервера |
| Очередь переполнена | Увеличить `queue_config.max_shards` и `queue_config.capacity` |
| TLS ошибка | Проверить сертификаты, `insecure_skip_verify` для тестов |
| Очередь забита из-за медленного LTS | Увеличить `max_samples_per_send`, проверить IOPS на LTS |

```yaml
# Оптимизация queue_config для Remote Write
remote_write:
  - url: "http://victoriametrics:8428/api/v1/write"
    queue_config:
      max_samples_per_send: 2000
      batch_send_deadline: 5s
      max_shards: 30
      capacity: 10000
      min_shards: 5
```

### Сценарий 7: Алерты не приходят в Alertmanager

**Симптом:** Prometheus показывает `Firing` алерты, но Alertmanager их не получает.

**Диагностика:**

```bash
# 1. Проверка активных алертов в Prometheus
curl -s 'http://localhost:9090/api/v1/alerts' | jq '.data.alerts[] | select(.state=="firing") | .labels.alertname'

# 2. Проверка конфигурации alerting в Prometheus
curl -s 'http://localhost:9090/api/v1/status/config' | grep -A5 "alerting:"

# 3. Проверка доступности Alertmanager
curl -s http://localhost:9093/-/healthy

# 4. Проверка кластерного состояния Alertmanager
curl -s http://localhost:9093/api/v2/status | jq '.cluster.peers'

# 5. Проверка маршрутизации (amtool)
amtool config routes --config.file=/etc/alertmanager/alertmanager.yml
```

**Решения:**

| Причина | Решение |
| :--- | :--- |
| Alertmanager не доступен | Проверить сеть, DNS, порт 9093 |
| Ошибка в маршрутизации | Проверить `route.receiver` и `match` в alertmanager.yml |
| Inhibit rules блокируют | Проверить `inhibit_rules` через `amtool config routes` |
| Mute Timing активен | Проверить `mute_time_intervals` в текущий временной промежуток |
| Кластер Alertmanager не здоров | Проверить `amtool cluster peer` и gossip-соединения |

### Сценарий 8: Compaction stall (зависание компакции)

**Симптом:** `prometheus_tsdb_compaction_delay_seconds` растёт, Head Block не сбрасывается на диск.

**Диагностика:**

```bash
# 1. Проверка задержки компакции
curl -s 'http://localhost:9090/api/v1/query?query=prometheus_tsdb_compaction_delay_seconds' | jq '.data.result[0].value[1]'

# 2. Проверка количества блоков
curl -s 'http://localhost:9090/api/v1/query?query=prometheus_tsdb_blocks_loaded' | jq '.data.result[0].value[1]'

# 3. Проверка IOPS диска
iostat -x 1 5

# 4. Проверка размера Head Block
curl -s 'http://localhost:9090/api/v1/query?query=prometheus_tsdb_head_chunks' | jq '.data.result[0].value[1]'
```

**Решения:**

| Причина | Решение |
| :--- | :--- |
| Недостаточно CPU | Увеличить CPU (компакция - CPU-bound операция) |
| Медленный диск | Переместить TSDB на NVMe SSD |
| Слишком много маленьких блоков | Увеличить `--storage.tsdb.max-block-duration` |
| Очень высокий ingestion rate | Рассмотреть sharding или Agent Mode |

### Сценарий 9: Нет данных за определённый период

**Симптом:** На графиках видны "дырки" - пропуски данных за конкретные промежутки времени.

**Диагностика:**

```bash
# 1. Проверка статуса целей за этот период (через TSDB)
curl -s 'http://localhost:9090/api/v1/query?query=changes(prometheus_tsdb_head_series[1h])' | jq '.data.result[:5]'

# 2. Проверка перезапусков Prometheus
curl -s 'http://localhost:9090/api/v1/query?query=time() - prometheus_start_time_seconds' | jq '.data.result[0].value[1]'

# 3. Проверка scrape_interval vs step в Grafana
# step должен быть >= scrape_interval

# 4. Проверка stale markers
# Если target перезапускался, Prometheus ставит stale markers через 5 минут
```

**Решения:**

| Причина | Решение |
| :--- | :--- |
| Target был перезапущен | Нормальное поведение, данные восстановятся после старта target |
| Prometheus перезапускался | Проверить WAL, увеличить retention |
| Scrape timeout меньше, чем время ответа | Увеличить `scrape_timeout` |
| Gap в remote write | Проверить `prometheus_remote_storage_dropped_samples_total` |
| Compaction удалила данные | Проверить `retention.time`, не слишком ли он мал |

### Сценарий 10: Высокий Churn Rate

**Симптом:** `prometheus_tsdb_head_series` быстро растёт, индекс раздувается.

**Диагностика:**

```bash
# 1. Проверка скорости создания новых серий
curl -s 'http://localhost:9090/api/v1/query?query=rate(prometheus_tsdb_head_series_created_total[5m])' | jq '.data.result[0].value[1]'

# 2. Поиск метрик с высоким churn
curl -s 'http://localhost:9090/api/v1/status/tsdb' | jq '.data.seriesCountByLabelName[:10]'

# 3. Проверка ephemeral labels (Kubernetes pod names, request IDs)
curl -s 'http://localhost:9090/api/v1/label/pod/values' | jq 'length'
# -> Если pod nameLabel имеет тысячи значений - проблема
```

**Решения:**

| Причина | Решение |
| :--- | :--- |
| Pod names в лейблах | Использовать `honor_labels: true` или `metric_relabel_configs` |
| Session IDs / Request IDs | Удалять через `labeldrop` в `metric_relabel_configs` |
| Короткоживущие поды в K8s | Использоватьstable labels: `app.kubernetes.io/name` вместо pod name |
| Метрики с dynamic labels | Рассмотреть Native Histograms вместо отдельных серий |

```yaml
# Удаление ephemeral labels из Kubernetes
scrape_configs:
  - job_name: 'kubernetes-pods'
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        target_label: app
      # Удалить pod-specific labels
      - action: labeldrop
        regex: '__meta_kubernetes_pod_label_pod_template_hash'
      - action: labeldrop
        regex: '__meta_kubernetes_pod_label_controller_uid'
```

## Дополнительная информация

### Быстрый чеклист при инциденте

1. Проверить `/-/healthy` и `/-/ready`
2. Проверить `prometheus_tsdb_head_series` (кардинальность)
3. Проверить `process_resident_memory_bytes` (RAM)
4. Проверить `prometheus_tsdb_wal_size_bytes` (диск)
5. Проверить `rate(prometheus_http_requests_total{code=~"5.."}[5m])` (ошибки API)
6. Проверить `up` (все ли цели доступны)
7. Проверить логи: `journalctl -u prometheus -n 50 --no-pager`

### Полезные PromQL-запросы для диагностики

```promql
# Потребление RAM процессом Prometheus
process_resident_memory_bytes

# Количество активных серий
prometheus_tsdb_head_series

# Размер WAL
prometheus_tsdb_wal_size_bytes

# Скорость записи сэмплов
rate(prometheus_tsdb_head_samples_appended_total[5m])

# Количество блоков на диске
prometheus_tsdb_blocks_loaded

# Задержка компакции
prometheus_tsdb_compaction_delay_seconds

# Ошибки HTTP API
rate(prometheus_http_requests_total{code=~"5.."}[5m])

# Dropped samples при remote write
rate(prometheus_remote_storage_dropped_samples_total[5m])

# Время выполнения PromQL-запросов (99-й перцентиль)
histogram_quantile(0.99, rate(prometheus_engine_query_duration_seconds_bucket[5m]))

# Все цели в состоянии down
up == 0
```

### Профилирование Prometheus (pprof)

```bash
# Включить профилирование (добавить флаг)
--web.enable-pprof

# Сбор CPU-профиля (30 секунд)
curl -o cpu.prof http://localhost:9090/debug/pprof/profile?seconds=30

# Сбор memory-профиля
curl -o mem.prof http://localhost:9090/debug/pprof/heap

# Анализ через go tool pprof
go tool pprof cpu.prof
go tool pprof mem.prof

# Топ потребителей CPU
go tool pprof -top cpu.prof

# Топ потребителей RAM
go tool pprof -top -inuse_space mem.prof
```

### Лучшие практики по диагностике

1. **Всегда начинайте с логов:** `journalctl -u prometheus` или `docker logs prometheus`
2. **Используйте `promtool`:** `promtool check config`, `promtool check rules`, `promtool query`
3. **Мониторьте самомониторинг:** Настройте алерты на метрики самого Prometheus
4. **Создайте runbook:** Документируйте типичные проблемы и решения
5. **Ведите журнал инцидентов:** Записывайте что произошло, какие действия были предприняты
6. **Тестируйте алерты:** Используйте `promtool test rules` для валидации

### См. также

*   [Безопасность Prometheus](./security.md) - диагностика проблем с TLS и авторизацией
*   [TSDB](./concepts/tsdb.md) - внутреннее устройство хранилища
*   [Capacity Planning](./installation/capacity_planning.md) - расчёт ресурсов
*   [Prometheus API](./prometheus_api.md) - справочник по HTTP API
*   [Правила](./rules.md) - настройка recording и alerting rules
*   [Alertmanager](./alertmanager.md) - настройка доставки оповещений
*   [Масштабирование](./scaling/overview.md) - стратегии при росте нагрузки
