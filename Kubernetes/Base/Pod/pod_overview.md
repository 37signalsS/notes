# Pod в Kubernetes: Обзор

## Определения

**Pod (под)** — наименьшая и простейшая развёртываемая единица в Kubernetes. Это атомарная единица планирования: группа из одного или нескольких container (контейнеров), гарантированно размещаемых на одном Node (узле/ноде), будь то физическая или виртуальная машина.

**Эфемерность Pod** — Pod не обладают механизмом самовосстановления. При сбое Node или завершении процесса объект Pod не восстанавливается автоматически; за его жизненный цикл отвечают контроллеры.

**Pause-container (пауз-контейнер)** — инфраструктурный container, создаваемый первым при старте Pod. Он создаёт сетевой Namespace (пространство имён) и удерживает его, пока работают основные container. Все container внутри Pod присоединяются к этому сетевому пространству.

---

## Базовые концепции

### Ключевые характеристики Pod

| Характеристика | Описание |
| :--- | :--- |
| **Атомарность планирования** | Невозможно запустить container одного Pod на разных Node |
| **Со-локация (co-location)** | Container в Pod работают в общей "песочнице" и разделяют ключевые ресурсы |
| **Единый IP-адрес** | У Pod один IP (Internet Protocol) адрес, общий для всех container |
| **Общий localhost** | Container взаимодействуют между собой через `localhost` |
| **Общее пространство портов** | Два container в одном Pod не могут использовать один и тот же порт |

### Общие ресурсы контейнеров в поде

| Ресурс | Описание |
| :--- | :--- |
| **Сеть (Network Namespace)** | Единый IP-адрес на все container, общий `localhost`, общее пространство портов. Каждый container должен слушать уникальный порт. |
| **Хранилище (Volumes)** | Pod назначается набор томов; каждый container монтирует их через `volumeMounts`. Все container могут читать и писать в общие тома. |
| **IPC Namespace** | Container используют механизмы IPC (Inter-Process Communication), такие как семафоры и разделяемая память, для взаимодействия без сетевых вызовов. |

### Pod Template (шаблон пода)

**Pod Template** — спецификация для создания Pod, используемая высокоуровневыми контроллерами (Deployment, Job, StatefulSet, DaemonSet). Контроллеры включают шаблон Pod (`spec.template`) в свою спецификацию для обеспечения **желаемого состояния**.

**Механика работы Pod Template:**

| Аспект | Описание |
| :--- | :--- |
| **Определение** | Часть спецификации контроллера, описывающая конфигурацию будущих Pod |
| **Гарантия соответствия** | Контроллер обеспечивает соответствие запущенных Pod текущему шаблону |
| **Уникальность имён** | При создании Pod из шаблона контроллер добавляет хэш-суффикс для уникальности |
| **Инстанцирование** | Все параметры, указанные в шаблоне, применяются к каждому созданному Pod |

**Пример Pod Template в Job:**

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: hello-job
spec:
  template:  # ← Pod Template начинается здесь
    metadata:
      labels:
        app: hello-job
    spec:
      containers:
      - name: hello
        image: busybox:1.28
        command: ["sh", "-c", "echo Hello Kubernetes && sleep 3600"]
      restartPolicy: OnFailure
```

**Важно:** Pod, созданные из шаблона, получают уникальные имена (например, `hello-job-abc123`). Сам контроллер сохраняет своё статичное имя.

### Управление и обновление

**Способы редактирования:**

| Способ | Описание | Рекомендация |
| :--- | :--- | :--- |
| **Файлы (IaC)** | Изменения в манифесте → `kubectl apply -f` | **Рекомендуемый подход** |
| **Напрямую в кластере** | `kubectl edit <тип> <имя>` | Не рекомендуется (риск рассинхрона) |

**Механизм обновления:**
При изменении поля `pod template` в контроллере, старые Pod не обновляются "на лету". Вместо этого контроллер создаёт **новые Pod** с обновлённой спецификацией и постепенно удаляет старые (в зависимости от стратегии).

### Эфемерность и роль контроллеров

Поскольку Pod эфемерны, для управления ими используются высокоуровневые контроллеры, обеспечивающие orchestration (оркестрацию), самовосстановление и масштабирование:

| Контроллер | Назначение |
| :--- | :--- |
| [Deployment](../Deployment/index.md) | Приложения без сохранения состояния (stateless) |
| [StatefulSet](../StatefulSet/statefulset_core_concepts.md) | Приложения с сохранением состояния (stateful) |
| [DaemonSet](../daemonset.md) | Запуск Pod на каждом Node кластера (агенты, логи) |
| [Job](../job.md) | Одноразовые задачи и вычисления |

### Структура манифеста Pod

Для описания Pod используются декларативные манифесты в формате YAML или JSON.

| Поле | Описание | Пример |
| :--- | :--- | :--- |
| `apiVersion` | Версия API (Application Programming Interface) | `v1` |
| `kind` | Тип ресурса | `Pod` |
| `metadata` | Данные для идентификации | `name`, `labels`, `namespace` |
| `spec` | Описание желаемого состояния | Container, Volumes, ресурсы |

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: example-pod
  labels:
    app: web
spec:
  containers:
    - name: web-container
      image: nginx:1.25.0
      ports:
        - containerPort: 80
```

---

## Практические сценарии

### Пример 1: Multi-container Pod с общим хранилищем

Совместное использование данных несколькими container в одном Pod:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: storage-demo
spec:
  volumes:
  - name: shared-vol
    emptyDir: {}
  containers:
  - name: producer
    image: busybox
    command: ["sh", "-c", "echo 'shared data' > /data/info.txt"]
    volumeMounts:
    - name: shared-vol
      mountPath: /data
  - name: consumer
    image: busybox
    command: ["sh", "-c", "cat /data/info.txt"]
    volumeMounts:
    - name: shared-vol
      mountPath: /data
```

### Пример 2: Sidecar-паттерн

Использование вспомогательного container для обработки логов основного приложения:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: sidecar-example
spec:
  containers:
  - name: main-app
    image: nginx:1.25.0
    volumeMounts:
    - name: logs
      mountPath: /var/log/nginx
  - name: log-collector
    image: busybox
    command: ["sh", "-c", "tail -f /var/log/nginx/access.log"]
    volumeMounts:
    - name: logs
      mountPath: /var/log/nginx
  volumes:
  - name: logs
    emptyDir: {}
```

### Пример 3: Init-контейнеры

Подготовка среды перед запуском основных container:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: init-demo
spec:
  initContainers:
  - name: wait-service
    image: busybox
    command: ["sh", "-c", "until nc -z db-service 5432; do sleep 1; done"]
  containers:
  - name: app
    image: my-app:latest
```

---

## Дополнительная информация

**Связанные темы:**

- [Рекомендации по написанию манифестов Pod](./pod_best_practices.md)
- [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md)
- [Sidecar Patterns в Kubernetes](./pod_sidecar_patterns.md)
- [Инициализирующие контейнеры](./pod_init_containers.md)
