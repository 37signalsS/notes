# Поиск и устранение неисправностей в Kubernetes

## Определения

**Troubleshooting Kubernetes** — систематический процесс диагностики и устранения неисправностей в работе подов, сервисов, узлов и контроллеров кластера.

**Распространенные ошибки** — типичные состояния подов и узлов, указывающие на проблемы с планированием, конфигурацией, ресурсами или доступностью компонентов кластера.

> **Смежные разделы:**
> - Классификация ошибок: [Common Errors](./Common_Errors/)
> - QoS и управление ресурсами: [qos_limit_and_requests](../Scheduling/qos_limit_and_requests.md)
> - Taints и tolerations: [taints_and_tolerations](../Scheduling/taints_and_tolerations.md)
> - RBAC: [rbac_overview](../Security/rbac/rbac_overview.md)
> - Node maintenance: [node_maintenance](../Operations/node_maintenance.md)

## Основные концепции

### Классификация ошибок по уровням

| Уровень | Ошибки | Детали |
|---------|--------|--------|
| **Планирование** | `Pending` | [pod_pending](./Common_Errors/pod_pending/) |
| **Конфигурация** | `ImagePullBackOff`, `CreateContainerConfigError` | [pod_image_pull_errors](./Common_Errors/PodImagePullErrors/), [create_container_config_error](./Common_Errors/CreateContainerConfigError/) |
| **Запуск приложения** | `CrashLoopBackOff`, `OOMKilled` | [pod_crash_loop_back_off](./Common_Errors/pod_crash_loop_back_off/), [oomkilled_pods](./Common_Errors/oomkilled_pods.md) |
| **Ресурсы узла** | `Evicted`, `NodeNotReady` | [pod_evicted](./Common_Errors/PodEvicted/), [node_unavailability](./Common_Errors/NodeUnavailability/) |
| **Безопасность** | `Forbidden`, `Unauthorized` | [api_access_forbidden](./Common_Errors/ApiAccessForbidden/) |
| **Завершение** | `Terminating` | [pod_terminating_issues](./Common_Errors/PodTerminating/) |

### Workflow диагностики

```
1. kubectl get pods --show-labels
   ↓
2. kubectl describe pod <pod-name>  → Events section
   ↓
3. kubectl logs <pod-name> [--previous]
   ↓
4. kubectl exec -it <pod-name> -- /bin/sh  (при необходимости)
   ↓
5. kubectl debug -it <pod-name> --image=nicolaka/netshoot  (для продвинутой отладки)
```

Дополнительные команды для специфичных проблем:
- `kubectl auth can-i [...]` — для диагностики RBAC
- `kubectl top pod/node` — для мониторинга ресурсов

> **Правило:** Всегда начинайте с `kubectl describe` — раздел `Events` содержит хронологию событий и часто указывает на корневую причину.

### Быстрая диагностика по статусу

| Статус пода | Первая команда | Вероятная причина |
|-------------|----------------|-------------------|
| `Pending` | `kubectl describe pod` | Нехватка ресурсов, taints, affinity |
| `ContainerCreating` | `kubectl describe pod` | Проблемы с образом, PV, сетью |
| `ImagePullBackOff` | `kubectl describe pod` | Ошибка имени образа, нет доступа к registry |
| `CrashLoopBackOff` | `kubectl logs --previous` | Ошибка приложения, конфигурации, зависимостей |
| `OOMKilled` | `kubectl describe pod` + `kubectl top pod` | Превышен limits.memory, утечка памяти |
| `Evicted` | `kubectl describe node` | Node Pressure (memory/disk) |
| `Terminating` | `kubectl get pod -o yaml` | Finalizers, volume unmount |

### Связь с QoS классами

При нехватке ресурсов на узле Kubernetes выселяет поды на основе [QoS класса](../Scheduling/qos_limit_and_requests.md):

1. **`BestEffort`** — выселяются первыми (нет requests/limits)
2. **`Burstable`** — выселяются вторыми (requests < limits)
3. **`Guaranteed`** — выселяются последними (requests == limits)

> **Best Practice:** Всегда указывайте `requests` и `limits` для production-приложений.

### Основные инструменты командной строки

#### `kubectl describe`: Детальная диагностика ресурсов

`kubectl describe` предоставляет текущий статус, недавние события и диагностические данные ресурса.

**Ключевые поля вывода:**

| Поле | Описание |
|------|----------|
| `State` / `Last State` | Текущее и предыдущее состояние контейнера |
| `Reason` | Причина завершения (`OOMKilled`, `Error`, `Completed`) |
| `Exit Code` | Код выхода (`137` = OOMKilled, ненулевой = ошибка) |
| `Restart Count` | Количество перезапусков (`> 0` указывает на проблему) |
| `Events` | Хронологический список событий — **приоритетный раздел** |

#### `kubectl logs`: Анализ логов контейнеров

Просмотр `stdout` и `stderr` процессов в контейнерах.

**Ключевые флаги:**

| Флаг | Назначение |
|------|------------|
| `--previous` (`-p`) | Логи до последнего падения (критичен при `CrashLoopBackOff`) |
| `--follow` (`-f`) | Стриминг в реальном времени |
| `--tail=<N>` | Последние N строк |
| `--all-containers` | Логи всех контейнеров в поде |
| `-l <метка>` | Логи всех подов с меткой |
| `--since=<время>` | Логи за период (`10m`, `1h`) |

> **Совет:** Для одновременного просмотра логов нескольких подов используйте [`kubetail`](../ToolsUtilities/kubetail.md) — утилиту с цветовой индикацией.

#### `kubectl exec`: Выполнение команд внутри контейнера

Интерактивный доступ к shell запущенного контейнера.

**Синтаксис:**
```bash
kubectl exec -it <pod-name> -- /bin/bash
kubectl exec -it <pod-name> -c <container-name> -- /bin/sh  # multi-container
```

#### `kubectl port-forward`: Доступ к приложению

Проброс локального порта на порт пода для отладки внутренних сервисов.

**Синтаксис:**
```bash
kubectl port-forward pod/<pod-name> 8080:80
```

#### `kubectl debug`: Эфемерные контейнеры для отладки

Подключение отладочных контейнеров (`netshoot`, `busybox`) без перезапуска пода.

**Пример:**
```bash
# Подключить контейнер с сетевыми утилитами
kubectl debug -it my-pod --image=nicolaka/netshoot --target=app-container
```

Команда позволяет запускать `tcpdump`, `ping`, `nslookup` в сетевом namespace проблемного пода.

## Практические сценарии

### Изоляция пода для отладки с помощью меток

Удаление меток — безопасный способ изоляции пода от трафика `Service` без его остановки.

**Процесс:**

1. **Изоляция:** Удалить метку с пода (`-` в конце ключа удаляет метку).

    ```bash
    # Сервис ищет поды с меткой app=myapp
    kubectl label pod myapp-pod-xyz app-
    ```

    Под работает, но `Service` не направляет на него трафик.

2. **Отладка:** Подключиться к поду для диагностики.

    ```bash
    kubectl exec -it myapp-pod-xyz -- /bin/sh
    ```

3. **Завершение:** Удалить под. `Deployment`/`ReplicaSet` создаст новый экземпляр.

    ```bash
    kubectl delete pod myapp-pod-xyz
    ```

### Временная "заморозка" падающего пода с помощью `sleep`

При `CrashLoopBackOff` можно изменить `command` контейнера на `sleep` для получения доступа к окружению.

**Команда:**

```bash
kubectl patch deployment my-app \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"app","command":["sleep","3600"]}]}}}}'
```

Где `my-app` — имя деплоймента, `app` — имя контейнера.

**Применение:**

- Под в состоянии `Running` — доступен через `kubectl exec`
- Проверка переменных окружения, файлов, конфигурации, сети
- Выявление причины сбоя (отсутствующий конфиг, неверная переменная, права доступа)

**Завершение:** Откатить деплоймент или применить оригинальный манифест.

## Дополнительная информация

### Сбор и анализ Core Dumps

Настройка сохранения core dump при аварийном завершении приложения (segmentation fault и др.).

**Механизм:**

- `initContainer` с `privileged: true` изменяет `kernel.core_pattern` и `ulimit`
- Дампы сохраняются в `PersistentVolume`
- Анализ: `gdb` (C/C++), `delve` (Go)

### Удаленная отладка с Delve (Go)

Подключение локального отладчика к процессу внутри пода.

**Механизм:**

1. В `Dockerfile` приложение запускается через `dlv` в режиме сервера отладки
2. `kubectl port-forward` пробрасывает порт отладчика на локальную машину
3. IDE (GoLand, VS Code) подключается к `localhost:<port>`

### Отладка прав доступа с помощью `strace`

`strace` отслеживает системные вызовы для диагностики `Permission Denied` (особенно с `readOnlyRootFilesystem`).

**Механизм:**

```bash
# Запуск отладочного контейнера
kubectl debug -it -c debugger --target=app --image=alpine ${POD_NAME} --profile=sysadmin
# Внутри отладчика: отслеживаем сбои системных вызовов
strace -f -e status=failed -p 1
```

### Связанные разделы

- [Pod Lifecycle](../Base/Pod/pod_lifecycle_and_state.md) — состояния пода, probes
- [Deployment](../Base/Deployment/index.md) — стратегии развертывания, rollback
- [High Availability](../Base/high_availability.md) — PDB, eviction timeout
- [Node Maintenance](../Operations/node_maintenance.md) — обслуживание узлов
- [Pod Distribution](../Autoscaling/pod_distribution/basic_concepts.md) — affinity, topologySpreadConstraints
