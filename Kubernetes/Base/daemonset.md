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

## Операции и диагностика

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

### Типичные проблемы и их решение

- **Узлы в состоянии Ready, но поды не запускаются:** Проверьте `Taints` на узлах и `Tolerations` в манифесте DS.
- **Поды постоянно перезапускаются (CrashLoopBackOff):** Часто связано с нехваткой прав (RBAC) или конфликтом портов при использовании `hostPort`.
- **Обновление «зависло»:** Проверьте параметры `maxUnavailable`. Если они слишком жесткие, а узлы имеют проблемы, обновление может остановиться.
- **DaemonSet не запускается на новых узлах:** Проверьте наличие `resources.requests`. Если узел слишком мал, планировщик не сможет разместить там системный под.

## Дополнительная информация

### Рекомендации (Best Practices)

1.  **Priority Classes:** Системные DaemonSet (CNI, DNS) должны использовать `system-node-critical`, а вспомогательные (логи) — `system-cluster-critical`.
2.  **Обновление maxUnavailable:** Для больших кластеров устанавливайте `maxUnavailable: 10%`, чтобы ускорить процесс выкатки.
3.  **Использование NodeAffinity:** Используйте `spec.template.spec.affinity.nodeAffinity` для более гибкого выбора узлов вместо `nodeSelector`.
4.  **События и дренаж:** При выполнении `kubectl drain` поды DaemonSet игнорируются. Для их принудительного удаления используйте флаг `--ignore-daemonsets`.

### См. также

*   **[Безопасность подов (Security Context)](../Security/pod_security_context.md)** — настройка прав для системных агентов.
*   **[Жизненный цикл пода (Pod Lifecycle)](./Pod/pod_lifecycle_and_state.md)** — стадии работы и Graceful Shutdown.
*   **[Taints и Tolerations](../Scheduling/taints_and_tolerations.md)** — механизмы размещения и исключения.
*   **[NodeLocalDNS](../Networking/dns_deep_dive.md#принцип-работы-nodelocaldns)** — пример реализации системного DaemonSet.
