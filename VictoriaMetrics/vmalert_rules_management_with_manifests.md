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

## 2.1. Требования к окружению

### Операционная система и кластер

`vmalert` запускается внутри подов Kubernetes. Минимальные требования к кластеру:

- **Kubernetes:** >= 1.28 (рекомендуется >= 1.30 для стабильной работы Admission Webhooks и EndpointSlice).
- **Helm:** >= 3.12 (если используется Helm-чарт VictoriaMetrics Operator).
- **Сеть:** стабильная connectivity между подами `vmalert`, источником данных (`vmselect`/`VictoriaMetrics`) и `Alertmanager` (порт `9093`). Задержка RTT между `vmalert` и источником данных влияет на время оценки правил.

### Аппаратные требования (Kubernetes)

| Сценарий | CPU (requests/limits) | RAM (requests/limits) | Replicas |
| :--- | :--- | :--- | :--- |
| **Малая нагрузка** (< 5000 активных алертов, < 50 recording rules) | 250m / 1 | 512Mi / 2Gi | 1–2 |
| **Средняя нагрузка** (5K–50K алертов, 50–500 recording rules) | 500m / 2 | 1Gi / 4Gi | 2–3 |
| **Высокая нагрузка** (> 50K алертов, сложный MetricsQL) | 1 / 4+ | 2Gi / 8Gi+ | 3+ |

### Программные зависимости

- **VictoriaMetrics Operator** (CRD: `VMAlert`, `VMRule`, `VMServiceScrape`) или стандартный Deployment с монтированием ConfigMap.
- **Источник данных:** VictoriaMetrics (single/cluster) или Prometheus-совместимое хранилище.
- **Alertmanager:** для доставки уведомлений (порт `9093`).
- **vmauth** (опционально): если `vmalert` должен работать с метриками и логами одновременно.

### Сетевые порты

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| `8880` | HTTP | Веб-UI, `/api/v1/rules`, `/api/v1/alerts`, `/-/reload`, `/metrics` |
| `8428` | HTTP | VictoriaMetrics (datasource, remote write/read) |
| `9093` | HTTP | Alertmanager (внешний) |

### Безопасность и управление доступом

#### RBAC (ServiceAccount, Role, ClusterRole)

Оператор VictoriaMetrics требует прав на чтение/запись ресурсов `VMRule`, `VMAlert`, `VMServiceScrape` и ConfigMap. Минимальный набор прав оператора описывается в его Helm-чарте. Для пода `vmalert` (при использовании ConfigMap или ServiceAccount) достаточно стандартных прав на чтение ConfigMap.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: vmalert
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: vmalert-rules-reader
  namespace: monitoring
rules:
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["operator.victoriametrics.com"]
  resources: ["vmalerts", "vmalerts/status"]
  verbs: ["get", "list", "watch"]
```

#### NetworkPolicy

Ограничьте сетевой доступ пода `vmalert` только источникам данных и Alertmanager:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: vmalert-netpol
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: vmalert
  policyTypes:
  - Ingress
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          name: victoriametrics
    ports:
    - protocol: TCP
      port: 8428
  - to:
    - namespaceSelector:
        matchLabels:
          name: alertmanager
    ports:
    - protocol: TCP
      port: 9093
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
      except:
      - 10.0.0.0/8
      - 172.16.0.0/12
      - 192.168.0.0/16
    ports:
    - protocol: TCP
      port: 53
    - protocol: UDP
      port: 53
```

#### Secrets и конфиденциальные данные

Если `-datasource.url` или `-notifier.url` содержат credentials, используйте `Secret` и `envFrom`:

```yaml
spec:
  containers:
    - name: vmalert
      envFrom:
      - secretRef:
          name: vmalert-datasource-secret
```

#### Аудит изменений

Включите аудит для `VMRule` и `VMAlert` через Kubernetes Audit Policy, чтобы отслеживать, кто и когда изменял алерты.

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

### Сценарий 3: GitOps-рабочий процесс (ArgoCD / Flux)

При использовании GitOps-инструментов (ArgoCD, Flux) манифесты `VMRule` и `VMAlert` хранятся в Git. Оператор автоматически применяет изменения. Ключевые моменты:

- **Health Assessment:** настройте ArgoCD `resource.customization` для ресурсов `operator.victoriametrics.com/v1beta1`, чтобы ArgoCD корректно оценивал статус `VMAlert` (сравнивайте `status.phase` или `status.podList`).
- **Pruning:** по умолчанию ArgoCD удаляет ресурсы, отсутствующие в Git. Если это нежелательно для `VMRule` (например, временные правила), используйте `argocd.argoproj.io/prune: Disabled` в аннотациях.
- **Sync Waves:** размещайте `VMServiceScrape` и `VMAuth` в волнах `0` и `1`, а `VMAlert` и `VMRule` — в волне `2`, чтобы источники данных были доступны до запуска оценки правил.

Пример аннотации для управления prune:

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMRule
metadata:
  name: temporary-rule
  namespace: monitoring
  annotations:
    argocd.argoproj.io/prune: Disabled
    argocd.argoproj.io/sync-options: Prune=false
spec:
  groups:
    - name: TemporaryGroup
      interval: 1m
      rules:
        - alert: TemporaryAlert
          expr: up == 0
          for: 1m
```

### Сценарий 4: Запись правил (Recording Rules) и chaining

#### Naming conventions

Используйте префиксы для организации recording rules:

- `rec:<service>:<metric>:<agg>` — например, `rec:payment:request_duration:p99`.
- Избегайте дублирования имён: оператор и `vmalert` запрещают дубликаты `name` + `expr` + labels в одной группе.

#### Chaining групп (зависимости)

Поскольку правила внутри группы выполняются последовательно, а результат recording rule становится доступен только после записи в удалённое хранилище, используйте chaining групп:

```yaml
spec:
  groups:
    - name: base-metrics
      interval: 1m
      rules:
        - record: job:request_rate:rate5m
          expr: sum by (job) (rate(http_requests_total[5m]))
    - name: derived-metrics
      interval: 1m
      rules:
        - record: job:error_ratio:ratio
          expr: sum by (job) (rate(http_requests_errors_total[5m])) / job:request_rate:rate5m
```

Важно: `derived-metrics` зависит от `base-metrics`. При изменении `base-metrics` ArgoCD/оператор применяет изменения в один проход, но `vmalert` оценивает группы последовательно. Убедитесь, что `interval` и `evaluationInterval` позволяют завершить оценку первой группы до начала второй.

#### Backfilling recording rules

Для заполнения исторических данных используйте режим replay (детали в [обзоре vmalert](./vmalert_overview.md)). При использовании `VMRule` backfill выполняется отдельным Job, который запускает `vmalert` с флагами `-replay.timeFrom` и `-replay.timeTo` и монтирует те же правила.

### Сценарий 5: Интеграция с vmauth

Если `vmalert` должен обслуживать и метрики (MetricsQL), и логи (LogsQL), используйте `vmauth` как единую точку входа:

```yaml
# vmauth.yml
routes:
  - path_prefix: /api/v1/query*
    url: http://vmselect.monitoring.svc:8481/select/0/prometheus
  - path_prefix: /select/logsql/*
    url: http://vlselect.monitoring.svc:9497/select/logsql/
```

`vmalert` обращается к `vmauth` (например, `http://vmauth.monitoring.svc:8427`), а `vmauth` маршрутизирует запросы в зависимости от типа правила. Это упрощает RBAC и аудит (единый ingress point).

### Сценарий 6: Sidecar reloader для ConfigMap (legacy)

При использовании ConfigMap без оператора автоматической горячей перезагрузки нет. Используйте sidecar `stakater/reloader`:

```yaml
spec:
  containers:
    - name: vmalert
      image: victoriametrics/vmalert:v1.136.0
      args:
        - -datasource.url=http://vmselect:8481/select/0/prometheus
        - -notifier.url=http://alertmanager:9093
        - -rule=/config/rules/*.yaml
      volumeMounts:
        - name: rules-volume
          mountPath: /config/rules
    - name: reloader
      image: stakater/reloader:latest
      args:
        - --container-name-to-reload=vmalert
        - --volume-mounted-in-container=rules-volume
        - --reload-strategy=env
      volumeMounts:
        - name: rules-volume
          mountPath: /config/rules
  volumes:
    - name: rules-volume
      configMap:
        name: vmalert-manual-rules
```

### Сценарий 7: Готовые пакеты правил из репозитория VictoriaMetrics

Базовые алерты здоровья стека не пишутся с нуля — официальные пакеты лежат в каталоге [`deployment/docker/rules`](https://github.com/VictoriaMetrics/VictoriaMetrics/tree/master/deployment/docker/rules) репозитория VictoriaMetrics: здоровье (`alerts-health.yml`), single-node и кластер, vmagent/vmalert/vmauth, тесты. Состав, скачивание и проверка — [Самомониторинг: Официальные пакеты алертов](./self-monitoring.md#2-официальные-пакеты-алертов); алерты самого Alertmanager — [Prometheus: практические примеры alert rules](../Prometheus/installation/alert_rules_quickstart.md).

**В bare-metal/kubernetesless** — скачать файлы и подключить wildcard-флагом:

```bash
mkdir -p /etc/vmalert/rules
curl -sL https://raw.githubusercontent.com/VictoriaMetrics/VictoriaMetrics/master/deployment/docker/rules/alerts-health.yml \
  -o /etc/vmalert/rules/alerts-health.yml
curl -sL https://raw.githubusercontent.com/VictoriaMetrics/VictoriaMetrics/master/deployment/docker/rules/alerts-vmagent.yml \
  -o /etc/vmalert/rules/alerts-vmagent.yml

./vmalert -rule='/etc/vmalert/rules/*.yml' \
  -datasource.url=http://vmsingle:8428 \
  -remoteWrite.url=http://vmsingle:8428
# → веб-UI: http://vmalert:8880
```

Обратите внимание на расширение: файлы пакета — `.yml`, поэтому glob должен быть `*.yml` (либо `*`), а не `*.yaml`.

**В Kubernetes** — упаковать файлы в ConfigMap и подключить монтированием каталога (подробный пример — [Сценарий 2: Управление через ConfigMap](#сценарий-2-управление-через-configmap)):

```bash
kubectl -n monitoring create configmap vmalert-rules \
  --from-file=alerts-health.yml --from-file=alerts-vmagent.yml
# → configmap/vmalert-rules created
```

Альтернатива для новых проектов — обернуть те же файлы в CRD `VMRule` ([Сценарий 1](#сценарий-1-управление-через-vmrule-crd-рекомендуемый)); для Kubernetes-специфичных алертов (kube-state-metrics, cadvisor) — [Grafana: алерты для Kubernetes](../Grafana/alerting/kubernetes_alerts.md).

Валидация после подключения — [Преддеплойная проверка](#преддеплойная-проверка) и [Unit-тестирование правил](#unit-тестирование-правил-vmalert-tool-test) в следующем разделе.

## 4. Валидация манифестов и CI/CD

### Преддеплойная проверка

Перед применением манифестов в кластер проверьте синтаксис всех правил:

```bash
# Проверка YAML-синтаксиса и MetricsQL/LogsQL
vmalert-tool check /etc/vmalert/rules/*.yaml
# → SUCCESS
```

`vmalert-tool check` проверяет:
- Корректность YAML-структуры.
- Уникальность имён правил внутри группы.
- Наличие `type: vlogs` для LogsQL-групп.
- Базовая валидация PromQL/MetricsQL/LogsQL выражений.

### Unit-тестирование правил (vmalert-tool test)

Для сложных алертов используйте unit-тесты на синтетических данных:

```bash
vmalert-tool test \
  -rule=/etc/valerts/test-rules.yaml \
  -datasource.type=prometheus \
  -datasource.url=http://test-storage:8428
```

Тесты описываются в YAML-файле и содержат:
- `input_metric` — синтетические временные ряды.
- `expected_alerts` — ожидаемые алерты после оценки правил.

### CI/CD-пайплайн

Пример этапа для GitHub Actions / GitLab CI:

```yaml
# .github/workflows/alert-rules.yml
name: Validate Alert Rules
on: [push, pull_request]
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Download vmalert-tool
        run: |
          curl -sSL https://github.com/VictoriaMetrics/VictoriaMetrics/releases/download/v1.136.0/vmalert-tool-v1.136.0-linux-amd64.tar.gz | tar xz
          sudo mv vmalert-tool /usr/local/bin/
      - name: Validate rules
        run: vmalert-tool check rules/*.yaml
      - name: Unit tests
        run: vmalert-tool test -rule=rules/*.yaml -datasource.url=http://test-storage:8428
```

### Admission Webhook

Оператор VictoriaMetrics может настроить Admission Webhook для валидации `VMRule` на этапе `kubectl apply`. Это предотвращает применение некорректных правил в кластер. Убедитесь, что в конфигурации оператора включён параметр `admissionWebhooks`.

## 5. Поиск и устранение неисправностей (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Правила не отображаются в UI | `ruleSelector` / `ruleNamespaceSelector` не соответствуют меткам VMRule; WATCH_NAMESPACE ограничивает область | Проверить соответствие меток и селекторов в `VMAlert` и `VMRule`, область `WATCH_NAMESPACE` |
| Ошибка в MetricsQL/LogsQL | Синтаксическая ошибка или неверный `type` группы | Убедиться в `type: vlogs` для LogsQL; запустить `vmalert-tool check` |
| LogsQL-правило молчит | Пропущен `stats`-пайп или `filter`-пайп в `expr` | Добавить обязательные пайпы; проверить time filter |
| Правила из другого Namespace не подхватываются | Не настроен `ruleNamespaceSelector` | Убедиться, что `ruleNamespaceSelector` в `VMAlert` разрешает поиск в целевой namespace |
| ConfigMap обновился, но vmalert не видит изменений | Использование `subPath` в монтировании | Отказаться от `subPath` или использовать sidecar (stakater/reloader) для рестарта пода |
| После рестарта алерты отправляются заново | Не настроен `remoteRead`/`remoteWrite` для восстановления состояния | Указать `remoteRead.url` и `remoteWrite.url` (см. раздел HA) |
| Дублирование уведомлений при нескольких репликах VMAlertmanager | Указан неполный список подов (`notifier` вместо `notifiers`) | Перечислить все FQDN в `notifiers` или использовать service discovery |
| Operator не обновляет VMAlert | CRD устарел или оператор перезапускается | Проверить версию CRD `VMAlert` и статус пода оператора |
| VMRule создан, но не применяется | Нет VMAlert, который бы выбрал это правило по селектору | Создать `VMAlert` с соответствующими `ruleSelector` / `ruleNamespaceSelector` |
| Алерт переходит в Firing и сразу снова в Pending | Значение `for` слишком мало или источник данных возвращает скачки | Увеличить `for` или добавить hysteresis (например, `for` + `threshold` в expr) |

## 6. Управление жизненным циклом правил

### Версионирование и организация

- **Один `VMRule` = одна группа ответственности:** не смешивайте правила от разных команд в одном ресурсе.
- **Именование групп:** используйте формат `<team>-<env>-<component>` (например, `infra-prod-hostmetrics`, `app-dev-log-alerts`).
- **Именование алертов:** префикс с именем сервиса/команды (например, `payment_high_error_rate` вместо просто `HighErrorRate`).

### Deprecation и удаление

1. **Soft deprecation:** добавьте аннотацию `deprecated: "true"` и уменьшите `for` до `0s` или переведите алерт в `no_data` через `expr: vector(0)`. Мониторьте активность алерта в течение 2–4 недель.
2. **Hard delete:** после подтверждения, что алерт больше не нужен, удалите `VMRule` или запись из ConfigMap. Оператор автоматически перезагрузит конфигурацию.

### Миграция между подходами

При переходе от ConfigMap к VMRule CRD:

1. Создайте `VMRule` с тем же содержимым, что и в ConfigMap.
2. Создайте `VMAlert` с селектором, выбирающим новые `VMRule`.
3. Убедитесь, что оба инстанса `vmalert` (старый через ConfigMap и новый через оператор) загрузили одни и те же правила.
4. Отключите старый Deployment и удалите ConfigMap.

## 7. Обновление и откат

### Обновление VictoriaMetrics Operator

Обновление оператора влияет на генерацию конфигурации `vmalert` и обработку `VMRule`:

```bash
# 1. Бэкап CRD и ресурсов
kubectl get crd vmrules.operator.victoriametrics.com vmalters.operator.victoriametrics.com -o yaml > vm-crds-backup.yaml
kubectl get vmrule,vmalert -A -o yaml > vm-resources-backup.yaml

# 2. Обновление Helm-репозитория
helm repo update victoria-metrics
helm upgrade vm-operator victoria-metrics/vm-operator \
  --namespace monitoring --create-namespace \
  --version <новая-версия>

# 3. Проверка статуса оператора
kubectl rollout status deployment/vm-operator -n monitoring
kubectl get pods -n monitoring -l app.kubernetes.io/name=vm-operator
```

После обновления оператор автоматически пересмотрит все `VMAlert` и `VMRule`. Проверьте, что конфигурация перезагрузилась:

```bash
curl -s http://<vmalert-service>:8880/api/v1/rules | jq '.data.groups | length'
```

### Обновление манифестов правил

Изменения `VMRule` применяются атомарно через operator:

1. Обновите `VMRule` манифест в Git.
2. ArgoCD/Flux автоматически применит изменения.
3. Operator обнаружит изменение и обновит ConfigMap, подключённый к подам `vmalert`.
4. `vmalert` выполнит hot reload (`/-/reload`) без перезапуска подов.

### Откат

При проблемах с новыми правилами:

```bash
# 1. Откат манифеста в Git (ArgoCD откатит автоматически)
git revert HEAD~1
git push

# 2. Если ArgoCD не откатился, принудительно:
kubectl rollout undo deployment/<vmalert-deployment> -n monitoring

# 3. При проблемах с оператором — откат Helm-релиза
helm rollback vm-operator -n monitoring
```

### Проверка после обновления

```bash
# Проверка версии оператора
kubectl get deployment vm-operator -n monitoring -o jsonpath='{.spec.template.spec.containers[0].image}'
# → victoriametrics/vm-operator:v1.x.x

# Проверка, что правила загружены
kubectl exec -n monitoring deploy/<vmalert-deployment> -- curl -s http://localhost:8880/api/v1/rules | jq '.data.groups[].name'

# Проверка метрик самомониторинга
kubectl exec -n monitoring deploy/<vmalert-deployment> -- curl -s http://localhost:8880/metrics | grep vmalert_build_info
```

## 8. Мониторинг самомониторинг

### Ключевые метрики

`vmalert` экспортирует метрики на эндпоинте `/metrics`:

| Метрика | Описание | Рекомендуемый алерт |
| :--- | :--- | :--- |
| `vmalert_rule_group_last_duration_seconds` | Время оценки последней группы правил | `> (interval * 1.5)` — группа не успевает за интервалом |
| `vmalert_queries_failed_total` | Количество неудачных запросов к источнику данных | `rate(...) > 0` в течение 2m |
| `vmalert_alerts_fired_total` | Количество сработавших алертов | Спайк может указывать на проблему |
| `vmalert_rule_group_last_evaluation_timestamp_seconds` | Время последней оценки (unix timestamp) | Отставание > 2 * interval |
| `vmalert_remote_write_errors_total` | Ошибки Remote Write | `rate(...) > 0` |
| `vmalert_remote_read_errors_total` | Ошибки Remote Read | `rate(...) > 0` |

### Recording rules для самомониторинга

Создайте recording rules для своевременного обнаружения проблем:

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMRule
metadata:
  name: vmalert-self-monitoring
  namespace: monitoring
spec:
  groups:
    - name: vmalert-sli
      interval: 30s
      rules:
        - record: vmalert:rule_group_duration_seconds:p99
          expr: histogram_quantile(0.99, sum(rate(vmalert_rule_group_last_duration_seconds_bucket[5m])) by (le))
        - record: vmalert:query_failures:rate5m
          expr: sum(rate(vmalert_queries_failed_total[5m]))
        - record: vmalert:remote_write_errors:rate5m
          expr: sum(rate(vmalert_remote_write_errors_total[5m]))
```

### Алерты на самомониторинг

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMRule
metadata:
  name: vmalert-self-alerts
  namespace: monitoring
spec:
  groups:
    - name: vmalert-alerts
      interval: 30s
      rules:
        - alert: VmalertRuleGroupEvaluationStale
          expr: time() - vmalert_rule_group_last_evaluation_timestamp_seconds > 120
          for: 2m
          labels:
            severity: critical
          annotations:
            summary: "vmalert {{ $labels.instance }} не оценивает правила"
        - alert: VmalertQueryFailures
          expr: sum(rate(vmalert_queries_failed_total[5m])) > 0
          for: 3m
          labels:
            severity: warning
          annotations:
            summary: "Ошибки запросов к источнику данных в vmalert {{ $labels.instance }}"
        - alert: VmalertDown
          expr: up{job="vmalert"} == 0
          for: 1m
          labels:
            severity: critical
          annotations:
            summary: "vmalert {{ $labels.instance }} недоступен"
```

## 9. Resource Limits и планирование

### Запросы и лимиты пода

Рекомендуемые ресурсы для пода `vmalert`:

```yaml
spec:
  containers:
    - name: vmalert
      resources:
        requests:
          cpu: 500m
          memory: 1Gi
        limits:
          cpu: 2
          memory: 4Gi
```

### Тюнинг параметров

| Параметр | Рекомендация | Обоснование |
| :--- | :--- | :--- |
| `evaluationInterval` (группа) | `30s` для инфра, `1m–5m` для логов | Чем ниже, тем выше нагрузка на источник данных |
| `concurrency` | Оставьте `1` (последовательная оценка) | Параллелизм внутри группы не поддерживается |
| `-datasource.queryTimeout` | `30s`–`1m` | Запросы к логам ресурсоёмкие |
| `-remoteWrite.maxQueueSize` | `10000` | Размер очереди для записи состояния |
| `replicaCount` | 2+ для HA | Дублирование алертов при отсутствии `-external.label` |

### Ограничение количества правил

- В одной группе ограничьтесь 20–50 правил. При >100 rules время evaluation может превысить `interval`.
- Разделяйте правила по группам по признаку: инфраструктура, приложения, логи, бизнес-метрики.

## 10. Ограничения и особые случаи

### Последовательная оценка внутри группы

Правила внутри одной группы выполняются последовательно (`concurrency: 1`). При большом количестве правил время оценки накапливается. Решение: дробление на несколько групп с разными `interval`.

### Восстановление состояния (State Recovery)

- Восстановление происходит **только один раз при старте**. При hot reload состояние не восстанавливается.
- Если конфигурация правил изменилась, восстановление для удалённых правил не произойдёт.
- Серии `ALERTS_FOR_STORE` устаревают через `-remoteRead.lookback` (по умолчанию 1 час).

### LogsQL-ограничения

- Обязательно `type: vlogs` на уровне группы.
- Обязательно наличие `stats`- и `filter`-пайпов.
- Backfill для правил с кастомным time filter не поддерживается.

### Сеть

- При недоступности источника данных `vmalert` логирует ошибку, но продолжает работу с другими правилами.
- Нет встроенного circuit breaker — проектируйте `for` и пороги с учётом возможных пропусков.

### Известные проблемы

- При использовании `for` > 10 минут и высокой `interval` группам требуется больше времени для перехода в Firing.
- При рестарте `vmalert` без `-remoteRead.url` все алерты переходят в Pending заново.

## 11. FAQ

**Q: Можно ли использовать один `vmalert` и для метрик, и для логов?**
A: Да, через `vmauth` с маршрутизацией по пути запроса. Альтернатива — отдельные инстансы `vmalert`.

**Q: Какой `interval` выбрать для правил алертинга?**
A: Для метрик infrastructure — `30s`. Для бизнес-метрик и логов — `1m–5m`. Чем ниже interval, тем выше нагрузка.

**Q: Нужно ли использовать recording rules для простых запросов?**
A: Нет. Recording rules целесообразны для сложных aggregations, переиспользуемых в 3+ алертах или дэшбордах.

**Q: Что происходит при перезапуске Alertmanager?**
A: `vmalert` повторно отправит алерты в новый инстанс. Для подавления дублей используйте `-external.label` и настройте Alertmanager на дедупликацию.

**Q: Как откатить изменение правила без перезапуска?**
A: Используйте `/-/reload` после отката файла правил. При VMRule оператор применит изменения автоматически.

**Q: Где хранится состояние алертов?**
A: В памяти процесса. Для персистентности используйте `-remoteWrite.url` и `-remoteRead.url`.

**Q: Как мониторить сам `vmalert`?**
A: Используйте эндпоинт `/metrics` и добавьте алерты на `up{job="vmalert"}`, `vmalert_queries_failed_total`, `vmalert_rule_group_last_duration_seconds`.

**Q: Что такое vmalert-tool и зачем он нужен?**
A: CLI-утилита для валидации YAML-конфигурации и unit-тестирования правил. Обязательна для CI/CD пайплайнов.

**Q: Поддерживает ли `vmalert` multi-tenancy?**
A: В Enterprise-версии да (`-clusterMode=true` + поле `tenant` в правилах). В Community — нет встроенного механизма, используйте отдельные инстансы.

**Q: Почему LogsQL-правило молчит?**
A: Проверьте `type: vlogs` на уровне группы, наличие `stats`- и `filter`-пайпов в `expr`, а также time filter.

## 12. Дополнительная информация

### Лучшие практики

- **Один `VMRule` = одна группа ответственности:** не смешивайте правила от разных команд.
- **Именование:** используйте префиксы `<team>-<env>-<component>` для групп и `<service>_<condition>` для алертов.
- **Валидация:** запускайте `vmalert-tool check` и `vmalert-tool test` в CI/CD перед деплоем.
- **GitOps:** храните манифесты в Git, используйте ArgoCD/Flux с правильными настройками pruning и sync waves.
- **Версионирование образов:** используйте фиксированные теги (например, `v1.136.0`), а не `latest`.

**Ссылки:**
- [Обзор vmalert](./vmalert_overview.md) — архитектура, запуск, самомониторинг.
- [VictoriaMetrics Operator](./operator_overview.md) — CRD и reconcile-цикл.
- [VMAlert Operator CRD Docs](https://docs.victoriametrics.com/operator/resources/vmalert/)
- [VMRule CRD Docs](https://docs.victoriametrics.com/operator/resources/vmrule/)
- [LogsQL Alerting Guide](https://docs.victoriametrics.com/victorialogs/vmalert/)
