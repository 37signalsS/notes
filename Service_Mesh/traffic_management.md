# Управление трафиком в Service Mesh

## Определения

**Управление трафиком (Traffic Management)** — это набор техник для контроля потоков запросов (трафика) между сервисами на уровне L7. В контексте [Service Mesh](./service_mesh_concepts.md) эти техники реализуются в прокси-сайдкарах и управляются декларативно через API плоскости управления, что позволяет изменять сетевое поведение без вмешательства в код приложений.

## Основные концепции

Ключевые задачи, решаемые с помощью управления трафиком:

* **Динамическая маршрутизация**: Направление запросов на основе атрибутов (хост, путь, заголовки, cookie). Позволяет реализовывать сложные сценарии развертывания.
* **Сегментация по версиям**: Изоляция трафика для разных версий сервиса (например, `v1`, `v2`) с помощью подмножеств (subsets).
* **Отказоустойчивость**: Повышение надежности системы за счет применения паттернов, таких как таймауты, повторные попытки (retries), размыкатели цепи (circuit breaking) и изоляция сбойных экземпляров (outlier detection).
* **Тестирование и эксперименты**: Безопасное тестирование новых версий с помощью зеркалирования трафика (shadowing/mirroring) или внесения неисправностей (fault injection).

Сравнение основных примитивов в Istio и Linkerd:

| Примитив | Istio | Linkerd |
| :--- | :--- | :--- |
| **Взвешенная маршрутизация** | `VirtualService` + `DestinationRule` | `TrafficSplit` (SMI) |
| **Ретраи/таймауты** | `VirtualService` | `ServiceProfile` |
| **Circuit breaking** | `DestinationRule` (outlierDetection) | Ограниченно, на уровне прокси |
| **Маршрутизация по заголовкам** | `VirtualService` (секция `match`) | Нативно не поддерживается (реализуется через Ingress) |
| **Зеркалирование** | `VirtualService` (секция `mirror`) | Нативно не поддерживается |

## Практические сценарии

### Сценарий 1: Канареечное развертывание в Istio

Направить 10% трафика на новую версию `v2` сервиса `api`, а 90% — на стабильную `v1`. Дополнительно для всех запросов установить таймаут в 2 секунды и 3 попытки ретрая в случае сбоев.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: api
spec:
  hosts: [ "api.default.svc.cluster.local" ]
  http:
  - route:
    - destination: { host: api, subset: v1 }
      weight: 90
    - destination: { host: api, subset: v2 }
      weight: 10
    timeout: 2s
    retries:
      attempts: 3
      perTryTimeout: 1s
      retryOn: 5xx,connect-failure,refused-stream
---
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: api
spec:
  host: api
  subsets:
  - name: v1
    labels: { version: v1 }
  - name: v2
    labels: { version: v2 }
```

### Сценарий 2: Зеркалирование трафика в Istio

Отправлять 100% реального трафика на `v1`, а 10% этого трафика незаметно для пользователя дублировать на `v2` для тестирования под нагрузкой.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: api-mirror
spec:
  hosts: [ "api" ]
  http:
  - route:
    - destination: { host: api, subset: v1 }
    mirror:
      host: api
      subset: v2
    mirrorPercentage:
      value: 10.0
```

### Сценарий 3: Настройка ретраев и таймаутов в Linkerd

Для сервиса `api` определить, что GET-запросы к `/api/v1` можно повторять в случае сбоя, и установить для них таймаут в 2 секунды.

```yaml
apiVersion: linkerd.io/v1alpha2
kind: ServiceProfile
metadata:
  name: api.default.svc.cluster.local
spec:
  routes:
  - name: GET /api/v1
    condition:
      method: GET
      pathRegex: /api/v1
    isRetryable: true
    timeout: 2s
```

## Дополнительная информация

Архитектура Istio и полный набор его CRD описаны в [Istio: компоненты и архитектура](./istio_architecture.md). Сравнение философии и возможностей Istio и Linkerd доступно в документе [Сравнение Istio и Linkerd](./istio_vs_linkerd.md).
