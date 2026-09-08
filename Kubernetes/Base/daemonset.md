# DaemonSet

## Определения

**DaemonSet** — это специализированный контроллер в Kubernetes, предназначенный для обеспечения запуска ровно одного экземпляра пода (**Pod**) на каждом узле кластера (или на строго определенном наборе узлов). 

В отличие от контроллера **Deployment**, в спецификации **DaemonSet** отсутствует поле `replicas`. Количество запущенных копий определяется динамически на основе количества доступных и подходящих под критерии планирования узлов.

### Ключевые дифференциаторы DaemonSet

В контексте проектирования систем и подготовки к интервью выделяют следующие уникальные преимущества DaemonSet:

- **Автоматическое масштабирование:** При появлении в кластере нового узла контроллер автоматически разворачивает на нем под. При удалении узла из кластера соответствующие поды удаляются сборщиком мусора.
- **Охват кластера (Full Coverage):** Гарантирует полное покрытие инфраструктуры системными сервисами без ручного вмешательства.
- **Оптимизация ресурсов:** Запускаясь на каждом узле, DaemonSet позволяет оптимизировать использование ресурсов кластера, так как системные инструменты (мониторинг, логи) работают максимально близко к источнику данных с минимальными задержками.
- **Надежность и Очистка:** Обеспечивает автоматизированный способ гарантировать, что критически важные службы всегда запущены. Удаление объекта `DaemonSet` автоматически очищает все созданные им поды.

### ControllerRevision — механизм версионирования

Для управления историей изменений DaemonSet использует объекты **ControllerRevision**. Каждый раз, когда обновляется шаблон пода (`spec.template`), контроллер создает новую ревизию. Это позволяет:
- Отслеживать историю изменений манифеста.
- Выполнять откат (rollback) к предыдущим стабильным состояниям.
- Хранить конфигурацию (Data) для каждой версии.

## Основные концепции

### Ключевые сценарии использования

DaemonSet является фундаментальным инструментом для развертывания системных сервисов и агентов, которые обеспечивают работу инфраструктуры «под капотом» на уровне каждого хоста. Это особенно важно для операций, специфичных для узла (node-specific operations):

*   **Сбор и агрегация логов:** Агенты **Fluent Bit**, **Fluentd**, **Promtail**, **Vector**. Установка такого агента на каждую ноду гарантирует полный охват логов всех контейнеров, запущенных на этом узле, через чтение файлов из `/var/log/pods/`.
*   **Мониторинг инфраструктуры:** **Prometheus Node Exporter**, агенты **Datadog**, **Dynatrace** или **Zabbix**. Они собирают метрики ресурсов хоста (CPU, память, дисковые операции, сетевая активность).
*   **Сетевое взаимодействие и безопасность:** Плагины **CNI (Container Network Interface)**, такие как **Cilium**, **Calico**, **Flannel**, а также **kube-proxy**. В современных реализациях (v1.29+) сюда также входят **Ztunnel** (Istio Ambient Mesh) и агенты безопасности (Falco, Tracee), использующие eBPF.
*   **Управление хранилищами (Storage):** Драйверы **CSI (Container Storage Interface)**, выполняющие монтирование сетевых томов (например, для Ceph, Longhorn, GlusterFS).

### Взаимодействие с сервисами и сетью

Как правило, для подов DaemonSet не создают стандартные объекты **Service** типа `ClusterIP` или `LoadBalancer`. Системные агенты обычно работают по модели «push»: они сами инициируют отправку телеметрии во внешние системы (Loki, Prometheus, Elasticsearch).

Особенности сетевой конфигурации:
*   **hostNetwork: true**: Часто используется для сетевых плагинов и экспортеров метрик, чтобы под имел прямой доступ к сетевым интерфейсам узла.
*   **hostPort**: Позволяет пробросить порт контейнера напрямую на узел. Это позволяет обращаться к агенту по IP узла, но требует осторожности для избежания конфликтов портов.
*   **InternalTrafficPolicy: Local**: (v1.26+ GA) Если всё же используется Service, установка этого поля в `Local` гарантирует, что трафик от приложения на узле попадет именно в локальный экземпляр DaemonSet (например, в локальный прокси-кэш или пулер соединений), минимизируя сетевые задержки.

### Стратегии обновления и жизненный цикл

Управление процессом обновления подов осуществляется через поле `spec.updateStrategy`:

1.  **`RollingUpdate` (по умолчанию):** Постепенное обновление.
    *   **`maxUnavailable`**: Количество подов, которые могут быть недоступны в процессе обновления (по умолчанию `1`).
    *   **`maxSurge` (GA v1.25):** Позволяет запустить новый под на узле *рядом* со старым. Полезно для минимизации «слепых пятен» в мониторинге. При значении `1` на время обновления на узле будут работать два пода.
2.  **`OnDelete`:** Автоматическое обновление не происходит. Контроллер создаст новый под только после того, как администратор вручную удалит старый. Рекомендуется для критических CNI-плагинов.

**Дополнительные параметры контроля:**
- **`minReadySeconds`**: Время (в секундах), в течение которого новый под должен проработать без падений, чтобы считаться доступным. Помогает замедлить выкатку неисправных версий.
- **`revisionHistoryLimit`**: Количество старых ревизий (`ControllerRevision`), сохраняемых для возможности отката (по умолчанию `10`).

**Математика `maxUnavailable` и `maxSurge`.**
Для DaemonSet обе величины могут быть заданы абсолютным числом или процентами от общего числа узлов, на которых должен быть развёрнут контроллер (`desiredNumberScheduled`). Важные комбинации:

| Конфигурация | Поведение при обновлении |
| :--- | :--- |
| `maxUnavailable: 1` (по умолчанию) | На каждом узле старый под удаляется, затем создаётся новый. Простой (gap) покрытия в один узел одновременно. |
| `maxUnavailable: 0` + `maxSurge: 1` | Новый под создаётся **рядом** со старым на одном узле, и только после его готовности старый удаляется. Минимизирует «слепые пятна» в мониторинге ценой двойного расхода ресурсов на узле. |
| `maxUnavailable: 10%` | Групповое обновление: одновременно недоступны до 10% узлов с сервисом. Быстрее выкатывается, но увеличивает окно частичного покрытия. |
| `maxUnavailable: 0` + `maxSurge: 0` | Обновление блокируется, пока не будет выполнено условие. Используйте осторожно: стратегия может «зависнуть», если узлы не могут принять дублирующий под. |

**Обновление только на подмножестве узлов (on-selector).**
Иногда требуется раскатить новую версию агента сначала на узлах с определённой меткой. Для этого можно временно модифицировать `spec.template.spec.affinity.nodeAffinity` (или `nodeSelector`) в новой ревизии. Пока селектор сужен, DaemonSet обрабатывает только подходящие узлы; после проверки получите полный манифест (`kubectl get ds <name> -o yaml`) и вновь расширьте селектор — начнётся вторая волна обновления. Такой canary-подход применяется для рискованных версий CNI или агентов безопасности.

**Учёт архитектуры узлов (OS/arch).**
Один DaemonSet физически не может обслуживать узлы с разной `os`/`arch` одновременно — шаблон пода один. Для смешанных кластеров (Linux + Windows) используйте **несколько DaemonSet** с разными `nodeSelector`/`tolerations` (например, отдельный DS для Windows-узлов с `kubernetes.io/os: windows`), либо операторский подход. Даже для чисто Linux-кластера при использовании агрегатов type-`arm64`/`amd64` разделяйте агенты по `nodeSelector: kubernetes.io/arch`.

### Взаимодействие с PodDisruptionBudget (PDB)

Поскольку DaemonSet размещает строго по одному поду на узле, обычный смысл PDB (минимум доступных реплик) для него ограничен. Однако PDB применим для контроля скорости выселения во время `kubectl drain`:
- Если на узле работает DaemonSet-под, а на нём задан PDB, `kubectl drain` будет ждать, пока выселение не станет допустимым по бюджету (например, `minAvailable: 1` по метке будет блокировать выселение, т.к. на других узлах «запасных» реплик нет).
- Для DaemonSet-подов, как правило, задают PDB с `minAvailable: 0` либо не задают вовсе, полагаясь на стратегию обновления и авто-выселение.
- При `kubectl drain` поды DaemonSet **по умолчанию не выселяются** (их контроллер всё равно пересоздаст), что регулируется флагом `--ignore-daemonsets`. Подробнее — в [Обслуживание узлов (Cordon/Drain)](../Operations/node_maintenance.md).

### Механизмы планирования и обслуживания (Cordon/Drain)

**Scheduling:** С версии 1.17 DaemonSet планируется стандартным планировщиком (**kube-scheduler**). Это означает, что он полностью учитывает **Node Affinity**, **Taints** и **PriorityClasses**.

**Поведение при обслуживании (Cordon):**
Когда узел помечается как `unschedulable` (через `kubectl cordon`), на него накладывается Taint `node.kubernetes.io/unschedulable:NoSchedule`. DaemonSet автоматически добавляет подам **Tolerations** для этого ограничения. Это гарантирует, что системные агенты продолжат работу на узле, пока на нем остаются прикладные поды.

**DaemonSet vs Static Pods:**
В отличие от статических подов (управляемых напрямую `kubelet` через файлы в `/etc/kubernetes/manifests`), DaemonSet:
- Управляется через API-сервер.
- Поддерживает стратегии обновления.
- Учитывает параметры планирования кластера.
- Имеет полноценный жизненный цикл контроллера.

## Практические сценарии

### Выборочное развертывание через NodeAffinity

Сценарий: запуск агента мониторинга только на узлах с определенным типом дисков (SSD) или в конкретной зоне доступности.

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: ssd-monitor
spec:
  selector:
    matchLabels:
      app: ssd-monitor
  template:
    metadata:
      labels:
        app: ssd-monitor
    spec:
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
            - matchExpressions:
              - key: disktype
                operator: In
                values:
                - ssd
      containers:
      - name: monitor
        image: monitor-agent:latest
```

### Использование preStop для корректного завершения (Logging Agent)

Для агентов сбора логов критически важно успеть отправить накопленный буфер перед завершением работы пода.

```yaml
spec:
  template:
    spec:
      containers:
      - name: fluent-bit
        image: fluent/fluent-bit:latest
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 20 && /usr/local/bin/fluent-bit-flush"]
      terminationGracePeriodSeconds: 30
```

### Развертывание агента Fluentd (с допуском для мастер-узлов)

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluentd-logging
  namespace: kube-system
spec:
  selector:
    matchLabels:
      name: fluentd-elasticsearch
  template:
    metadata:
      labels:
        name: fluentd-elasticsearch
    spec:
      priorityClassName: system-node-critical
      tolerations:
      - key: node-role.kubernetes.io/master
        operator: Exists
        effect: NoSchedule
      - key: node-role.kubernetes.io/control-plane
        operator: Exists
        effect: NoSchedule
      containers:
      - name: fluentd-elasticsearch
        image: quay.io/fluentd_elasticsearch/fluentd:v2.5.2
        resources:
          limits:
            memory: 500Mi
          requests:
            cpu: 100m
            memory: 200Mi
        volumeMounts:
        - name: varlog
          mountPath: /var/log
        - name: varlibdockercontainers
          mountPath: /var/lib/docker/containers
          readOnly: true
      terminationGracePeriodSeconds: 30
      volumes:
      - name: varlog
        hostPath:
          path: /var/log
      - name: varlibdockercontainers
        hostPath:
          path: /var/lib/docker/containers
```

### Альтернатива DaemonSet: Pod Anti-Affinity в Deployment

Иногда требуется запустить приложение «по одному на узел», но с фиксированным количеством копий.

**Пример конфигурации:**
```yaml
spec:
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchExpressions:
          - key: app
            operator: In
            values: ["cache-proxy"]
        topologyKey: "kubernetes.io/hostname"
```

### Права доступа агента: ServiceAccount и RBAC (running as DaemonSet)

Системные агенты (Node Exporter, log-collectors, CNI, Falco) почти всегда обращаются к Kubernetes API, поэтому им нужен собственный `ServiceAccount`, а не `default`. Это часть модели наименьших привилегий.

**1. ServiceAccount + минимальные права:**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: node-exporter-sa
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: node-exporter
rules:
- apiGroups: [""]
  resources: ["nodes/metrics"]   # минимально возможный ресурс для Node Exporter
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: node-exporter
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: node-exporter
subjects:
- kind: ServiceAccount
  name: node-exporter-sa
  namespace: monitoring
```

**2. Использование в DaemonSet:**

```yaml
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
      serviceAccountName: node-exporter-sa   # ← связываем агента с учёткой
      hostNetwork: true                      # доступ к метрикам хоста
      hostPID: true                          # Node Exporter смотрит процессы узла
      tolerations:
      - operator: Exists                     # запуск на всех узлах, включая control-plane
        effect: NoSchedule
      containers:
      - name: node-exporter
        image: quay.io/prometheus/node-exporter:latest
        args:
        - --path.procfs=/host/proc
        - --path.sysfs=/host/sys
        ports:
        - containerPort: 9100
```

**Проверка (Validation):** после применения убедитесь, что привилегии агента минимальны и ошибок RBAC нет:

```bash
kubectl -n monitoring get ds           # → NAME  DESIRED  CURRENT  READY  UP-TO-DATE  AVAILABLE
# → node-exporter    3       3       3       3           3
kubectl -n monitoring logs ds/node-exporter --tail=20
# → смотрим: нет строк уровня error про "forbidden" / RBAC
kubectl auth can-i --list --as=system:serviceaccount:monitoring:node-exporter-sa
```

Принцип: выдавайте ровно те права, которые нужны конкретному агенту, а не `cluster-admin`. Например, лог-агент с доступом только на чтение `pods/log`, `nodes`, `events`, но не на создание объектов. Подробнее о модели — в [RBAC: роли](../Security/rbac/roles.md).

## Операции и диагностика

### Справочник kubectl для DaemonSet

```bash
# Список DaemonSet с ключевыми статусными колонками
kubectl get daemonsets
# → NAME            DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR   AGE
# → node-exporter   3         3         3       3            3           <none>          5m

# Подробный статус: условия, события, конфликты планировщика
kubectl describe daemonset <name>

# Манифест в YAML (например, для сужения селектора при canary-раскатке)
kubectl get ds <name> -o yaml

# Поды конкретного DaemonSet по всем узлам
kubectl get pods --selector=<selector> -o wide

# Проверить, что под развёрнут на конкретном узле
kubectl get pods -o wide --field-selector spec.nodeName=<node>

# Обновить образ без копипасты: отредактировать live-объект
kubectl edit ds <name>
```

Ключевые поля секции `status` в выводе `kubectl get ds -o yaml` (их стоит понимать при диагностике):

| Поле статуса | Значение |
| :--- | :--- |
| `currentNumberScheduled` | Сколько подов сейчас размещено на узлах, где они должны быть. |
| `desiredNumberScheduled` | Сколько подов должно быть (число подходящих узлов). |
| `numberMisscheduled` | Поды, оказавшиеся на узлах, где их быть не должно (например, из-за ошибки в `nodeSelector` до применения).
| `numberAvailable` / `numberReady` | Поды в состоянии Available/Ready. |
| `numberUnavailable` | `desiredNumberScheduled - numberAvailable` (должно быть 0 после выкатки). |
| `updatedNumberScheduled` | Поды, переведённые на актуальную ревизию шаблона. |
| `numberUnavailable` != 0 | Признак незавершённой или заблокированной выкатки. |

### Управление выкаткой (Rollout)

Основные команды для управления жизненным циклом DaemonSet:

```bash
# Просмотр статуса обновления
kubectl rollout status ds/logging-agent

# Просмотр истории ревизий (ControllerRevisions)
kubectl rollout history ds/logging-agent

# Откат к предыдущей версии
kubectl rollout undo ds/logging-agent --to-revision=2

# Перезапуск всех подов DaemonSet (полезно для обновления секретов/ConfigMap)
kubectl rollout restart ds/logging-agent
```

Это не блокирующая команда: она создаёт новую ревизию (через аннотацию `kubectl.kubernetes.io/restartedAt` на шаблоне), и контроллер последовательно пересоздаёт поды согласно `updateStrategy`. Для проверки завершения используйте `kubectl rollout status`.

### Типичные проблемы и их решение

Ниже — расширенный чек-лист диагностики. Начинайте всегда с `kubectl describe daemonset <name>` (события и причины) и `kubectl get events` по namespace.

| Симптом | Вероятные причины | Диагностика и решение |
| :--- | :--- | :--- |
| Узлы Ready, но поды не создаются | Taints/Tolerations не совпадают; `nodeSelector`/`nodeAffinity` не матчатся ни с одним узлом | `kubectl describe node <node>` — посмотреть `Taints`. Сверьте с `tolerations` и `nodeSelector` в манифесте. Узел должен либо не иметь запрещающего taint, либо иметь подходящую `toleration`. |
| Поды создаются, но в `Pending` / `FailedCreate` в событиях при `kubectl create` — ошибки планировщика | Недостаточно ресурсов (CPU/mem) на узле под `resources.requests`; несовместимость `affinity` | `kubectl describe pod <ds-pod>` — в разделе `Events` будет причина (`Insufficient cpu`, `0/3 nodes are available`). Проверьте `resources` в DS. |
| `CrashLoopBackOff` | Нехватка прав (RBAC `forbidden`), конфликт `hostPort`, отсутствие mount-пути на хосте, битый контейнер | `kubectl logs <ds-pod>` + `kubectl describe pod <ds-pod>`. Проверьте права ServiceAccount, занятость порта (`ss -ltnp` на узле), корректность `hostPath`. |
| Обновление «зависло» (полностью/частично) | Слишком жёсткий `maxUnavailable`; узел в `notReady`; проблема на конкретном узле блокирует прогресс | `kubectl get ds -o yaml` → сравните `desired=updated` и `numberUnavailable`. Ослабьте `maxUnavailable`/добавьте `maxSurge`. Проверьте статус узла. |
| Под не развёрнут на новом узле | Новый узел не проходит селектор (метка отсутствует); нет ресурсов; узел в Maintenance | Проверьте метки нового узла (`kubectl get node --show-labels`), наличие `resources.requests` и состояние узла. DaemonSet реагирует на появление/исчезновение меток узла автоматически. |
| Поды «не там»: `numberMisscheduled > 0` | Устаревший/широкий `nodeSelector` до применения | Перепроверьте `kubectl get ds -o yaml` и селектор пода. Обычно временно, пока DaemonSet не перезапущен. |
| Ошибка создания пода `Forbidden` | Отсутствует разрешение в RBAC у ServiceAccount | `kubectl auth can-i` и решение из раздела про RBAC выше. |
| После `drain` агент исчез с узла | Пропущен флаг `--ignore-daemonsets` при drain | При корректном `drain --ignore-daemonsets` поды DaemonSet остаются; иначе контроллер пересоздаст их на том же узле после `uncordon`. |

Основные принципы: сначала смотрите `Events` (в `kubectl describe pod`/`daemonset`), затем логи контейнера, и только потом — конфигурацию планировщика, RBAC и ресурсы.

## Мониторинг и алертинг (SRE/DevOps)

Для DaemonSet важно отслеживать не «сколько реплик», а **полноту покрытия** (`desiredNumberScheduled`) и **актуальность версии** (`updatedNumberScheduled`). Отсутствие агента на одном узле часто незаметно, пока не потеряешь телеметрию именно с него.

### Метрики (kube-state-metrics)

`kube-state-metrics` (часть kube-prometheus-stack) публикует метрики с префиксом `kube_daemonset_`:

| Метрика | Назначение |
| :--- | :--- |
| `kube_daemonset_status_desired_number_scheduled` | Сколько подов должно быть (`desired`). |
| `kube_daemonset_status_current_number_scheduled` | Сколько размещено сейчас. |
| `kube_daemonset_status_number_ready` | Готовые к работе. |
| `kube_daemonset_status_number_available` | Доступные (Ready и прошедшие `minReadySeconds`). |
| `kube_daemonset_status_number_unavailable` | `desired - available`; **ключевая метрика для алерта**. |
| `kube_daemonset_status_number_misscheduled` | Поды «не там» (проблемы селектора). |
| `kube_daemonset_status_updated_number_scheduled` | Поды на актуальной ревизии. |
| `kube_daemonset_metadata_generation` | Поколение шаблона (растёт с каждой правкой). |

### Практический алерт (Prometheus)

Типовое правило — сигнализировать, когда агент недоступен на одном или нескольких узлах дольше заданного времени:

```yaml
groups:
- name: daemonsets
  rules:
  - alert: DaemonSetNotCovered
    expr: |
      kube_daemonset_status_number_unavailable{namespace!=""} > 0
        and on(namespace, daemonset)
      kube_daemonset_status_desired_number_scheduled{namespace!=""} > 1
    for: 15m
    labels:
      severity: warning
    annotations:
      summary: "DaemonSet {{ $labels.namespace }}/{{ $labels.daemonset }} не покрывает все узлы"
      description: "{{ $value }} подов DaemonSet недоступны (желательно: {{ $labels.desired }})"

  - alert: DaemonSetNotScheduled
    expr: |
      (kube_daemonset_status_number_misscheduled > 0)
    for: 15m
    labels:
      severity: warning
    annotations:
      summary: "Поды DaemonSet размещены не на тех узлах"
```

Почему важно `desired > 1`: на одноузловых кластерах (например, тестовых) значение `numberUnavailable` может постоянно быть `1` из-за особенностей хоста, что даст ложные срабатывания.

**Проверка вручную (Validation)** без Prometheus:

```bash
# У всех DaemonSet желаемое число должно совпадать с доступным
kubectl get ds -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,DESIRED:.status.desiredNumberScheduled,AVAILABLE:.status.numberAvailable,UNAVAILABLE:.status.numberUnavailable,UPDATED:.status.updatedNumberScheduled
# → если в колонке UNAVAILABLE 0 и DESIRED=UP-TO-DATE — выкатка завершена
```

Детальный мониторинг кластера и дашборды — в разделе [Kubernetes Monitoring & Logging](../MonitoringLogging/kubernetes-monitoring-logging-architecture.md).

### Контроль выкатки в CI/CD

При раскатке DaemonSet в пайплайне (ArgoCD, скрипты) дожидайтесь завершения через rollout, а не по `kubectl apply`:

```bash
kubectl rollout status ds/<name> --timeout=300s
# → daemon set "node-exporter" successfully rolled out
```

Не ставьте алерт на непостоянные отклонения во время плановой выкатки — используйте `for: 15m` и учитывайте, что отдельные поды обновляются последовательно.

## Дополнительная информация

### Рекомендации (Best Practices)

1.  **Priority Classes:** Системные DaemonSet (CNI, DNS) должны использовать `system-node-critical`, а вспомогательные (логи) — `system-cluster-critical`.
2.  **Обновление maxUnavailable:** Для больших кластеров устанавливайте `maxUnavailable: 10%`, чтобы ускорить процесс выкатки; для критичных сервисов — `maxUnavailable: 0` + `maxSurge: 1`.
3.  **Использование NodeAffinity:** Используйте `spec.template.spec.affinity.nodeAffinity` для более гибкого выбора узлов вместо `nodeSelector`.
4.  **События и дренаж:** При выполнении `kubectl drain` поды DaemonSet игнорируются. Для их принудительного удаления используйте флаг `--ignore-daemonsets`.
5.  **Immutable-имейджи агентов:** Используйте фиксированные теги образов (не `:latest`) для системных агентов — они критичны и должны быть воспроизводимы; обновление выполняйте намеренно через rollout.
6.  **Не забывайте про ресурсы:** Всегда задавайте `resources.requests` и `limits` для агентов. Предсказуемое потребление позволяет планировщику корректно размещать поды даже на небольших узлах.
7.  **RBAC по минимуму:** Для агентов с доступом к API создавайте отдельный ServiceAccount с точечными правами (решение из раздела выше), никогда — `cluster-admin` по умолчанию.
8.  **Наблюдайте за покрытием:** Настройте алерт на `numberUnavailable` и `numberMisscheduled` — «тихая» потеря агента на одном узле обходится дороже всего.

### См. также

*   **[Обслуживание узлов (Cordon/Drain)](../Operations/node_maintenance.md)** — как DaemonSet ведёт себя при выводу узла в обслуживание.
*   **[Taints и Tolerations](../Scheduling/taints_and_tolerations.md)** — механизмы размещения и исключения, стандартные taints.
*   **[RBAC: роли](../Security/rbac/roles.md)** — настройка прав системных агентов.
