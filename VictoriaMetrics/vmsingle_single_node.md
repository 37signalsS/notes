# vmsingle — однобинарная замена стека Prometheus

**Актуально для:** VictoriaMetrics v1.136+

## Определения

**vmsingle** — режим работы VictoriaMetrics, объединяющий приём (vminsert), хранение и выполнение запросов (vmselect) в одном процессе. Заменяет Prometheus + оператор на одиночном узле.

**Прометеус-оператор** — Kubernetes-оператор для управления стекк Prometheus (Prometheus, Alertmanager, etc.) через CRD (PrometheusRule, ServiceMonitor, etc.).

## Основные концепции

vmsingle предназначен для сценариев, когда полноценный стек Prometheus с оператором избыточен, например, на небольшом VPS с ограниченными ресурсами. Вместо отдельных компонентов Prometheus, оператора и связанных CRD, vmsingle предоставляет единый бинарник, который:

- Принимает метрики через встроенный скрейпер, совместимый со стандартными `scrape_configs` Prometheus.
- Хранит метрики в эффективном временно-рядном хранилище с высокой степенью сжатия.
- Отвечает на запросы по PromQL с расширениями MetricsQL.
- Предоставляет встроенный веб-интерфейс (VMUI) для ad-hoc запросов и визуализации.
- Может быть дополнен vmalert для оценки правил алертинга.

Архитектурно, vmsingle устраняет необходимость в:
- Отдельном сервере Prometheus.
- Операторе Prometheus и его CRD (PrometheusRule, ServiceMonitor, etc.).
- Внешнем слое долговременного хранения для простых сценариев (хотя может использоваться как локальное хранилище с длительным retention).

## Практические сценарии

### Установка и настройка

vmsingle может быть развёрнут в Kubernetes через Helm чарт `vm/victoria-metrics-single`. Пример значения файла (`values.yaml`):

```yaml
server:
  fullnameOverride: "vmsingle-server"
  retentionPeriod: "90d"
  persistentVolume:
    enabled: true
    existingClaim: vmsingle-data
  resources:
    limits:
      cpu: 500m
      memory: 512Mi
    requests:
      cpu: 50m
      memory: 128Mi
  extraArgs:
    enableTCP6: "true"
    envflag.enable: "true"
    loggerFormat: json
    vmalert.proxyURL: http://vmalert.monitoring.svc.cluster.local:8080
    memory.allowedPercent: "20"
```

#### Важные флаги

- `memory.allowedPercent: 20` — VictoriaMetrics рассчитывает размер внутренних кэшей как процент от доступной памяти. Значение по умолчанию (60%) берётся от cgroup-лимита, а когда на узле живёт ещё куча всего, кэши безопаснее держать маленькими. Скорость запросов на датасете такого размера не страдает.
- `vmalert.proxyURL` — VMUI проксирует вкладки алертинга в vmalert, и сработавшие правила видны в том же UI.

#### Срок хранения

Срок хранения 90 дней для домашнего кластера — с запасом, и всё равно укладывается в считанные гигабайты: VictoriaMetrics сжимает медленно меняющиеся ряды сильно меньше байта на сэмпл.

### Хранилище: hostPath PV с Retain

Если в кластере нет storage class, PV объявляется вручную и привязывается к каталогу на узле:

```yaml
apiVersion: v1
kind: PersistentVolume
metadata:
  name: vmsingle-data
spec:
  capacity:
    storage: 20Gi
  accessModes: [ReadWriteOnce]
  persistentVolumeReclaimPolicy: Retain
  hostPath:
    path: /var/lib/victoria-metrics
    type: DirectoryOrCreate
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: vmsingle-data
  namespace: monitoring
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 20Gi
  volumeName: vmsingle-data
  storageClassName: ""
```

- `storageClassName: ""` — пустая строка отключает динамический провижнинг, иначе PVC повиснет в Pending в ожидании провижионера по умолчанию, которого нет.
- `Retain` означает, что 90 дней метрик переживут `helm uninstall`.

### Конфиг скрейпа

Встроенный скрейпер включается через `scrape.enabled: true`. Конфиг — обычный синтаксис Prometheus:

```yaml
scrape:
  enabled: true
  config:
    global:
      scrape_interval: 30s
      scrape_timeout: 10s
    scrape_configs:
    - job_name: node
      static_configs:
      - labels:
          instance: k0s-node
        targets:
        - node-exporter-prometheus-node-exporter.monitoring.svc.cluster.local:9100
    - job_name: kube-state-metrics
      static_configs:
      - targets:
        - kube-state-metrics.monitoring.svc.cluster.local:8080
    - job_name: traefik
      static_configs:
      - labels:
          instance: traefik
        targets:
        - traefik.traefik.svc.cluster.local:9101
      metric_relabel_configs:
      - source_labels: [service]
        regex: '(.+)-[0-9a-f]{16}@kubernetescrd'
        replacement: '$1'
        target_label: service
```

На одном узле со стабильными именами Service'ов service discovery не добавляет ничего, кроме движущихся частей. Полный список таргетов: node-exporter, kube-state-metrics, сам vmsingle, vmalert, Traefik, два экспортёра прокси, три джоба blackbox-exporter (HTTP-аптайм девяти сайтов, TCP-проверки портов прокси, внешняя DNS-связность), kubelet cAdvisor и textfile-коллектор для пиров WireGuard.

#### Relabel-правило для Traefik

Сервисы из IngressRoute CRD Traefik называют как `namespace-name-<16 hex символов>@kubernetescrd`. Хеш меняется при изменении роута, и любой дашборд с группировкой по `service` разваливается. Relabel срезает хеш прямо на этапе скрейпа.

### Скрейп cAdvisor через kubelet

Метрики CPU и памяти по контейнерам отдаёт встроенный в kubelet cAdvisor — ему нужны TLS и токен:

```yaml
- job_name: cadvisor
  scheme: https
  tls_config:
    insecure_skip_verify: true
  bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
  metrics_path: /metrics/cadvisor
  honor_labels: true
  static_configs:
  - targets:
    - 91.184.248.13:10250
  metric_relabel_configs:
  - source_labels: [container]
    regex: ".+"
    action: keep
  - source_labels: [container]
    regex: "POD"
    action: drop
```

Токен ServiceAccount работает, только если этому ServiceAccount разрешено ходить в API kubelet'а. Это маленький ClusterRole:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: vmsingle-kubelet-metrics
rules:
  - apiGroups: [""]
    resources: ["nodes", "nodes/metrics"]
    verbs: ["get", "list", "watch"]
  - nonResourceURLs: ["/metrics", "/metrics/cadvisor", "/metrics/resource"]
    verbs: ["get"]
```

привязанный к ServiceAccount vmsingle-server. Два metric_relabel_configs выкидывают ряды pause-контейнеров (container="POD") и агрегаты по cgroup с пустым лейблом container — без них каждый под порождает два-три фантомных дубля, и дашборды считают память дважды.

### Стабильное имя сервиса

Одно неочевидное дополнение — обычный ClusterIP Service перед vmsingle:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: vmsingle-stable
  namespace: monitoring
spec:
  selector:
    app.kubernetes.io/instance: vmsingle
    app.kubernetes.io/name: victoria-metrics-single
  ports:
    - port: 8428
      targetPort: 8428
  type: ClusterIP
```

Чарт создаёт headless Service, а headless DNS резолвится прямо в IP пода. Во время рестартов CoreDNS (на одном узле это каждая перезагрузка ноды) клиенты с закэшированным старым IP пода ловят connection refused. Grafana и vmalert смотрят на `vmsingle-stable` — ClusterIP переживает пересоздание пода.

## Устранение неполадок

### OOMKilled под нагрузкой запросов

Cgroup-лимит 512 МБ, и тяжёлые запросы по длинным диапазонам дают всплески. `memory.allowedPercent: 20` держит кэши маленькими; если OOM всё равно случается — сначала поднимайте лимит, а не трогайте флаг: кэши меньше ~100 МБ замедляют вообще всё.

### PVC висит в Pending

Почти всегда — отсутствующая пара `storageClassName: ""` / `volumeName` на самодельных PV+PVC. Смотрите `kubectl -n monitoring describe pvc vmsingle-data`: «waiting for first consumer» — нормально, «no persistent volumes available» — биндинг настроен неверно.

### Скрейп cAdvisor возвращает 401

ClusterRoleBinding должен указывать на то имя ServiceAccount, которое чарт реально сгенерировал — `fullnameOverride` его меняет. Проверьте `kubectl -n monitoring get sa` и `subject` в биндинге.

### Дашборды считают память контейнеров дважды

Прорвались ряды container="POD" и с пустым container. Убедитесь, что metric_relabel_configs есть в работающем конфиге: `curl -s localhost:8428/config | grep -A5 cadvisor` после port-forward.

## Лучшие практики

Среди повторяющихся решений для наблюдаемости на ограниченных ресурсах выделяются следующие паттерны:

- **Одиночный бинарник вместо распределённого** — vmsingle вместо Prometheus+оператор, single-node victoria-logs вместо кластера, promtail вместо конвейера агентов. На одном узле любой слой координации — чистый оверхед.
- **Статический конфиг вместо discovery** — Scrape-таргеты — static_configs, путь к логам — глоб, дашборды и datasources — файлы в git. Механизмы discovery окупают сложность там, где вещи приходят и уходят; здесь не уходит ничего.
- **hostPath PV + Retain + явный биндинг через volumeName** — Ни storage class, ни провижионера; данные переживают helm uninstall, а `storageClassName: ""` на PVC не даёт ему ждать провижионер, которого нет.
- **Ограниченная память везде** — У каждого компонента лимиты; vmsingle дополнительно зажимает кэши через `memory.allowedPercent: 20`. На общей ноде безлимитный стек наблюдаемости первым делом OOM-ит те самые сервисы, за которыми должен следить.
- **Стабильные ClusterIP-имена** — Grafana и vmalert ходят в `vmsingle-stable` — обычный ClusterIP перед headless-сервисом чарта: headless DNS раздаёт IP подов, которые протухают при рестартах CoreDNS.

## Дополнительная информация

- [Обзор VictoriaMetrics](../VictoriaMetrics/overview.md) — архитектура, компоненты, сравнение
- [Обзор vmalert](../VictoriaMetrics/vmalert_overview.md) — правила алертинга, интеграция с VictoriaLogs
- [Архитектура наблюдаемости в Kubernetes](./kubernetes-monitoring-logging-architecture.md) — общая схема стека мониторинга
- [Полная наблюдаемость на одном VPS: метрики, логи, алерты, дашборды](../Kubernetes/MonitoringLogging/single-vps-observability-case-study.md) — пример использования vmsingle в стеке с VictoriaLogs
- [LogsQL: руководство по запросам](../VictoriaMetrics/logsql_overview.md) — синтаксис и функции аналитики логов