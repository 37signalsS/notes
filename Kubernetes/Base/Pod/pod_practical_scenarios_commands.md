# Pod: Практические сценарии и команды kubectl

## Определения

**Императивная команда** — команда kubectl, создающая объект напрямую (например, `kubectl create`). Если объект существует, команда завершится ошибкой.

**Декларативная команда** — команда kubectl, применяющая конфигурацию из файла (например, `kubectl apply`). Создает объект или обновляет существующий.

**Ephemeral Container** — временный отладочный контейнер, добавляемый в работающий Pod без его перезапуска.

---

## Базовые концепции

### kubectl apply vs kubectl create

| Команда | Описание | Когда использовать |
| :--- | :--- | :--- |
| `kubectl create` | Императивная команда. Создает объект с нуля. При наличии объекта вернет ошибку | Одноразовое создание, скрипты, dev-среда |
| `kubectl apply` | Декларативная команда. Применяет конфигурацию из файла. Создает или обновляет объект | **Предпочтительный способ** для production, CI/CD, GitOps |

**Ключевое отличие:** `kubectl apply` хранит последнюю примененную конфигурацию в аннотации `kubectl.kubernetes.io/last-applied-configuration`. Это позволяет отслеживать изменения и применять только дельту при следующем вызове.

### Диагностика проблем с Pod

Две основные команды для отладки:

| Команда | Назначение |
| :--- | :--- |
| `kubectl describe pod` | Подробная сводка состояния пода с событиями |
| `kubectl logs` | Вывод stdout/stderr процессов в контейнере |

---

## Практические сценарии

### Пример 1: Базовый манифест Pod

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

### Пример 2: Multi-container Pod с взаимодействием через localhost

Два контейнера в одном поде используют общее сетевое пространство:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: multi-container-demo
spec:
  containers:
  - name: web-server
    image: my-date-server:1.0
    ports:
      - containerPort: 5005
  - name: client
    image: busybox:1.36.1
    command: ['sh', '-c', 'while true; do wget -q -O- http://localhost:5005/date; sleep 5; done']
```

**Как это работает:**

- Контейнер `client` обращается к `web-server` через `http://localhost:5005`
- Просмотр логов: `kubectl logs multi-container-demo -c client` и `kubectl logs multi-container-demo -c web-server`

### Пример 3: Диагностика пода с проблемами

```bash
# Получить подробную информацию о поде с событиями
kubectl describe pod my-nginx-pod -n <namespace>

# Что смотреть в выводе:
# 1. Status — текущая фаза пода (Pending, Running, Failed)
# 2. Conditions — детали состояния (PodScheduled, Initialized, Ready)
# 3. Events — журнал событий (ошибки pull image, нехватка ресурсов, результаты проб)

# Посмотреть логи контейнера
kubectl logs my-pod-name

# Следить за логами в реальном времени
kubectl logs -f my-pod-name

# Логи для multi-container Pod (указать контейнер)
kubectl logs my-multi-container-pod -c main-app

# Логи init-контейнера
kubectl logs my-pod-with-init -c my-init-container

# Логи предыдущего экземпляра контейнера (после перезапуска)
kubectl logs my-pod-name --previous
```

Подробнее об init-контейнерах: [Init Containers](./pod_init_containers.md).
Подробнее о sidecar-паттернах: [Sidecar Patterns](./pod_sidecar_patterns.md).

### Пример 4: Отладка с помощью Ephemeral Containers

**Проблема:** В контейнере отсутствуют инструменты диагностики (`tcpdump`, `netstat`, `ps`) или distroless-образ без shell.

**Решение:** Добавить временный отладочный контейнер без перезапуска пода.

Полное руководство: **[Ephemeral Containers](./ephemeral_containers.md)**.

**Быстрый старт:**

```bash
# Базовая отладка — добавить ephemeral контейнер
kubectl debug -it pod/my-pod \
  --image=busybox:1.36.1 \
  --target=app-container
```

### Пример 5: Graceful Shutdown

Настройка корректного завершения работы пода. Полное описание процесса: **[Graceful Shutdown](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md)**.

**Ключевые параметры:**

- `terminationGracePeriodSeconds` — время на корректное завершение (по умолчанию 30с)
- `preStop` hook — выполняется до отправки SIGTERM (уведомление приложения, дренаж трафика)
- `readinessProbe` — при возврате 503 pod исключается из Service

**Порядок завершения:**

1. Kubernetes решает завершить pod
2. `preStop` hook + SIGTERM отправляются одновременно
3. `readinessProbe` возвращает ошибку → pod исключается из Service
4. Приложение завершает текущие запросы
5. По истечении grace period → SIGKILL

**Связанные темы:** [Пробы](../probes.md), [Жизненный цикл пода](./pod_lifecycle_and_state.md).

### Пример 6: Основные команды управления Pod

```bash
# Создать под из файла
kubectl apply -f pod.yaml

# Получить список подов
kubectl get pods

# Поды в конкретном namespace
kubectl -n <namespace> get pod

# Подробная информация о поде
kubectl describe pod my-nginx-pod

# Удалить под
kubectl delete pod my-nginx-pod

# Поды на конкретной ноде
kubectl get pod --field-selector spec.nodeName=<node-name>
```

### Пример 7: Использование меток (label selectors)

```bash
# Получить поды по метке
kubectl get pods -l app=frontend

# Получить все ресурсы в namespace по метке
kubectl get all -l environment=production

# Удалить ресурсы по метке
kubectl delete all -l environment=test

# Комбинированные селекторы
kubectl get pods -l 'app=web,environment in (staging,production)'

# Отрицание
kubectl get pods -l 'app!=backend'
```

---

## Дополнительная информация

**См. также:** [Жизненный цикл пода](./pod_lifecycle_and_state.md), [Ephemeral Containers](./ephemeral_containers.md), [Graceful Shutdown](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md).
