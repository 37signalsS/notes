## Практические сценарии

## Пример манифеста Pod

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

  # nodeName: worker-node-1 # Можно жестко указать узел для запуска, но это не рекомендуется.
                           # Лучше использовать nodeSelector или affinity.
```

## Пример: Взаимодействие контейнеров в одном поде

Этот пример демонстрирует, как два контейнера (`web-server` и `client`) могут взаимодействовать внутри одного пода, используя общее сетевое пространство (`localhost`).

**Манифест пода:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: multi-container-demo
spec:
  containers:
  # 1. Контейнер с веб-сервером
  - name: web-server
    image: my-date-server:1.0 # Предполагается, что этот образ собран и доступен
    ports:
      - containerPort: 5005

  # 2. Контейнер-клиент
  - name: client
    image: busybox:1.36.1
    # Бесконечный цикл, который делает запросы к серверу
    command: ['sh', '-c', 'while true; do wget -q -O- http://localhost:5005/date; sleep 5; done']
```

**Как это работает:**

- Контейнер `client` может напрямую обращаться к `web-server` через `http://localhost:5005`.
- Посмотреть логи можно командами `kubectl logs multi-container-demo -c client` и `kubectl logs multi-container-demo -c web-server`.

## Настройка Graceful Shutdown

Grace period и lifecycle определяют, успеет ли сервис завершить работу корректно.

**Почему важно:** Срезанные запросы, потерянные сообщения, corrupted state и странные ошибки у клиентов при релизах/эвиктах.

```yaml
spec:
  terminationGracePeriodSeconds: 90  # Увеличено для запаса на graceful shutdown
  containers:
  - name: app
    lifecycle:
      preStop:
        exec:
          command:
          - /bin/sh
          - -c
          - |
            # 1. Сигнализируем приложению начать graceful shutdown
            # Например, через HTTP-эндпоинт или пользовательский сигнал
            curl -sf -X POST http://localhost:8080/prestop || true
            
            # 2. Короткая пауза, чтобы сигнал был обработан
            sleep 2
    # КРИТИЧЕСКИ ВАЖНО: Настроенные Readiness Probe!
    # Они заставят K8s немедленно исключить pod из Service
    readinessProbe: # Подробности см. в документе [Пробы (Probes)](./probes.md)
      httpGet:
        path: /health/ready
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 2  # Частая проверка для быстрого исключения
      failureThreshold: 1  # Одного провала достаточно
```

**Порядок действий при завершении работы пода:**

1. **Начало eviction:** Kubernetes решает завершить pod.
2. **Срабатывает preStop-хук:** Ваш скрипт отправляет сигнал приложению начать подготовку к завершению (например, перестать принимать новые соединения).
3. **Readiness Probe сразу проваливается:** Приложение, получив сигнал, начинает отвечать 503 на запросы к эндпоинту готовности (`/health/ready`). Kubelet видит это и мгновенно удаляет pod из Endpoints Service.
4. **Kubernetes отправляет SIGTERM:** После выполнения preStop-хука K8s отправляет `SIGTERM` процессу в контейнере. Ваше приложение должно быть готово его обработать.
5. **Grace period:** У приложения есть оставшееся время до `terminationGracePeriodSeconds` (90с), чтобы завершить текущие запросы и корректно выключиться.
6. **SIGKILL (если необходимо):** Если по истечении grace period процесс ещё жив, K8s отправляет `SIGKILL`.

## Отладка с помощью Ephemeral Containers при отсутствии инструментов диагностики и отладки

**Проблема:** Приложение в работающем Pod'е ведет себя некорректно, но в его контейнере отсутствуют необходимые инструменты для диагностики (`netstat`, `tcpdump`, `ps` и т.д.). Добавлять их в основной образ — плохая практика, так как это увеличивает его размер и поверхность атаки.

**Решение:** Использовать **Ephemeral Containers** (эфемерные контейнеры) — временные контейнеры, которые "внедряются" в уже запущенный Pod для отладки без его перезапуска.

**Пример: Добавление контейнера `busybox` для отладки**

```bash
kubectl debug -it pod/my-pod 
  --image=busybox:1.36.1 
  --target=app-container 
  --share-processes 
  -- bash
```

- `--target=app-container`: Указывает, к какому основному контейнеру в Pod'е мы хотим "прицепиться".
- `--share-processes`: Позволяет эфемерному контейнеру видеть и взаимодействовать с процессами целевого контейнера.

## Команды для работы с подами

```bash
# Создать под из файла
kubectl apply -f pod.yaml

# Получить информацию о подах
kubectl get pods

# Вывести поды только определенного неймспейса
kubectl -n <имя неймспейса> get pod

# Получить подробную информацию о конкретном поде
kubectl describe pod my-nginx-pod

# Удалить под
kubectl delete pod my-nginx-pod

# Получить поды на конкретной ноде
kubectl get pod --field-selector spec.nodeName=<имя_ноды>
```

**Примеры использования меток:**

```bash
# Получить все frontend поды
kubectl get pods -l app=frontend

# Получить все ресурсы в production окружении
kubectl get all -l environment=production

# Удалить все тестовые ресурсы
kubectl delete all -l environment=test

# Комбинировать селекторы
kubectl get pods -l 'app=web,environment in (staging,production)'
```

## `kubectl apply` vs `kubectl create`

| Команда | Описание | Когда использовать |
|---------|----------|-------------------|
| **`kubectl create`** | **Императивная команда.** Создает новый объект с нуля. Если объект с таким именем уже существует, команда вернет ошибку. | Для одноразового создания объектов, когда вы уверены, что их еще нет. Удобно для простых сценариев или скриптов. |
| **`kubectl apply`** | **Декларативная команда.** Применяет конфигурацию из файла. Если объекта не существует, он будет создан. Если объект уже существует, `apply` сравнит текущую конфигурацию с новой и применит только изменения. | **Предпочтительный способ** для управления ресурсами в Kubernetes. Идеально подходит для CI/CD и управления инфраструктурой как кодом (IaC), так как позволяет отслеживать изменения в Git. |

**Ключевое отличие:** `kubectl apply` хранит последнюю примененную конфигурацию в аннотации `kubectl.kubernetes.io/last-applied-configuration` внутри самого объекта. Это позволяет ему понимать, какие поля были изменены при следующем вызове `apply`. `kubectl create` этого не делает.
