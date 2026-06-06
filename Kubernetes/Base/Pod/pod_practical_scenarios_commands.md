# Практические сценарии и команды управления Pod

## Определения

**kubectl** — интерфейс командной строки для управления кластерами Kubernetes. Взаимодействует с API (Application Programming Interface) сервером для управления ресурсами.

**Императивный подход** — способ управления, при котором команды отдаются напрямую (например, `kubectl run`). Каждая команда описывает конкретное действие ("создай этот объект").

**Декларативный подход** — способ управления через файлы конфигурации (манифесты). Пользователь описывает желаемое состояние (например, через `kubectl apply`), а Kubernetes сам приводит систему к этому состоянию. Это основа методологии IaC (Infrastructure as Code — инфраструктура как код).

---

## Базовые концепции

### kubectl apply против kubectl create

Выбор между декларативным и императивным методами создания объектов.

| Команда | Характер | Поведение | Применение |
| :--- | :--- | :--- | :--- |
| `kubectl create` | Императивный | Создает объект. Если объект уже существует — возвращает ошибку. | Быстрое тестирование, создание ресурсов из CLI (Command Line Interface). |
| `kubectl apply` | Декларативный | Создает или обновляет объект на основе файла. Хранит историю изменений. | **Рекомендуемый метод** для Production, CI/CD (Continuous Integration / Continuous Deployment). |

**Аннотация `last-applied-configuration`:** При использовании `kubectl apply` в метаданных объекта сохраняется JSON (JavaScript Object Notation) копия последней примененной конфигурации. Это позволяет Kubernetes вычислять разницу (diff) между текущим и новым состоянием.

### Цикл диагностики Pod

При возникновении проблем с Pod (подом) рекомендуется следовать стандартному алгоритму:

1. **`kubectl get pods`**: Проверка общей фазы и статуса.
2. **`kubectl describe pod`**: Анализ событий (Events) и условий (Conditions) для поиска инфраструктурных ошибок.
3. **`kubectl logs`**: Просмотр вывода приложения (stdout/stderr) для поиска внутренних ошибок кода.

---

## Практические сценарии

### Сценарий 1: Базовое управление жизненным циклом

Создание, просмотр и удаление ресурсов.

```bash
# Создание или обновление Pod из манифеста
kubectl apply -f my-pod.yaml

# Просмотр списка Pod в текущем Namespace (пространстве имен)
kubectl get pods

# Просмотр Pod с расширенной информацией (IP, Node)
kubectl get pods -o wide

# Удаление Pod
kubectl delete pod my-pod-name
```

### Сценарий 2: Многоконтейнерный Pod и взаимодействие через localhost

Container (контейнеры) внутри одного Pod разделяют сетевое пространство (Network Namespace), что позволяет им взаимодействовать через `localhost`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: sidecar-demo
spec:
  containers:
  - name: app
    image: my-app:1.0
    ports:
    - containerPort: 8080
  - name: sidecar-proxy
    image: nginx:alpine
    # Проксирование трафика на 127.0.0.1:8080
```

**Логирование в многоконтейнерных Pod:**
При наличии нескольких container необходимо явно указывать имя через флаг `-c`.

```bash
kubectl logs sidecar-demo -c sidecar-proxy
```

### Сценарий 3: Глубокая диагностика и отладка

Инструменты для анализа работающих приложений.

| Действие | Команда |
| :--- | :--- |
| **События и ошибки** | `kubectl describe pod <name>` |
| **Логи (Real-time)** | `kubectl logs -f <name>` |
| **Логи после краша** | `kubectl logs <name> --previous` |
| **Интерактивный shell** | `kubectl exec -it <name> -- /bin/sh` |
| **Копирование файлов** | `kubectl cp <name>:/tmp/log.txt ./log.txt` |

Подробности о фазах и условиях см. в [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md).

### Сценарий 4: Отладка через Ephemeral Containers

Если в основном образе нет оболочки (например, Distroless-образы), используются временные отладочные контейнеры.

```bash
kubectl debug -it <pod-name> --image=busybox:1.36 --target=<container-name>
```

Полное руководство: [Эфемерные контейнеры](./ephemeral_containers.md).

### Сценарий 5: Использование селекторов меток (Label Selectors)

Метки позволяют группировать объекты и выполнять массовые операции.

```bash
# Получение Pod по конкретной метке
kubectl get pods -l app=frontend

# Получение Pod по нескольким условиям (логическое И)
kubectl get pods -l 'app=frontend,tier=backend'

# Использование операторов (In, NotIn)
kubectl get pods -l 'environment in (production, staging)'

# Массовое удаление по метке
kubectl delete pods -l tier=testing
```

Подробнее о метаданных см. в [Метаданные, метки и аннотации](../../Concepts/metadata_and_labels.md).

---

## Дополнительная информация

**Связанные темы:**

- [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — детальный разбор фаз и условий.
- [Перезапуск Pod в Kubernetes](./pod_restarts.md) — различие между перезапуском и пересозданием.
- [Пробы в Kubernetes](../probes.md) — механизмы `liveness` и `readiness`.
- [Graceful Shutdown (корректное завершение)](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md) — процедура остановки.
- [Метки, аннотации и выбор узлов](./pod_labels_annotations_node_selection.md) — продвинутое управление метаданными.
