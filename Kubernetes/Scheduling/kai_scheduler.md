# KAI Scheduler: GPU-планировщик для AI/ML-нагрузок

**Актуально для:** KAI Scheduler 0.18.x

## Определения

* **KAI Scheduler** — открытый (Apache License 2.0) Kubernetes-native планировщик, оптимизирующий выделение GPU для AI/ML-нагрузок. Разработан NVIDIA (на базе технологии Run:ai), открыт в 2025 году и продолжает поставляться как часть платформы NVIDIA Run:ai. Построен на базе **kube-batch**.
* **PodGroup** — атомарная единица планирования: группа взаимозависимых подов, которые должны выполняться как единое целое (gang scheduling). Ключевая сущность KAI Scheduler наряду с очередями.
* **Queue** — очередь с квотами ресурсов; задания направляются в очередь и получают ресурсы в рамках её квоты.
* **Topology-Aware Scheduling (TAS)** — размещение подов с учётом физической топологии GPU (NVLink-домены), чтобы тесно связанные поды попали на GPU с высокоскоростным соединением между ними.
* **Bin-packing** — стратегия упаковки подов на минимальное число узлов (`placementStrategy: binpack`), повышающая утилизацию GPU.
* **Fairshare** — непрерывный пересчёт справедливой доли ресурсов для каждой очереди/потребителя в реальном времени.
* **Consolidation** — действие планировщика: перераспределение уже запущенных подов для формирования непрерывного блока ресурсов под новое задание.

---

## Основные концепции

### Зачем нужен специализированный GPU-планировщик

Стандартный `kube-scheduler` планирует под-под и не понимает:

* топологию соединений между GPU (NVLink внутри ноды vs сеть между нодами);
* необходимость запуска группы подов одновременно (gang scheduling);
* справедливое разделение GPU между командами.

KAI Scheduler решает эти задачи: поды группируются в PodGroup, планировщик учитывает топологию GPU и квоты очередей, приоритизирует нагрузки (в том числе на основе SLA) и пересчитывает fair-share в реальном времени.

**Пример проблемы (из доклада):** заданию нужно 8 GPU. Без топологического планирования они попадают на 4 разные ноды: соединение GPU внутри ноды (NVLink) на порядки быстрее межнодовой сети, и скорость обучения падает многократно (в докладе приводится оценка замедления ~6 раз), а дорогие GPU простаивают.

### Архитектура

```
Рабочая нагрузка (Job/JobSet/RayJob/Training Operator)
        │
        ▼
KAI Scheduler (namespace kai-scheduler)
        │
        ├── PodGrouper — автоматически детектирует фреймворки
        │   (Kubeflow, Ray, Argo, Training Operator) и группирует поды
        │
        ├── Цикл планирования:
        │   snapshot кластера (GPU/CPU) → разделение ресурсов →
        │   действия: allocate / consolidate / reclaim / preempt →
        │   обновление состояния
        │
        └── Очереди с квотами и fair-share
```

### Ключевые возможности

* **Gang scheduling через PodGroup** — задание запускается целиком или не запускается.
* **GPU bin-packing** — `placementStrategy: binpack`, отдельные стратегии для GPU (`gpu: binpack`) и CPU (`cpu: spread`).
* **Topology-Aware Scheduling** — размещение PodGroup в одном NVLink-домене (см. ниже).
* **GPU sharing** — эффективное разделение одного или нескольких GPU между нагрузками (компонент `kai-gpu-fractioning`).
* **Hierarchical PodGroups** (v0.10.0+) — иерархические группы подов.
* **Time-based Fairshare** (v0.10.0+) — справедливое разделение по времени использования.
* **Workload signatures** — оптимизация больших многоподовых заявок.
* **Explainability** — каждый значимый шаг планирования логируется в Kubernetes Events.
* **KubeRay integration** — нативная интеграция с Ray (v0.10.0+).
* **Интеграция с Grove & Dynamo** — оркестрация многокомпонентных нагрузок (disaggregated serving, agentic pipelines).
* **Multi-scheduler** — работает рядом с другими планировщиками в том же кластере; совместим с автоскейлерами (Karpenter) и on-premise.

### Topology-Aware Scheduling (TAS)

TAS (выпущена в v0.10.0, 2025-10) — флагманская возможность для распределённого обучения:

1. Драйвер NVIDIA GPU DRA (Dynamic Resource Allocation) размечает ноды меткой `nvidia.com/gpu.clique`, идентифицирующей NVLink-партицию (группу GPU с высокоскоростным соединением).
2. KAI Scheduler читает кластерный ресурс `Topology` (`kai.scheduler/v1alpha1`) с уровнями доменов (от широкого к узкому).
3. Рабочая нагрузка запрашивает топологическое размещение аннотациями:
   * `kai.scheduler/topology` — имя ресурса Topology;
   * `kai.scheduler/topology-required-placement` — требуемый уровень домена (например, `nvidia.com/gpu.clique`).

KAI удерживает PodGroup, пока все реплики не поместятся в один домен указанного уровня — это одновременно и gang-scheduling-запрос, и топологическое ограничение.

---

## Предварительные требования

| Компонент | Требование |
|-----------|------------|
| Kubernetes | работающий кластер |
| KAI Scheduler | 0.18.x (Helm chart `oci://ghcr.io/kai-scheduler/kai-scheduler/kai-scheduler`) |
| NVIDIA GPU-Operator | обязателен для планирования GPU-ресурсов |
| Helm | для установки |
| TAS | NVIDIA GPU DRA driver (разметка `nvidia.com/gpu.clique`) |

---

## Практические сценарии

### Установка

```bash
# Установка в namespace kai-scheduler
helm upgrade -i kai-scheduler \
  oci://ghcr.io/kai-scheduler/kai-scheduler/kai-scheduler \
  -n kai-scheduler --create-namespace --version <VERSION>
# → NAME: kai-scheduler
# → LAST DEPLOYED: ...
# → NAMESPACE: kai-scheduler
# → STATUS: deployed
```

Важно: отправлять рабочие нагрузки нужно в **отдельный** namespace, не в `kai-scheduler`.

### Конфигурация: bin-packing и очереди

```yaml
# values.yaml
scheduler:
  placementStrategy: binpack
  plugins:
    nodeplacement:
      arguments:
        gpu: binpack      # GPU — упаковка
        cpu: spread       # CPU — равномерное распределение
    actions:
      preempt:
        enabled: false
      consolidation:
        enabled: false
defaultQueue:
  createDefaultQueue: true
  parentName: default-parent-queue
  childName: default-queue
  parentResources:
    cpu:    { quota: -1, limit: -1, overQuotaWeight: 1 }
    gpu:    { quota: -1, limit: -1, overQuotaWeight: 1 }
    memory: { quota: -1, limit: -1, overQuotaWeight: 1 }
  childResources:
    cpu:    { quota: -1, limit: -1, overQuotaWeight: 1 }
    gpu:    { quota: -1, limit: -1, overQuotaWeight: 1 }
    memory: { quota: -1, limit: -1, overQuotaWeight: 1 }
```

`quota: -1` означает неограниченную квоту (отслеживание полной ёмкости кластера); для реального разделения между командами задайте конечные квоты на child-очередях.

### Топологическое размещение (NVLink-домен)

```yaml
# Ресурс Topology: уровни доменов от широкого к узкому
apiVersion: kai.scheduler/v1alpha1
kind: Topology
metadata:
  name: nvlink-topology
spec:
  levels:
  - nodeLabel: nvidia.com/gpu.clique   # NVLink-партиция
  - nodeLabel: kubernetes.io/hostname
---
# Рабочая нагрузка: все реплики — в одном NVLink-домене
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: distributed-training
  annotations:
    kai.scheduler/topology: "nvlink-topology"
    kai.scheduler/topology-required-placement: "nvidia.com/gpu.clique"
spec:
  podManagementPolicy: Parallel
  replicas: 8
  # ...
```

KAI Scheduler дождётся, пока все 8 реплик поместятся в одну NVLink-партицию, и только затем запустит их — обучение идёт по высокоскоростному соединению между GPU.

---

## Проверка работы (валидация)

```bash
# Поды, запланированные KAI Scheduler
kubectl get pods -A -o json | jq -r '.items[] | select(.spec.schedulerName=="kai-scheduler") | .metadata.name'

# События планировщика (explainability)
kubectl get events -A --field-selector reason=Scheduled | grep kai

# Состояние очередей и PodGroup — через KAI UI/метрики
kubectl get pods -n kai-scheduler
# → NAME                                        READY   STATUS    RESTARTS   AGE
# → kai-scheduler-xxxxx                         1/1     Running   0          5m

# Логи планировщика
kubectl logs -n kai-scheduler -l app=kai-scheduler --tail=50
```

---

## Траблшутинг

| Симптом | Причина | Решение |
|---------|---------|---------|
| PodGroup завис в ожидании | Нет узла с достаточным числом GPU в одном домане | Проверить метки `nvidia.com/gpu.clique` на нодах; уменьшить replicas или ослабить `topology-required-placement` |
| TAS не работает | Не установлен NVIDIA GPU DRA driver / нет меток `nvidia.com/gpu.clique` | Установить GPU DRA driver, проверить разметку нод |
| Задания не попадают в очередь | Нет настроенных очередей или квоты исчерпаны | Проверить `defaultQueue`/child-очереди в values.yaml; задать конечные квоты |
| Конфликт с другим планировщиком | Поды с `schedulerName: kai-scheduler` на кластере без KAI | Убедиться, что KAI Scheduler установлен и работает в `kai-scheduler` namespace |

---

## Лучшие практики

* **TAS для распределённого обучения** — требуйте NVLink-домен для тесно связанных подов; без этого обучение на межнодовой сети замедляется многократно.
* **Bin-packing для GPU** — повышает утилизацию дорогих GPU; CPU при этом лучше распределять (`cpu: spread`).
* **Конечные квоты на child-очередях** — иначе одна команда может монополизировать GPU.
* **Fairshare** — используйте time-based fairshare для справедливого разделения между командами.
* **Не отправляйте нагрузку в `kai-scheduler` namespace** — только в выделенные namespace команд.
* **Explainability** — читайте Events планировщика при диагностике размещения.

---

## Дополнительная информация

### Ограничения

* TAS требует NVIDIA GPU DRA driver и NVLink-оптимизированного кластера; на кластерах без NVLink топологическое размещение не применимо.
* KAI Scheduler — специализирован для AI/ML; для общих batch-очередей и квот без GPU топологии проще Kueue.
* Вопрос из Q&A доклада: разрезание GPU без MIG (проект Hami) — спикер не тестировал, опыт применения не подтверждён.

### См. также

* [Kueue](./kueue.md) — квоты и очереди (может комбинироваться с KAI)
* [Volcano для batch-нагрузок](../Autoscaling/on_premise_autoscaling.md#volcano-для-batch-нагрузок) — gang scheduling + приоритетные очереди
* [Apache YuniKorn](./yunikorn.md) — иерархические очереди
* [Kube-scheduler](../Concepts/kube_scheduler.md) — стандартный планировщик
* [Topology Manager](./topology_manager.md) — NUMA-осознанное планирование ресурсов
* [Device Manager](./device_manager.md) — управление GPU и специализированным оборудованием
* [Обзор решений для планирования](./scheduling_solutions_overview.md) — матрица выбора
* [Официальный репозиторий KAI Scheduler](https://github.com/kai-scheduler/KAI-Scheduler)
