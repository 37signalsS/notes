# Descheduler: автоматическая дефрагментация и ребалансировка кластера

## Определения

**Descheduler** — контроллер Kubernetes, который периодически анализирует распределение подов по узлам и инициирует их выселение (eviction) для исправления субоптимального размещения. В отличие от `kube-scheduler`, который принимает решения только при создании пода, Descheduler работает с уже запущенными подами и корректирует их расположение.

**Eviction API** — часть Kubernetes API (`policy/v1`), позволяющая приложениям и контроллерам запрашивать «вежливое» выселение подов. В отличие от прямого `kubectl delete`, Eviction API учитывает `PodDisruptionBudget` и может быть отклонен API-сервером.

**DeschedulerPolicy** — CRD, определяющая набор политик (стратегий) выселения. Каждая политика описывает условие, при котором под должен быть перемещен, и параметры фильтрации.

---

## Предварительные требования

| Компонент | Минимальная версия | Рекомендуемая | Примечание |
|-----------|-------------------|---------------|------------|
| Kubernetes | 1.25 | 1.28+ | API `policy/v1` для Eviction |
| Descheduler | v1alpha2 (Helm) | v1alpha2 | Образ `registry.k8s.io/descheduler/descheduler` |
| Metrics Server | 0.6.0+ | 0.7.0+ | Для политик, основанных на утилизации |
| PDB | — | — | Descheduler уважает `minAvailable` / `maxUnavailable` |

### Проверка готовности

```bash
# Проверка версии Kubernetes
kubectl version --short
# → Server: v1.28.0

# Проверка наличия Metrics Server
kubectl top nodes
# → NAME   CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%

# Проверка отсутствующих политик (до установки Descheduler)
kubectl get pods -A -o json | jq -r '.items[] | select(.spec.nodeName != "") | .spec.nodeName' | sort | uniq -c | sort -rn
# → Показывает перекос распределения подов по узлам
```

---

## Теоретический блок

### Зачем нужен Descheduler

`kube-scheduler` принимает решения только в момент создания пода. Со временем кластер деградирует:

- Узлы перегружаются, пока другие простаивают (дрейф нагрузки)
- HPA масштабирует поды, и они все попадают на один узел (кластеризация)
- После удаления узла поды не мигрируют автоматически
- Anti-affinity правила перестают соблюдаться после масштабирования кластера

Descheduler решает эти проблемы,周期ically запуская цикл анализа и выселения подов, нарушающих политики.

### Архитектура

```
Descheduler (CronJob / Deployment)
    │
    ├─── Считывает текущее состояние кластера (API server)
    │
    ├─── Применяет политики (DeschedulerPolicy)
    │    ├── RemoveDuplicates
    │    ├── RemoveLowPriorityNodes
    │    ├── RemovePodsViolatingInterPodAntiAffinity
    │    ├── RemovePodsViolatingNodeAffinity
    │    ├── RemovePodsViolatingNodeTaints
    │    ├── RemovePodsViolatingTopologySpreadConstraints
    │    ├── RemovePodsViolatingPodDisruptionBudget
    │    ├── LowNodeUtilization / HighNodeUtilization
    │    ├── RemovePodsHavingTooManyRestarts
    │    └── RemoveFailedPods
    │
    ├─── Проверяет PDB перед выселением
    │
    └─── Вызывает Eviction API для каждого пода
         ├── PDB соблюдается → под выселен
         └── PDB нарушается → под пропущен
```

### Политики (стратегии) выселения

| Политика | Описание | Типичное применение |
|----------|----------|---------------------|
| `RemoveDuplicates` | Удаляет дубликаты подов с `RequiredDuringScheduling` anti-affinity на одном узле | Дефрагментация после ошибок планирования |
| `RemoveLowPriorityNodes` | Выселяет поды с низким `PriorityClass` с перегруженных узлов | Освобождение места для критичных подов |
| `RemovePodsViolatingInterPodAntiAffinity` | Выселяет поды, нарушающие `RequiredDuringScheduling` anti-affinity | Исправление после миграции узлов |
| `RemovePodsViolatingNodeAffinity` | Выселяет поды, не соответствующие `RequiredDuringScheduling` nodeAffinity | После обновления меток узлов |
| `RemovePodsViolatingNodeTaints` | Выселяет поды без tolerations для новых taints | После добавления taints на узлы |
| `RemovePodsViolatingTopologySpreadConstraints` | Исправляет перекос `maxSkew` при нарушении `DoNotSchedule` | Дефрагментация по зонам/узлам |
| `RemovePodsViolatingPodDisruptionBudget` | Удаляет поды, нарушающие PDB (при `unhealthyPodEvictionPolicy: AlwaysAllow`) | Очистка нездоровых подов |
| `LowNodeUtilization` | Перемещает поды с перегруженных узлов на недозагруженные | Балансировка загрузки |
| `HighNodeUtilization` | Выселяет поды с недозагруженных узлов (оставляет только «горячий резерв») | Экономия ресурсов, консолидация |
| `RemovePodsHavingTooManyRestarts` | Удаляет поды, которые многократно перезапускались | Очистка «битых» подов |
| `RemoveFailedPods` | Удаляет завершившиеся с ошибкой поды | Гигиена кластера |

### Взаимодействие с HPA

Descheduler и HPA могут конфликтовать:

1. **HPA scale-up** → добавляет поды → они попадают на уже загруженные узлы (из-за `preferredDuringScheduling`)
2. **Descheduler** → видит перекос → выселяет поды → HPA пытается добавить новые → цикл

**Решение:** Используйте `LowNodeUtilization` вместо агрессивного `RemoveDuplicates`. Настройте `nodeUtilizationThresholds` так, чтобы порог не совпадал с целевым значением HPA.

### Взаимодействие с Cluster Autoscaler

- Descheduler выселяет поды → освобождает ресурсы на узлах → CA может удалить пустые узлы (scale-down)
- CA добавляет узлы → Descheduler может перемещать поды на новые узлы для балансировки

**Опасность:** Descheduler выселяет поды, CA добавляет узлы для «высвобожденных» подов → бесконечный цикл. Решение: настройте `highNodeUtilization` carefully и используйте `--scale-down-delay-after-add` в CA.

---

## Практический блок

### Установка через Helm

```bash
# Добавление репозитория
helm repo add descheduler https://kubernetes-sigs.github.io/descheduler/
helm repo update

# Установка
helm install descheduler descheduler/descheduler \
  --namespace kube-system \
  --set image.tag=v0.29.0 \
  --set replicaCount=2
# → NAME: descheduler
# → NAMESPACE: kube-system

# Проверка
kubectl get pods -n kube-system -l app.kubernetes.io/name=descheduler
# → NAME                             READY   STATUS    RESTARTS   AGE
# → descheduler-xxxxx-yyy            1/1     Running   0          30s
```

### Базовая конфигурация политики

```yaml
apiVersion: "descheduler/v1alpha2"
kind: "DeschedulerPolicy"
profiles:
- name: ProfileName
  pluginConfig:
  - name: "RemovePodsViolatingTopologySpreadConstraints"
    args:
      includeSoftConstraints: false
  - name: "LowNodeUtilization"
    args:
      thresholds:
        cpu: 20
        memory: 20
        pods: 15
      targetThresholds:
        cpu: 50
        memory: 50
        pods: 30
  - name: "RemoveFailedPods"
    args:
      reasons:
        - "CrashLoopBackOff"
        - "ImagePullBackOff"
      minPodLifetimeSeconds: 3600
  plugins:
    balance:
      enabled:
        - "RemovePodsViolatingTopologySpreadConstraints"
        - "LowNodeUtilization"
    remove:
      enabled:
        - "RemoveFailedPods"
        - "RemovePodsViolatingNodeTaints"
```

### Запуск как CronJob (рекомендуется для production)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: descheduler
  namespace: kube-system
spec:
  schedule: "*/30 * * * *"  # Каждые 30 минут
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: descheduler
          containers:
          - name: descheduler
            image: registry.k8s.io/descheduler/descheduler:v0.29.0
            args:
            - --policy-config-file=/policy/policy.yaml
            - --v=3
            volumeMounts:
            - name: policy
              mountPath: /policy
          volumes:
          - name: policy
            configMap:
              name: descheduler-policy
          restartPolicy: Never
```

### Проверка работы

```bash
# Просмотр логов
kubectl logs -n kube-system -l app.kubernetes.io/name=descheduler --tail=50
# → I0101 00:00:00.000000 1 descheduler.go:100] Processing node "node-1"
# → I0101 00:00:00.000000 1 evictor.go:200] Evicting pod "my-app-xxxxx"

# Проверка выселенных подов
kubectl get pods -A --field-selector=status.phase=Failed | grep "Evicted"
# → my-app-xxxxx   0/1     Evicted   0          5m

# Проверка PDB (Descheduler не нарушает PDB)
kubectl get pdb -A
# → NAME         MIN AVAILABLE   MAX UNAVAILABLE   DISABLED   ALLOWED DISRUPTIONS
# → my-app-pdb   2               N/A               false      1
```

### Сценарий: Дефрагментация после масштабирования кластера

**Ситуация:** После добавления 5 новых узлов через CA поды остались на старых узлах, новые простаивают.

```yaml
apiVersion: "descheduler/v1alpha2"
kind: "DeschedulerPolicy"
profiles:
- name: rebalance
  pluginConfig:
  - name: "LowNodeUtilization"
    args:
      thresholds:
        cpu: 20
        memory: 20
        pods: 15
      targetThresholds:
        cpu: 40
        memory: 40
        pods: 25
  plugins:
    balance:
      enabled:
        - "LowNodeUtilization"
```

### Сценарий: Очистка failed-подов

```yaml
apiVersion: "descheduler/v1alpha2"
kind: "DeschedulerPolicy"
profiles:
- name: cleanup
  pluginConfig:
  - name: "RemoveFailedPods"
    args:
      reasons:
        - "CrashLoopBackOff"
        - "ImagePullBackOff"
        - "CreateContainerConfigError"
      excludeOwnerKinds:
        - "Job"
        - "CronJob"
      minPodLifetimeSeconds: 1800
  - name: "RemovePodsHavingTooManyRestarts"
    args:
      podRestartThreshold: 5
      includingInitContainers: true
  plugins:
    remove:
      enabled:
        - "RemoveFailedPods"
        - "RemovePodsHavingTooManyRestarts"
```

### Удаление Descheduler

```bash
# Если установлен через Helm
helm uninstall descheduler -n kube-system

# Если установлен через манифесты
kubectl delete deployment descheduler -n kube-system
kubectl delete configmap descheduler-policy -n kube-system
kubectl delete clusterrolebinding descheduler
kubectl delete clusterrole descheduler
kubectl delete serviceaccount descheduler -n kube-system
```

---

## Дополнительная информация

### Ограничения и особенности

- Descheduler уважает PDB — не выселяет поды, если это нарушит `minAvailable`
- При использовании с `ScheduleAnyway` (мягкие правила) — Descheduler может перемещать поды для оптимизации баланса
- Поды с `cluster-critical` или `system-node-critical` PriorityClass не выселяются
- Pod с аннотацией `descheduler.alpha.kubernetes.io/safe-to-evict: false` не выселяются
- Descheduler не пересоздает поды — он только вызывает Eviction, а родительский контроллер (Deployment, ReplicaSet) создает новые
- При работе с HPA — настройте `stabilizationWindowSeconds` в HPA, чтобы избежать флаппинга
- **Тестируйте политики в staging перед production**: выселение подов увеличивает время простоя нагрузки (переезд, запуск, загрузка). Агрессивные политики не запускайте в prime-time — сначала проверьте поведение перепланировки в предпродакшн/тестовом окружении и настройте политики под свои кейсы

### Диагностика проблем

| Проблема | Диагностика | Решение |
|----------|-------------|---------|
| Descheduler не выселяет поды | Проверьте логи: `kubectl logs -n kube-system -l app.kubernetes.io/name=descheduler` | Убедитесь, что политики включены в `plugins` |
| Поды выселяются слишком агрессивно | Проверьте `nodeUtilizationThresholds` | Увеличьте пороги или добавьте `minPodLifetimeSeconds` |
| Конфликт с HPA | Descheduler выселяет поды, HPA добавляет новые | Уменьшите частоту запуска Descheduler или отключите `LowNodeUtilization` |
| PDB блокирует выселение | `kubectl get pdb -A` — проверьте `ALLOWED DISRUPTIONS` | Descheduler пропускает поды, которые нарушат PDB |

### См. также

- [Pod Disruption Budget (PDB)](pod_disruption_budget.md) — защита доступности при выселении
- [Управление размещением подов (Affinity, TSC)](../Scheduling/affinity.md) — политики, которые исправляет Descheduler
- [Cluster Autoscaler](cluster_autoscaler_detailed.md) — взаимодействие с CA при scale-down
- [HPA: Продвинутые темы](HPA/hpa_advanced.md) — конфликты с HPA
