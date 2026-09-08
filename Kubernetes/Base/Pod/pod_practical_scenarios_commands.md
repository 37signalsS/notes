# Практические сценарии и команды управления Pod

## Определения

**kubectl** — основной CLI-инструмент для взаимодействия с API-сервером Kubernetes. Позволяет выполнять CRUD-операции над ресурсами, управлять жизненным циклом приложений и проводить диагностику.

**Императивный подход** — управление через прямые команды (например, `kubectl run`, `kubectl scale`), где каждое действие описывает *как* изменить систему. Быстр, но не оставляет трассировки изменений.

**Декларативный подход** — управление через манифесты (YAML/JSON). Пользователь описывает *желаемое состояние* (например, `kubectl apply`), а контроллеры Kubernetes приводят текущее состояние к целевому. Это фундамент методологии **IaC (Infrastructure as Code)**.

**kubectl proxy** — встроенный проксирующий сервер kubectl, который создаёт локальный HTTP-эндпоинт (по умолчанию `localhost:8001`), проксирующий запросы к API-серверу Kubernetes. Упрощает доступ к API без ручной настройки аутентификации и TLS.

**kubectl attach** — команда для подключения к уже запущенному процессу контейнера для чтения stdout/stderr и (при наличии `stdin`) отправки ввода. В отличие от `exec` **не создаёт нового процесса**, а присоединяется к существующему PID 1.

**kubectl cp** — утилита для копирования файлов и каталогов между локальной машиной и контейнером Pod (или наоборот). Работает через подключаемый tar-архиватор внутри контейнера. Не требует установленного `tar` на локальной машине.

**kubectl auth can-i** — команда проверки RBAC-разрешений: позволяет определить, может ли указанный пользователь или ServiceAccount выполнить определённое действие над конкретным ресурсом. Незаменима для отладки ошибок `Forbidden` и `Unauthorized`.

---

## Базовые концепции

### Методы создания и обновления

| Команда | Подход | Особенности | Рекомендация |
| :--- | :--- | :--- | :--- |
| `kubectl run` | Императивный | Создает одиночный Pod. Быстро, но не сохраняет историю. | Только для тестов. |
| `kubectl create` | Императивный | Создает ресурс. Выдает ошибку, если ресурс уже существует. | Разовые задачи (Job). |
| `kubectl apply` | Декларативный | Создает или обновляет ресурс. Вычисляет diff через аннотацию. | **Стандарт для Prod/CI.** |
| `kubectl delete` | Императивный | Удаляет ресурс по имени или через манифест. | Для завершения жизненного цикла. |
| `kubectl patch` | Императивный | Частичное обновление существующего ресурса (JSON Merge/Strategic). | Точечные изменения без полного манифеста. |
| `kubectl edit` | Императивный | Открывает ресурс в `$EDITOR` для интерактивного редактирования. | Быстрые правки вручную. |
| `kubectl expose` | Императивный | Создает Service для Pod/Deployment. | Быстрое предоставление доступа. |

**Механизм Diff:** `kubectl apply` использует аннотацию `kubectl.kubernetes.io/last-applied-configuration` для сравнения локального файла, текущего состояния в кластере и предыдущей конфигурации, чтобы применить только необходимые изменения.

### Референс команд для работы с Pod

| Команда | Назначение | Подробнее |
| :--- | :--- | :--- |
| `kubectl get pods` | Просмотр состояния Pod (фаза, готовность, IP, узел). | [Жизненный цикл Pod](./pod_lifecycle_and_state.md) |
| `kubectl describe pod` | Детальный анализ: Conditions, Events, лимиты, Volume'ы. | [Траблшутинг](../../Troubleshooting/troubleshooting_overview.md) |
| `kubectl logs` | Просмотр stdout/stderr контейнера. | [Логирование](../../MonitoringLogging/kubernetes-monitoring-logging-architecture.md) |
| `kubectl exec` | Запуск команды внутри контейнера (новый процесс). | [Эфемерные контейнеры](./ephemeral_containers.md) |
| `kubectl attach` | Подключение к stdin/stdout запущенного процесса (без fork). | Раздел ниже |
| `kubectl port-forward` | Проброс порта из Pod на локальную машину. | Раздел ниже |
| `kubectl cp` | Копирование файлов между Pod и локальной машиной. | Раздел ниже |
| `kubectl delete pod` | Удаление Pod (с проверкой PDB при eviction). | [Жизненный цикл удаления](./pod_lifecycle_and_state.md#жизненный-цикл-удаления-pod) |
| `kubectl top pod` | Потребление CPU/Memory (требует metrics-server). | [Мониторинг](../../MonitoringLogging/metrics-server.md) |
| `kubectl wait` | Ожидание наступления условия (Ready, Exists, deleting). | Раздел ниже |
| `kubectl rollout` | Управление Rolling Update (status, undo, restart). | [Управление обновлениями](../Deployment/lifecycle_management.md) |
| `kubectl debug` | Подключение эфемерного контейнера к Pod. | [Эфемерные контейнеры](./ephemeral_containers.md) |
| `kubectl get events` | Хронологический список событий кластера или namespace. | Раздел ниже |
| `kubectl auth can-i` | Проверка RBAC-разрешений. | Раздел ниже |

### Стандартный алгоритм диагностики

Если Pod не работает корректно, следуйте цепочке «Снаружи → Внутрь»:

1.  **Общий статус**: `kubectl get pods -o wide` (проверка фазы, узла, IP).
2.  **События**: `kubectl get events --sort-by='.lastTimestamp'` (хронология ошибок).
3.  **Детали**: `kubectl describe pod <name>` (секция Events, Conditions).
4.  **Логи приложения**: `kubectl logs <name>` (анализ stdout/stderr).
5.  **Интерактивная проверка**: `kubectl exec` или `kubectl debug`.

> **Подробнее:** [Алгоритм диагностики](../../Troubleshooting/troubleshooting_overview.md#рабочий-процесс-диагностики).

---

## Практические сценарии

### Сценарий 1: Быстрое создание и модификация (Императивный путь)

Используется для быстрой проверки гипотез или отладки, когда нецелесообразно писать полноценный манифест.

```bash
# Быстрый запуск Nginx с последним образом
kubectl run my-nginx --image=nginx:latest

# Проверка статуса и логов
kubectl get pods my-nginx
kubectl logs my-nginx

# Временное изменение контента (не переживет рестарт контейнера!)
kubectl exec -it my-nginx -- sh -c "echo 'Welcome to Shortcut' > /usr/share/nginx/html/index.html"
```

> **Важно:** Любые изменения файлов внутри работающего Pod через `exec` являются временными. Для постоянных изменений используйте `ConfigMap`, `Volume` или пересборку образа.

### Сценарий 2: Продвинутый просмотр и фильтрация

Использование селекторов и кастомных форматов вывода.

```bash
# Просмотр подов с конкретными метками
kubectl get pods -l app=nginx,env=prod

# Просмотр подов в конкретном namespace (включая системные)
kubectl get pods -n kube-system -l k8s-app=kube-dns

# Использование JSONPath для получения конкретных полей (например, IP всех подов)
kubectl get pods -o jsonpath='{.items[*].status.podIP}'

# Вывод в табличном виде с кастомными колонками
kubectl get pods -o custom-columns="NAME:.metadata.name,NODE:.spec.nodeName,IP:.status.podIP"

# Сортировка по времени создания (старые первые)
kubectl get pods --sort-by=.metadata.creationTimestamp

# Мониторинг изменений в реальном времени
kubectl get pods -w

# Быстрый поиск подов в特定ном статусе
kubectl get pods --field-selector=status.phase=Running -o wide
kubectl get pods --field-selector=status.phase=Pending
```

### Сценарий 3: Диагностика многоконтейнерных подов

При наличии Sidecar-контейнеров необходимо всегда указывать целевой контейнер флагом `-c`.

```bash
# Просмотр логов конкретного контейнера (например, прокси)
kubectl logs <pod-name> -c envoy-proxy

# Логи предыдущей (упавшей) инстанции контейнера
kubectl logs <pod-name> -p

# Логи конкретного контейнера из предыдущего запуска
kubectl logs <pod-name> -c app-container --previous

# Агрегированные логи всех контейнеров в поде
kubectl logs <pod-name> --all-containers

# Логи с таймстампами (удобно для корреляции с внешними системами)
kubectl logs <pod-name> --timestamps=true

# Логи с ограничением по времени (только последние 5 минут)
kubectl logs <pod-name> --since=5m

# Логи с ограничением по количеству строк
kubectl logs <pod-name> --tail=100

# Непрерывный просмотр логов (follow)
kubectl logs <pod-name> -f

# Логи по меткам (все поды с label app=nginx)
kubectl logs -l app=nginx --all-containers
```

> **Подробнее:** Обзор инструментов логирования — [Мониторинг и логирование в Kubernetes](../../MonitoringLogging/kubernetes-monitoring-logging-architecture.md).

### Сценарий 4: Временный доступ и проброс портов

Доступ к приложению (например, базе данных или UI), которое не опубликовано через Ingress/Service.

```bash
# Проброс порта 8080 локальной машины на порт 80 внутри пода
kubectl port-forward pod/<name> 8080:80

# Проброс порта на Service (автоматический выбор активного пода)
kubectl port-forward svc/my-service 5432:5432

# Проброс на конкретный namespace
kubectl port-forward -n monitoring svc/prometheus 9090:9090

# Проброс с привязкой к внешнему интерфейсу (для доступа с других машин)
kubectl port-forward --address 0.0.0.0 pod/<name> 8080:80

# Проброс нескольких портов одновременно
kubectl port-forward pod/<name> 3000:3000 8080:8080

# Проброс для доступа к мониторингу (Prometheus, Grafana, Jaeger)
kubectl port-forward -n monitoring svc/grafana 3000:3000
```

> **Важно:** `port-forward` создаёт только одно соединение и не поддерживает failover. Для production-доступа используйте Ingress, LoadBalancer или NodePort.

### Сценарий 5: Управление жизненным циклом и ожидание

Использование команд для автоматизации скриптов.

```bash
# Ожидание готовности пода перед выполнением следующих шагов (например, в CI)
kubectl wait --for=condition=Ready pod/<name> --timeout=60s

# Ожидание завершения Pod (для Job)
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded job/<name> --timeout=300s

# Ожидание удаления Pod
kubectl wait --for=delete pod/<name> --timeout=120s

# Ожидание готовности всех подов с меткой
kubectl wait --for=condition=Ready pods -l app=my-app --timeout=120s

# Ожидание появления конкретного условия
kubectl wait --for=condition=ContainersReady pod/<name> --timeout=60s

# Принудительное удаление (без graceful shutdown, не рекомендуется в Prod)
kubectl delete pod <name> --force --grace-period=0

# Удаление с увеличенным Graceful Shutdown Period
kubectl delete pod <name> --grace-period=120

# Перезапуск всех подов Deployment (путем обновления шаблона)
kubectl rollout restart deployment <name>

# Проверка статуса rollout
kubectl rollout status deployment <name>

# Откат к предыдущей версии
kubectl rollout undo deployment <name>

# Просмотр истории rollout
kubectl rollout history deployment <name>
```

> **Подробнее:** [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md), [Управление обновлениями Deployment](../Deployment/lifecycle_management.md).

### Сценарий 6: Инспекция ресурсов (Metrics)

Требуется наличие установленного `metrics-server`.

```bash
# Просмотр потребления CPU и памяти подом
kubectl top pod <name>

# Потребление ресурсов по конкретным контейнерам внутри пода
kubectl top pod <name> --containers

# Сортировка подов по памяти в текущем namespace
kubectl top pods --sort-by=memory

# Сортировка подов по CPU
kubectl top pods --sort-by=cpu

# Сортировка всех подов кластера (включая системные)
kubectl top pods -A --sort-by=memory

# Потребление ресурсов узлами
kubectl top nodes

# Сравнение запросов (requests) с реальным потреблением
kubectl get pods -o custom-columns="NAME:.metadata.name,CPU_REQ:.spec.containers[*].resources.requests.cpu,MEM_REQ:.spec.containers[*].resources.requests.memory"
```

> **Подробнее:** [Metrics Server](../../MonitoringLogging/metrics-server.md), [CPU Throttling](../../Troubleshooting/Common_Errors/cpu_throttling.md).

### Сценарий 7: Копирование файлов между Pod и локальной машиной

```bash
# Копирование файла из контейнера на локальную машину
kubectl cp <namespace>/<pod-name>:/var/log/app.log ./app.log

# Копирование файла с указанием контейнера (для multi-container Pod)
kubectl cp <namespace>/<pod-name>:/var/log/app.log ./app.log -c app-container

# Копирование каталога из контейнера
kubectl cp <namespace>/<pod-name>:/app/config ./config-dir

# Копирование локального файла в контейнер
kubectl cp ./config.yaml <namespace>/<pod-name>:/app/config/config.yaml

# Копирование через stdin (из pipe)
cat ./local-config.yaml | kubectl exec -i <pod-name> -- tee /app/config/config.yaml > /dev/null

# Копирование логов Pod на локальную машину (без kubectl cp)
kubectl logs <pod-name> > pod-logs.txt

# Копирование логов предыдущего запуска
kubectl logs <pod-name> --previous > pod-crash-logs.txt
```

> **Ограничения:** `kubectl cp` не работает с контейнерами без `tar` (например, `distroless`, `scratch`). В таких случаях используйте `kubectl exec` с pipe'ом или эфемерные контейнеры.

### Сценарий 8: Сетевая отладка Pod

```bash
# Запуск отладочного контейнера в сетевом пространстве Pod
kubectl debug -it <pod-name> --image=nicolaka/netshoot --target=<container-name>

# Внутри отладочного контейнера:
# nslookup kubernetes.default          -- проверка DNS
# curl -v http://my-service:8080       -- проверка HTTP-соединения
# nc -zv my-service 8080               -- проверка TCP-соединения
# tcpdump -i eth0 -w capture.pcap      -- захват трафика
# ip route show                        -- проверка маршрутизации

# Проверка DNS внутри Pod
kubectl exec -it <pod-name> -- nslookup kubernetes.default
# → Server:    10.96.0.10
# → Address:   10.96.0.10#53
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.96.0.1

# Проверка доступности сервиса из Pod
kubectl exec -it <pod-name> -- curl -s http://my-service:8080/health

# Проверка сетевых политик (NetworkPolicy)
kubectl get networkpolicy -A
kubectl describe networkpolicy <policy-name>

# Диагностика DNS-проблем
kubectl get pods -n kube-system -l k8s-app=kube-dns
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=50
```

> **Подробнее:** [Диагностика сетевого взаимодействия](../../Troubleshooting/troubleshooting_overview.md#диагностика-сетевого-взаимодействия), [Эфемерные контейнеры](./ephemeral_containers.md).

### Сценарий 9: Проверка RBAC-разрешений

```bash
# Проверка: может ли ServiceAccount создавать подов?
kubectl auth can-i create pods --as system:serviceaccount:default:my-sa
# → yes

# Проверка: может ли пользователь удалять поды в namespace?
kubectl auth can-i delete pods --as jane.doe
# → no

# Проверка всех доступных действий для ServiceAccount
kubectl auth can-i --list --as system:serviceaccount:default:my-sa

# Проверка доступа к конкретному ресурсу
kubectl auth can-i get pods --as system:serviceaccount:monitoring:prometheus -n kube-system
# → yes

# Проверка доступа через subresource
kubectl auth can-i get pods/log --as system:serviceaccount:default:my-sa
# → yes

# Диагностика ошибок Forbidden
kubectl get pods -n kube-system -l k8s-app=kube-dns  # если Forbidden — проблема в RBAC
```

> **Подробнее:** [RBAC в Kubernetes](../../Security/rbac/roles.md).

### Сценарий 10: Просмотр событий кластера

`kubectl get events` показывает хронологию всех событий — планирование, ошибки запуска, обновления, выселения.

```bash
# Все события в текущем namespace (отсортированные по времени)
kubectl get events --sort-by='.lastTimestamp'

# События только для конкретного Pod
kubectl get events --field-selector involvedObject.name=<pod-name>

# События в конкретном namespace
kubectl get events -n kube-system

# События типа Warning (ошибки)
kubectl get events --field-selector type=Warning

# События с фильтрацией по.reason
kubectl get events --field-selector reason=FailedScheduling

# Форматированный вывод с таймстампами
kubectl get events -o custom-columns="TIME:.lastTimestamp,TYPE:.type,REASON:.reason,OBJECT:.involvedObject.name,MESSAGE:.message"

# События за последние N минут (через pipe)
kubectl get events --sort-by='.lastTimestamp' | tail -20

# Мониторинг событий в реальном времени
kubectl get events -w
```

### Сценарий 11: Быстрое создание Pod для отладки

```bash
# Запуск временного Pod для проверки DNS
kubectl run dns-test --image=busybox --rm -it --restart=Never -- nslookup kubernetes.default

# Запуск временного Pod для проверки сетевой связности
kubectl run net-test --image=busybox --rm -it --restart=Never -- wget -qO- --timeout=5 http://my-service:8080

# Запуск Pod с sleep для последующего exec
kubectl run debug-pod --image=busybox --rm -it --restart=Never -- sleep 3600

# Запуск Pod с hostNetwork для проверки DNS узла
kubectl run dns-node-test --image=busybox --rm -it --restart=Never --host-network -- nslookup 8.8.8.8

# Запуск Pod с volume для проверки данных
kubectl run vol-test --image=busybox --rm -it --restart=Never \
  --overrides='{"spec":{"volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"my-pvc"}}],"containers":[{"name":"vol-test","image":"busybox","command":["sh"],"volumeMounts":[{"name":"data","mountPath":"/data"}]}]}}' \
  -- ls -la /data
```

### Сценарий 12: Редактирование Pod напрямую (editing in place)

```bash
# Интерактивное редактирование Pod в дефолтном редакторе
kubectl edit pod <pod-name>

# Быстрое изменение конкретного поля через patch
kubectl patch pod <pod-name> -p '{"metadata":{"annotations":{"maintenance":"true"}}}'

# Добавление метки к Pod
kubectl label pod <pod-name> debug=true

# Удаление метки с Pod
kubectl label pod <pod-name> debug-

# Добавление аннотации к Pod
kubectl annotate pod <pod-name> description="temporary debug instance"

# Удаление аннотации
kubectl annotate pod <pod-name> description-
```

> **Подробнее:** [Метки, аннотации и выбор узлов](./pod_labels_annotations_node_selection.md), [Метаданные, метки и аннотации](../../Concepts/metadata_and_labels.md).

### Сценарий 13: Очистка завершенных Pod

```bash
# Удаление всех завершенных Pod (Succeeded/Failed)
kubectl delete pods --field-selector=status.phase=Succeeded
kubectl delete pods --field-selector=status.phase=Failed

# Удаление Pod с определённой меткой
kubectl delete pods -l cleanup=true

# Удаление Pod старше определённого времени (через jq)
kubectl get pods -o json | jq -r '.items[] | select(.status.phase=="Succeeded") | .metadata.name' | xargs kubectl delete pod

# Очистка Job Pod (после завершения)
kubectl delete pods -l job-name=my-job

# Очистка всех Pod в namespace (кроме системных)
kubectl delete pods --all -n my-namespace
```

---

## Troubleshooting: типичные ошибки команд

### Ошибка 1: `kubectl exec` — « unable to upgrade connection: container not found»

**Причина:** Контейнер не запущен, находится в `Waiting` или `Terminated`��态е.

**Решение:** Проверьте статус контейнера:
```bash
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].state}'
# → {"running":{"startedAt":"2026-01-15T10:00:00Z"}}
```
Если контейнер в `Waiting` — используйте `kubectl logs <pod-name>` для просмотра логов запуска.

### Ошибка 2: `kubectl exec` — « OCI runtime exec failed: exec failed: unable to start container process: exec: "sh": executable file not found in $PATH»

**Причина:** В образе отсутствует shell (`sh`, `bash`). Типично для `distroless` и `scratch` образов.

**Решение:** Используйте эфемерные контейнеры:
```bash
kubectl debug -it <pod-name> --image=busybox --target=<container-name>
```
Подробнее: [Эфемерные контейнеры](./ephemeral_containers.md).

### Ошибка 3: `kubectl cp` — « tar: removinig leading '/' from member names»

**Причина:** kubectl cp автоматически убирает ведущий `/` из абсолютных путей.

**Решение:** Используйте относительные пути или учитывайте это поведение:
```bash
# Правильно (абсолютный путь работает, но архив будет с относительными путями)
kubectl cp <pod-name>:/var/log/app.log ./app.log

# Неправильно (попытка сохранить структуру каталогов)
kubectl cp <pod-name>:/var/log/ ./logs/
```

### Ошибка 4: `kubectl port-forward` — « Unable to listen on port»

**Причина:** Локальный порт уже занят другим процессом.

**Решение:** Проверьте, какой процесс использует порт, и выберите другой:
```bash
lsof -i :8080
# → COMMAND  PID  USER   FD   TYPE DEVICE NODE NAME
# → nginx   1234  user   6u  IPv4  ...    TCP *:8080 (LISTEN)

# Использовать другой локальный порт
kubectl port-forward pod/<name> 9090:80
```

### Ошибка 5: `kubectl wait` — « error: timed out waiting for the condition on pods»

**Причина:** Pod не достиг указанного условия за отведённое время.

**Решение:** Проверьте статус Pod и увеличьте таймаут:
```bash
# Проверка текущего статуса
kubectl get pod <pod-name> -o wide

# Проверка Conditions
kubectl get pod <pod-name> -o jsonpath='{.status.conditions[*].type}'

# Увеличение таймаута
kubectl wait --for=condition=Ready pod/<pod-name> --timeout=300s
```

### Ошибка 6: `kubectl delete pod` — « The Pod "..." is invalid»

**Причина:** Pod принадлежит ReplicaSet/Deployment и будет пересоздан контроллером.

**Решение:** Удаляйте через контроллер или уменьшите количество реплик:
```bash
# Через контроллер (правильный путь)
kubectl scale deployment <name> --replicas=0

# Или удаление с игнорированием каскадного удаления (опасно!)
kubectl delete pod <name> --cascade=orphan
```

### Ошибка 7: `kubectl logs` — « a container name must be specified for pod»

**Причина:** Pod содержит несколько контейнеров, kubectl не может определить целевой.

**Решение:** Укажите контейнер явно или используйте `--all-containers`:
```bash
kubectl logs <pod-name> -c <container-name>
# или
kubectl logs <pod-name> --all-containers
```

### Ошибка 8: `kubectl auth can-i` — «yes» (ожидалось «no»)

**Причина:** `auth can-i` проверяет разрешения конкретного пользователя, но не учитывает `deny` правила (Kubernetes не поддерживает deny rules в RBAC). Также не учитывает NetworkPolicy и Admission Controllers.

**Решение:** Для полной проверки доступа используйте `kubectl auth can-i --list` и проверяйте все доступные действия:
```bash
kubectl auth can-i --list --as system:serviceaccount:default:my-sa
```

---

## Best Practices

1. **Используйте `-o wide`** для `kubectl get pods` — расширенный вывод показывает IP, узел и Runtime, что критично для диагностики.
2. **Указывайте `-c <container>`** при работе с multi-container Pod — по умолчанию kubectl обращается к первому контейнеру, что может не совпадать с ожиданиями.
3. **Не используйте `kubectl exec` для Production-систем** без предварительного `kubectl describe` — сначала проверьте Events и логи.
4. **Для CI/CD используйте `kubectl wait`** вместо `sleep` — это идиоматичный и надёжный способ ожидания готовности.
5. **Сохраняйте логи падающих Pod** через `kubectl logs --previous > crash.log` перед удалением — после удаления Pod логи недоступны.
6. **Используйте `kubectl cp` с осторожностью** — команда копирует только файлы, доступные контейнерному рантайму; для `distroless` образов используйте эфемерные контейнеры.
7. **Избегайте `kubectl port-forward` в Production** — используйте Ingress, LoadBalancer или VPN для постоянного доступа.
8. **Проверяйте RBAC через `kubectl auth can-i`** перед выполнением команд в автоматизированных скриптах — это предотвращает неожиданные ошибки `Forbidden`.
9. **Используйте `--field-selector`** для быстрой фильтрации Pod по статусу — это работает на стороне API-сервера и эффективнее локальной фильтрации.
10. **Для отладки сетевых проблем** используйте `kubectl debug` с `netshoot` вместо установки инструментов в production Pod — это не требует изменения образа.

---

## Связанные темы

* [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — теория фаз и условий.
* [Перезапуск Pod в Kubernetes](./pod_restarts.md) — различие между перезапуском и пересозданием.
* [Пробы в Kubernetes (Probes)](../probes.md) — настройка Liveness/Readiness.
* [Эфемерные контейнеры](./ephemeral_containers.md) — глубокая отладка через `kubectl debug`.
* [Graceful Shutdown](../../Troubleshooting/Common_Errors/PodTerminating/graceful_shutdown.md) — детали процесса остановки.
* [Траблшутинг Kubernetes](../../Troubleshooting/troubleshooting_overview.md) — общий алгоритм диагностики.
