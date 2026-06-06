# DaemonSet

## Определения

**DaemonSet** — это контроллер в Kubernetes, который обеспечивает запуск ровно одного экземпляра пода (**Pod**) на каждом узле кластера (или на определенном наборе узлов). При добавлении нового узла в кластер контроллер автоматически разворачивает на нем под, а при удалении узла — корректно удаляет соответствующий экземпляр.

В отличие от **Deployment**, в манифесте **DaemonSet** отсутствует поле `replicas`, так как количество копий напрямую зависит от количества доступных узлов.

## Основные концепции

### Ключевые сценарии использования

DaemonSet предназначен для развертывания системных сервисов и агентов, которые должны обеспечивать работу инфраструктуры на уровне каждого узла:

* **Сбор данных и логов:** агенты **Fluentd**, **Logstash**, **Promtail**.
* **Мониторинг инфраструктуры:** **Prometheus Node Exporter**, агенты **Datadog** или **Zabbix**.
* **Сетевое взаимодействие:** плагины **CNI (Container Network Interface)**, такие как Calico, Cilium или Flannel.
* **Управление хранилищами:** драйверы для **Ceph** или **GlusterFS**.

### Взаимодействие с сервисами

Как правило, для **DaemonSet** не создают стандартный объект **Service** с типом **ClusterIP** или **LoadBalancer**. Системные агенты обычно сами инициируют отправку данных в центральную систему (например, в стек **Loki** или **Prometheus**) и не требуют входящих соединений от других подов.

В отличие от **StatefulSet**, для **DaemonSet** не предусмотрен механизм **Headless Service** для обращения к конкретным экземплярам по именному шаблону.

### Стратегии обновления

Управление процессом обновления подов осуществляется через поле `spec.updateStrategy.type`:

1. **`RollingUpdate` (по умолчанию):** постепенное обновление. Старый под удаляется, и только после этого создается новый на том же узле. Параметр `maxUnavailable` (по умолчанию 1) определяет, какое количество подов может быть недоступно одновременно в процессе обновления.
2. **`OnDelete`:** автоматическое обновление не происходит. После изменения манифеста администратор должен вручную удалить старые поды, чтобы контроллер создал новые с обновленной конфигурацией. Это полезно для критически важных агентов, где требуется полный контроль над процессом.

### Поведение при обслуживании узлов (Cordon)

Команда `kubectl cordon` помечает узел как недоступный для планирования новых задач, добавляя специальный **Taint** (ограничение): `node.kubernetes.io/unschedulable:NoSchedule`.

**DaemonSet** игнорирует это ограничение по умолчанию. Контроллер автоматически добавляет подам встроенные **Tolerations** (допуски) для этого ограничения. Это гарантирует, что системные агенты (мониторинг, сеть) продолжат работу на узле даже во время его обслуживания или вывода из эксплуатации.

## Практические сценарии

### Пример базового манифеста

Манифест описывает запуск прокси-сервера на каждом узле.

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: edge-proxy
  namespace: infrastructure
spec:
  selector:
    matchLabels:
      app: edge-proxy
  template:
    metadata:
      labels:
        app: edge-proxy
    spec:
      containers:
      - name: traefik
        image: traefik:v3.1
        ports:
        - containerPort: 80
          name: http
```

### Развертывание агента сбора логов (Fluentd)

В данном примере используются допуски для запуска на мастер-узлах и монтирование директорий хоста.

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluentd-agent
  namespace: logging
  labels:
    app: fluentd
spec:
  selector:
    matchLabels:
      app: fluentd
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
  template:
    metadata:
      labels:
        app: fluentd
    spec:
      # Запуск только на узлах с определенной ОС (Operating System)
      nodeSelector:
        kubernetes.io/os: linux
      # Разрешение запуска на мастер-узлах (Control Plane)
      tolerations:
      - key: "node-role.kubernetes.io/master"
        operator: "Exists"
        effect: "NoSchedule"
      - key: "node-role.kubernetes.io/control-plane"
        operator: "Exists"
        effect: "NoSchedule"
      containers:
      - name: fluentd
        image: fluent/fluentd:v1.16
        resources:
          limits:
            memory: 512Mi
          requests:
            cpu: 100m # CPU (Central Processing Unit)
            memory: 256Mi
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

### Гарантированный запуск до подов приложений

Для критических компонентов (например, CNI-плагинов) используется паттерн отложенного запуска:

1. Узел помечается как `NotReady` или с кастомным `Taint`.
2. **DaemonSet** имеет `Toleration` к этому ограничению и запускается первым.
3. После готовности агента (например, настройки сети), ограничение снимается, и планировщик начинает размещать прикладные поды.

## Дополнительная информация

* **[Безопасность подов (Security Context)](../Security/pod_security_context.md)** — настройка прав доступа.
* **[Жизненный цикл пода (Pod Lifecycle)](./Pod/pod_lifecycle_and_state.md)** — стадии работы контейнеров.
* **[Taints and Tolerations](../Scheduling/taints_and_tolerations.md)** — детальное описание механизмов размещения.
* **[NodeLocalDNS](../Networking/dns_deep_dive.md#принцип-работы-nodelocaldns)** — пример реализации системного DaemonSet.
