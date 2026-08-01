# Поиск и устранение неисправностей в Kubernetes

## Определения

**Траблшутинг (Troubleshooting) Kubernetes** — систематический процесс диагностики и устранения неисправностей в работе подов (Pods), сервисов (Services), узлов (Nodes) и компонентов управления (Control Plane).

## Основные концепции

### Ключевые области диагностики

Траблшутинг в Kubernetes традиционно разделяется на три критических направления:
*   **Сбои приложений:** Ошибки запуска, циклическая перезагрузка, неверная конфигурация или утечки ресурсов внутри контейнеров.
*   **Состояние узлов (Nodes):** Недоступность рабочих узлов, нехватка ресурсов (Pressure), проблемы рантайма (CRI) или системные ошибки ОС.
*   **Сетевое взаимодействие:** Ошибки маршрутизации трафика, проблемы DNS, блокировки NetworkPolicy или сбои в Service Mesh.

### Классификация ошибок по уровням

| Уровень | Ошибки | Ссылки на руководства |
|:---|:---|:---|
| **Планирование** | `Pending` | [Ошибки планирования](./Common_Errors/pod_pending/definitions_and_concepts.md) |
| **Конфигурация** | `ImagePullBackOff`, `CreateContainerConfigError` | [Ошибки образов](./Common_Errors/PodImagePullErrors/definitions.md), [Ошибки конфигурации](./Common_Errors/CreateContainerConfigError/definitions.md) |
| **Запуск приложения** | `CrashLoopBackOff`, `OOMKilled` | [Циклические перезапуски](./Common_Errors/pod_crash_loop_back_off/definitions_and_concepts.md), [Нехватка памяти (OOMKilled)](./Common_Errors/oomkilled_pods.md) |
| **Работоспособность** | `Liveness/Readiness Probe Failed` | [Диагностика проб](../Base/probes.md#диагностика-и-устранение-неисправностей) |
| **Ресурсы узла** | `Evicted`, `NodeNotReady` | [Выселение подов](./Common_Errors/PodEvicted/definitions.md), [Недоступность узла](./Common_Errors/NodeUnavailability/definitions.md) |
| **Безопасность** | `Forbidden`, `Unauthorized` | [Ошибки доступа (RBAC)](./Common_Errors/ApiAccessForbidden/definitions.md) |
| **Завершение** | `Terminating` | [Проблемы удаления подов](./Common_Errors/PodTerminating/definitions.md) |

### Рабочий процесс диагностики

Для эффективного поиска причины рекомендуется последовательно проверять уровни абстракции:

1. **kubectl get pods -o wide** — проверка статуса, меток, IP-адреса и узла (Node).
   ```bash
   kubectl get pods -o wide
   # → NAME  READY  STATUS   RESTARTS  AGE  IP           NODE
   # → app   1/1    Running  0         5m   10.244.1.5   worker-1
   ```
2. **kubectl get events --sort-by='.lastTimestamp'** — хронологический список событий. Часто информативнее, чем `describe`.
   ```bash
   kubectl get events --sort-by='.lastTimestamp'
   # → 45s  Warning  FailedScheduling  pod/app  0/3 nodes are available: 3 Insufficient cpu.
   ```
3. **kubectl describe pod <pod-name>** — детальный анализ жизненного цикла пода и раздел `Events`.
4. **kubectl logs <pod-name> --tail=100 -f** — просмотр логов в реальном времени. Флаг `--previous` (`-p`) нужен, если контейнер перезапустился.
   ```bash
   kubectl logs my-app -p
   # → panic: runtime error: invalid memory address or nil pointer dereference
   ```
5. **kubectl debug -it <pod-name> --image=nicolaka/netshoot** — использование специализированных отладочных образов (например, `netshoot`) для сетевой диагностики.

### Быстрая диагностика по статусу

| Статус пода | Рекомендуемая команда | Вероятная причина |
|:---|:---|:---|
| `Pending` | `kubectl describe pod` | Нехватка ресурсов, Taints, Affinity, ошибки PVC |
| `ContainerCreating` | `kubectl describe pod` | Проблемы монтирования Volume, загрузки образа, CNI |
| `ImagePullBackOff` | `kubectl logs` (если возможно) | Неверные `imagePullSecrets`, ошибка в имени образа |
| `CrashLoopBackOff` | `kubectl logs --previous` | Ошибка приложения (exit code > 0), отсутствие конфигов |
| `OOMKilled` | `kubectl top pod` | Превышение лимитов (Limits). Exit Code: 137 |
| `Evicted` | `kubectl describe node` | DiskPressure (нехватка места) или MemoryPressure на узле |
| `Terminating` | `kubectl get pod -o yaml` | Finalizers в метаданных, зависшие процессы в контейнере |

### Диагностика сетевого взаимодействия

Проблемы с сетью часто проявляются как ошибки **502 Bad Gateway** или **Connection Timeout**.

**Цепочка проверок:**

1. **Состояние Service и Endpoints:** Убедитесь, что селекторы Service совпадают с метками подов. Подробные сценарии см. в разделе **[Устранение неполадок Service](../Networking/Service/service_practical_scenarios.md#устранение-неполадок-troubleshooting)**.
   ```bash
   kubectl get endpoints <service-name>
   # → NAME      ENDPOINTS            AGE
   # → my-svc    10.244.1.5:8080      1h
   ```
2. **DNS внутри кластера:** Проверьте разрешение имен через `CoreDNS`. Подробный алгоритм диагностики см. в разделе **[Устранение неполадок DNS](../Networking/Network/dns_service_discovery.md#устранение-неполадок-dns-troubleshooting)**.
   ```bash
   kubectl exec -it <pod-name> -- nslookup kubernetes.default
   # → Server: 10.96.0.10
   # → Address: 10.96.0.10#53
   # → Name: kubernetes.default.svc.cluster.local
   # → Address: 10.96.0.1
   ```
3. **NetworkPolicy:** Проверьте, не блокирует ли трафик объект `NetworkPolicy`.
   ```bash
   kubectl get networkpolicy -A
   ```
4. **Пробы готовности (Readiness Probes):** Если под не прошел пробу, он удаляется из Endpoints, и трафик на него не идет. Подробнее в разделе **[Диагностика и устранение неисправностей проб](../Base/probes.md#диагностика-и-устранение-неисправностей)**.

### Диагностика уровня узла (Node)

Если проблема не в подах, необходимо проверить состояние `Kubelet` и системные ресурсы узла.

- **Статус узла:** `kubectl describe node <node-name>`. Обратите внимание на раздел `Conditions` (MemoryPressure, DiskPressure, PIDPressure).
- **Логи Kubelet:**
  ```bash
  # Выполняется на узле
  journalctl -u kubelet -f
  ```
- **Проверка контейнерного рантайма (CRI):**
  ```bash
  # Использование crictl (универсальный инструмент)
  crictl ps
  crictl logs <container-id>
  ```

### Диагностика компонентов управления (Control Plane)

Проблемы с API-сервером, планировщиком (Scheduler) или контроллерами обычно влияют на весь кластер.

1. **Проверка подов системы:** `kubectl get pods -n kube-system`.
2. **Логи статических подов:** Если кластер развернут через `kubeadm`, логи компонентов находятся в `/var/log/pods/` или проверяются через `docker ps`/`crictl ps`.
3. **Состояние etcd:** Проверка доступности хранилища и свободного места (quota).

## Основные инструменты командной строки

#### kubectl describe: Детальный статус ресурсов

Предоставляет текущее состояние, лимиты, назначенные ресурсы и хронологический список событий.
- **Exit Code 137:** процесс убит по OOM (Out Of Memory).
- **Exit Code 143:** корректное завершение по сигналу SIGTERM.

#### kubectl logs: Анализ вывода приложения

Позволяет просматривать `stdout` и `stderr`.
- `-l app=nginx`: логи всех подов с определенной меткой.
- `--all-containers`: для подов с sidecar-контейнерами.

#### kubectl auth can-i: Проверка разрешений

Незаменимо для отладки проблем с RBAC (Role-Based Access Control).
```bash
kubectl auth can-i create deployments --as system:serviceaccount:default:my-sa
# → yes
```

#### kubectl top: Мониторинг ресурсов

Требует установленного `Metrics Server`.
```bash
kubectl top node
# → NAME    CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → node-1  150m         4%     1200Mi          15%
```

#### kubectl debug: Эфемерные контейнеры

Позволяет подключать инструменты к "тонким" образам (distroless).
```bash
kubectl debug -it <pod-name> --image=nicolaka/netshoot --target=<container-name>
```

## Практические сценарии

### Изоляция пода для отладки

Удаление меток (labels) позволяет временно "спрятать" под от трафика Service для детального изучения.
```bash
kubectl label pod <pod-name> app-
# → pod/my-app labeled (метка 'app' удалена)
```

### Предотвращение перезагрузки падающего пода

Если под постоянно падает, можно изменить `entrypoint` на `sleep`, чтобы войти внутрь и проверить конфигурацию.
```bash
kubectl patch deployment <deploy-name> \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"app","command":["sleep","3600"]}]}}}}'
```

## Дополнительная информация

### Продвинутые методы отладки

- **Трассировка системных вызовов:** использование `strace` или `tcpdump` через привилегированные контейнеры или `kubectl debug`.
- **Remote Debugging:** проброс портов для подключения IDE к процессу внутри контейнера.
  ```bash
  kubectl port-forward pod/<pod-name> 5005:5005
  ```

### См. также

- [Жизненный цикл и состояния Pod](../Base/Pod/pod_lifecycle_and_state.md)
- [Пробы (Probes) в Kubernetes](../Base/probes.md)
- [Классификация типичных ошибок](./Common_Errors/)
- [Эфемерные контейнеры](../Base/Pod/ephemeral_containers.md)
- [QoS, Requests и Limits](../Scheduling/qos_limit_and_requests.md)

