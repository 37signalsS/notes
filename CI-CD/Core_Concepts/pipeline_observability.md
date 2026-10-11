# Наблюдаемость пайплайнов (Pipeline Observability)

## Определения

- **Наблюдаемость пайплайнов (Pipeline Observability)** — практика применения принципов распределенной трассировки, сбора метрик и логов к процессам CI/CD. В отличие от мониторинга инфраструктуры раннеров, она фокусируется на внутреннем поведении конвейера: жизненном цикле задач, зависимостях в графе (DAG), эффективности кэширования и причинах задержек на критическом пути.
- **Трассировка пайплайнов (Pipeline Tracing)** — представление выполнения пайплайна как распределенной транзакции. Весь запуск (Run) является родительским пролетом (Parent Span), а стадии, джобы и отдельные шаги — дочерними (Child Spans).
- **Критический путь (Critical Path)** — самая длинная последовательность зависимых задач, определяющая общее время выполнения пайплайна. Задержка в любой задаче на этом пути напрямую увеличивает DORA-метрику Lead Time.
- **Семантические конвенции (Semantic Conventions)** — стандартизированные в OpenTelemetry имена атрибутов для CI/CD (например, `cicd.pipeline.name`, `cicd.job.id`), обеспечивающие единообразие данных между различными CI-платформами.
- **Наблюдаемость на базе eBPF** — метод низкоуровневого мониторинга процессов внутри раннера без изменения кода пайплайна. Позволяет отслеживать системные вызовы, сетевую активность и дисковые операции команд сборки.
- **Сэмплирование (Sampling)** — выборочное сохранение подмножества трейсов для снижения объёма хранения и нагрузки на backend. Различают head-based (решение на входе) и tail-based (решение после завершения спана, например, «сохранять все упавшие и медленные»).
- **Голден-сигналы (Golden Signals)** — ключевые сигналы, перенесённые на пайплайны: **RED** (Rate — частота запусков, Errors — доля падений, Duration — длительность) и **USE** (Utilization/Saturation/Errors применительно к раннерам и Collector).
- **Cardinality (кардинальность)** — число уникальных комбинаций тегов в метрике. Высокая кардинальность (trace_id, полный путь) в метриках Prometheus приводит к взрыву объёма series и memory pressure на TSDB.
- **Tail-based сэмплирование** — принятие решения о сохранении трейса после завершения всех спанов. Позволяет сохранять 100% упавших и медленных (>N мс) трейсов, сбрасывая успешные.
- **Parent Span / Child Span** — иерархическая модель трейса: Parent Span — весь пайплайн (Run), Child Spans — стадии, джобы, отдельные команды. `needs` в DAG реализуется как Span Links.
- **Span Link** — связь между спанами, не совпадающая с родительско-дочерней иерархией. В CI/CD используется для выражения `needs` между джобами, которые не являются прямыми предками/потомками.
- **OTLP (OpenTelemetry Protocol)** — стандартизированный протокол экспорта телеметрии (traces, metrics, logs). Вself-hosted средах — основной транспорт между раннерами/коллектором и хранилищами.

## Основные концепции

### Зачем нужна наблюдаемость пайплайнов?

1. **Диагностика Lead Time:** Выявление конкретных этапов (очереди, загрузка образов, тесты), которые замедляют поставку.
2. **Анализ DAG и параллелизма:** Визуализация реальных простоев, когда задача ждет завершения предшественников, несмотря на наличие свободных раннеров.
3. **Борьба с нестабильностью (Flaky Tests):** Корреляция трейса упавшего теста с метриками системы (CPU/RAM раннера) и сетевыми задержками во время выполнения. Подробнее: **[Наблюдаемость тестов](../../Testing/testing_cicd_integration.md#ci-cd-observability-opentelemetry)**.
4. **Прозрачность Supply Chain:** Интеграция с аттестациями безопасности (SLSA) — трейс служит доказательством того, какие именно команды выполнялись при сборке артефакта.

### Роли и ответственность

| Объект / Задача | DevOps | SRE | Sysadmin |
| :--- | :--- | :--- | :--- |
| **SLI/SLO пайплайнов** | Определение SLI (Success Rate, p95 Duration, Queue Time), интеграция с DORA | Калибровка порогов, burn rate алерты, Error Budget политика | Нет |
| **Архитектура сбора** | Выбор стека (OTel/Tempo/Prometheus/Loki), интеграция с CI-платформой | Проектирование resilience коллектора, tail-based сэмплирование, SLO на Collector | Развёртывание Collector на хосте, systemd-юнит, лимиты cgroup |
| **Инструментация пайплайна** | Внедрение `otel-cli` в `.gitlab-ci.yml`, семантические конвенции `cicd.*` | Валидация корреляции trace_id между джобами, карантин flaky | Настройка eBPF-сборщиков на хостах раннеров, CAP_SYS_ADMIN |
| **Backend / Хранилище** | Дашборды Grafana, алерты, retention политики | SLO на запись/поиск трейсов, capacity planning VictoriaMetrics/Tempo | Установка/обновление Tempo/Loki/Prometheus, диски, иноды, бэкапы |
| **Диагностика инцидента** | Поиск по `trace_id` в Tempo, корреляция с артефактами | Burn rate анализ, RCA по трейсам, координация отката | Доступ к хосту коллектора, логи journald, сетевые дампы |

### SLI и SLO пайплайнов

Наблюдаемость питает измерение надёжности самого конвейера. Ключевые индикаторы уровня сервиса (SLI):

- **Pipeline Success Rate** = успешные запуски / все запуски (цель ≥ 95%).
- **Pipeline Duration (p95)** = 95-й перцентиль длительности Run (цель < 15 мин).
- **Queue/Wait Time** = время ожидания свободного раннера в очереди (цель < 2 мин).
- **Flaky Rate** = доля тестов, упавших нестабильно при повторном прогоне (цель < 1%).

**SLO** формулируется как: «95% сборок успешны и укладываются в p95 < 15 мин за скользящее окно 28 дней». Исчерпание Error Budget сигнализирует о деградации конвейера раньше, чем пострадают [DORA-метрики](./dora_metrics.md). Целевые значения удобно хранить как recording rules в Prometheus и визуализировать в Grafana.

### Архитектура сбора данных

Современная система наблюдаемости строится на базе **OpenTelemetry (OTel)**:

1. **Источник (CI Platform / Agent):**
   - *Нативная интеграция:* CI-сервер (например, GitLab) сам отправляет OTLP-данные.
   - *Инструментация скриптов:* Использование `otel-cli` или GitHub Actions для генерации спанов вручную.
   - *eBPF-сборщики:* Устанавливаются на хосты раннеров для прозрачного сбора данных о процессах.
2. **Collector (OpenTelemetry Collector):** Агрегирует сигналы, обогащает их метаданными (версия ОС, ID хоста раннера) и направляет в хранилище.
3. **Backend (Storage & Visualization):**
   - **Grafana Tempo / Jaeger:** Для трейсов.
   - **Prometheus / VictoriaMetrics:** Для агрегированных метрик пайплайнов.
   - **Grafana Loki:** Для корреляции логов джоб с трейсами.

### Ключевые атрибуты телеметрии (OTel Conventions)

Для эффективного анализа каждый спан должен содержать:
- `cicd.pipeline.id`: Уникальный ID запуска.
- `cicd.job.name`: Название задачи.
- `cicd.system`: Название платформы (gitlab, github_actions, jenkins).
- `vcs.repository.url`: Ссылка на исходный код.
- `vcs.revision.sha`: Хэш коммита.
- `error.type`: Код ошибки при падении.

## Практические сценарии

### Сценарий 1: Нативная интеграция GitLab CI

GitLab поддерживает отправку трейсов напрямую в OTel Collector через настройки проекта или инстанса.

**Настройка `.gitlab-ci.yml` (логика):**
1. Включить `OpenTelemetry` в `Admin Area -> Settings -> Observability`.
2. Указать `OTEL_EXPORTER_OTLP_ENDPOINT`.
3. Пайплайн автоматически генерирует трейс, где:
   - Pipeline = Trace
   - Stage/Job = Spans
   - `needs` = Span Links / Зависимости

### Сценарий 2: Детальная трассировка шагов через `otel-cli`

Если нужно понять, какая именно команда внутри джобы тормозит (например, `npm install` vs `npm test`), используется инструментация шагов.

```yaml
# Пример для GitLab или GitHub Actions
job_with_tracing:
  script:
    - export OTEL_EXPORTER_OTLP_ENDPOINT="http://otel-collector:4317"
    # Обертка для команды сборки
    - otel-cli exec --name "docker_build" \
        --service "my-app-ci" \
        --attrs "docker.image=app:latest" \
        docker build -t app:latest .
    # Обертка для тестов
    - otel-cli exec --name "unit_tests" \
        --service "my-app-ci" \
        npm test
```

### Сценарий 3: Поиск «бутылочного горлышка» в DORA Lead Time

**Ситуация:** Время сборки выросло с 10 до 30 минут.
**Алгоритм расследования:**
1. **Tempo:** Открываем трейс пайплайна и смотрим на **Gantt Chart**.
2. **Анализ:** Видим длинный спан `setup_environment` перед каждой джобой.
3. **Детализация:** В атрибутах спана обнаруживаем `cache_result: miss`.
4. **Решение:** Оптимизация ключей кэширования или переход на локальный Registry-прокси для образов.
5. **Результат:** Время сократилось до 12 минут, что подтверждается на графике Lead Time в Grafana.

### Сценарий 4: Алертинг на деградацию (Prometheus)

На основе метрик, экспортируемых Collector, настраиваются правила оповещения. Пример `prometheus_rules.yml`:

```yaml
groups:
  - name: pipeline_observability
    rules:
      - alert: PipelineDurationHigh
        expr: |
          histogram_quantile(0.95,
            sum by (le, cicd_pipeline_name)
              (rate(cicd_pipeline_duration_seconds_bucket[1h]))) > 900
        for: 15m
        labels: { severity: warning }
        annotations:
          summary: "p95 длительности сборки {{ $labels.cicd_pipeline_name }} > 15 мин"
      - alert: PipelineFailureRateHigh
        expr: |
          sum(rate(cicd_pipeline_runs_total{status="error"}[1h]))
          / sum(rate(cicd_pipeline_runs_total[1h])) > 0.05
        for: 30m
        labels: { severity: critical }
        annotations:
          summary: "Доля упавших сборок > 5% (SLO нарушен)"
      - alert: RunnerQueueWaitHigh
        expr: histogram_quantile(0.95, rate(cicd_queue_wait_seconds_bucket[1h])) > 120
        for: 15m
        labels: { severity: warning }
        annotations:
          summary: "Ожидание раннера в очереди > 2 мин (p95)"
```

### Сценарий 5: Self-hosted OTel Collector

Минимальный конфигурационный файл коллектора для приёма OTLP и маршрутизации сигналов в self-hosted хранилища:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318
processors:
  batch: {}
  # tail-based сэмплирование: сохраняем все ошибки и медленные (>60с) трейсы
  tail_sampling:
    policies:
      - name: keep_errors
        type: status_code
        status_code: { status_codes: [ERROR] }
      - name: keep_slow
        type: latency
        latency: { threshold_ms: 60000 }
exporters:
  otlphttp/tempo:
    endpoint: http://tempo:4318
  prometheus:
    endpoint: 0.0.0.0:8889
  loki:
    endpoint: http://loki:3100/loki/api/v1/push
service:
  pipelines:
    traces:  { receivers: [otlp], processors: [batch, tail_sampling], exporters: [otlphttp/tempo] }
    metrics: { receivers: [otlp], processors: [batch],                  exporters: [prometheus] }
    logs:    { receivers: [otlp], processors: [batch],                  exporters: [loki] }
```

## Операции и команды

### Управление OpenTelemetry Collector

```bash
# Проверка статуса сервиса Collector
systemctl status opentelemetry-collector
# → ● opentelemetry-collector.service - OpenTelemetry Collector
# →    Active: active (running) since ...

# Живой просмотр логов Collector
journalctl -u opentelemetry-collector -f
# → ... level=info msg="Traces batch published" trace_id=...

# Метрики приёма спанов
curl -s http://localhost:8889/metrics | grep otelcol_receiver_accepted_spans
# → otelcol_receiver_accepted_spans_total 1234

# Размер очереди экспорта
curl -s http://localhost:8889/metrics | grep otelcol_exporter_queue_size
# → otelcol_exporter_queue_size 0 (норма), рост — проблема

# Количество failed exports
curl -s http://localhost:8889/metrics | grep otelcol_exporter_send_failed_spans
# → otelcol_exporter_send_failed_spans_total 0

# Проверка порта OTLP gRPC
ss -tnp | grep 4317
# → LISTEN 0 4096 *:4317

# Проверка порта OTLP HTTP
ss -tnp | grep 4318
# → LISTEN 0 4096 *:4318
```

| Команда | Описание | Ожидаемый вывод | Роль |
| :--- | :--- | :--- | :--- |
| `systemctl status opentelemetry-collector` | Проверка статуса сервиса Collector | `active (running)` / `failed` | Sysadmin |
| `journalctl -u opentelemetry-collector -f` | Живой просмотр логов Collector | Логи приёма/экспорта сигналов | Sysadmin / SRE |
| `curl -s http://localhost:8889/metrics | grep otelcol_receiver_accepted_spans` | Метрики приёма спанов | `otelcol_receiver_accepted_spans_total 1234` | SRE |
| `curl -s http://localhost:8889/metrics | grep otelcol_exporter_queue_size` | Размер очереди экспорта | `otelcol_exporter_queue_size 0` (норма), рост — проблема | SRE |
| `curl -s http://localhost:8889/metrics | grep otelcol_exporter_send_failed_spans` | Количество failed exports | `otelcol_exporter_send_failed_spans_total 0` | SRE |
| `ss -tnp | grep 4317` | Проверка порта OTLP gRPC | `LISTEN 0 4096 *:4317` | Sysadmin |
| `ss -tnp | grep 4318` | Проверка порта OTLP HTTP | `LISTEN 0 4096 *:4318` | Sysadmin |

### Диагностика пайплайнов и трейсов

```bash
# Проверка доступности Tempo API и поиск трейса по ID
curl -s http://localhost:3200/api/search?q={trace_id}
# → [{"traceID":"abc123","duration":"123ms","spanCount":5}]

# Поиск логов по trace_id в Loki
curl -s "http://localhost:3100/loki/api/v1/query_range?query={trace_id}&limit=50"
# → {"status":"success","data":{"result":[{"stream":{"trace_id":"abc123"},"values":[["1234567890","log line with trace_id"]]}]}}

# p95 длительности пайплайна за последний час
promtool query instant http://localhost:9090 \
  'histogram_quantile(0.95, rate(cicd_pipeline_duration_seconds_bucket[1h]))'
# → 840 (14 минут)

# Доля упавших сборок за последний час
promtool query instant http://localhost:9090 \
  'sum(rate(cicd_pipeline_runs_total{status="error"}[1h])) / sum(rate(cicd_pipeline_runs_total[1h]))'
# → 0.03 (3%)

# p95 Queue Time за последний час
promtool query instant http://localhost:9090 \
  'histogram_quantile(0.95, rate(cicd_queue_wait_seconds_bucket[1h]))'
# → 45 (0.75 мин)
```

| Команда | Описание | Ожидаемый вывод | Роль |
| :--- | :--- | :--- | :--- |
| `grep -i "traceparent" /var/log/gitlab-runner/runner.log` | Проверка прокидывания traceparent в логах раннера | Строки с `traceparent=00-...-...-01` | Sysadmin / DevOps |
| `cat /etc/gitlab-runner/config.toml | grep -i token` | Проверка конфигурации раннера на наличие токена | `token = "..."` | Sysadmin |

### Управление семантическими конвенциями и сэмплированием

| Команда / Действие | Описание | Ожидаемый вывод | Роль |
| :--- | :--- | :--- | :--- |
| `otel-cli span --service ci --name job-duration --duration $(measure)` | Ручная отправка спана длительности задачи | `Span reported: job-duration (1234ms)` | DevOps |
| `otel-cli exec --name "build" --service "ci" --attrs "cicd.job.name=build" make build` | Обёртка команды в спан | Создан спан `build` с атрибутами | DevOps |
| `grep -E "cicd\.(pipeline|job|system|vcs)" /etc/otel-collector/config.yaml` | Проверка атрибутов в конфиге Collector | Строки с `cicd.pipeline.id` и др. | SRE / Sysadmin |
| Отредактировать `tail_sampling` в `config.yaml` | Изменить порог сохранения медленных трейсов | Перезапуск Collector, новые правила в логах | SRE / Sysadmin |
| `curl -s http://localhost:8889/metrics \| grep "cardinality"` | Проверка кардинальности метрик (если настроен exporter) | Значение cardinality по метрикам | SRE |

### eBPF и инструментация хостов

| Команда | Описание | Ожидаемый вывод | Роль |
| :--- | :--- | :--- | :--- |
| `tetragon list --events` | Просмотр событий процессов раннера | Таблица PID, comm, syscall, latency | Sysadmin |
| `tetragon list --events --pod-name <runner-pod>` | Фильтрация по поду раннера | События только из пода | Sysadmin |
| `bpftool prog list` | Проверка загруженных eBPF-программ | Список программ с типом и именем | Sysadmin |
| `bpftool map list` | Проверка eBPF-карт (maps) | Список карт с размером | Sysadmin |
| `journalctl -u tetragon -f` | Живой просмотр логов Tetragon | Логи событий, ошибок загрузки | Sysadmin |

## Типичные ошибки и решения

| Проблема | Вероятная причина | Метод диагностики | Роль |
| :--- | :--- | :--- | :--- |
| **Разрывы в трейсах** | Не прокидывается `traceparent` между джобами. | Проверить передачу переменной `OTEL_TRACEPARENT` через артефакты. | DevOps / SRE |
| **Высокая задержка (Latency)** | Перегрузка OTel Collector или медленный экспорт в Backend. | Проверить метрики `otelcol_receiver_accepted_spans` и очереди коллектора. | SRE / Sysadmin |
| **Отсутствие данных eBPF** | Недостаточно прав (CAP_SYS_ADMIN) у контейнера-раннера. | Проверить логи сборщика на хосте раннера. | Sysadmin |
| **Шум в данных** | Отсутствие сэмплирования для частых мелких пайплайнов. | Настроить `tail_sampling` в коллекторе для фильтрации только долгих или упавших сборок. | SRE |
| **Высокая кардинальность** | В метрики попали высококардинальные теги (точное время, trace_id, полный путь). | Ограничить набор атрибутов в `spanmetrics`/`batch`; использовать `attributes` processor для дропа. | SRE |
| **Переполнение очереди Collector** | Backend недоступен или слишком медленный. | Следить за `otelcol_exporter_queue_size` и `otelcol_exporter_send_failed_spans`; увеличить ресурсы или retention. | Sysadmin / SRE |
| **Collector не стартует** | Недостаточно файловых дескрипторов, неверный конфиг YAML. | `journalctl -u opentelemetry-collector -n 50`, `LimitNOFILE` в systemd-юните. | Sysadmin |
| **Трейсы есть, но нет метрик** | Ошибка в `service.pipelines` конфига, exporter prometheus не настроен. | `curl -s localhost:8889/metrics | grep cicd_`, проверить pipeline `metrics` в `config.yaml`. | SRE / Sysadmin |
| **Логи не привязываются к трейсам** | В логах нет `trace_id`, или Loki не настроен на индексирование по нему. | Проверить вывод раннера на наличие `trace_id`, проверить labels в Loki. | DevOps / SRE |
| **p95 растёт, p50 стабилен** | Проблема на хвосте распределения (tail latency), а не в среднем. | Профилировать по p99, анализировать длинные спаны в Tempo Gantt. | SRE |
| **Flaky тесты не корреллируются с трейсами** | В тестах нет `trace_id` в stdout, или не настроен log correlation. | Проверить вывод тестов, настроить `trace_id` в стандартный вывод раннера. | DevOps |
| **eBPF сборщик падает с EPERM** | Контейнер раннера запущен без `CAP_SYS_ADMIN` или `privileged`. | `kubectl describe pod <runner-pod>`, проверить securityContext. | Sysadmin |
| **OTLP порты недоступны** | Firewall блокирует 4317/4318, или Collector слушает только на `127.0.0.1`. | `ss -tnp | grep 4317`, `nft list ruleset`, проверить `endpoint` в `config.yaml`. | Sysadmin |
| **Retention не работает** | Не настроен TTL в Tempo/Loki, или диск переполнен. | `df -h /var/lib/tempo`, проверить `compaction` и `retention` в конфигах. | Sysadmin |
| **Алерт не срабатывает на упавший пайплайн** | Метрика `status="error"` не экспортируется, или `for: 15m` слишком долго. | Проверить `cicd_pipeline_runs_total{status="error"}` в Prometheus, настроить `for: 0m` или `1m`. | SRE / DevOps |

## Лучшие практики

### Методология и данные

1. **Метрики перед трейсами:** начинайте диагностику с Golden Signals (Rate, Errors, Duration, Saturation), чтобы локализовать проблему, и только потом открывайте трейс. Трейс без контекста метрик — это «стрельба по звездам».
2. **SLO на сам пайплайн:** определите `pipeline_success_rate` и `pipeline_duration_p95` как SLI, задайте Error Budget и настройте burn rate алерты. Без SLO пайплайн нельзя защищать SLO сервиса, который он деплоит.
3. **Tail-based сэмплирование:** для успешных пайплайнов достаточно 5–10% трейсов, но для упавших (`status=error`) и медленных (>60 с) — 100%. Это снижает объём хранения в 10–100 раз без потери диагностической ценности.
4. **Корреляция по `trace_id`:** каждый запуск пайплайна и каждая стадия должны иметь уникальный `trace_id`. Это позволяет связать `perf.data` или логи раннера с конкретным запуском и искать регрессии.
5. **Критический путь — первый объект мониторинга:** настройте алертинг на аномальное увеличение длительности спанов, находящихся на DAG-critical-path. Средняя длительность скрывает проблемы на хвосте.

### Инфраструктура и конфигурация

6. **Immutable Collector config:** храните `config.yaml` в репозитории, меняйте через CI, валидируйте `otelcol validate config.yaml` перед деплоем. Патч на живом коллекторе — source of truth потерян.
7. **Отдельные тома для Tempo/Loki/Prometheus:** каждый компонент на отдельном устройстве/томе с `noatime`, мониторинг `df -h` и `df -i`. Retention через lifecycle-политики, а не через cron-очистку.
8. **cgroups v2 для Collector:** `MemoryMax=`, `CPUQuota=`, `LimitNOFILE=` в systemd-юните. Collector при перегрузке backend должен throttle gracefully, а не падать с OOM.
9. **Внутренний DNS и кэширование:** локальный resolver (Unbound/systemd-resolved) для контура. DNS-задержки часто маскируются под «медленный export в Tempo».
10. **Backpressure handling:** Collector не должен бесконечно буферизировать при недоступном backend. Настройте `queue_size` и `send_failed_spans` алерты; при переполнении — graceful degradation (drop или head-based сэмплирование).

### Наблюдаемость и связь с DORA

11. **Grafana как единая панель:** трейсы (Tempo), логи (Loki), метрики (Prometheus) и DORA-дашборд в одном Grafana с correlation по `trace_id` и `pipeline_id`.
12. **Runbook для деградации телеметрии:** порядок действий при пропаже трейсов/метрик должен быть записан и протестирован. См. раздел «Типичные ошибки и решения» и **[Управление инцидентами](./incident_response_sre.md)**.
13. **Correlation ID в логах раннера:** CI-раннеры должны писать `trace_id` в stdout/stderr. Это позволяет jump из трейса Tempo в Loki-лог одной кнопкой.
14. **Capacity planning по метрикам Collector:** `otelcol_receiver_accepted_spans` и `otelcol_exporter_send_failed_spans` — ранние индикаторы необходимости расширения backend или оптимизации сэмплирования.

### Связь с другими дисциплинами

15. **Pipeline Observability и Postmortem:** трейсы и метрики — источник данных для RCA по CI/CD-инцидентам. См. **[Управление инцидентами и постмортемы (SRE)](./incident_response_sre.md)**.
16. **Performance Profiling:** системный профайлинг `perf`, `pprof`, `py-spy` — для случаев, когда observability пайплайна показывает, *что* медленно, но не показывает, *почему* на уровне функции/команды. См. **[Профилирование производительности CI/CD](./performance_profiling.md)**.
17. **Load Shedding:** лимиты раннера (`LimitNOFILE`, `concurrent`, cgroup) и shedding на уровне Collector (drop при перегрузке) — часть единой стратегии защиты от каскадных отказов. См. **[Сброс нагрузки (Load Shedding)](./load_shedding.md)**.

## Дополнительная информация

### GitHub Actions: специфическая наблюдаемость

Встроенные механизмы GitHub Actions требуют отдельного подхода, так как доступ к метрикам ограничен API и логами платформы.

**Ключевые источники данных:**
- **Workflow Runs API** — статус, длительность, commit SHA каждого запуска.
- **Check Runs API** — результаты job'ов и отдельных шагов.
- **Job Logs** — текстовые логи с `trace_id` (при настройке).
- **Runner Metrics** — метрики self-hosted runner'ов через `actions-runner-controller` (ARC) или prometheus-экспортер.
- **gh-otel-cli** — официальное расширение `gh` для отправки OTLP-спанов прямо из workflow-шагов.

**Настройка gh-otel-cli в workflow:**
```yaml
jobs:
  observe:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: Setup gh-otel-cli
        uses: github/setup-gh-otel-cli@v1
        with:
          otel_endpoint: http://otel-collector.internal:4317
      - name: Build with tracing
        run: |
          gh otel exec --name "build" --service "myapp-ci" \
            --attrs "cicd.job.name=build,cicd.system=github_actions" \
            ./build.sh
```

**SLI для GitHub Actions:**
- **Workflow Success Rate** = успешные runs / все runs (цель ≥ 95%).
- **Workflow Duration (p95)** — 95-й перцентиль длительности Run (цель < 15 мин).
- **Queue Time** — время ожидания runner'а (для self-hosted: метрики ARC; для hosted — косвенно через разницу `created_at` и `started_at`).
- **Runner Saturation** — доля занятых слотов self-hosted runner'ов (через `actions-runner-controller` metrics).

**Алерты на основе API:**
```yaml
# Пример через GitHub Actions + curl в job'е
- name: Check failure rate
  run: |
    FAILURES=$(gh run list --limit 100 --json conclusion --jq '[.[] | select(.conclusion == "failure")] | length')
    TOTAL=$(gh run list --limit 100 --json conclusion --jq 'length')
    RATE=$(echo "scale=2; $FAILURES * 100 / $TOTAL" | bc)
    echo "Failure rate: $RATE%"
    if (( $(echo "$RATE > 5" | bc -l) )); then
      echo "::warning::Failure rate exceeded 5%"
    fi
```

**Особенности кардинальности:** `run_id`, `repository`, `branch` — высококардинальные теги. Используйте агрегирование на уровне Collector и избегайте индексирования `trace_id` в Prometheus.

### Инструментарий

- **OpenTelemetry Collector:** Универсальный сервис (коллектор) для обработки телеметрии.
- **Grafana Tempo:** Масштабируемое хранилище трейсов.
- **otel-cli:** CLI-утилита для ручной отправки спанов из bash-скриптов.
- **gh-otel-cli:** Официальное расширение `gh` для GitHub Actions (отправка OTLP из workflow).
- **Tetragon / Hubble (eBPF):** Инструменты для глубокой наблюдаемости сетевого стека и процессов.

### Grafana-дашборд (что выводить)

- **Длительность этапов (Gantt/Heatmap)** из Tempo — где теряется время на критическом пути.
- **Успешность сборок (Stat)** = `rate(error) / rate(total)` за 24ч.
- **Топ по времени ожидания (Queue)** — `cicd_queue_wait_seconds` по раннерам.
- **Flaky rate по тестам** — корреляция повторных прогонов с падениями.
- **Загрузка Collector** — `otelcol_receiver_accepted_spans`, размер очереди, failed exports.

### Самодостаточный стек наблюдаемости (self-hosted)

В закрытом/продакшен-контуре недопустимы внешние SaaS-системы мониторинга. Минимальный полностью self-hosted стек под телеметрию пайплайнов:

- **Метрики:** Prometheus (сбор/оповещения) + Grafana (дашборды). Для долгосрочного хранения и высокой кардинальности — VictoriaMetrics как замена/дополнение TSDB (см. [VictoriaMetrics: обзор](../../VictoriaMetrics/overview.md)).
- **Логи:** Loki + Promtail/Alloy (лёгкий, индексирует по меткам, а не по тексту, как ELK) — см. [Loki: обзор](../../Loki/loki_overview.md).
- **Трейсы:** Tempo (если уже используется OTLP) или Jaeger (зрелый стек с собственным UI и storage backends) — см. [Jaeger: обзор](../../Jaeger/jaeger_overview.md).
- **Коллектор:** OpenTelemetry Collector принимает OTLP от раннеров и маршрутизирует в Prometheus/Loki/Tempo (конфигурация — в Сценарии 5 выше).

Практическая развязка: раннеры и шаги пайплайна шлют OTLP на Collector; метрики оседают в Prometheus/VictoriaMetrics (алерты через Alertmanager), логи — в Loki, трейсы — в Tempo/Jaeger; всё визуализируется в единой Grafana с корреляцией по `trace_id`. Все компоненты разворачиваются внутри контура (см. [Изолированные среды](./air_gapped_environments.md) и [Linux для CI/CD-узлов](./linux_sysadmin_for_ci.md) — диски, лимиты, systemd-юниты).

### См. также

- [Метрики DORA](./dora_metrics.md) — ключевые показатели, которые диагностируются через наблюдаемость.
- [OpenTelemetry: обзор](../../OpenTelemetry/opentelemetry_overview.md) — фундаментальные знания о протоколе OTLP и архитектуре сигналов.
- [Направленный ациклический граф (DAG)](../GitLab_CI/Advanced/workflow_rules/dag_with_needs.md) — структура пайплайна, оптимизация которой требует визуализации трейсов.