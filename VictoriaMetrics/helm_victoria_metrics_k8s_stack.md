# VictoriaMetrics в Kubernetes: чарт `victoria-metrics-k8s-stack`

**Актуально для:** VictoriaMetrics Helm chart `victoria-metrics-k8s-stack` v0.96.0 (AppVersion: VM v1.154.0, VM Operator 0.68.1)

## Определения

**`victoria-metrics-k8s-stack`** — официальный Helm-чарт VictoriaMetrics для развёртывания полноценного мониторингового стека в Kubernetes «из коробки»: VictoriaMetrics (single или cluster), `vmagent`, `vmalert`, `vmauth`, `Alertmanager` и вложенный `Grafana` с готовыми дашбордами и datasource. Полный аналог `kube-prometheus-stack`, но на компонентах VictoriaMetrics.

**Отличие от Operator** — оператор (см. [operator_overview.md](./operator_overview.md)) управляет VM через CRD (декларативный подход для сложных сценариев и автоматизации). `k8s-stack` — готовый «стек в один helm install»: быстрее для большинства сред, но менее гибкий для кастомных CRD-манипуляций.

**Dependency chart** — вспомогательный Helm-чарт, который `k8s-stack` включает как зависимость (grafana, prometheus-node-exporter, kube-state-metrics, victoria-metrics-operator). Параметры зависимых чартов задаются в `values.yaml` под ключом имени зависимости.

## Базовые концепции

### Что входит в чарт

| Компонент | Роль |
| :--- | :--- |
| `vmsingle` (single-node CRD) или `vmcluster` (cluster CRD) | Хранение метрик и query API |
| `vmagent` | Скрейпинг node/job/ServiceMonitor и Push |
| `vmalert` | Правила алертинга + recording rules |
| `vmauth` | Маршрутизация и аутентификация внешнего доступа |
| `alertmanager` | Рассылка оповещений (связан с `vmalert`) |
| `grafana` | Дашборды; datasources VM подключаются автоматически через sidecar |
| `prometheus-node-exporter` | Метрики узлов |
| `kube-state-metrics` | Метрики объектов Kubernetes |
| `victoria-metrics-operator` | Управление CRD (VMSingle, VMCluster, VMAgent, VMAlert и др.) |

Опционально (начиная с v0.85.0):

| Компонент | Роль |
| :--- | :--- |
| `vlsingle` (VLSingle CRD) или `vlcluster` (VLCluster CRD) | Хранение логов (VictoriaLogs) |
| `vlagent` | Сбор логов с подов и узлов |
| `vtsingle` (VTSingle CRD) или `vtcluster` (VTCluster CRD) | Хранение трейсов (VictoriaTraces) |

- Default-дашборды (node, kube-state-metrics, VM) приходят в Grafana через sidecar;
- Datasource «VictoriaMetrics» типа Prometheus создаётся автоматически (URL на `vmsingle`/`vmcluster`), datasource «VictoriaLogs (DS)» — для логов (требуется плагин `victoriametrics-logs-datasource`), datasource «VictoriaTraces» — для трейсов (встроенный Jaeger datasource);
- vmalert маршрутизирует запросы через внутренний vmauth: `/select/logsql/.*` → VictoriaLogs (LogsQL), остальные → VictoriaMetrics (MetricsQL).

### Когда использовать

- Средние/крупные prod-окружения: быстрый старт мониторинга node + kube-state + приложений;
- Для deep-CRD автоматизации (автомасштабирование, секции много-кластерых реплик) — предпочесть [оператор](./operator_overview.md);
- Мелкие кластеры — подойдёт даже `vmsingle` (один инстанс VM вместо кластера).

## Предварительные требования

- **Kubernetes кластер** — рабочий кластер v1.21+ с достаточными ресурсами;
- **Helm v3** — менеджер пакетов ([установка](https://helm.sh/docs/intro/install/));
- **kubectl** — для управления кластером и проверки ([установка](https://kubernetes.io/docs/tasks/tools/install-kubectl/));
- **Хранилище** — PVC включено по умолчанию, т.е. необходимо наличие default StorageClass или явное указание `storageClassName`.

## Установка и настройка

### Добавление репозитория

```bash
helm repo add vm https://victoriametrics.github.io/helm-charts/
helm repo update
```

Альтернативно через OCI-реестр:

```bash
helm install vmks oci://ghcr.io/victoriametrics/helm-charts/victoria-metrics-k8s-stack \
  --version 0.96.0
```

### Просмотр доступных версий

```bash
helm search repo vm/victoria-metrics-k8s-stack -l
# → vm/victoria-metrics-k8s-stack    0.96.0    1.154.0    ...
```

### Быстрая установка (default-конфигурация)

```bash
helm upgrade --install vmks vm/victoria-metrics-k8s-stack \
  --version 0.96.0 \
  --namespace monitoring --create-namespace \
  --set argoContainerImage.registry=none 2>/dev/null
```

Если релиз называется длиннее 11 символов, имена сервисов могут превысить лимит 63 символов Kubernetes. Рекомендуется короткое имя релиза:

```bash
helm upgrade --install vmks vm/victoria-metrics-k8s-stack \
  --namespace monitoring --create-namespace
```

#### Проверка установки

```bash
kubectl -n monitoring get pods
# → vmsingle-0            1/1 Running
# → vmagent-xxxxx         1/1 Running
# → vmalert-xxxxx         1/1 Running
# → grafana-xxxxx         2/2 Running

kubectl -n monitoring port-forward svc/vmks-grafana 3000:80
# login admin / <пароль из grafana-admin секрета>
# → откройте http://localhost:3000
```

> **Пароль Grafana:** по умолчанию `prom-operator`. Для продакшена задавайте явно через `grafana.adminPassword` или используйте `existingSecret` — см. [Grafana Helm installation](./../Grafana/Installation/grafana_helm_installation.md).

### Минимальный production-конфиг через `values.yaml`

```yaml
# values.yaml
prometheus-node-exporter:
  enabled: true

vmsingle:
  enabled: true
  repo: ""
  tag: v1.154.0
  resources:
    requests:
      memory: "2Gi"
      cpu: "500m"
  storage:
    enabled: true
    volumeClaimTemplate:
      spec:
        resources:
          requests:
            storage: 100Gi

vmagent:
  enabled: true
  resources:
    requests:
      memory: "512Mi"
      cpu: "200m"

vmalert:
  enabled: true
  spec:
    dataSource:
      url: http://vmks-vmsingle:8428
    notifier:
      url: http://vmks-alertmanager:9093

grafana:
  enabled: true
  adminPassword: "REPLACE_ME"
  sidecar:
    dashboards:
      enabled: true
    datasources:
      enabled: true

alertmanager:
  enabled: true
  config:
    global:
      resolve_timeout: 5m
```

> Структура `values.yaml` и названия ключей могут меняться между мажорными версиями чарта — сверяйтесь с [README релиза](https://github.com/VictoriaMetrics/helm-charts).

### Переключение single → cluster

Замените `vmsingle:` на `vmcluster:`:

```yaml
prometheus-node-exporter:
  enabled: true

vmcluster:
  enabled: true
  vmsingle_count: 1
  vmstorage:
    podManagementPolicy: Parallel
    replicaCount: 3
    storage:
      volumeClaimTemplate:
        spec:
          resources:
            requests:
              storage: 100Gi
  vminsert:
    replicaCount: 2
  vmselect:
    replicaCount: 2
```

Часть данных снова шардируется — см. детали репликации в [cluster_operations.md](./cluster_operations.md).

### Кастомные алерты через `prometheusRule`

```yaml
vmalert:
  enabled: true
  spec:
    dataSource:
      url: http://vmks-vmsingle:8428
    notifier:
      url: http://vmks-alertmanager:9093
    prometheusRule:
      vmks-custom:
        rules:
          - group: "custom"
            rules:
              - alert: HighCPULoad
                expr: "100 - (avg by(instance) (rate(node_cpu_seconds_total{mode=\"idle\"}[5m])) * 100) > 80"
                for: 10m
                labels:
                  severity: warning
```

### Доступ к UI через ingress/vmauth

```yaml
vmauth:
  enabled: true
  spec:
    routeSettings: {}
    unauthorizedUser:
      urlMap:
        - src_paths: ["/vmui", "/api/v1/.*"]
          url_prefix: http://vmks-vmsingle:8428

ingress:
  enabled: true
  className: nginx
  hosts:
    - vm.example.com
```

## Интеграция VictoriaLogs и VictoriaTraces

Начиная с v0.85.0 чарт поддерживает развёртывание VictoriaLogs и VictoriaTraces параллельно с VictoriaMetrics.

### VictoriaLogs (хранение и сбор логов)

**VLSingle** (single-node):

```yaml
vlsingle:
  enabled: true
  spec:
    retentionPeriod: 30d
    storage:
      resources:
        requests:
          storage: 50Gi
```

**VLCluster** (HA, взаимно исключающий с VLSingle):

```yaml
vlcluster:
  enabled: true
  spec:
    retentionPeriod: 30d
    vlstorage:
      replicaCount: 2
    vlselect:
      replicaCount: 2
    vlinsert:
      replicaCount: 2
```

Подключение к существующему VictoriaLogs:

```yaml
external:
  vl:
    read:
      url: http://your-victorialogs-host:9428
    write:
      url: http://your-victorialogs-host:9428
```

VLAgent для сбора логов с подов и узлов:

```yaml
vlagent:
  enabled: true
  spec:
    k8sCollector:
      enabled: true
```

Datasource для Grafana требует плагин `victoriametrics-logs-datasource`:

```yaml
grafana:
  plugins:
    - victoriametrics-logs-datasource
```

### VictoriaTraces (хранение трейсов)

**VTSingle** (single-node):

```yaml
vtsingle:
  enabled: true
  spec:
    retentionPeriod: "7"  # дней
    storage:
      resources:
        requests:
          storage: 20Gi
```

**VTCluster** (HA):

```yaml
vtcluster:
  enabled: true
  spec:
    retentionPeriod: 14d
    vtstorage:
      replicaCount: 2
```

Подключение к существующему VictoriaTraces:

```yaml
external:
  vt:
    read:
      url: http://your-victoriatraces-host:10428
    write:
      url: http://your-victoriatraces-host:10428
```

Datasource для трейсов создаётся автоматически как Jaeger datasource (встроен в Grafana, плагин не нужен).

### vmalert с VictoriaMetrics и VictoriaLogs

При включённом `vmalert.enabled` и обоих endpoints (VM read и VL read) chart устанавливает внутренний vmauth proxy с маршрутизацией:

- `/select/logsql/.*` → VictoriaLogs (правила LogsQL)
- `/*` → VictoriaMetrics (правила MetricsQL)

Дополнительная конфигурация не требуется — маршрутизация работает прозрачно.

## Сбор метрик Control Plane (etcd, CoreDNS, kube-proxy)

Чарт умеет скрейпить компоненты control plane без отдельных экспортёров — через `VMServiceScrape` с селекторами подов (или endpoints, если компонент не запущен подом). Значения по умолчанию из `values.yaml` чарта:

| Ключ | По умолчанию | Что скрейпит |
| :--- | :--- | :--- |
| `coreDns.enabled` | `true` | CoreDNS: порт `9153`, селектор `k8s-app: kube-dns` (альтернатива `kubeDns.enabled` — `false`, legacy KubeDNS) |
| `kubelet.enabled` | `true` | kubelet + cAdvisor (`vmScrapes.cadvisor.enabled: true`, путь `/metrics/cadvisor`) |
| `kubeControllerManager.enabled` | `true` | Порт сервиса `10257`, HTTPS с CA serviceaccount |
| `kubeScheduler.enabled` | `true` | Порт `10259`, селектор `component: kube-scheduler`, HTTPS |
| `kubeEtcd.enabled` | `true` | Порт `2379`, селектор `component: etcd`, HTTPS + bearer token |
| `kubeProxy.enabled` | **`false`** | kube-proxy: порт `10249`, селектор `k8s-app: kube-proxy` |

Важные нюансы:

- **kube-proxy выключен по умолчанию** — включите ключом `kubeProxy: {enabled: true}`. Но одного чарта недостаточно: kube-proxy по умолчанию слушает метрики только на `127.0.0.1:10249` (`--metrics-bind-address`), и при работе через `--config` этот флаг вообще игнорируется — задавайте `metricsBindAddress: 0.0.0.0:10249` в `KubeProxyConfiguration`. Иначе Service чарта не достучится до пода и скрейп будет падать. Ключевые метрики: `kubeproxy_sync_proxy_rules_duration_seconds`, `kubeproxy_sync_proxy_rules_endpoint_changes_pending`, `kubeproxy_sync_proxy_rules_service_changes_pending`.
- **Компоненты вне подов** (etcd/control plane на стендовых узлах) — укажите IP в `kubeEtcd.endpoints` / `kubeControllerManager.endpoints` / `kubeScheduler.endpoints` / `kubeProxy.endpoints`: при непустом `endpoints` используются только `port`/`targetPort` сервиса, селектор подов отключается.
- Статические поды control plane и их ограничения — [Prometheus: Мониторинг статических подов Control Plane](../Prometheus/kubernetes/service_discovery.md#6-мониторинг-статических-подов-control-plane-etcd-api-server); etcd отдельно — [Мониторинг etcd](../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/etcd-monitoring.md); CoreDNS — [Мониторинг CoreDNS](../Prometheus/kubernetes/service_discovery.md#5-мониторинг-coredns).

## Операции и команды

### Тест установки (dry-run)

Перед установкой всегда проверяйте шаблоны:

```bash
helm install vmks vm/victoria-metrics-k8s-stack \
  -f values.yaml \
  --namespace monitoring \
  --debug \
  --dry-run
# → произведён рендеринг manifest'ов без реальной установки
```

### Проверка работоспособности

```bash
# Порт-форвардинг vmsingle
kubectl -n monitoring port-forward svc/vmks-vmsingle 8428:8428 &
curl -s http://localhost:8428/metrics | head -n 3
curl -s 'http://localhost:8428/api/v1/query?query=up' | jq '.data.result | length'
# → 1

# vmui (web UI)
kubectl -n monitoring port-forward svc/vmks-vmsingle 8428:8428
# → откройте http://localhost:8428/vmui

# Grafana
kubectl -n monitoring port-forward svc/vmks-grafana 3000:80
# → http://localhost:3000
```

### Обновление чарта (upgrade)

```bash
helm repo update
helm upgrade --install vmks vm/victoria-metrics-k8s-stack \
  --version 0.96.0 \
  -f values.yaml \
  --namespace monitoring
# → Release "vmks" has been upgraded. Happy Helming!
```

### Просмотр PVC и статуса

```bash
kubectl -n monitoring get pvc
# → имя PVC, статус Bound, размер

kubectl -n monitoring get vmcluster -o yaml
# → статус кластера: количество vmstorage, репликация
```

### Удаление (uninstall)

```bash
helm uninstall vmks --namespace monitoring
# → удаление helm release

# Дополнительная очистка PVC (если нужно)
kubectl -n monitoring delete pvc -l app.kubernetes.io/instance=vmks
```

## Варианты развёртывания

### Внешний Grafana

Для прод-сред рекомендуется ставить Grafana отдельным релизом для управления паролями и идентификацией (см. [Grafana Helm installation](./../Grafana/Installation/grafana_helm_installation.md)):

```yaml
grafana:
  enabled: false
defaultDashboards:
  enabled: true  # ConfigMap-ы с дашбордами создаются для импорта в внешнюю Grafana
```

### Воздушный отсек (air-gapped)

Синхронизация дашбордов и правил алертов по умолчанию скачивает ресурсы из публичных источников (GitHub raw) во время `helm install`. В окружениях без интернета доступны варианты:

**Вариант 1 — Предварительная генерация manifest'ов:**

```bash
# 1. Рендер config.yaml из values
helm template vmks vm/victoria-metrics-k8s-stack \
  -f values.yaml \
  --show-only templates/sync-job/config.yaml \
  | yq '.data["config.yaml"]' > sync-job-config.yaml

# 2. Запуск sync-job локально
docker run --rm \
  -e OUTPUT=- \
  -e NAMESPACE=monitoring \
  -e RELEASE=vmks \
  -e RESOURCE_PREFIX=vmks \
  -e PRUNE=false \
  -e OWNER_REFERENCES=false \
  -v $(pwd)/sync-job-config.yaml:/etc/config/config.yaml:ro \
  ghcr.io/victoriametrics/sync-job:v0.0.11 > manifests.yaml

# 3. Применение в кластере
kubectl apply -f manifests.yaml

# Отключение sync-job в air-gapped среде
syncJob:
  enabled: false
```

**Вариант 2 — HTTP-прокси:**

```yaml
syncJob:
  env:
    - name: HTTPS_PROXY
      value: "http://proxy.example.com:3128"
    - name: NO_PROXY
      value: "kubernetes.default.svc,10.0.0.0/8"
```

**Вариант 3 — Зеркалирование источников на внутренний сервер:**

```yaml
defaultDashboards:
  sources:
    victoriametrics-cluster:
      url: http://artifacts.internal/dashboards/victoriametrics.json

defaultRules:
  sources:
    etcd:
      url: http://artifacts.internal/rules/etcd-alerts.yaml
```

### Альтернативный реестр образов

Все образы VictoriaMetrics доступны на [Docker Hub](https://hub.docker.com/u/victoriametrics) и [Quay](https://quay.io/organization/victoriametrics). Для переопределения реестра:

```yaml
global:
  image:
    registry: quay.io
    repository: victoriametrics

victoria-metrics-operator:
  env:
    - name: VM_VMALERTMANAGER_ALERTMANAGERDEFAULTBASEIMAGE
      value: prom/alertmanager
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Grafana 401 после входа | `adminPassword` не задан или не совпадает с secret | Задать `grafana.adminPassword` или `grafana.admin.existingSecret`; пароль из secret `grafana` |
| Datasource «No data» | URL datasource в Grafana изменился после апгрейда | Проверить `vmsingle` запущен; пересоздать datasource через sidecar или вручную |
| vmagent не скрейпит поды | ServiceMonitor/VMServiceScrape недоступен или в другом namespace | Настроить `vmagent.spec.serviceMonitorSelector` с `namespaceSelector: matchNames: [monitoring]` |
| vmalert не алертит | `notifier.url` не указывает на Alertmanager | Проверить `vmalert.spec.notifier.url` на сервис `vmks-alertmanager:9093`; проверить `vmalert.spec.dataSource.url` |
| Нет node-метрик | `prometheus-node-exporter` отключён | Включить `prometheus-node-exporter.enabled: true` в `values.yaml` |
| Дашборды не появляются в Grafana | sidecar dashboards выключен или sync-job не прошёл | Включить `grafana.sidecar.dashboards.enabled: true`; проверить логи sync-job: `kubectl -n monitoring logs deploy/vmks-grafana` |
| Ошибка `metadata.annotations: Too long` (ArgoCD) | Дашборд превышает лимит 256KB ConfigMap | Добавить аннотацию `argocd.argoproj.io/sync-options: ServerSideApply=true` к `defaultDashboards` |
| Password меняется при каждом sync (ArgoCD) | Helm `lookup` не работает в ArgoCD | Добавить в `ignoreDifferences` ArgoCD-приложения секрет `grafana` и `jsonPointers: [/data/admin-password]` |

## Ограничения и особые случаи

- **Стек не включает VictoriaLogs по умолчанию** — для логов включайте `vlsingle`/`vlcluster` отдельно или используйте standalone-чарты (`victoria-logs-single`/`victoria-logs-cluster`), см. [victorialogs_k8s_setup.md](./../Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md);
- **PVC расширение** — увеличение размера PVC не всегда требует пересоздания (volumeExpansion поддерживается в современных StorageClass), но сужение невозможно — уменьшайте retention вместо этого;
- **На кластерах < 3 нод** полноценный multi-узловой `vmcluster` не даёт отказоустойчивости хранилища (Shared-Nothing) — разумнее использовать `vmsingle`;
- **`unsupportedChart_` аннотации** — `k8s-stack` поддерживает `vmsingle`/`vmcluster` runtime, но не покрывает `vmbackupmanager` (оператор нужен для автоматизации бэкапов);
- **Ресурсы после uninstall** — Helm `pre-delete` hook очищает CRD через оператор, но в ArgoCD он игнорируется. Используйте ArgoCD sync phases или разворачивайте оператор отдельным релизом.

## Рекомендации по эксплуатации

- Обновляйте чарт осознанно по SemVer: мажорная версия чарта = значимые структурные изменения `values.yaml`;
- Для прод-сред отдельным релизом ставьте Grafana (управление паролями/идентификацией) — см. [Grafana Helm installation](./../Grafana/Installation/grafana_helm_installation.md);
- Datasource VM создаётся автоматически, но проверяйте его URL после каждого апгрейда;
- Следите за retention диска vmsingle/vmstorage через `kubectl get pvc` — планируйте расширение заранее;
- Используйте короткое имя релиза (`vmks`) — иначе имена сервисов могут превысить лимит 63 символов;
- В air-gapped средах используйте предварительную генерацию manifest'ов или зеркалирование источников (см. выше);
- Для алертинга на объёме диска используйте node-exporter метрики, а не встроенные алерты VM;
- Используйте `helm diff upgrade` перед применением изменений, чтобы увидеть изменения в манифестах.

## Дополнительная информация

### См. также

- [VictoriaMetrics Operator](./operator_overview.md) — CRD-подход (более гибкий для production);
- [Операции с кластером](./cluster_operations.md) — `vmcluster`: репликация, `vminsert`/`vmselect`/`vmstorage`;
- [Обзор хранилищ](./storage_internals.md) — архитектура хранилищ VM;
- [VMAlert: управление правилами](./vmalert_rules_management_with_manifests.md) — алёрты и recording rules;
- [vmagent](./vmagent_overview.md) — сбор метрик, scrape config;
- [vmauth](./vmauth_overview.md) — аутентификация и маршрутизация;
- [vmbackup/vmrestore](./vmbackup_restore.md) — резервное копирование и восстановление;
- [VictoriaLogs в Kubernetes](./../Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md) — чарты logs, vlmg;
- [Grafana Helm installation](./../Grafana/Installation/grafana_helm_installation.md) — отдельный Grafana;
- [Grafana integration](./grafana_integration.md) — datasource, provisioning, alerting;
- Официальный репозиторий чартов: `https://github.com/VictoriaMetrics/helm-charts`;
- [Страница карты компонентов](/victoriametrics/quick-start/);
- [vmui_overview.md](./vmui_overview.md) — веб-интерфейс администрирования VM.
