# Ephemeral Container в Kubernetes

## Определения

**Ephemeral Container (Эфемерный контейнер)** — временный контейнер, запускаемый в существующем работающем Pod для выполнения административных действий: отладки, инспектирования состояния или траблшутинга. В отличие от основных контейнеров, они не предназначены для выполнения бизнес-логики и не гарантируют доступность. Ключевое отличие от обычных контейнеров — эфемерные контейнеры **не имеют lifecycle hooks** (postStart/preStop), **не поддерживают пробы** (liveness/readiness/startup) и **не перезапускаются** автоматически после завершения.

**Distroless-образ** — минималистичный образ контейнера, содержащий только приложение и его зависимости (без shell, пакетных менеджеров и утилит). Отладка таких образов невозможна через `kubectl exec` и требует использования эфемерных контейнеров или `kubectl debug`.

**Профили отладки (Debug Profiles)** — предустановленные наборы конфигураций `securityContext` для `kubectl debug`, позволяющие быстро адаптировать отладочный контейнер под политики безопасности кластера (PSA). Профили определяют, какие Linux capabilities, volume mounts и namespace доступны отладочному контейнеру.

**Копия Pod (Copy-to)** — отладочная копия Pod, создаваемая флагом `--copy-to`, которая позволяет модифицировать `command`, `args`, `env` и другие поля контейнеров без влияния на оригинальный Pod. Используется для воспроизведения ошибок в изолированной среде.

---

## Базовые концепции

### Общие сведения

*   **Стабильность:** Механизм является стабильным (GA) с Kubernetes v1.25.
*   **Управление:** Создаются через специализированный эндпоинт `/ephemeralcontainers` в API Kubernetes. Их нельзя добавить через прямую модификацию YAML-манифеста Pod или команду `kubectl edit`. Доступные методы: `kubectl debug`, `kubectl` API (через `kubectl get --raw`), или прямой PUT-запрос к API.
*   **Жизненный цикл:**
    *   Не перезапускаются автоматически при завершении (`restartPolicy: Never` для обычных ephemeral).
    *   Удаляются вместе с родительским Pod.
    *   **Неизменяемость:** После добавления в Pod эфемерный контейнер нельзя изменить или удалить (до удаления всего Pod). Это ограничение API — поле `ephemeralContainers` доступно только для записи (append-only).
*   **Ограничения:** Не поддерживаются для статических подов (Static Pods), управляемых Kubelet напрямую.

### Ограничения спецификации

Хотя эфемерные контейнеры используют структуру `Container`, многие поля для них запрещены или игнорируются на уровне API:

| Поле | Статус | Причина |
| :--- | :--- | :--- |
| `ports` | **Запрещено** | Не могут открывать сетевые порты для внешнего доступа. |
| `resources` | **Ограничено** | Ресурсы Pod фиксируются при создании. Эфемерные контейнеры не влияют на QoS-класс Pod, но `limits.memory` может вызвать OOMKill ephemeral-контейнера. |
| `probes` | **Запрещено** | Не поддерживают Liveness, Readiness и Startup пробы. |
| `lifecycle` | **Запрещено** | Обработчики `postStart` и `preStop` неываются. |
| `volumeMounts` | **Доступно** | Можно монтировать существующие тома Pod (emptyDir, configMap, secret, PVC). |

### Влияние на QoS и ресурсы Pod

Эфемерные контейнеры **не влияют на QoS-класс** родительского Pod — их ресурсы не суммируются с основными контейнерами при расчете `EffectiveRequest`/`EffectiveLimit`. Однако:

*   **limits.memory:** Если указан, эфемерный контейнер будет OOMKill при превышении (но Pod не будет выселен из-за этого).
*   **limits.cpu:** Квота CPU берется из общей квоты Pod. Если Pod уже исчерпал CPU-лимит, эфемерный контейнер будет CPU-throttled.
*   **requests:** Игнорируются планировщиком — эфемерный контейнер может быть запущен на узле, где нет свободных ресурсов, указанных в requests.

**Рекомендация:** Указывайте `resources.limits` для защиты от бесконтрольного потребления памяти эфемерным контейнером, но не полагайтесь на `resources.requests` для планирования.

### securityContext и безопасность

Эфемерные контейнеры наследуют `securityContext` Pod, но могут переопределять отдельные поля:

```yaml
securityContext:
  runAsUser: 1000          # Переопределение пользователя
  runAsNonRoot: true        # Принудительный non-root
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
    add: ["NET_RAW"]        # Для tcpdump (требуется特权)
```

**Ограничения PSA (Pod Security Admission):**
*   Профиль `restricted` запрещает `privileged: true` и `hostNetwork: true` — эфемерный контейнер не сможет получить доступ к хостовым ресурсам.
*   Профиль `baseline` разрешает базовые операции — подходит для большинства задач отладки.
*   Профиль `sysadmin` требует `CAP_SYS_ADMIN` и доступ к хостовым namespace — используйте только для инспектирования узлов.

Подробнее: [Безопасность Pod](../../Security/pod_security_context.md).

### Профили и безопасность (v1.30+)

Начиная с v1.30, `kubectl debug` поддерживает профили безопасности, что критично для работы в защищенных средах (PSA):

| Профиль | Назначение | capabilities | hostNetwork | privileged |
| :--- | :--- | :--- | :--- | :--- |
| **`general`** | Базовые настройки для большинства задач (дефолт) | NET_BIND_SERVICE | Нет | Нет |
| **`baseline`** | Соответствие Baseline PSS | Ограничены | Нет | Нет |
| **`restricted`** | Максимальные ограничения (non-root, запрет эскалации) | Запрещены | Нет | Нет |
| **`sysadmin`** | Расширенные привилегии для инспектирования узлов | SYS_ADMIN | Да | Да |
| **`netadmin`** | Сетевые возможности для анализа трафика | NET_ADMIN, NET_RAW | Нет | Нет |

**Применение профилей:**
*   `restricted` — для Pod в namespaces с PSA `enforce: restricted` (большинство production-сред).
*   `baseline` — для namespaces с PSA `enforce: baseline`.
*   `sysadmin` — только для отладки узлов (`kubectl debug node/`) или инспектирования системных компонентов.

---

## Практические сценарии

### Шаблон workflow: Отладка упавшего Pod

```bash
# 1. Проверка статуса и events
kubectl describe pod <pod-name> | grep -A 10 "Events"
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].lastState.terminated}'

# 2. Логи с предыдущего запуска (если контейнер перезапустился)
kubectl logs <pod-name> -c <container-name> --previous

# 3. Добавление ephemeral контейнера для интерактивной отладки
kubectl debug -it <pod-name> --image=nicolaka/netshoot --target=<container-name>

# 4. Внутри отладочного контейнера:
#    curl -v http://localhost:8080/health    # Проверка health endpoint
#    nslookup <service-name>                 # Проверка DNS
#    tcpdump -i eth0 -w /tmp/capture.pcap   # Захват трафика
#    ps aux                                  # Просмотр процессов
```

### Шаблон workflow: Диагностика сетевой связности

```bash
# Вариант 1: Ephemeral контейнер с инструментами
kubectl debug <pod> -it --image=nicolaka/netshoot
# Внутри: curl -v http://service.namespace.svc.cluster.local:8080

# Вариант 2: Если нужен доступ к файловой системе целевого контейнера
kubectl debug <pod> -it --image=nicolaka/netshoot --target=<container>
# Внутри: ls /app/config/, cat /etc/resolv.conf

# Вариант 3: Копия Pod для воспроизведения сетевого окружения
kubectl debug <pod> -it --image=nicolaka/netshoot --copy-to=debug-pod

# Вариант 4: Если в контейнере есть bash
kubectl exec <pod> -- bash -c 'echo > /dev/tcp/service/8080 && echo OK || echo FAIL'
```

### Шаблон workflow: Профилирование приложения (CPU/Memory)

```bash
# Добавление ephemeral контейнера с инструментами профилирования
kubectl debug -it <pod> --image=nicolaka/netshoot --target=<app-container>

# Внутри отладочного контейнера:
# Просмотр процессов и потребления ресурсов
ps aux --sort=-%mem | head -20
top -bn1 | head -20

# Захват CPU-профиля (если приложение поддерживает pprof)
curl -o /tmp/cpu.prof http://localhost:6060/debug/pprof/profile?seconds=30

# Захват memory-профиля
curl -o /tmp/mem.prof http://localhost:6060/debug/pprof/heap

# Анализ сетевого трафика
tcpdump -i eth0 -nn port 8080 -w /tmp/capture.pcap
```

### Шаблон workflow: Forensic-анализ инцидента

```bash
# 1. Захват состояния Pod BEFORE удаления (если Pod еще жив)
kubectl get pod <pod> -o yaml > /tmp/pod-manifest-backup.yaml
kubectl logs <pod> > /tmp/pod-logs-full.txt 2>&1
kubectl describe pod <pod> > /tmp/pod-describe.txt

# 2. Добавление ephemeral контейнера для сбора артефактов
kubectl debug -it <pod> --image=ubuntu:24.04 --profile=sysadmin
# Внутри:
#   tar czf /tmp/artifacts.tar.gz /app/logs /app/config /tmp
#   cp /proc/1/cmdline /tmp/cmdline.txt
#   cat /proc/1/environ | tr '\0' '\n' > /tmp/env.txt

# 3. Если Pod уже упал — создание копии для анализа
kubectl debug <pod> -it --copy-to=forensic-pod --container=<app-container> -- sh
```

Полные сценарии forensic-расследования, включая реагирование на инциденты, изоляцию компрометированных подов и сбор доказательств, описаны в [Реагирование на инциденты безопасности](../../Security/incident_response.md).

### Шаблон workflow: Проверка конфигурации и зависимостей

```bash
# Проверка переменных окружения
kubectl debug -it <pod> --image=alpine --target=<container>
# Внутри:
#   env | sort | grep -E "DB_|REDIS_|API_"
#   cat /etc/resolv.conf

# Проверка доступности внешних сервисов
kubectl debug -it <pod> --image=nicolaka/netshoot
# Внутри:
#   curl -sf http://external-api:8080/health
#   nc -zv database 5432
#   dig +short service-name.namespace.svc.cluster.local

# Проверка прав доступа к TOM
kubectl debug -it <pod> --image=alpine --target=<container>
# Внутри:
#   ls -la /var/run/secrets/
#   cat /etc/app/config.yaml
```

### Сценарий 1: Отладка Distroless-контейнера

Подключение к поду, в котором нет `/bin/sh`, с использованием образа для сетевой диагностики:

```bash
kubectl debug -it <pod_name> \
  --image=nicolaka/netshoot \
  --target=<container_name> \
  --profile=netadmin
```
*   `--target`: Позволяет видеть файловую систему и процессы целевого контейнера.
*   `--profile=netadmin`: Дает права на использование `tcpdump` и других низкоуровневых инструментов.

### Сценарий 2: Анализ процессов через общий PID Namespace

Если в спецификации Pod не включено `shareProcessNamespace: true`, это можно сделать «на лету» через отладочную копию:

```bash
kubectl debug <pod_name> \
  -it \
  --image=alpine \
  --share-processes \
  --copy-to=debug-pod-v2
```

### Сценарий 3: Использование кастомных профилей (v1.31+)

Для специфических нужд (например, проброс переменных окружения или монтирование томов) можно использовать YAML-файл конфигурации:

```yaml
# custom-debug.yaml
env:
  - name: DEBUG_TOKEN
    valueFrom:
      secretKeyRef:
        name: debug-secrets
        key: token
volumeMounts:
  - name: app-logs
    mountPath: /var/log/app
```

Запуск с кастомным профилем:
```bash
kubectl debug <pod_name> -it --image=ubuntu --custom=custom-debug.yaml
```

### Сценарий 4: Диагностика сетевой связности между подами

**Задача:** Проверить доступность одного пода с другого, когда в поде нет сетевых утилит (distroless или минимальный образ).

**Методы:**

1. **Ephemeral Container с нужными инструментами** — наиболее правильный подход:

```bash
# Добавить отладочный контейнер с сетевыми утилитами
kubectl debug <source_pod> -it --image=nicolaka/netshoot

# Внутри ephemeral контейнера:
curl http://<service_name>.<namespace>.svc.cluster.local:8080/health
# или
nc -zv <service_name>.<namespace>.svc.cluster.local 8080
```

2. **Отладочная копия Pod на той же ноде** — если нужно воспроизвести сетевое окружение:

```bash
# Создать копию pod с инструментами отладки
kubectl debug <pod_name> -it --image=nicolaka/netshoot --copy-to=debug-pod
```

3. **Bash /dev/tcp** — если в контейнере есть bash, но нет curl/nc:

```bash
# Проверка TCP-порта без дополнительных утилит
kubectl exec <pod_name> -- bash -c 'echo > /dev/tcp/<service>/8080 && echo OK || echo FAIL'
```

4. **Proc filesystem** — через /proc/{pid}/net/tcp можно увидеть состояние TCP-соединений процесса:

```bash
# Просмотр активных TCP-соединений контейнера
kubectl exec <pod_name> -- cat /proc/1/net/tcp
```

**Важно:** Команды вроде `echo > /dev/tcp/host/port` работают только если в контейнере есть bash с поддержкой /dev/tcp (опция `HAVE_DEV_TCP` при компиляции). В busybox/alpine bash обычно включен, в distroless — нет.

### Сценарий 5: Отладка узла через ephemeral контейнер

Запуск контейнера в пространстве имен хоста для инспектирования `kubelet` или конфигурации сети узла:

```bash
kubectl debug node/<node_name> -it --image=ubuntu:24.04 --profile=sysadmin
```
*Файловая система узла будет доступна по пути `/host`.*

**Примеры диагностики внутри узла:**
```bash
# Проверка состояния kubelet
chroot /host systemctl status kubelet

# Просмотр конфигурации CNI
ls /host/etc/cni/net.d/
cat /host/etc/cni/net.d/*.conf

# Проверка disk space на узле
df -h /host

# Просмотр логов kubelet
journalctl -u kubelet --no-pager -n 50 --root=/host
```

### Сценарий 6: Отладка Job и CronJob

Ephemeral контейнеры работают с Job и CronJob, но с ограничениями:

```bash
# Добавление ephemeral контейнера к завершающемуся Job
kubectl debug -it <job-pod> --image=nicolaka/netshoot

# Проверка логов завершенного Job перед перезапуском
kubectl logs <job-pod> --previous

# Для CronJob: создание отладочной копии для воспроизведения
kubectl debug <job-pod> --copy-to=debug-job --image=ubuntu:24.04 -- sh
```

**Ограничение:** Если Job уже завершен (status: Succeeded/Failed), Pod удалится, и ephemeral контейнер не будет добавлен. Используйте `kubectl logs --previous` или `--copy-to` до завершения Pod.

### Сценарий 7: Отладка DaemonSet Pod

DaemonSet Pod на разных узлах могут вести себя по-разному. Ephemeral контейнеры позволяют отладить конкретный Pod:

```bash
# Определение Pod'а на проблемном узле
kubectl get pods -l <daemonset-label> -o wide | grep <problem-node>

# Добавление ephemeral контейнера
kubectl debug -it <daemonset-pod> --image=nicolaka/netshoot --target=<container>

# Проверка файловой системы узла (через volume mount)
kubectl debug -it <daemonset-pod> --image=alpine --target=<container>
# Внутри:
#   ls /host/var/log/           # если замонтирован hostPath
#   cat /host/etc/kubernetes/kubelet.conf
```

### Сценарий 8: Диагностика статусов ephemeral контейнеров

```bash
# Просмотр статуса всех ephemeral контейнеров в Pod
kubectl get pod <pod> -o jsonpath='{.status.ephemeralContainerStatuses}'
# → [{"name":"debugger","state":{"running":{...}},"ready":true,"restartCount":0}]

# Просмотр конкретного ephemeral контейнера
kubectl get pod <pod> -o jsonpath='{.status.ephemeralContainerStatuses[?(@.name=="debugger")].state}'

# Просмотр логов ephemeral контейнера
kubectl logs <pod> -c debugger

# Проверка, что ephemeral контейнер добавлен
kubectl describe pod <pod> | grep -A 5 "Ephemeral Containers"
```

---

## Troubleshooting: типичные ошибки ephemeral контейнеров

### Ошибка 1: Отказ в добавлении ephemeral контейнера (Forbidden)

**Причина:** PSA (Pod Security Admission) запрещает операцию или RBAC не разрешает доступ к `ephemeralcontainers` subresource.

**Диагностика:**
```bash
kubectl describe pod <pod> | grep -A 3 "Warning"
# → Warning  FailedCreate  Error creating pod: pods "..." is forbidden:
#   violates PodSecurity "restricted:latest": ...ephemeral containers ...

kubectl auth can-i create pods/ephemeralcontainers --as=<user>
# → no
```

**Решение:**
1. Проверьте PSA-политику в Namespace:
```bash
kubectl label namespace <ns> pod-security.kubernetes.io/enforce-  # Временно ослабить
```
2. Используйте `--profile=restricted` для соответствия политике:
```bash
kubectl debug -it <pod> --image=busybox --profile=restricted
```
3. Проверьте RBAC: создайте ClusterRole для доступа к ephemeralcontainers.

### Ошибка 2: Ephemeral контейнер не может видеть процессы основного контейнера

**Причина:** `shareProcessNamespace: false` (по умолчанию) — каждый контейнер в Pod имеет свой PID namespace.

**Диагностика:**
```bash
kubectl debug -it <pod> --image=alpine --target=<container>
# Внутри:
#   ps aux    # Видны только процессы ephemeral контейнера
```

**Решение:**
1. Используйте флаг `--share-processes`:
```bash
kubectl debug -it <pod> --image=alpine --target=<container> --share-processes
```
2. Или добавьте `--copy-to` с `--share-processes` для полного доступа:
```bash
kubectl debug <pod> -it --copy-to=debug-pod --share-processes --image=alpine
```

### Ошибка 3: OOMKill ephemeral контейнера

**Причина:** Эфемерный контейнер превысил `limits.memory`. Unlike app containers, Pod не перезапускается — ephemeral контейнер просто умирает.

**Диагностика:**
```bash
kubectl get pod <pod> -o jsonpath='{.status.ephemeralContainerStatuses[*].lastState.terminated.reason}'
# → OOMKilled
```

**Решение:**
1. Увеличьте `limits.memory` при добавлении:
```bash
kubectl debug -it <pod> --image=ubuntu --overrides='{"spec":{"ephemeralContainers":[{"name":"debugger","image":"ubuntu","resources":{"limits":{"memory":"512Mi"}}}]}}'
```
2. Используйте легковесные образы (`alpine`, `busybox`) вместо тяжелых (`ubuntu`, `netshoot`).

### Ошибка 4: Ephemeral контейнер не может записать в Volume

**Причина:** Volume монтирован как `readOnly: true` или не поддерживает запись.

**Диагностика:**
```bash
kubectl debug -it <pod> --image=alpine --target=<container>
# Внутри:
#   touch /var/log/app/test.log    # → Read-only file system
```

**Решение:**
1. Проверьте `volumeMounts.readOnly` в манифесте Pod.
2. Для `configMap` и `secret` — тома доступны только для чтения.
3. Используйте `emptyDir` для записи:
```yaml
volumes:
- name: debug-workspace
  emptyDir: {}
```
4. Монтируйте workspace в ephemeral контейнер через `--custom`:
```yaml
volumeMounts:
- name: debug-workspace
  mountPath: /workspace
```

### Ошибка 5: `--target` не работает (контейнер не найден)

**Причина:** Имя контейнера указано неверно или целевой контейнер не существует.

**Диагностика:**
```bash
kubectl get pod <pod> -o jsonpath='{.spec.containers[*].name}'
# → app-1 app-2

kubectl debug -it <pod> --image=alpine --target=app-3
# → error: container "app-3" not found in pod "<pod>"
```

**Решение:**
1. Проверьте имена контейнеров: `kubectl get pod <pod> -o jsonpath='{.spec.containers[*].name}'`
2. Для init-контейнеров: `kubectl get pod <pod> -o jsonpath='{.spec.initContainers[*].name}'`
3. Убедитесь, что контейнер запущен (не в Waiting/Waiting state).

### Ошибка 6: Ephemeral контейнер не виден в `kubectl get pods`

**Причина:** `kubectl get pods` по умолчанию не показывает ephemeral контейнеры.

**Диагностика:**
```bash
kubectl get pods -o yaml | grep -A 5 "ephemeralContainers"
# Или:
kubectl describe pod <pod> | grep -A 10 "Ephemeral Containers"
```

**Решение:**
1. Используйте `-o jsonpath` или `-o yaml` для полного вывода.
2. `kubectl get pods` показывает только основные контейнеры — ephemeral отображаются отдельно.

---

## Сравнение методов отладки Pod

| Метод | Использование | Создание нового Pod | Сохранение IP | Сохранение файловой системы | Replay ошибки |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `kubectl exec` | Интерактивная отладка запущенного контейнера | Нет | Да | Да (оригинальная) | Нет |
| `kubectl debug <pod>` | Добавление ephemeral контейнера «на лету» | Нет | Да | Да (с target) | Нет |
| `kubectl debug --copy-to` | Глубокая отладка с модификацией контейнера | Да | Нет | Копия | Да |
| `kubectl debug node/` | Инспектирование узла | Да (специальный) | N/A | N/A | Нет |
| `kubectl port-forward` | Проброс порта для IDE/инструментов | Нет | Да | Да | Нет |
| `kubectl cp` | Копирование файлов из/в контейнер | Нет | Да | Да | Нет |

### Когда использовать каждый метод

| Задача | Рекомендуемый метод |
| :--- | :--- |
| Проверка логов и переменных | `kubectl exec` |
| Сетевая диагностика (curl, nc, dig) | `kubectl debug` с netshoot |
| Анализ процессов в distroless-образе | `kubectl debug --target` + `--share-processes` |
| Воспроизведение ошибки в изоляции | `kubectl debug --copy-to` |
| Инспектирование узла (kubelet, сеть) | `kubectl debug node/` |
| Подключение IDE к процессу | `kubectl port-forward` |
| Копирование артефактов (логи, дампы) | `kubectl cp` или ephemeral + `tar` |
| Forensic-анализ после инцидента | `kubectl debug` + `--profile=sysadmin` |

---

## Best Practices для Production

1.  **Минимализм образов:** Используйте `alpine`, `busybox`, `nicolaka/netshoot` вместо `ubuntu` или `debian`. Уменьшает время pull и потребление памяти.
2.  **Указывайте limits:** Всегда задавайте `resources.limits.memory` для защиты от OOMKill. Пример: `--overrides='{"spec":{"ephemeralContainers":[{"name":"debug","image":"alpine","resources":{"limits":{"memory":"128Mi"}}}]}}'`.
3.  **Профили PSA:** Используйте `--profile=restricted` или `--profile=baseline` в средах с PSA enforce. Проверяйте политику Namespace перед отладкой.
4.  **Ограничение по времени:** Ephemeral контейнеры не имеют `activeDeadlineSeconds` — удаляйте их вручную после завершения отладки (через удаление Pod или API).
5.  **Безопасность:** Не запускайте ephemeral контейнеры с `privileged: true` в production. Используйте `--profile=netadmin` для сетевых задач, `--profile=sysadmin` только для узлов.
6.  **Сбор артефактов:** Перед удалением Pod собирайте логи (`kubectl logs --previous`), манифесты (`kubectl get pod -o yaml`), и события (`kubectl describe pod`).
7.  **shareProcessNamespace:** Включайте `shareProcessNamespace: true` в манифесте Pod для облегчения отладки процессов между контейнерами.
8.  **Избегайте копирования:** Используйте `kubectl debug <pod>` вместо `--copy-to` когда возможно — копия Pod не сохраняет IP и может не воспроизвести сетевые условия.

---

## Дополнительная информация

### Сравнение с альтернативными методами

| Метод | Преимущества | Недостатки |
| :--- | :--- | :--- |
| **Ephemeral Container** | Не перезапускает Pod, доступ к FS и процессам, PSA-совместим | Неизменяем, нет probes/lifecycle |
| **kubectl exec** | Простой, быстрый, работает с запущенным контейнером | Только если есть shell, не работает в distroless |
| **port-forward** | Проброс порта для IDE, безопасный | Только сетевой доступ, нет FS |
| **Copy-to Pod** | Полная модификация контейнера, replay ошибок | Создает новый Pod, теряет IP |
| **Debug Node** | Полный доступ к узлу | Привилегированный, затрагивает все Pod'ы на узле |

### Диагностика эфемерных контейнеров

Чтобы увидеть статус эфемерных контейнеров в уже запущенном поду:

```bash
kubectl get pod <pod_name> -o jsonpath='{.status.ephemeralContainerStatuses}'
```

### Связанные темы

- [Отладка образов Distroless](../../../Docker/Docker_troubleshooting/debugging_distroless.md) — общие принципы и подходы.
- [Жизненный цикл и состояния Pod](./pod_lifecycle_and_state.md) — как эфемерные контейнеры влияют на фазы Pod.
- [Практические команды управления Pod](./pod_practical_scenarios_commands.md) — расширенный список команд диагностики.
- [Поиск и устранение неисправностей в Kubernetes](../../Troubleshooting/troubleshooting_overview.md) — общая методология.
