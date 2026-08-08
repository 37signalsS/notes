# Управление правилами vmalert в Kubernetes

## 1. Определения

**vmalert** — специализированный компонент [VictoriaMetrics](./overview.md), отвечающий за вычисление правил алертинга и записи (alerting и recording rules). В инфраструктуре Kubernetes управление правилами осуществляется двумя основными способами:

1.  **Декларативный (VMRule CRD)** — использование Custom Resource Definitions и VictoriaMetrics Operator. Это текущий индустриальный стандарт, обеспечивающий автоматизацию жизненного цикла правил: оператор непрерывно отслеживает изменения `VMRule` и ресурса `VMAlert`, формирует из них конфигурацию и «горячо» перезагружает её без перезапуска подов.
2.  **Традиционный (ConfigMap)** — монтирование YAML-файлов правил в поды через стандартные механизмы Kubernetes. Используется, когда установка оператора невозможна или нецелесообразна, а также для специфических конфигураций и legacy-сред.

## 2. Базовые концепции

### Сравнение подходов

| Характеристика | VMRule (Operator) | ConfigMap (Manual) |
| :--- | :--- | :--- |
| **Обновление** | Автоматический «горячий» reload (`/-/reload`), без перезапуска подов | Требует рестарта пода или sidecar (reloader) |
| **Валидация** | На уровне Admission Webhook (до применения, при включённом `admissionWebhooks`) | Только после запуска компонента (в логах) |
| **Масштабируемость** | Высокая: Discovery по меткам в любых Namespaces через селекторы | Низкая: ручное управление путями и томами |
| **GitOps** | Нативная поддержка (ArgoCD, Flux) | Требует сложной настройки монтирования файлов |
| **Типы данных** | Метрики (MetricsQL) и логи (LogsQL) | Любые, поддерживаемые vmalert |

При подходе через оператор учитывайте, что:

- Для каждого ресурса `VMAlert` оператор разворачивает `Deployment`, а также `Service` и `VMServiceScrape` с префиксом имени ресурса.
- Под vmalert монтируется набор `ConfigMap` с префиксом `<VMAlert-name>-<number>`, содержащих сгенерированную конфигурацию правил.
- Оператор непрерывно отслеживает изменения `VMRule` и `VMAlert`; изменение правил не требует рестарта подов (конфигурация перечитывается автоматически).

### Поля спецификации VMAlert

Обязательные поля ресурса `VMAlert` — `datasource` (источник запросов) и `notifier` (приёмник алертов). Ключевые параметры:

| Поле | Назначение |
| :--- | :--- |
| `datasource.url` | URL источника метрик (vmselect/single-node) |
| `notifier.url` / `notifiers` | URL Alertmanager (одиночный URL или список для HA — см. раздел HA) |
| `evaluationInterval` | Периодичность оценки правил (например, `"30s"`) |
| `ruleSelector` (matchLabels) | Селектор выборки `VMRule` по меткам |
| `ruleNamespaceSelector` | Селектор выборки неймспейсов, где искать `VMRule` |
| `selectAllByDefault` | Если `true` — при отсутствии селекторов выбрать все `VMRule` в кластере |
| `remoteWrite` / `remoteRead` | Сохранение состояния алертов в удалённое хранилище |
| `image` / `resources` | Версия образа и ресурсы пода |
| `extraArgs` | Дополнительные флаги командной строки vmalert |

### Правила выборки VMRule (селекторы Discovery)

Фильтрация определяется комбинацией `ruleNamespaceSelector`, `ruleSelector` и `selectAllByDefault`:

| `ruleNamespaceSelector` | `ruleSelector` | `selectAllByDefault` | Выбранные правила |
| :--- | :--- | :--- | :--- |
| не задан | не задан | `false` | ничего (по умолчанию) |
| не задан | не задан | `true` | все `VMRule` в кластере |
| задан | не задан | безразлично | все `VMRule` из неймспейсов, подошедших по селектору |
| не задан | задан | безразлично | все `VMRule` из неймспейса `VMAlert`, подошедшие по селектору |
| задан | задан | безразлично | все `VMRule` из подходящих неймспейсов, подошедшие по селектору |

Это позволяет реализовать **разграничение правил** (rule access control) по командам/окружениям: например, команда «прод» видит только свои `VMRule`, при этом каждый `VMAlert` может обслуживать свои наборы правил из разных подов кластера.

### Типы правил и источники данных

«vmalert» через оператор может работать с несколькими типами правил, задаваемых на уровне группы атрибутом `type`:

- `prometheus` (по умолчанию) — PromQL/MetricsQL, источник — VictoriaMetrics.
- `vlogs` — LogsQL для VictoriaLogs (требование: `type: vlogs` на уровне группы).
- `graphite` — GraphiteQl.

Один инстанс `vmalert` может обслуживать только один `-datasource.url`, поэтому совместная работа правил для метрик и логов через один компонент реализуется через `vmauth`, маршрутизирующий запросы по префиксам путей (`/api/v1/query*` для метрик, `/select/logsql/*` для логов). Альтернатива — запуск отдельных инстансов `vmalert` под каждый тип правил.

## 3. Практические сценарии

### Сценарий 1: Управление через VMRule CRD (Рекомендуемый)

VictoriaMetrics Operator использует ресурс **VMRule** для определения групп правил. Оператор автоматически сканирует кластер на наличие этих ресурсов и обновляет конфигурацию `vmalert`.

#### Пример алертинга на основе метрик (MetricsQL)

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMRule
metadata:
  name: infrastructure-alerts
  namespace: monitoring
  labels:
    role: alert-rules
    tier: production
spec:
  groups:
    - name: HostMetrics
      interval: 30s
      rules:
        - alert: HighCpuUsage
          expr: 100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 85
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Высокая загрузка CPU на {{ $labels.instance }}"
            description: "Загрузка CPU превышает 85% более 5 минут. Текущее значение: {{ $value | printf \"%.2f\" }}%"
```

#### Пример алертинга на основе логов (LogsQL)

С VictoriaLogs правила алертинга могут анализировать журналы напрямую через тот же ресурс `VMRule`. Для LogsQL-выражений **обязательно** указать `type: vlogs` на уровне группы, иначе выражение будет трактоваться как PromQL и не запустится.

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMRule
metadata:
  name: application-log-alerts
  namespace: monitoring
  labels:
    role: alert-rules
spec:
  groups:
    - name: AppErrors
      type: vlogs  # Обязательно для LogsQL
      interval: 1m
      rules:
        - alert: HighErrorRateInLogs
          expr: '{app="api-gateway"} status:in(error,warn) | stats by (k8s.pod.name) count() as errors | filter errors:>20'
          for: 2m
          labels:
            severity: critical
          annotations:
            summary: "Всплеск ошибок в логах"
            description: "Более 20 ошибок или предупреждений на поде {{ index $labels \"k8s.pod.name\" }} за последнюю минуту"
```

Пара пояснений к LogsQL-правилам:

- В `expr` обязательно должен присутствовать `stats`-пайп, чтобы посчитать метрику по выбранным логам, и `filter`-пайп для задания порога срабатывания.
- Время запроса (time filter) подставляется автоматически в соответствии с `interval` группы: для группы с интервалом `1m` анализируются логи за последнюю минуту. Кастомный time filter (`_time:...`) задаётся явно, но **backfill для правил с кастомным time filter не поддерживается**.
- В `annotations` доступны `{{ $labels }}` и `{{ $value }}`, а также шаблонная функция `query` — удобно прикладывать к алерту пример лога (через `row_any`).

#### Пример recording rule (предварительный расчёт метрики)

Оператор поддерживает и recording rules через `VMRule`:

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMRule
metadata:
  name: recording-example
  namespace: monitoring
spec:
  groups:
    - name: vm_http_errors
      interval: 1m
      rules:
        - record: http_requests_errors_total:sum_by_cluster_namespace_job:rate5m
          expr: |
            sum by (cluster, namespace, job) (
              rate(http_requests_errors_total[5m])
            )
```

#### Пример recording rule на основе логов — несколько серий из одного expr (performance tip)

В LogsQL можно получить сразу несколько значений из одного выражения и сохранить их в несколько серий:

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMRule
metadata:
  name: log-recording
  namespace: monitoring
spec:
  groups:
    - name: RequestDurationQuantiles
      type: vlogs
      interval: 5m
      rules:
        - record: requestDurationQuantile
          expr: '* | stats by (service) quantile(0.5, request_duration_seconds) p50, quantile(0.9, request_duration_seconds) p90, quantile(0.99, request_duration_seconds) p99'
```

Результат: для каждого `service` создаются серии `requestDurationQuantile{stats_result="p50"}`, `...{stats_result="p90"}` и т.д.

### Связывание VMRule и VMAlert (Discovery)

Чтобы `vmalert` «увидел» ваши правила, в его конфигурации (ресурс `VMAlert`) должны быть настроены селекторы:

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMAlert
metadata:
  name: main-vmalert
spec:
  # Ограничить выборку правил меткой
  ruleSelector:
    matchLabels:
      role: alert-rules
  # Искать правила во всех Namespaces с меткой мониторинга
  ruleNamespaceSelector:
    matchLabels:
      monitoring-enabled: "true"
  datasource:
    url: "http://vmselect:8481/select/0/prometheus"
  notifier:
    url: "http://alertmanager:9093"
```

Выбор всего правила без селекторов:

```yaml
spec:
  selectAllByDefault: true  # выбрать все VMRule в кластере
```

### Сценарий 2: Управление через ConfigMap

Используется для специфических конфигураций или legacy-сред. Основная сложность — обеспечение обновления правил без простоя.

**1. Создание ConfigMap с правилами:**
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: vmalert-manual-rules
data:
  rules.yaml: |
    groups:
      - name: ManualGroup
        rules:
          - alert: ManualAlert
            expr: up == 0
```

**2. Монтирование в Deployment:**
При использовании ConfigMap рекомендуется монтировать весь каталог, а не отдельные файлы через `subPath`, так как `subPath` блокирует автоматическое обновление файлов внутри контейнера при изменении ConfigMap.

```yaml
spec:
  containers:
    - name: vmalert
      args:
        - "-rule=/etc/vmalert/rules/*.yaml"
      volumeMounts:
        - name: rules-volume
          mountPath: /etc/vmalert/rules
  volumes:
    - name: rules-volume
      configMap:
        name: vmalert-manual-rules
```

### Высокая доступность (HA)

`VMAlert` может запускаться с несколькими репликами (например, `spec.replicaCount: 2`) без дополнительной настройки, так как за дедупликацию отвечает [VMAlertmanager](../Prometheus/alertmanager.md).

При HA-развёртывании VMAlertmanager (более 1 реплики) необходимо указать все pod FQDN через `spec.notifiers` (список URLs), либо использовать service discovery через селектор (labelSelector + namespaceSelector), например:

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMAlert
metadata:
  name: example-ha
  namespace: default
spec:
  replicaCount: 2
  evaluationInterval: "10s"
  datasource:
    url: http://vmsingle-example.default.svc:8428
  notifiers:
    - url: http://vmalertmanager-example-0.vmalertmanager-example.default.svc:9093
    - url: http://vmalertmanager-example-1.vmalertmanager-example.default.svc:9093
  ruleSelector: {}
  remoteWrite:
    url: http://vminsert:8480/insert/0/prometheus
  remoteRead:
    url: http://vmselect:8481/select/0/prometheus
```

Альтернатива перечислению FQDN — service discovery по селекторам меток и неймспейсов:

```yaml
spec:
  notifiers:
    - selector:
        namespaceSelector:
          matchNames:
            - default
        labelSelector:
          matchLabels:
            usage: dedicated
```

Для восстановления состояния алертов после рестартов HA-инсталляции необходимо указывать `remoteWrite` и `remoteRead` (детали в [обзоре vmalert](./vmalert_overview.md)). Это даёт автоматическое восстановление временных серий `ALERTS` / `ALERTS_FOR_STATE`.

### Enterprise-функциональность

Для Enterprise-версии `vmalert` (лицензия `spec.license`) доступны:

- **Multitenancy (многоарендность):** с флагом `-clusterMode=true` и полем `tenant` на уровне правил в `VMRule` — каждая группа/правило может работать с отдельным tenant-ом VictoriaMetrics.
- **Чтение правил из object storage:** через `extraArgs.rule: s3://bucket/dir/alert.rules` (S3/GCS).

## 4. Поиск и устранение неисправностей (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Правила не отображаются в UI | `ruleSelector` / `ruleNamespaceSelector` не соответствуют меткам VMRule; WATCH_NAMESPACE ограничивает область | Проверить соответствие меток и селекторов в `VMAlert` и `VMRule`, область `WATCH_NAMESPACE` |
| Ошибка в MetricsQL/LogsQL | Синтаксическая ошибка или неверный `type` группы | Убедиться в `type: vlogs` для LogsQL; запустить `vmalert-tool check` |
| LogsQL-правило молчит | Пропущен `stats`-пайп или `filter`-пайп в `expr` | Добавить обязательные пайпы; проверить time filter |
| Правила из другого Namespace не подхватываются | Не настроен `ruleNamespaceSelector` | Убедиться, что `ruleNamespaceSelector` в `VMAlert` разрешает поиск в целевой namespace |
| ConfigMap обновился, но vmalert не видит изменений | Использование `subPath` в монтировании | Отказаться от `subPath` или использовать sidecar (stakater/reloader) для рестарта пода |
| После рестарта алерты отправляются заново | Не настроен `remoteRead`/`remoteWrite` для восстановления состояния | Указать `remoteRead.url` и `remoteWrite.url` (см. раздел HA) |
| Дублирование уведомлений при нескольких репликах VMAlertmanager | Указан неполный список подов (`notifier` вместо `notifiers`) | Перечислить все FQDN в `notifiers` или использовать service discovery |

## 5. Дополнительная информация

### Лучшие практики

- **CI/CD Валидация:** запускайте `vmalert-tool test` в пайплайне перед деплоем манифестов — тестирование логики алертов на синтетических данных (unit tests для алертов).
- **Разделение ответственности:** создавайте отдельные `VMRule` для разных команд/приложений, используя метки (`ruleSelector`) для фильтрации в соответствующих инстансах `vmalert`.
- **Версионирование:** применяйте проверенные достаточно стабильные теги образов (например, версии серии `v1.1xx`) — отслеживайте [LTS / стабильные релизы](https://docs.victoriametrics.com/lts-releases/), чтобы зафиксировать поведение движка правил.
- **`selectAllByDefault`:** используйте для scope правил осознанно — без ограничения селекторов и при `WATCH_NAMESPACE` по всем неймспейсам можно собрать лишние правила.

**Ссылки:**
- [VMAlert Operator CRD Docs](https://docs.victoriametrics.com/operator/resources/vmalert/)
- [VMRule CRD Docs](https://docs.victoriametrics.com/operator/resources/vmrule/)
- [LogsQL Alerting Guide](https://docs.victoriametrics.com/victorialogs/vmalert/)
- [Обзор vmalert](./vmalert_overview.md)