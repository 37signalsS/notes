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

### Стратегии обновления и Rollout

Управление процессом обновления подов осуществляется через поле `spec.updateStrategy`:

1.  **`RollingUpdate` (по умолчанию):** Постепенное обновление.
    *   **`maxUnavailable`**: Количество подов, которые могут быть недоступны в процессе обновления (по умолчанию `1`).
    *   **`maxSurge` (GA v1.25):** Позволяет запустить новый под на узле *рядом* со старым. Это полезно, если нужно дождаться готовности нового агента перед убийством старого, минимизируя «слепое пятно» в мониторинге или логах. При значении `1` на время обновления на узле будут работать два пода.
2.  **`OnDelete`:** Автоматическое обновление не происходит. Контроллер создаст новый под только после того, как администратор вручную удалит старый. Это критически важно для сетевых плагинов, где бесконтрольный рестарт может привести к кратковременному разрыву связи во всем кластере.

### Механизмы планирования и обслуживания (Cordon/Drain)

**Scheduling:** С версии 1.17 DaemonSet планируется стандартным планировщиком (**kube-scheduler**). Это означает, что он полностью учитывает **Node Affinity**, **Taints** и **PriorityClasses**.

**Поведение при обслуживании (Cordon):**
Когда узел помечается как `unschedulable` (через `kubectl cordon`), на него накладывается Taint `node.kubernetes.io/unschedulable:NoSchedule`. DaemonSet автоматически добавляет подам **Tolerations** для этого ограничения. Это гарантирует, что системные агенты продолжат работу на узле, пока на нем остаются прикладные поды, требующие мониторинга или сети.

## Практические сценарии

### Упрощенный пример агента регистрации

Минимальный манифест для обеспечения присутствия агента на каждом узле:

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: logging-agent
  labels:
    app: logging
spec:
  selector:
    matchLabels:
      name: logging-agent
  template:
    metadata:
      labels:
        name: logging-agent
    spec:
      containers:
      - name: logging-agent
        image: logging-agent:v1
```

### Развертывание агента Fluentd (с допуском для мастер-узлов)

Пример конфигурации для сбора логов, который должен запускаться на всех узлах, включая Master/Control-Plane.

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
      # Защита от вытеснения при нехватке ресурсов
      priorityClassName: system-node-critical
      # Допуски для работы на мастер-узлах
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

### Гарантированный запуск до подов приложений (CNI Pattern)

Для сетевых плагинов используется механизм `InitContainers` или специализированные Taints:
1.  Узел стартует с Taint `node.kubernetes.io/network-unavailable:NoSchedule`.
2.  DaemonSet CNI-плагина имеет Toleration к этому Taint.
3.  Плагин запускается, настраивает сеть и удаляет Taint с узла.
4.  Только после этого планировщик начинает размещать обычные приложения.

### Альтернатива DaemonSet: Pod Anti-Affinity в Deployment

Иногда требуется запустить приложение «по одному на узел», но с фиксированным количеством копий (например, кэширующий прокси).

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
**Сравнение:**
*   **Deployment + Anti-Affinity:** Если в кластере 10 узлов, а `replicas: 3`, приложение будет только на 3 узлах. При добавлении 11-го узла ничего не изменится.
*   **DaemonSet:** Приложение будет на всех 10 (и затем 11) узлах автоматически.

## Дополнительная информация

### Рекомендации (Best Practices)

1.  **Priority Classes:** Системные DaemonSet (CNI, DNS) должны использовать `system-node-critical`, а вспомогательные (логи) — `system-cluster-critical`. Это предотвратит их удаление (eviction) при нехватке ресурсов ради прикладных подов.
2.  **Обновление maxUnavailable:** Для больших кластеров устанавливайте `maxUnavailable: 10%`, чтобы ускорить процесс выкатки новой версии.
3.  **Использование NodeAffinity:** Используйте `spec.template.spec.affinity.nodeAffinity` вместо устаревшего `nodeSelector` для более гибкого выбора узлов (например, запуск только на узлах с GPU или SSD).
4.  **События и дренаж:** При выполнении `kubectl drain` поды DaemonSet игнорируются. Для их принудительного удаления (если они используют `emptyDir`) используйте флаг `--ignore-daemonsets`.

### См. также

*   **[Безопасность подов (Security Context)](../Security/pod_security_context.md)** — настройка прав для системных агентов.
*   **[Жизненный цикл пода (Pod Lifecycle)](./Pod/pod_lifecycle_and_state.md)** — стадии работы и Graceful Shutdown.
*   **[Taints и Tolerations](../Scheduling/taints_and_tolerations.md)** — глубокое погружение в механизмы размещения.
*   **[NodeLocalDNS](../Networking/dns_deep_dive.md#принцип-работы-nodelocaldns)** — пример реализации системного DaemonSet.
