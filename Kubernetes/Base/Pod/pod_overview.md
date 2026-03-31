# Pod в Kubernetes: Обзор

## Определения

**Pod** — наименьшая и простейшая развёртываемая единица в Kubernetes. Атомарная единица планирования: группа из одного или нескольких контейнеров, гарантированно размещаемых на одной физической или виртуальной машине (ноде).

**Эфемерность подов** — поды не обладают механизмом самовосстановления. При выходе ноды из строя или завершении процесса под не восстанавливается автоматически.

**Pause-контейнер** — инфраструктурный контейнер, создаваемый первым при старте пода. Создаёт сетевое пространство имён (network namespace) и удерживает его, пока работают основные контейнеры. Все контейнеры пода присоединяются к этому сетевому пространству.

---

## Базовые концепции

### Ключевые характеристики Pod

| Характеристика | Описание |
| :--- | :--- |
| **Атомарность планирования** | Невозможно запустить контейнеры одного пода на разных нодах |
| **Со-локация (co-location)** | Контейнеры в поде работают в общей "песочнице" и разделяют ключевые ресурсы |
| **Единый IP-адрес** | У пода один IP-адрес, общий для всех контейнеров |
| **Общий localhost** | Контейнеры взаимодействуют через `localhost` |
| **Общее пространство портов** | Два контейнера в одном поде не могут слушать один порт |

### Общие ресурсы контейнеров в поде

| Ресурс | Описание |
| :--- | :--- |
| **Сеть (Network Namespace)** | Единый IP, общий `localhost`, общее пространство портов |
| **Хранилище (Volumes)** | Поду назначается набор томов; каждый контейнер монтирует тома через `volumeMounts` |
| **IPC Namespace** | Контейнеры используют механизмы IPC (семафоры, разделяемая память) для взаимодействия |

### Эфемерность и контроллеры

На практике поды редко создаются напрямую. Для управления подами используются **высокоуровневые контроллеры**, обеспечивающие самовосстановление и отказоустойчивость:

| Контроллер | Назначение |
| :--- | :--- |
| [Deployment](../Deployment/index.md) | Stateless-приложения |
| [StatefulSet](../StatefulSet/statefulset_core_concepts.md) | Stateful-приложения (базы данных, очереди) |
| [DaemonSet](../daemonset.md) | Запуск по одному поду на каждом узле (агенты мониторинга, сборщики логов) |

Контроллеры оборачивают шаблон пода (`template`) в свою спецификацию и обеспечивают **желаемое состояние**. При падении пода контроллер обнаруживает это и создаёт новый под взамен.

### Манифест пода

Для создания и управления ресурсами в Kubernetes используются **декларативные манифесты** — YAML/JSON-файлы, описывающие желаемое состояние.

**Структура манифеста:**

| Поле | Описание | Пример |
| :--- | :--- | :--- |
| `apiVersion` | Версия API Kubernetes | `v1` для Pod |
| `kind` | Тип объекта | `Pod` |
| `metadata` | Метаданные для идентификации | `name`, `labels`, `namespace` |
| `spec` | Спецификация желаемого состояния | Контейнеры, тома, сетевые настройки |

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: my-nginx-pod
  labels:
    app: web
spec:
  containers:
    - name: nginx-container
      image: nginx:1.28.0
      ports:
        - containerPort: 80
```

Полное руководство по созданию качественных манифестов см. в [Рекомендации по написанию манифестов Pod](./pod_best_practices.md).

---

## Практические сценарии

### Пример 1: Multi-container Pod с общим хранилищем

Два контейнера в одном поде используют общий том для обмена данными:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: multi-container-demo
spec:
  volumes:
  - name: shared-data
    emptyDir: {}
  containers:
  - name: producer
    image: busybox
    command: ["sh", "-c", "echo 'data' > /shared/data.txt"]
    volumeMounts:
    - name: shared-data
      mountPath: /shared
  - name: consumer
    image: busybox
    command: ["sh", "-c", "cat /shared/data.txt"]
    volumeMounts:
    - name: shared-data
      mountPath: /shared
```

### Пример 2: Sidecar-паттерн

Вспомогательный контейнер расширяет функциональность основного:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: web-with-logger
spec:
  containers:
  - name: web-server
    image: nginx:1.28.0
    ports:
    - containerPort: 80
  - name: log-shipper
    image: fluent/fluent-bit
    # Отправляет логи из общей директории в центральную систему
    command: ["fluent-bit", "-c", "/fluent-bit/etc/fluent-bit.conf"]
    volumeMounts:
    - name: varlog
      mountPath: /var/log
  volumes:
  - name: varlog
    emptyDir: {}
```

Подробнее о sidecar-паттерне см. в [Sidecar-паттерн](./pod_sidecar_pattern.md).

### Пример 3: Init-контейнеры для инициализации

Init-контейнеры выполняются до запуска основных контейнеров:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-with-init
spec:
  initContainers:
  - name: init-db
    image: busybox
    command: ["sh", "-c", "until nc -z db-service 5432; do sleep 2; done"]
  containers:
  - name: app
    image: my-app:1.0
    # Запускается только после успешного выполнения init-контейнера
```

---

## Дополнительная информация

**Связанные темы:** [Рекомендации по написанию манифестов](./pod_best_practices.md), [Жизненный цикл и состояния](./pod_lifecycle_and_state.md), [Sidecar-паттерн](./pod_sidecar_pattern.md), [Deployment](../Deployment/index.md), [StatefulSet](../StatefulSet/statefulset_core_concepts.md), [DaemonSet](../daemonset.md).
