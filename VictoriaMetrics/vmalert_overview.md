# Обзор vmalert

## 1. Определения

**vmalert** — это высокопроизводительный компонент стека [VictoriaMetrics](./overview.md), предназначенный для выполнения правил алертинга и правил записи (recording rules). Он является полноценной заменой встроенного механизма правил Prometheus, полностью совместим с его синтаксисом и предлагает расширенные возможности масштабирования и интеграции.

`vmalert` лёгкий, не имеет внешних зависимостей и запускается как отдельный бинарник или контейнер (`victoriametrics/vmalert`).

## 2. Базовые концепции

`vmalert` периодически выполняет выражения, объявленные в **правилах** (`-rule`), против источника данных, заданного через `-datasource.url`. По результатам выполнения он отправляет оповещения в [Alertmanager](../Prometheus/alertmanager.md) (флаг `-notifier.url`) или записывает новые (агрегированные) метрики обратно через Remote Write (флаг `-remoteWrite.url`).

### Поддерживаемые источники данных и типы правил

Язык выражения `expr` определяется полем `type` на уровне группы правил (глобальный дефолт задаётся флагом `-rule.defaultRuleType`):

| Тип | Язык запросов | Источник данных |
| :--- | :--- | :--- |
| `prometheus` (default) | PromQL / MetricsQL | VictoriaMetrics (single/cluster), Prometheus и другие Prometheus-совместимые хранилища |
| `vlogs` | LogsQL | логи [VictoriaLogs](https://docs.victoriametrics.com/victorialogs/), трейсы [VictoriaTraces](https://docs.victoriametrics.com/victoriatraces/) |
| `graphite` | Graphite | Graphite-совместимые хранилища |

`vmalert` работает только с одним `-datasource.url`. Для одновременного использования метрик и логов используется [vmauth](https://docs.victoriametrics.com/vmauth/) с маршрутизацией запросов по пути (`/api/v1/query*` → VictoriaMetrics, `/select/logsql/*` → VictoriaLogs/VictoriaTraces).

### Ключевые функции

- **Выполнение правил алертинга** — запрашивает данные из источника, оценивает условия и генерирует алерты. Поддерживает сложные условия благодаря MetricsQL/LogsQL.
- **Выполнение правил записи (recording rules)** — позволяет предварительно вычислять сложные запросы и сохранять их как новые метрики. Это критично для ускорения тяжёлых дашбордов в Grafana и для агрегации данных с высокой точностью из хранилища с коротким сроком хранения в долгосрочное хранилище.
- **Интеграция с VictoriaLogs и VictoriaTraces** — поддержка алертинга на основе логов (LogsQL, `type: vlogs`) с версии `v1.106.0` также работает с трейсами VictoriaTraces.
- **Сохранение состояния (Stateful Alerting)** — `vmalert` может сохранять состояние алертов (Pending/Firing) в удалённое хранилище через Remote Write. Это позволяет не терять историю алертов при перезапуске компонента.
- **Поддержка множества источников и нотификаторов** — может работать с несколькими источниками данных (через vmauth) и отправлять уведомления в несколько кластеров Alertmanager (несколько флагов `-notifier.url` или через конфигурационный файл).
- **Шаблонизация аннотаций** — расширенная поддержка Go-templates с дополнительными функциями (`now`, `query`, `label`, `humanize`, `toTime`, `parseDuration` и т. д.).
- **Relabeling** — поддержка переименования и фильтрации меток (labels) как для алертов перед отправкой, так и для записываемых метрик.
- **Hot reload** — обновление конфигурации без простоя через сигнал SIGHUP или HTTP-эндпоинт `/-/reload`.
- **Гибкая загрузка правил** — `-rule` принимает пути, wildcard-шаблоны, рекурсивные маски, HTTP URL; для Enterprise-версии дополнительно доступны S3 и GCS.
- **Валидация** — дубликаты правил (одинаковые `name` + `expr` + labels в одной группе) запрещены; проверка синтаксиса выполняется через `vmalert-tool`.

### Отличие от Alertmanager

Важно понимать различие в ролях:

| Компонент | Назначение | Пример |
| :--- | :--- | :--- |
| **`vmalert`** | **Генерирует** алерты (логика "когда бить тревогу"): выполняет запросы к БД, оценивает условия и формирует алерты | `IF rate(errors) > 5 THEN fire alert` |
| **`Alertmanager`** | **Обрабатывает** алерты (маршрутизация, дедупликация, группировка, нотификации) | Группировка 100 алертов в одно письмо в Slack |

`vmalert` — это "движок" выполнения логики, который делает запросы к БД, в то время как Alertmanager — система управления уведомлениями. Зоны ответственности не пересекаются.

### Ограничения

- Выполнение правил внутри группы происходит **последовательно** (по умолчанию `concurrency: 1`), но запись результатов в удалённое хранилище — **асинхронно**. Поэтому в рекурсивных сценариях, когда результат одного recording rule переиспользуется в следующем, полагаться на цепочку нельзя — используйте механизм **chaining groups** (группы с зависимостями) либо перестраивайте запросы.
- Выполнение запросов к источнику идёт по сети, поэтому существует риск сетевых сбоев — пороговые значения срабатываний следует проектировать с учётом возможных ошибок запросов.
- Для корректного backfilling правил с *кастомным* time filter (LogsQL) поддержка ещё не реализована.

## 3. Практические сценарии

### Пример конфигурации правил алертинга

Файл правил `alert-rules.yaml`:

```yaml
groups:
  - name: node-alerts
    interval: 30s  # Как часто выполнять правила
    rules:
      - alert: HighCpuUsage
        expr: 100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85
        for: 5m
        labels:
          severity: warning
          team: infrastructure
        annotations:
          summary: "High CPU usage on {{ $labels.instance }}"
          description: "CPU usage is above 85% for more than 5 minutes on {{ $labels.instance }}. Current value: {{ $value }}%"

      - alert: HighMemoryUsage
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100 > 90
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High memory usage on {{ $labels.instance }}"
          description: "Memory usage is above 90% for more than 5 minutes. Current value: {{ $value }}%"

      - alert: DiskSpaceLow
        expr: (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) * 100 < 10
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Low disk space on {{ $labels.instance }}"
          description: "Disk space is below 10% on {{ $labels.instance }}. Current value: {{ $value }}%"
```

> Примечание: для каждого правила в `expr` используется MetricsQL/PromQL, `for` задаёт минимальную длительность непрерывного отклонения для перехода в состояние Firing, а `annotations` поддерживают Go-шаблоны (`$labels`, `$value`, функции `printf`, `humanize`, `query` и др.).

### Пример алертинга на основе логов (VictoriaLogs)

Для правил на основе LogsQL на **уровне группы** обязательно указать `type: vlogs`, иначе выражение будет проверено как PromQL и не запустится. Правило срабатывает, когда в логах сервиса `auth` за 5 минут на одном поде появилось более 10 ошибок:

```yaml
groups:
  - name: log-alerts
    type: vlogs  # Обязательно для LogsQL
    interval: 1m
    rules:
      - alert: AuthServiceHighErrorRate
        expr: '{env=prod} status:in(error,warn) | stats by (k8s.pod.name) count() | filter count:>10'
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate in logs for {{ index $labels "k8s.pod.name" }}"
          description: "Found more than 10 errors in auth service logs within last 5 minutes."
```

В LogsQL-выражениях (`type: vlogs`) обязательно наличие `stats pipe` для агрегации и `filter pipe`, чтобы отфильтровать результат по порогу. По умолчанию `vmalert` сам добавляет ко времени фильтр `_time: <group_interval>` — указывать его в выражении не нужно (можно для переопределения). См. также [Alerting with Logs](https://docs.victoriametrics.com/victorialogs/vmalert/).

### Пример правил записи (recording rules)

Recording rules полезны для предварительного вычисления сложных запросов:

```yaml
groups:
  - name: rec
    interval: 1m
    rules:
      # Предварительный расчет среднего CPU usage по кластеру (MetricsQL)
      - record: cluster:node_cpu:avg_rate5m
        expr: avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))
      # Расчет процента использования памяти
      - record: node:memory_usage_percent:ratio
        expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100
```

### Replay API: Пересчёт исторических данных

Уникальная функция `vmalert` — **backfilling (aka replay)**: позволяет выполнить правила на исторических данных. Это полезно, если вы создали новое правило записи и хотите заполнить историю метрики за прошлый месяц.

Запуск отдельного процесса пересчёта:

```bash
vmalert -rule=rules.yaml \
  -replay.timeFrom=2024-01-01T00:00:00Z \
  -replay.timeTo=2024-01-31T23:59:59Z \
  -datasource.url=http://victoriametrics:8428 \
  -remoteWrite.url=http://victoriametrics:8428
```

Ограничения backfill: не поддерживается для правил с кастомным time filter в LogsQL (и добавить её невозможно — см. выше), а также — при backfill правила, результат складывается с уже существующими данными.

### Пример запуска vmalert

#### Локальный запуск (с сохранением состояния)

```bash
vmalert \
  -datasource.url=http://localhost:8428 \
  -notifier.url=http://localhost:9093 \
  -remoteWrite.url=http://localhost:8428 \
  -remoteRead.url=http://localhost:8428 \
  -rule=/path/to/rules/*.yaml
```
*Флаг `-remoteWrite.url` включает сохранение состояния алертов в саму VictoriaMetrics.*

#### Kubernetes (фрагмент Deployment)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vmalert
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: vmalert
          # Рекомендуется использовать LTS версию или последнюю стабильную
          image: victoriametrics/vmalert:v1.136.0
          args:
            - -datasource.url=http://vmstorage.monitoring.svc:8428
            - -notifier.url=http://alertmanager.monitoring.svc:9093
            - -remoteWrite.url=http://vmstorage.monitoring.svc:8428
            - -remoteRead.url=http://vmstorage.monitoring.svc:8428
            - -rule=/config/rules/*.yaml
            - -httpListenAddr=:8080
            - -external.label=replica=$(POD_NAME)  # чтобы отличать инстансы при HA
          ports:
            - containerPort: 8080
              name: http
```

При запуске нескольких реплик `vmalert` (HA) каждому инстансу задаётся уникальный `-external.label` (например, `replica=instance-1`), чтобы логирование и отправка уведомлений не дублировались.

### Проверка состояния vmalert

`vmalert` запускает веб-сервер (по умолчанию на порту **`8880`**, переопределяется через `-httpListenAddr`) и интегрируется в основной `vmui`:

- `/api/v1/rules` — список групп правил и их состояние.
- `/api/v1/alerts` — список активных алертов с текущим статусом (Firing/Pending) и метками.
- `/vmalert/rule` и `/vmalert/alert` — страницы правил и алертов в веб-UI.
- `/metrics` — внутренние метрики компонента (формат Prometheus).
- `/-/reload` — «горячее» обновление конфигурации без рестарта.

### Сохранение и восстановление состояния алертов

Каждый процесс `vmalert` хранит состояние алертов в памяти. Для восстановления при рестарте используются два флага:

- `-remoteWrite.url` — URL, куда сохраняется состояние в виде временных серий `ALERTS` и `ALERTS_FOR_STATE` через Remote Write;
- `-remoteRead.url` — URL (MetricsQL-совместимый, VictoriaMetrics или vmselect), откуда при старте восстанавливается состояние по серии `ALERTS_FOR_STATE`.

Восстановление происходит **только один раз при старте** (не при hot reload). Если серии отсутствуют, не обновлялись дольше `-remoteRead.lookback` (по умолчанию 1 час) или не соответствуют текущей конфигурации правил — восстановление не выполнится. Успешно восстановленные правила помечаются меткой `restored` в веб-UI.

### Поиск и устранение неисправностей (Troubleshooting)

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Правила не выполняются | Неверный путь или права доступа | Проверить `-rule`-параметр и логи контейнера |
| Алерты пропадают после рестарта | Не настроен Remote Write | Добавить флаг `-remoteWrite.url` (+ `-remoteRead.url`) |
| "Failed to execute request" (на старте/в логах) | Тайм-аут источника данных | Увеличить `-datasource.queryTimeout` или оптимизировать запрос |
| Восстановление состояния не сработало | Серия `ALERTS_FOR_STATE` устарела на >1 час | Настроить `-remoteRead.lookback` |
| Ошибки синтаксиса | Ошибка в YAML или MetricsQL/LogsQL | Запустить `vmalert-tool check` и unit-testing (`vmalert-tool test`) |

## 4. Дополнительная информация

- **VMUI (Alerting Tab):** современный способ визуализации алертов `vmalert` доступен напрямую в UI VictoriaMetrics.
- **vmalert-tool:** утилита для валидации синтаксиса и модульного тестирования правил (unit testing: `vmalert-tool check` / `vmalert-tool test`) — рекомендуется добавить в CI/CD перед деплоем.
- **vmauth:** позволяет направлять запросы vmalert на разные хранилища (метрики/логи/трейсы) по пути запроса (`/api/v1/query*` vs `/select/logsql/*`), интегрируя единый доступ.

Официальная документация: [vmalert docs](https://docs.victoriametrics.com/vmalert/), [Troubleshooting vmalert](https://docs.victoriametrics.com/vmalert/#troubleshooting), [Alerting with VictoriaLogs](https://docs.victoriametrics.com/victorialogs/vmalert/).

Связанные компоненты: [VictoriaMetrics](./overview.md), [Управление правилами vmalert в Kubernetes](./vmalert_rules_management_with_manifests.md), [Alertmanager](../Prometheus/alertmanager.md).