# Crossplane: Управление парком кластеров (Fleet Management)

**Актуально для:** Crossplane v1.18+ / v2.x (актуально v2.4); provider-kubernetes v1.3.x; Kubernetes 1.28–1.32+; On-Premise / Bare-Metal

## Определения

**Management Cluster (управляющий кластер)** — Kubernetes-кластер, в котором развёрнут Crossplane Core, пакеты провайдеров и функции; выполняет роль единого control plane для парка целевых кластеров.

**Fleet / Downstream Cluster (парк кластеров)** — набор удалённых (downstream) кластеров Kubernetes, управляемых из Management Cluster через `provider-kubernetes` (мультикластерный топология) или чьи ресурсы заказываются как Managed Resources (например, кластеры Cluster API).

**Hosted Provider (Namespaced Provider)** — в Crossplane v2 провайдер, чьи Managed Resources и `ProviderConfig` размещаются в namespace тенанта (`*.m.crossplane.io`), а не глобально. Позволяет изолировать управление инфраструктурой внутри namespace без cluster-scoped объектов.

**ClusterProviderConfig** — cluster-scoped ресурс провайдера (например, `kubernetes.m.crossplane.io/v1alpha1`), описывающий единый набор учётных данных для подключения к целевому кластеру; в отличие от namespace-scoped `ProviderConfig`, доступен из всех namespace (при наличии RBAC).

**ObservedObjectCollection** — в provider-kubernetes ресурс для непрерывного сбора (read-only) состояния внешних объектов целевого кластера — аудит и инвентаризация без создания/изменения.

**Cluster API (CAPI)** — подпроект Kubernetes (SIG Cluster Lifecycle), предоставляющий декларативные API для создания и управления кластерами Kubernetes; в On-Premise стеке Crossplane может композировать CAPI-ресурсы (`Cluster`, `MachineDeployment`) как обычные MR.

## Базовые концепции и архитектура

### Топология Fleet Management

```text
┌─────────────────────────────────────────────────────────┐
│  Management Cluster (Crossplane Control Plane)          │
│  ┌────────────────┐  ┌──────────────────────────────┐   │
│  │ Crossplane Core│  │ provider-kubernetes          │   │
│  │ + Functions    │  │ (Fleet Orchestration)        │   │
│  └───────┬────────┘  └──────────────┬───────────────┘   │
│          │                          │                    │
│  ClusterProviderConfig              │  Object / XRs      │
│  (worker-dc1-creds)                 │  (platform-stacks) │
└──────────┼──────────────────────────┼────────────────────┘
           │ kubeconfig / token       │ SSA / apply
           ▼                          ▼
┌──────────────────┐        ┌──────────────────┐
│ Downstream DC-1  │        │ Downstream DC-2  │
│ (Bare-Metal K8s) │        │ (DMZ / Edge)     │
│ agents, quotas,  │        │ agents, quotas,  │
│ operators        │        │ operators        │
└──────────────────┘        └──────────────────┘
```

### Механизмы управления

| Механизм | Назначение | Где описан |
|---|---|---|
| `provider-kubernetes` + `Object` | Декларативное применение манифестов K8s в downstream-кластере (namespace, NetworkPolicy, DaemonSet) | [provider_kubernetes_setup.md](./provider_kubernetes_setup.md) |
| `ClusterProviderConfig` | Единая точка подключения к downstream-кластеру (kubeconfig secret) | Этот файл + [provider_kubernetes_setup.md](./provider_kubernetes_setup.md) |
| Namespaced MR (v2, `*.m.*`) | Изоляция Managed Resources внутри namespace тенанта | [multi_tenancy.md](./multi_tenancy.md) |
| ApplicationSet (Argo CD) | Массовое применение platform-стека во все downstream-кластеры | [gitops_integration.md](./gitops_integration.md) |
| CAPI-ресурсы в Composition | Заказ и день-2 управление самими кластерами Kubernetes | Этот файл (Сценарий 3) |

### Crossplane v2: namespaced провайдеры и MRD

В Crossplane v2 Managed Resources стали namespaced по умолчанию (`*.m.crossplane.io`), а `ManagedResourceActivationPolicy` (MRAP) позволяет активировать только нужные типы MR, снижая нагрузку на API-сервер:

```yaml
apiVersion: apiextensions.crossplane.io/v1alpha1
kind: ManagedResourceActivationPolicy
metadata:
  name: fleet-essentials
spec:
  activate:
    - objects.kubernetes.m.crossplane.io
    - clusters.cluster.x-k8s.io
```

Это критично для fleet: Management Cluster с десятками провайдеров не должен вешать на etcd сотни неиспользуемых CRD.

## Практические сценарии и конфигурация

### Сценарий 1: ClusterProviderConfig для downstream-кластера

На стороне downstream (worker-dc1):

```bash
kubectl create namespace platform-system
kubectl -n platform-system create serviceaccount crossplane-agent
kubectl create clusterrolebinding crossplane-agent-binding \
  --clusterrole=cluster-admin \
  --serviceaccount=platform-system:crossplane-agent

kubectl apply -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: crossplane-agent-token
  namespace: platform-system
  annotations:
    kubernetes.io/service-account.name: crossplane-agent
type: kubernetes.io/service-account-token
EOF
```

В Management Cluster:

```bash
TARGET_API="https://k8s-worker-dc1.corp.internal:6443"
CA_DATA=$(kubectl -n platform-system get secret crossplane-agent-token \
  -o jsonpath='{.data.ca\.crt}')
TOKEN_DATA=$(kubectl -n platform-system get secret crossplane-agent-token \
  -o jsonpath='{.data.token}' | base64 --decode)

cat <<EOF > kubeconfig-worker-dc1.yaml
apiVersion: v1
kind: Config
clusters:
- cluster:
    certificate-authority-data: ${CA_DATA}
    server: ${TARGET_API}
  name: worker-dc1
contexts:
- context:
    cluster: worker-dc1
    user: crossplane-agent
  name: worker-dc1
current-context: worker-dc1
users:
- name: crossplane-agent
  user:
    token: ${TOKEN_DATA}
EOF

kubectl -n crossplane-system create secret generic cluster-worker-dc1-creds \
  --from-file=kubeconfig=kubeconfig-worker-dc1.yaml
rm -f kubeconfig-worker-dc1.yaml
```

ClusterProviderConfig (v2, namespaced MR):

```yaml
apiVersion: kubernetes.m.crossplane.io/v1alpha1
kind: ClusterProviderConfig
metadata:
  name: worker-dc1
spec:
  credentials:
    source: Secret
    secretRef:
      namespace: crossplane-system
      name: cluster-worker-dc1-creds
      key: kubeconfig
```

### Сценарий 2: Platform-стек во всех downstream-кластерах

`Object` с `providerConfigRef` на конкретный downstream:

```yaml
apiVersion: kubernetes.m.crossplane.io/v1alpha1
kind: Object
metadata:
  name: dc1-monitoring-agent
  namespace: platform-fleet
spec:
  providerConfigRef:
    name: worker-dc1
  managementPolicies: ["*"]
  forProvider:
    manifest:
      apiVersion: apps/v1
      kind: DaemonSet
      metadata:
        name: node-exporter
        namespace: monitoring
      spec:
        selector:
          matchLabels:
            app: node-exporter
        template:
          metadata:
            labels:
              app: node-exporter
          spec:
            containers:
              - name: node-exporter
                image: prom/node-exporter:v1.8.2
```

Массовое применение — через ApplicationSet Argo CD с генератором list:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: fleet-platform-stack
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - cluster: worker-dc1
            providerConfig: worker-dc1
          - cluster: worker-dc2
            providerConfig: worker-dc2
  template:
    metadata:
      name: 'platform-{{cluster}}'
    spec:
      project: platform
      source:
        repoURL: https://git.corp.internal/platform/fleet-stacks.git
        targetRevision: main
        path: 'stacks/common'
      destination:
        server: https://kubernetes.default.svc
        namespace: platform-fleet
```

### Сценарий 3: Crossplane композирует кластеры Cluster API

В On-Premise Management Cluster, где CAPI управляется Rancher или отдельно (см. [Rancher overview](../../Kubernetes/Rancher/rancher_overview.md)), Crossplane может выступать абстракцией поверх CAPI:

```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: xcluster-capi
spec:
  compositeTypeRef:
    apiVersion: platform.internal/v1alpha1
    kind: XCluster
  mode: Pipeline
  pipeline:
    - step: patch-and-transform
      functionRef:
        name: function-patch-and-transform
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          - name: cluster
            base:
              apiVersion: cluster.x-k8s.io/v1beta1
              kind: Cluster
              spec:
                clusterNetwork:
                  pods:
                    cidrBlocks: ["192.168.0.0/16"]
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: spec.parameters.name
                toFieldPath: metadata.annotations[crossplane.io/external-name]
              - type: FromCompositeFieldPath
                fromFieldPath: spec.parameters.podCIDR
                toFieldPath: spec.clusterNetwork.pods.cidrBlocks[0]
    - step: auto-ready
      functionRef:
        name: function-auto-ready
```

> CAPI-ресурсы в Crossplane v2 доступны namespaced XR как «третьи» CRD. Для Day-2 (масштабирование `MachineDeployment`) используйте `managementPolicies: ["Observe", "Update"]` или отдельные композиции.

### Сценарий 4: Инвентаризация через ObservedObjectCollection

Для аудита состояния downstream-кластеров без вмешательства:

```yaml
apiVersion: kubernetes.crossplane.io/v1alpha1
kind: ObservedObjectCollection
metadata:
  name: dc1-namespaces-audit
spec:
  providerConfigRef:
    name: worker-dc1
  query:
    apiVersion: v1
    kind: Namespace
```

## Операции и команды

| Задача | Команда |
|---|---|
| Список ClusterProviderConfig | `kubectl get clusterproviderconfig` |
| Статус `Object` по downstream | `kubectl get objects -A \| grep worker-dc1` |
| Трассировка графа XR → MR | `crossplane beta trace <xr-kind> <name> -n <ns>` |
| Логи провайдера для конкретного кластера | `kubectl logs -n crossplane-system -l pkg.crossplane.io/provider=provider-kubernetes --tail=100` |
| Проверка доступа из Management Cluster | `kubectl get secret -n crossplane-system cluster-worker-dc1-creds -o jsonpath='{.data.kubeconfig}' \| base64 -d \| kubectl --kubeconfig - get ns` |

## Устранение неполадок (Troubleshooting)

| Симптом | Первопричина | Диагностика | Решение |
|---|---|---|---|
| `Object` в `Synced=False` с `Forbidden` | Недостаточно прав `crossplane-agent` в downstream | `kubectl describe object <name>` → Events | Расширить ClusterRole downstream-аккаунта (verb `patch` обязателен для SSA) |
| `dial tcp ... i/o timeout` | NetworkPolicy/firewall не пропускает трафик Management → downstream `:6443` | `nc -zvw3 <downstream>:6443` из пода провайдера | Открыть egress с нод Management Cluster; проверить DNS |
| Токен downstream истёк | `ServiceAccount` token rotation | `kubectl describe secret crossplane-agent-token` | Перевыпустить токен, обновить Secret в Management Cluster |
| Конфликт SSA с другим GitOps-агентом | Два контроллера управляют одними полями | `managedFields` в downstream-ресурсе | Разделить зоны ответственности (см. [provider_kubernetes_setup.md](./provider_kubernetes_setup.md)) |
| CRD-взрыв в Management Cluster | Установлены все типы MR провайдеров без MRAP | `kubectl get crd \| wc -l` | Настроить `ManagedResourceActivationPolicy` (v2) или `revisionHistoryLimit: 1` |

## Лучшие практики (Best Practices)

1. **Ограничьте `crossplane-agent` в downstream** scoped-ролью (не `cluster-admin`): только API-группы и ресурсы, реально применяемые платформой.
2. **Фиксируйте kubeconfig по digest / ротируйте токены** через ESO + Vault (см. [Интеграция с GitOps](./gitops_integration.md)).
3. **Используйте MRAP (v2)** для активации только нужных типов MR — снижает нагрузку на etcd/API-сервер Management Cluster (см. [Capacity Planning](./capacity_planning.md)).
4. **Мультикластерные Claims** — не создавайте один Claim на каждый downstream вручную; генерируйте их ApplicationSet / Kustomize overlays из одного шаблона.
5. **Для CAPI** соблюдайте порядок: сначала bootstrap CAPI (сами кластеры), затем Crossplane-композиции платформенных сервисов внутри этих кластеров — иначе chicken-and-egg (см. [Интеграция с GitOps](./gitops_integration.md), волна bootstrap).

## Дополнительная информация

### Внутренние ссылки

* [Управление ресурсами Kubernetes (provider-kubernetes)](./provider_kubernetes_setup.md) — детальная настройка SSA, multi-cluster, ObservedObjectCollection.
* [Интеграция с GitOps](./gitops_integration.md) — ApplicationSet для fleet, волны bootstrap.
* [Мультитенантность и изоляция](./multi_tenancy.md) — namespaced MR, ClusterProviderConfig vs ProviderConfig.
* [Capacity Planning](./capacity_planning.md) — сайзинг Management Cluster для парка кластеров.
* [Rancher overview](../../Kubernetes/Rancher/rancher_overview.md) — CAPI как движок провижининга Rancher.
* [Cluster API security audit](../../Kubernetes/Security/cluster_api_security_audit.md) — аудит безопасности CAPI-кластеров.

### Внешние ресурсы

* [Providers (Crossplane v2.4)](https://docs.crossplane.io/latest/packages/providers/) — ProviderConfig / ClusterProviderConfig, namespaced MR.
* [What's New in Crossplane v2](https://docs.crossplane.io/latest/whats-new/) — namespaced XR/MR, MRAP.
* [Cluster API documentation](https://cluster-api.sigs.k8s.io/) — декларативное управление кластерами Kubernetes.
