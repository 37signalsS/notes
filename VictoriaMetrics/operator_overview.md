# VictoriaMetrics Operator: управление стеком в Kubernetes

## Определения

**VictoriaMetrics Operator** — Kubernetes-оператор (controller/CRD-набор), который декларативно разворачивает и обслуживает компоненты VictoriaMetrics (`VMSingle`, `VMCluster`, `VMAgent`, `VMAlert`, `VMAuth`, `VictoriaLogs`, `VictoriaTraces` и др.) на основе пользовательских ресурсов (Custom Resources). Снимает ручную работу с манифестами, конфигурацией и rolling-обновлением.

**CRD / Custom Resource** — расширения Kubernetes API, описывающие желаемое состояние компонента (например, `VMAgent` → агент сбора, `VMCluster` → кластер vminsert/vmselect/vmstorage).

## Базовые концепции

### Установка и компоненты

```bash
# Установка оператора (Helm)
helm repo add vm https://victoriametrics.github.io/helm-charts/
helm install vm-operator victoriametrics/victoria-metrics-operator \
  --namespace victoria-metrics --create-namespace

# Альтернатива — OCI-чарт
helm upgrade -i vm-operator oci://ghcr.io/victoriametrics/helm-charts/victoria-metrics-operator
```

Основные ресурсы, которые «ведут» оператор:

| CRD | Создаёт | Примечание |
| :--- | :--- | :--- |
| `VMSingle` | Deployment + PVC для single-node VictoriaMetrics | `retentionPeriod`, `storage` |
| `VMCluster` | vminsert/vmselect/vmstorage (Deployment/StatefulSet) | `replicationFactor`, sharding, HA |
| `VMAgent` | Deployment (или StatefulSet при `statefulMode`) | `replicaCount`, `sharding`, remoteWrite |
| `VMAlert` | Deployment vmalert | вместимость, datasource |
| `VMRule` | конфигурацию правил vmalert | трансляция в конфиг с hot-reload |
| `VMAlertmanager`, `VMAlertmanagerConfig` | Alertmanager + его routing | |
| `VMAuth` (+ `VMUser`) | vmauth + генерация конфига от `VMUser` | |
| `VMServiceScrape` / `VMPodScrape` / `VMNodeScrape` / `VMProbe` | scrape-конфиги vmagent | миграция из Prometheus CR |
| `VLCluster`/`VLStorage` (`VLCluster`+`VLStorage`), `VLSingle`, `VLAgent` | VictoriaLogs кластер/single, vlagent | |
| `VTCluster`, `VTSingle`, `VTAgent` | VictoriaTraces (beta) | |

### Как работает (reconcile loop)

```
kubectl apply -f VMAgent.yml
   → operator замечает изменение ресурса
   → собирает конфиг (scrape_configs из *Scrape CRs, relabeling)
   → создаёт/обновляет Deployment + ConfigMap + Service + VMServiceScrape
   → sidecar (config-reloader) следит за изменениями и перезагружает конфиг без рестарта
```

Оператор поддерживает: rolling update, авто-настройку `-remoteWrite` для HA, бэкапы (интеграция vmbackup/vmbackupmanager), миграцию с Prometheus Operator (ServiceMonitor → VMServiceScrape) и многое другое.

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
    capacity: 100Gi
  resources:
    requests: { cpu: 500m, memory: 512Mi }
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
  vmStorage:
    replicaCount: 3
    storage:
      capacity: 1Ti
    resources: { requests: { cpu: "2", memory: 8Gi } }
  vmSelect:
    replicaCount: 2
  vmInsert:
    replicaCount: 2
```

Оператор сам сгенерирует `-storageNode`-список и разнос helm-манифестов, а также настроит `VMServiceScrape` для самомониторинга.

### 3. VMAgent: sharding и statefulMode

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMAgent
metadata:
  name: vmagent-prod
spec:
  serviceScrapeNamespaceSelector: { matchNames: [monitoring] }
  remoteWrite:
    - url: http://vm-single-victoria-metrics-8428.monitoring:8428/api/v1/write
  statefulMode: true          # persistent queue на PVC (не потеряется после рестарта)
  replicaCount: 2
  resources:
    requests: { cpu: 200m, memory: 256Mi }
```

### 4. Мониторинг: VMServiceScrape

```yaml
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMServiceScrape
metadata:
  name: myapp
  namespace: monitoring
spec:
  selector: { matchLabels: { app: myapp } }
  endpoints:
    - port: metrics
      path: /metrics
```

## Валидация установки

```bash
kubectl get crd | grep victoriametrics
kubectl get pods -n victoria-metrics -l app.kubernetes.io/name=victoria-metrics-operator
kubectl get vmcluster,vmagent,vmrule -A

# Проверка сгенерированной конфигурации агента
kubectl get configmap -n monitoring -l app.kubernetes.io/name=vmagent -o yaml
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Ресурс в статусе `error` | Ошибка валидации spec / образов | `kubectl describe <CR>` , `kubectl logs operator` |
| CRD-версия не совпадает с оператором | После обновления оператора не обновлены CRDs | Поднять CRD-чарт (`victoria-metrics-operator-crds`) до версии оператора |
| Scrape не появляются у агента | `serviceScrapeSelector` фильтрует по namespace/labels | Проверить selectors в `VMAgent` и `VMServiceScrape` |
| `VMAlert` не подхватывает `VMRule` | label selector на `ruleSelector` не совпадает | Согласовать `ruleSelector` и labels на `VMRule` |
| Сломалась конфигурация vmauth | `VMUser` мененён, конфиг регенерирован с ошибкой | `kubectl get vmauth -o yaml`; проверка `kubectl logs vmauth` |

## Рекомендации по эксплуатации

- Обновляйте operator **и CRDs вместе**: поставляйте `victoria-metrics-operator-crds` в том же релизе.
- Для production включайте `statefulMode` у `VMAgent` (keep persistent queue) и `replicationFactor` в `VMCluster`.
- Используйте `VMUser` + `VMAuth` как единую точку входа (вместо открытых Service).
- Настраивайте самомониторинг: оператор автоматически выставляет `VMServiceScrape` на свои компоненты — включайте их в набор скрейпов.
- Ресурсы `*Scrape` используйте с namespace/label-селекторами — без них агент соберёт всё, что согласуется, что дорого.

## Ограничения и особые случаи

- Оператор не «промотит» данные и не делает резервное копирование сам по себе (только интеграция с vmbackup/vmbackupmanager).
- Миграция с Prometheus Operator на лету поддерживается, но требует переноса CRD-наборов и проверки selectors.
- `VLCluster`/`VTCluster` — новые CRD: проверяйте версию оператора перед использованием в прод.

## Дополнительная информация

### См. также

- [VictoriaMetrics: обзор](./overview.md) — компоненты и роль оператора;
- [vmalert: управление правилами через манифесты](./vmalert_rules_management_with_manifests.md) — `VMRule`, `VMAlert`;
- [Kubernetes: VictoriaLogs + operator](./../Kubernetes/MonitoringLogging/victorialogs_k8s_setup.md) — деплой логов.
# force reindex test
