# Поиск и устранение неисправностей в Kubernetes

## Определения

**Траблшутинг (Troubleshooting) Kubernetes** — систематический процесс диагностики и устранения неисправностей в работе подов (Pods), сервисов (Services), узлов (Nodes) и контроллеров кластера.

**Распространенные ошибки** — типичные состояния подов и узлов, указывающие на проблемы с планированием, конфигурацией, ресурсами или доступностью компонентов кластера.

## Основные концепции

### Классификация ошибок по уровням

| Уровень | Ошибки | Ссылки на руководства |
|:---|:---|:---|
| **Планирование** | `Pending` | [Ошибки планирования](./Common_Errors/pod_pending/definitions_and_concepts.md) |
| **Конфигурация** | `ImagePullBackOff`, `CreateContainerConfigError` | [Ошибки образов](./Common_Errors/PodImagePullErrors/definitions.md), [Ошибки конфигурации](./Common_Errors/CreateContainerConfigError/definitions.md) |
| **Запуск приложения** | `CrashLoopBackOff`, `OOMKilled` | [Циклические перезапуски](./Common_Errors/pod_crash_loop_back_off/definitions_and_concepts.md), [Нехватка памяти (OOMKilled)](./Common_Errors/oomkilled_pods.md) |
| **Ресурсы узла** | `Evicted`, `NodeNotReady` | [Выселение подов](./Common_Errors/PodEvicted/definitions.md), [Недоступность узла](./Common_Errors/NodeUnavailability/definitions.md) |
| **Безопасность** | `Forbidden`, `Unauthorized` | [Ошибки доступа (RBAC)](./Common_Errors/ApiAccessForbidden/definitions.md) |
| **Завершение** | `Terminating` | [Проблемы удаления подов](./Common_Errors/PodTerminating/definitions.md) |

### Рабочий процесс диагностики (Workflow)

Для эффективного поиска причины рекомендуется следовать стандартной цепочке действий:

1. **kubectl get pods --show-labels** — проверка общего статуса и меток.
2. **kubectl describe pod <pod-name>** — анализ раздела `Events` (события). **Это основной источник информации о проблемах инфраструктуры.**
3. **kubectl logs <pod-name> [--previous]** — изучение логов приложения. Флаг `--previous` позволяет увидеть логи контейнера до его последнего падения.
4. **kubectl exec -it <pod-name> -- /bin/sh** — интерактивная проверка окружения внутри запущенного контейнера.
5. **kubectl debug -it <pod-name>** — использование эфемерных контейнеров для отладки образов без встроенного шелла (shell).

### Быстрая диагностика по статусу

| Статус пода | Рекомендуемая команда | Вероятная причина |
|:---|:---|:---|
| `Pending` | `kubectl describe pod` | Нехватка ресурсов, Taints, Affinity |
| `ContainerCreating` | `kubectl describe pod` | Проблемы с образом, PV (Persistent Volume), сетью |
| `ImagePullBackOff` | `kubectl describe pod` | Ошибка имени образа, нет доступа к Registry |
| `CrashLoopBackOff` | `kubectl logs --previous` | Ошибка приложения, конфигурации или зависимостей |
| `OOMKilled` | `kubectl describe pod` + `kubectl top pod` | Превышен `limits.memory`, утечка памяти |
| `Evicted` | `kubectl describe node` | Давление на ресурсы узла (память или диск) |
| `Terminating` | `kubectl get pod -o yaml` | Наличие Finalizers, проблемы с размонтированием Volume |

### Основные инструменты командной строки

#### kubectl describe: Детальный статус ресурсов

Команда предоставляет текущее состояние, лимиты, назначенные ресурсы и хронологический список событий.

- **Reason/Exit Code:** показывают причину завершения (например, `137` для OOMKilled).
- **Restart Count:** количество перезапусков (рост счетчика указывает на нестабильность).

#### kubectl logs: Анализ вывода приложения

Позволяет просматривать `stdout` и `stderr` процессов внутри контейнеров.

- `--previous` (`-p`): логи до последнего перезапуска.
- `--all-containers`: если в поде несколько контейнеров.
- `--since=<время>`: логи за конкретный период (например, `10m`).

#### kubectl exec: Интерактивный доступ

Выполнение команд внутри контейнера. Требует наличия шелла (sh/bash) в образе.

```bash
kubectl exec -it <pod-name> -c <container-name> -- /bin/sh
```

#### kubectl port-forward: Проверка сети

Проброс локального порта на порт пода для отладки сервисов без необходимости создания внешнего балансировщика.

```bash
kubectl port-forward pod/<pod-name> 8080:80
```

#### kubectl debug: Эфемерные контейнеры

Позволяет подключать отладочные инструменты к работающему поду без его перезапуска. Незаменимо для образов типа Distroless.

Подробное руководство: [Эфемерные контейнеры](../Base/Pod/ephemeral_containers.md).

### Связь с QoS (Quality of Service) классами

Kubernetes выселяет поды при нехватке ресурсов на основе их приоритета. Подробности см. в разделе: [QoS, Requests и Limits](../Scheduling/qos_limit_and_requests.md).

1. **BestEffort** — без лимитов/запросов, выселяются первыми.
2. **Burstable** — запросы меньше лимитов, средний приоритет.
3. **Guaranteed** — запросы равны лимитам, максимальная защита.

## Практические сценарии

### Изоляция пода для отладки

Удаление меток (labels) позволяет временно "спрятать" под от трафика Service, сохраняя его запущенным для диагностики.

```bash
# Удаление метки (минус в конце ключа)
kubectl label pod <pod-name> app-
```

После этого Service перестанет направлять трафик на этот под, но вы сможете изучить его состояние с помощью `exec` или `debug`.

### Предотвращение перезагрузки падающего пода

При `CrashLoopBackOff` можно временно изменить команду запуска на `sleep`, чтобы под перешел в состояние `Running` и позволил подключил к нему.

```bash
kubectl patch deployment <deploy-name> \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"app","command":["sleep","3600"]}]}}}}'
```

## Дополнительная информация

### Продвинутые методы отладки

- **Сбор Core Dumps:** настройка `initContainer` для изменения `kernel.core_pattern` и сохранения дампов памяти в Persistent Volume для последующего анализа в GDB (GNU Debugger).
- **Удаленная отладка (Remote Debugging):** использование инструментов вроде Delve (для Go) или JDWP (для Java) через `kubectl port-forward`.
- **Трассировка системных вызовов:** использование `strace` через `kubectl debug` (требует профиля `sysadmin` или соответствующих capabilities).

### См. также

- [Жизненный цикл и состояния Pod](../Base/Pod/pod_lifecycle_and_state.md)
- [Пробы (Probes) в Kubernetes](../Base/probes.md)
- [Классификация типичных ошибок](./Common_Errors/)
- [Эфемерные контейнеры](../Base/Pod/ephemeral_containers.md)
