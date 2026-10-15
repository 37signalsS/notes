# Crossplane: Capacity Planning и сайзинг Control Plane

**Актуально для:** Crossplane v1.18+ / v2.x (актуально v2.4); Kubernetes 1.28–1.32+; On-Premise / Bare-Metal

## Определения

**Control Plane Crossplane** — управляющий кластер Kubernetes с ядром Crossplane, подами провайдеров и функций; масштабируется по числу Managed Resources (MR), Composite Resources (XR) и типов CRD, а не по числу рабочих нагрузок пользователей.

**Накладные расходы (overhead)** — ресурсы CPU/RAM, потребляемые подами `crossplane`, `crossplane-rbac-manager`, подами провайдеров и функций, плюс нагрузка на `kube-apiserver` и etcd от CRD и объектов Crossplane.

**etcd quota** — лимит размера базы данных etcd (`--quota-backend-bytes`, по умолчанию 2 ГБ); при превышении API-сервер блокирует запись (`etcdserver: mvcc: database space exceeded`).

**ManagedResourceActivationPolicy (MRAP)** — в Crossplane v2 ресурс `apiextensions.crossplane.io/v1alpha1`, активирующий только перечисленные типы MR вместо всех CRD провайдера; снижает число CRD в API-сервере.

**Poll Interval** — интервал периодической сверки Managed Resource (`--poll-interval` в аргументах провайдера или `spec.pollInterval` в ресурсе); главный рычаг нагрузки на внешние API и сам control plane.

## Базовые концепции и архитектура

### Что масштабируется и от чего зависит

```text
Нагрузка на Control Plane = f(MR, XR, CRD types, poll interval, provider count)
│
├─ etcd: объекты MR/XR/CompositionRevision/ProviderRevision (штучно)
├─ kube-apiserver: watch-клиенты провайдеров + CRUD объектов
├─ Под провайдера: память ~ O(CRD types + watched objects)
└─ Под функции: CPU при каждом reconcile XR (gRPC call)
```

Ориентировочные ориентиры (калибровать замерами в конкретном окружении):

| Компонент | Ориентир | Комментарий |
|---|---|---|
| `crossplane` core (HA) | 2 реплики; 0.5 CPU / 512 MiB requests | Независимо от числа MR |
| Под провайдера (малый, 5–20 CRD) | 100–250 MiB | provider-kubernetes, provider-sql |
| Под провайдера (upjet-провайдер, 50–150 CRD) | 256 MiB–1 GiB | Провайдеры Terraform-bridge; зависит от числа watched MR |
| Под функции (patch-and-transform) | 50–100 MiB | gRPC-вызов на каждый reconcile XR |
| etcd кластера CP | 4–8 ГБ RAM; NVMe; fsync < 10 мс; quota ≥ 4–8 ГБ | См. [etcd monitoring](../../etcd/etcd_monitoring.md) |
| kube-apiserver CP | 2–4 CPU, 4–8 ГБ RAM (средний CP) | Растёт с числом CRD и watch-клиентов |

### Факторы роста

1. **Число MR** — линейно увеличивает размер etcd и watch-нагрузку провайдеров.
2. **Число типов CRD** — каждый тип добавляет запись в etcd и память API-сервера; CAPI-провайдеры и upjet-провайдеры весят особенно много (сотни CRD).
3. **Poll interval** — уменьшение с 1m до 10s увеличивает QPS к внешнему API в 6 раз.
4. **Количество провайдеров** — каждый под — отдельный watch на CRD и MR.
5. **CompositionRevisions** — каждое изменение Composition создаёт новую ревизию; без GC накапливаются.

## Практические сценарии и конфигурация

### Сценарий 1: Базовый сайзинг управляющего кластера (On-Premise)

Рекомендуемый минимальный профиль для продакшена с < 500 MR:

```yaml
# values-crossplane.yaml (Helm)
crossplane:
  replicas: 2
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      memory: 1Gi
  rbacManager:
    replicas: 2
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
```

Узлы control plane: минимум 3 ноды, 4 vCPU / 16 ГБ RAM каждая (етcd на NVMe), изолированные от прикладных нагрузок (`nodeSelector: node-role.kubernetes.io/infra: "true"`).

### Сценарий 2: MRAP — активация только нужных MR (v2)

Вместо установки AWS-провайдера со 150+ CRD:

```yaml
apiVersion: apiextensions.crossplane.io/v1alpha1
kind: ManagedResourceActivationPolicy
metadata:
  name: onprem-essentials
spec:
  activate:
    - objects.kubernetes.m.crossplane.io
    - releases.helm.m.crossplane.io
    - databases.postgresql.sql.m.crossplane.io
```

Проверка:

```bash
kubectl get crd | grep -c crossplane
# → до: 312
# → после MRAP: 48
```

### Сценарий 3: Тюнинг poll interval через DeploymentRuntimeConfig

```yaml
apiVersion: pkg.crossplane.io/v1beta1
kind: DeploymentRuntimeConfig
metadata:
  name: slow-api-runtime
spec:
  deploymentTemplate:
    spec:
      template:
        spec:
          containers:
            - name: package-runtime
              args:
                - --poll-interval=10m
                - --max-reconcile-rate=10
```

Правила выбора:

| Внешняя система | Рекомендуемый poll |
|---|---|
| Быстрый SQL / K8s API | 1–5 мс |
| Старые консоли виртуализации, SAN | 10–15 мс |
| Rate-limited API (облака) | 5–15 мс + jitter |

### Сценарий 4: Контроль числа ревизий

```yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-kubernetes
spec:
  package: harbor.corp.internal/crossplane/provider-kubernetes:v1.3.0
  revisionHistoryLimit: 3
```

```bash
# Массовая очистка неактивных ревизий (после обновления)
kubectl get providerrevisions -l pkg.crossplane.io/provider=provider-kubernetes \
  -o jsonpath='{range .items[?(@.spec.desiredState=="Inactive")]}{.metadata.name}{"\n"}{end}' \
  | xargs -r kubectl delete providerrevision
```

### Сценарий 5: Мониторинг наполнения etcd и API-сервера

```promql
# Размер базы etcd (байты) — приближение через count объектов
sum(kube_resource_count{resource=~"managed|composite|providerrevision"}) by (resource)

# Нагрузка API-сервера от Crossplane
sum(rate(apiserver_request_total{verb=~"LIST|WATCH"}[5m])) by (resource)

# Client-side throttling провайдеров (в логах)
# "waited for ... due to client-side throttling"
```

Пороговые значения:

* `etcd database size > 50% quota` — расширять quota или чистить ревизии;
* `apiserver_request_duration_seconds p99 > 1s` на LIST/WATCH Crossplane-ресурсов — увеличивать память API-сервера или уменьшать число MR;
* OOMKill пода провайдера — увеличивать limits через `DeploymentRuntimeConfig` (см. [Observability](./observability.md)).

## Операции и команды

| Задача | Команда |
|---|---|
| Число CRD Crossplane | `kubectl get crd \| grep -E 'crossplane\.io\|pkg\.' \| wc -l` |
| Число MR | `kubectl get managed -A \| wc -l` |
| Число XR | `kubectl get composite -A \| wc -l` |
| Размер etcd (etcdctl) | `etcdctl endpoint status -w table` → `DB SIZE` |
| Ревизии провайдеров | `kubectl get providerrevisions` |
| Логи throttling | `kubectl logs -n crossplane-system deploy/crossplane \| grep -i thrott` |
| Память подов провайдеров | `kubectl top pods -n crossplane-system` |

## Устранение неполадок (Troubleshooting)

| Симптом | Первопричина | Диагностика | Решение |
|---|---|---|---|
| `etcdserver: mvcc: database space exceeded` | Превышена quota etcd из-за накопления объектов/ревизий | `etcdctl endpoint status` | `revisionHistoryLimit`, дефрагментация etcd, расширение quota (`--quota-backend-bytes`) |
| `client-side throttling` в логах провайдера | Слишком много MR при малом `--max-reconcile-rate` | Логи пода провайдера | Увеличить `--max-reconcile-rate`, увеличить poll interval, шардировать провайдеры |
| OOMKill пода провайдера | Память пропорциональна числу watched MR/CRD | `kubectl describe pod` → Last State | Увеличить limits; вынести тяжёлых MR в отдельный провайдер |
| API-сервер деградирует (LIST/WATCH таймауты) | Массовые watch от Crossplane + приложений | `apiserver_request_duration_seconds` | Увеличить ресурсы API-сервера; MRAP; увеличить poll interval |
| CompositionRevision накапливаются | Нет `revisionHistoryLimit` в Configuration/Provider | `kubectl get compositionrevision \| wc -l` | Установить `revisionHistoryLimit: 1–3`; GC старых ревизий |

## Лучшие практики (Best Practices)

1. **Выделенный Control Plane** для крупных инфраструктур (> 500 MR или > 10 провайдеров); не смешивайте с прикладными неймспейсами.
2. **MRAP до массового обновления провайдеров** — сначала активируйте нужные типы, затем устанавливайте v2-провайдеры.
3. **Poll interval — первый рычаг** при росте парка MR: увеличивайте его до того, как масштабировать hardware.
4. **Регулярный аудит CRD/ревизий** в рамках capacity review (ежеквартально): `kubectl get crd | wc -l`, `kubectl get providerrevisions`.
5. **etcd на NVMe, quota ≥ 2× текущего размера**; мониторинг размера — обязательная часть SLO control plane (см. [Observability](./observability.md)).
6. **Для fleet** сайзить Management Cluster по числу downstream-кластеров × MR на кластер (см. [Fleet Management](./fleet_management.md)).

## Дополнительная информация

### Внутренние ссылки

* [Обзор Crossplane](./overview.md) — базовые архитектурные требования и сайзинг etcd.
* [Observability](./observability.md) — метрики, алерты на деградацию CP.
* [Обновление и миграция](./upgrade_migration.md) — нагрузка на etcd при апгрейдах, GC ревизий.
* [Fleet Management](./fleet_management.md) — сайзинг для парка кластеров.
* [etcd monitoring](../../etcd/etcd_monitoring.md) — эксплуатация etcd.

### Внешние ресурсы

* [What's New in Crossplane v2 — MRAP](https://docs.crossplane.io/latest/whats-new/) — управление активацией MR для снижения overhead.
* [etcd documentation — quota backend bytes](https://etcd.io/docs/v3.5/tuning/) — настройка quota и compaction.
