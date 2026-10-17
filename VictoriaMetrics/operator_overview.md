# VictoriaMetrics Operator: управление стеком в Kubernetes

**Актуально для:** VictoriaMetrics Operator v0.75.0

## Определения

**VictoriaMetrics Operator** (`vmoperator`) — Kubernetes-оператор (controller + набор CRD), который декларативно разворачивает и обслуживает компоненты VictoriaMetrics (`VMSingle`, `VMCluster`, `VMAgent`, `VMAlert`, `VMAuth`, `VictoriaLogs`, `VictoriaTraces` и др.) на основе пользовательских ресурсов. Снимает рутину с написания манифестов, конфигураций и rolling-обновлений, а также автоматизирует самомониторинг и бэкапы.

**CRD / Custom Resource** — расширение Kubernetes API, описывающее желаемое состояние компонента (например, `VMAgent` → агент сбора, `VMCluster` → кластер vminsert/vmselect/vmstorage).

**Reconcile (цикл согласования)** — процесс, в котором оператор сравнивает желаемое состояние (из CR) с фактическим состоянием кластера и создаёт/обновляет/удаляет ресурсы, чтобы устранить разницу.

**config-reloader** — sidecar-контейнер, который следит за изменениями ConfigMap/Secret и отправляет сигнал hot-reload в приложение без перезапуска пода.

**VM_FORCERESYNCINTERVAL** — переменная окружения оператора, задающая период принудительного повторного согласования (force resync) всех CR, даже без событий изменения.

## Базовые концепции

### Архитектура оператора

Оператор реализует паттерн [Kubernetes Operator](https://kubernetes.io/docs/concepts/extend-kubernetes/operator/):

```
User defines desired state in CR (VMAgent, VMCluster, etc.)
        ↓
Kubernetes API Server (CRUD, валидация через CRD)
        ↓
Operator controller (watch → reconcile → mutate)
        ↓
Managed objects (Deployment, StatefulSet, Service, ConfigMap, ...)
```

Оператор подписывается на события `create`/`update`/`delete` для CR и управляемых объектов. При срабатывании события или по таймеру (`VM_FORCERESYNCINTERVAL`) запускается **reconcile loop**:

1. Оператор читает CR (например, `VMAgent`).
2. Валидирует спецификацию (webhook-валидация).
3. Собирает конфигурацию: scrape_configs из `*Scrape` CRs, relabeling, remoteWrite.
4. Генерирует и применяет `Deployment`/`StatefulSet` + `ConfigMap` + `Service` + `VMServiceScrape`.
5. Обновляет статус CR (`status.updateStatus = "operational"`).

Для горячей перезагрузки конфигурации без рестарта пода используется **config-reloader sidecar** (на основе `victoriametrics/operator:config-reloader` начиная с v0.64.0). Оператор аннотирует ConfigMap временной меткой изменения, что запускает немедленную синхронизацию `kubelet` и последующий перезапуск конфига через config-reloader.

### CRD: обзор ресурсов

API group: `operator.victoriametrics.com`, версия большинства CRD — `v1beta1`. Исключение: `VMDistributed` и `VLDistributed` находятся в `v1alpha1` (экспериментальные).

| CRD | Создаёт | Примечание |
| :--- | :--- | :--- |
| `VMSingle` | Deployment + PVC для single-node VictoriaMetrics | `retentionPeriod`, `storage` |
| `VMCluster` | vminsert/vmselect/vmstorage (Deployment/StatefulSet) | `replicationFactor`, sharding, HA |
| `VMAgent` | Deployment (или StatefulSet при `statefulMode`) | `replicaCount`, `shardCount`, `remoteWrite` |
| `VMAlert` | Deployment vmalert | datasource, notifier, evaluationInterval |
| `VMRule` | конфигурацию правил vmalert | трансляция с hot-reload в ConfigMap |
| `VMAlertmanager`, `VMAlertmanagerConfig` | Alertmanager + routing | |
| `VMAuth` (+ `VMUser`) | vmauth + генерация конфига от `VMUser` | |
| `VMServiceScrape` / `VMPodScrape` / `VMNodeScrape` / `VMStaticScrape` / `VMProbe` / `VMScrapeConfig` | scrape-конфиги vmagent | миграция из Prometheus CR |
| `VLSingle`, `VLAgent` | VictoriaLogs: single/node-agent | `v1beta1` |
| `VLCluster` (+ `VLStorage`) | VictoriaLogs: кластер (vmselect/vminsert/vmstorage) | `v1beta1` |
| `VTSingle`, `VTCluster`, `VTAgent` | VictoriaTraces (pre-GA) | `v1beta1` |
| `VMDistributed` / `VLDistributed` | координированное обновление нескольких кластеров/инстансов | экспериментальный, `v1alpha1` |
| `VMAnomaly`, `VMAnomalyConfig` | vmanomaly (Enterprise) | обнаружение аномалий |

## Требования и предпосылки

- **Kubernetes:** v1.27+ (оператор тестируется на официально поддерживаемых версиях k8s).
- **kubectl** — для управления кластером и troubleshooting.
- **Helm v3** (опционально) — для установки через чарты.
- **CertManager** — только если установка со webhook-валидацией (manifest `install-with-webhook.yaml`).
- **Namespace:** оператор создаёт/ использует namespace `vm` (или указанный); CRD-ресурсы размещаются в том же namespace, где применяются CR.

## Установка и настройка

### Helm

```bash
helm repo add vm https://victoriametrics.github.io/helm-charts/
helm repo update

# Основной чарт оператора
helm install vm-operator vm/victoria-metrics-operator \
  --namespace vm --create-namespace

# CRDs отдельным чартом (рекомендуется для production)
# https://github.com/VictoriaMetrics/helm-charts/tree/main/charts/victoria-metrics-operator-crds
helm install vm-operator-crds vm/victoria-metrics-operator-crds \
  --namespace vm --create-namespace

# OCI-чарт (альтернатива)
helm upgrade -i vm-operator oci://ghcr.io/victoriametrics/helm-charts/victoria-metrics-operator \
  --namespace vm --create-namespace
```

```bash
# → NAME: vm-operator
# → STATUS: deployed
# → NAMESPACE: vm
```

**Важно:** CRDs и оператор версии должны совпадать. CRD-чарт (`victoria-metrics-operator-crds`) ставится отдельно и обновляется в паре с оператором.

### Манифест (без Helm)

```bash
# Получить последнюю версию оператора
export VM_OPERATOR_VERSION=$(basename $(curl -fs -o /dev/null -w %{redirect_url} \
  https://github.com/VictoriaMetrics/operator/releases/latest))
echo $VM_OPERATOR_VERSION
# → v0.75.0

# Манифест с webhook (требует CertManager)
wget -O operator.yaml \
  https://github.com/VictoriaMetrics/operator/releases/download/$VM_OPERATOR_VERSION/install-with-webhook.yaml

# Манифест без webhook
wget -O operator.yaml \
  https://github.com/VictoriaMetrics/operator/releases/download/$VM_OPERATOR_VERSION/install-no-webhook.yaml

# Переименовать namespace (по умолчанию vm)
sed -i "s/namespace: vm/namespace: YOUR_NAMESPACE/g" operator.yaml
kubectl apply -f operator.yaml
# → namespace/vm configured
# → ... (CRDs, Deployments, Services)
```

```bash
kubectl -n vm rollout status deployment/vm-operator
# → deployment "vm-operator" successfully rolled out
```

### Kustomize

```bash
export VM_OPERATOR_VERSION=$(basename $(curl -fs -o /dev/null -w %{redirect_url} \
  https://github.com/VictoriaMetrics/operator/releases/latest))
export NAMESPACE="monitoring"
export OVERLAY="base-with-webhook"  # или "default" (без webhook)

cat << EOF > kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - github.com/VictoriaMetrics/operator/config/${OVERLAY}?ref=${VM_OPERATOR_VERSION}
namespace: ${NAMESPACE}
images:
  - name: manager
    newName: victoriametrics/operator
    newTag: ${VM_OPERATOR_VERSION}
EOF

kustomize build . -o monitoring.yaml
kubectl apply -f monitoring.yaml
```

### Настройка оператора (переменные окружения)

Оператор конфигурируется через переменные окружения. Ключевые:

| Переменная | Назначение | По умолчанию |
| :--- | :--- | :--- |
| `VM_METRICS_VERSION` | Версия образов VictoriaMetrics (VMSingle, VMCluster, VMAgent, VMAlert, VMAuth) | `v1.154.0` |
| `VM_LOGS_VERSION` | Версия образов VictoriaLogs (VLSingle, VLCluster, VLAgent) | `v1.53.0` |
| `VM_ANOMALY_VERSION` | Версия образа VMAnomaly | `v1.31.0` |
| `VM_TRACES_VERSION` | Версия образов VictoriaTraces (VTSingle, VTCluster, VTAgent) | `v0.12.0` |
| `VM_OPERATOR_VERSION` | Собственная версия оператора; используется для тега config-reloader | `v0.75.0` |
| `VM_CONFIG_RELOADER_IMAGE` | Образ config-reloader sidecar | `victoriametrics/operator:config-reloader-${VM_OPERATOR_VERSION}` |
| `VM_FORCERESYNCINTERVAL` | Интервал принудительного resync всех CR (Go duration) | `1h` |
| `VM_PROMCR_VALIDATION_ENABLED` | Включить webhook-валидацию prometheus-operator CRD | `false` |
| `VM_ENABLEDPROMETHEUSCONVERTEROWNERREFERENCES` | Добавлять OwnerReferences к конвертированным из Prometheus CR (удаление при удалении оригинала) | `false` |
| `WATCH_NAMESPACE` | Список наблюдаемых namespace (`-` = все) | `-` |

```bash
# Просмотр всех дефолтных значений
OPERATOR_POD_NAME=$(kubectl get pod -l "app.kubernetes.io/name=victoria-metrics-operator" \
  -n vm -o jsonpath="{.items[0].metadata.name}")
kubectl exec -n vm "$OPERATOR_POD_NAME" -- /app --printDefaults
# → VM_METRICS_VERSION    v1.154.0    false    # VM_LOGS_VERSION      v1.53.0     false    # ...
```

### Управление версиями компонентов

Каждая CR позволяет задавать Docker-образы через поле `image`:

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMCluster
metadata:
  name: vm-cluster
  namespace: monitoring
spec:
  clusterVersion: "v1.154.0"  # общая версия для всех компонентов
  vmstorage:
    replicaCount: 3
    image:
      repository: victoriametrics/vmstorage
      tag: v1.154.0-cluster
    storage:
      volumeClaimTemplate:
        spec:
          resources:
            requests:
              storage: 1Ti
  vmselect:
    replicaCount: 2
  vminsert:
    replicaCount: 2
```

Поле `clusterVersion` задаёт тег образа для всех компонентов кластера; индивидуальное `image.tag` переопределяет его для конкретного компонента.

## Практические сценарии

### 1. Простой инстанс VMSingle

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMSingle
metadata:
  name: vm-single
  namespace: monitoring
spec:
  retentionPeriod: "30d"
  storage:
    storageClassName: standard
    resources:
      requests:
        storage: 100Gi
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
```

```bash
kubectl apply -f vmsingle.yaml
# → vmsingle.operator.victoriametrics.com/vm-single created

kubectl -n monitoring wait --for=jsonpath='{.status.updateStatus}'=operational vmsingle/vm-single
# → condition met

kubectl -n monitoring rollout status deployment vmsingle-vm-single
# → deployment "vmsingle-vm-single" successfully rolled out
```

### 2. Кластер (VMCluster) с репликацией

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMCluster
metadata:
  name: vm-cluster
  namespace: monitoring
spec:
  retentionPeriod: "90d"
  replicationFactor: 2
  vmstorage:
    replicaCount: 3
    storage:
      volumeClaimTemplate:
        spec:
          resources:
            requests:
              storage: 1Ti
    resources:
      requests:
        cpu: "2"
        memory: 8Gi
  vmselect:
    replicaCount: 2
  vminsert:
    replicaCount: 2
```

Оператор автоматически сгенерирует `-storageNode`-список (список vmstorage), настроит `VMServiceScrape` для самомониторинга и создаст сервисы:

| Сервис | Тип | Порт | Назначение |
| :--- | :--- | :--- | :--- |
| `vminsert-<name>` | ClusterIP | 8480 | приём данных (write path) |
| `vmselect-<name>` | Headless | 8481 | запросы (read path) |
| `vmstorage-<name>` | Headless | 8482 | admin API vmstorage |

### 3. VMAgent: sharding, statefulMode и remoteWrite

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMAgent
metadata:
  name: vmagent-prod
  namespace: monitoring
spec:
  selectAllByDefault: true
  serviceScrapeNamespaceSelector:
    matchNames: [monitoring]
  remoteWrite:
    - url: http://vmsingle-vm-single.monitoring.svc:8428/api/v1/write
  statefulMode: true          # StatefulSet с persistent queue на PVC
  statefulStorage:
    volumeClaimTemplate:
      spec:
        resources:
          requests:
            storage: 50Gi
  replicaCount: 2
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
```

`statefulMode: true` гарантирует сохранность буфера очереди (persistent queue) при перезапуске пода. Без него vmagent работает как Deployment и буфер теряется.

### 4. Мониторинг: VMServiceScrape

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMServiceScrape
metadata:
  name: myapp
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: myapp
  endpoints:
    - port: metrics
      path: /metrics
      interval: 15s
```

### 5. Алертинг: VMRule + VMAlert

```yaml
# VMRule — декларативное описание правил
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMRule
metadata:
  name: myapp-rules
  namespace: monitoring
spec:
  groups:
    - name: myapp
      rules:
        - alert: HighCPU
          expr: 'rate(process_cpu_seconds_total[5m]) > 0.8'
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "High CPU on {{ $labels.instance }}"

---
# VMAlert — подключение datasource и notifier
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMAlert
metadata:
  name: vmalert-main
  namespace: monitoring
spec:
  datasource:
    url: http://vmselect-vm-cluster.monitoring.svc:8481/select/0/prometheus
  remoteWrite:
    url: http://vminsert-vm-cluster.monitoring.svc:8480/insert/0/prometheus/api/v1/write
  notifier:
    url: http://vmalertmanager-demo.monitoring.svc:9093
  evaluationInterval: "15s"
  ruleSelector:
    matchLabels:
      app: myapp  # только VMRule с этим label
```

### 6. Миграция с Prometheus Operator

Оператор по умолчанию включает авто-конвертацию Prometheus CR в VM CR. Prometheus CRDs должны быть установлены отдельно (из [prometheus-operator](https://github.com/prometheus-operator/prometheus-operator/releases)). Оператор конвертирует `ServiceMonitor` → `VMServiceScrape`, `PodMonitor` → `VMPodScrape`, `PrometheusRule` → `VMRule`, `Probe` → `VMProbe`, `ScrapeConfig` → `VMScrapeConfig` в том же namespace.

| Prometheus CRD | VictoriaMetrics CRD |
| :--- | :--- |
| `ServiceMonitor` | `VMServiceScrape` |
| `PodMonitor` | `VMPodScrape` |
| `PrometheusRule` | `VMRule` |
| `Probe` | `VMProbe` |
| `ScrapeConfig` | `VMScrapeConfig` |
| `AlertmanagerConfig` | `VMAlertmanagerConfig` |

Управление конвертацией:

- **CLI-флаг** `-controller.disableReconcileFor=ServiceMonitor` — отключить конвертацию конкретного типа.
- **Helm values:** `operator.disable_prometheus_converter: true` — полностью отключить конвертер.
- **Env var** `VM_ENABLEDPROMETHEUSCONVERTEROWNERREFERENCES=true` — добавить `OwnerReferences` к конвертированным объектам (они будут удаляться вместе с оригиналом из Prometheus).
- **Аннотации** на VM-объектах: `operator.victoriametrics.com/ignore-prometheus-updates` (игнорировать обновления из Prometheus CR) и `operator.victoriametrics.com/merge-meta-strategy` (`prefer-prometheus` / `prefer-victoriametrics`).

```bash
# 1. Установите оператор (конвертер включён по умолчанию)
helm install vm-operator vm/victoria-metrics-operator -n vm --create-namespace

# 2. Установите Prometheus CRDs (если ещё не установлены)
kubectl apply -f https://github.com/prometheus-operator/prometheus-operator/releases/download/v0.79.0/bundle.yaml

# 3. Примените Prometheus CR — оператор создаст VM-аналог
kubectl apply -f servicemonitor.yaml
# → operator создаст VMServiceScrape с теми же селекторами

# 4. Проверьте, что целевые метрики попали в VM
curl -s http://localhost:8428/api/v1/targets | jq '.data.activeTargets[].labels.job'
```

### 7. VMAlertmanager с конфигурацией routing

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMAlertmanager
metadata:
  name: vmalertmanager-main
  namespace: monitoring
spec:
  configRawYaml: |
    global:
      resolve_timeout: 5m
    route:
      receiver: grafana-oncall
      group_by: ['alertname']
      group_wait: 10s
      group_interval: 10s
      repeat_interval: 1h
    receivers:
      - name: grafana-oncall
        webhook_configs:
          - url: http://grafana-oncall.prod.svc:8080/api/v1/prectrify
            send_resolved: true
```

## Операции и команды

### Проверка установки

```bash
# CRD зарегистрированы
kubectl get crd | grep victoriametrics
# → vmclusters.operator.victoriametrics.com
# → vmalerts.operator.victoriametrics.com
# → vmsingles.operator.victoriametrics.com
# → ...

# Оператор запущен
kubectl get pods -n vm -l app.kubernetes.io/name=victoria-metrics-operator
# → NAME                        READY   STATUS    RESTARTS   AGE
# → vm-operator-7b4c5c6d-x8k9p   1/1     Running   0          2m

# CR работают
kubectl get vmcluster,vmagent,vmrule,vmalert -A
# → NAME         AGE
# → vmcluster/vm-cluster   5m
```

### Проверка сгенерированной конфигурации

```bash
# ConfigMap агента
kubectl get configmap -n monitoring -l app.kubernetes.io/name=vmagent -o yaml

# Статус CR
kubectl get vmcluster vm-cluster -n monitoring -o yaml
# → status.updateStatus: operational
# → status.components:
# →   vmstorage: 3/3 pods ready
# →   vmselect: 2/2 pods ready
# →   vminsert: 2/2 pods ready
```

### Обновление оператора и CRDs

```bash
# 1. Бэкап CRD и ресурсов
kubectl get crd -l app.kubernetes.io/name=victoria-metrics-operator -o yaml > crds-backup.yaml
kubectl get vmcluster,vmagent,vmsingle,vmrule -A -o yaml > vm-resources-backup.yaml

# 2. Обновление Helm-релиза (CRDs и оператор вместе)
helm repo update vm
helm upgrade vm-operator vm/victoria-metrics-operator \
  --namespace vm --version <новая-версия>

# 3. Проверка
kubectl -n vm rollout status deployment/vm-operator
kubectl wait --for=jsonpath='{.status.updateStatus}'=operational vmcluster -A --timeout=120s
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Ресурс в статусе `error` | Ошибка валидации spec / образов | `kubectl describe <CR>`; `kubectl logs operator` |
| CRD-версия не совпадает с оператором | После обновления оператора не обновлены CRDs | Поднять CRD-чарт (`victoria-metrics-operator-crds`) до версии оператора |
| Scrape не появляются у агента | `serviceScrapeSelector`/`namespaceSelector` фильтрует | Проверить selectors в `VMAgent` и `VMServiceScrape`; включить `selectAllByDefault: true` |
| `VMAlert` не подхватывает `VMRule` | `ruleSelector` на `VMAlert` не совпадает с labels `VMRule` | Согласовать `ruleSelector.matchLabels` и метки на `VMRule` |
| Конфиг vmauth сломан | `VMUser` изменён, конфиг регенерирован с ошибкой | `kubectl get vmauth -o yaml`; `kubectl logs vmauth` |
| `statefulMode` не работает | `StatefulStorage` не задан | Добавить `statefulStorage.volumeClaimTemplate.spec.resources.requests.storage` |
| VMCluster pods not scheduling | `vmstorage` не хвватает ресурсов или PVC | Проверить `resources.requests` и наличие `storage.volumeClaimTemplate` |
| Reconcile застрял на `updateStatus: empty` | Ошибка валидации webhook | `kubectl describe <CR>` — смотреть события; проверить CRD версию |

### Диагностика reconcile loop

```bash
# Логи оператора для конкретного CR
kubectl -n vm logs deployment/vm-operator -- -n monitoring

# События CR
kubectl describe vmcluster vm-cluster -n monitoring
# → Events:
# →   Warning  SyncError  5s   vm-operator  failed to sync: storageSpec cannot be empty

# Принудительный resync (изменить аннотацию)
kubectl annotate vmcluster vm-cluster \
  force-resync=$(date +%s) -n monitoring --overwrite
```

## Рекомендации по эксплуатции

- **Обновляйте operator и CRDs вместе:** поставляйте `victoria-metrics-operator-crds` в том же релизе, что и оператор.
- **Production:** включайте `statefulMode` у `VMAgent` (persistent queue) и `replicationFactor: 2` в `VMCluster`.
- **Единая точка входа:** используйте `VMUser` + `VMAuth` вместо открытых Service.
- **Самомониторинг:** оператор автоматически создаёт `VMServiceScrape` для своих компонентов — включайте их в набор скрейпов.
- **Namespace-селекторы:** используйте `serviceScrapeSelector`/`namespaceSelector` — без них агент собирает всё, что согласуется, что дорого.
- **Версии образов:** явно пинните теги образов (`spec.clusterVersion` или `spec.image.tag`) — не используйте `:latest` в production.
- **Объём хранилища:** оставляйте ~20% свободного места на диске; используйте `-storage.minFreeDiskSpaceBytes` для жёсткого лимита.
- **Разделение компонентов:** размещайте `vminsert` и `vmselect` на отдельных хостах или используйте `resource limits/requests`.

### Очистка (cleanup)

```bash
# Удаление CR с последующей очисткой PVC
kubectl delete vmcluster vm-cluster -n monitoring
# PVC удалятся автоматически, если включён finalizers (по умолчанию)

# Если PVC остались — удалить вручную
kubectl get pvc -n monitoring | grep vmstorage
kubectl delete pvc -n monitoring vmstorage-vm-cluster-0

# Удаление оператора
helm uninstall vm-operator -n vm
helm uninstall vm-operator-crds -n vm
kubectl delete namespace vm
```

## Ограничения и особые случаи

- Оператор не «промотает» данные и не делает резервное копирование сам по себе (только интеграция с vmbackup/vmbackupmanager).
- Миграция с Prometheus Operator на лету поддерживается, но требует переноса CRD-наборов и проверки селекторов.
- `VLCluster`/`VTCluster` — новые CRD: проверяйте версию оператора перед использованием в прод.
- `VMDistributed`/`VLDistributed` — экспериментальные CRD на `v1alpha1`; API может измениться.
- `VMStaticScrape` — находится в `v1alpha1`; использовать осторожно.
- `VMAnomaly`/`VMAnomalyConfig` — Enterprise-фича, требует license key.

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — компоненты и роль оператора;
- [vmalert: управление правилами через манифесты](./vmalert_rules_management_with_manifests.md) — `VMRule`, `VMAlert`;
- [vmagent: обзор](./vmagent_overview.md) — сбор и доставка метрик;
- [Внутренние порты](./overview.md#внутренние-порты-по-умолчанию) — таблица портов компонентов;
- [Helm-чарт k8s-stack](./helm_victoria_metrics_k8s_stack.md) — деплой стека в Kubernetes без operator;
- [Безопасность VictoriaMetrics](./security.md) — TLS, RBAC, network policies;
- [Официальная документация оператора](https://docs.victoriametrics.com/operator/) — quick start, setup, high availability, FAQ;
- [Репозиторий operator на GitHub](https://github.com/VictoriaMetrics/operator/) — исходный код, changelog, примеры.