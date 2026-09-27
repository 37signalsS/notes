# Поиск и устранение неисправностей: Диагностика CrashLoopBackOff

## Определения

**Диагностика CrashLoopBackOff** — систематический процесс выявления причин циклического перезапуска контейнеров в Kubernetes. Цель процесса — последовательное исключение проблем на уровнях инфраструктуры, конфигурации среды, сетевой связности и внутренней логики приложения.

Полное описание механизмов BackOff, политик перезапуска и кодов завершения приведено в файле:
> **[Определения и концепции CrashLoopBackOff](./definitions_and_concepts.md)**

## Быстрая сортировка (Triage) — первые 60 секунд

Для SRE на дежурстве: выполните эту последовательность до углублённого разбора.

```bash
# 1. Статус пода и количество перезапусков
kubectl get pod <pod-name> -o wide
# → NAME   READY   STATUS            RESTARTS   AGE   IP           NODE
# → app    0/1     CrashLoopBackOff  12         45m   10.244.1.5   worker-1

# 2. Причина последнего завершения и exit code
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].lastState.terminated}'
# → map[exitCode:1 reason:Error finishedAt:2024-01-15T10:30:00Z]

# 3. События пода (фильтрация по типу Warning)
kubectl events --for pod/<pod-name> --types=Warning --watch

# 4. Ресурсы (требуется Metrics Server)
kubectl top pod <pod-name>
# → NAME   CPU(cores)   MEMORY(bytes)
# → app    250m         512Mi

# 5. Быстрая проверка RBAC (если в логах есть Forbidden)
kubectl auth can-i get pods --as=system:serviceaccount:<ns>:<sa>
```

## Уровни диагностики (Методология)

Для минимизации времени восстановления (MTTR) рекомендуется следовать иерархической модели анализа «снизу вверх»:

1.  **Инфраструктурный уровень (Events):** Ошибки планирования, монтирования томов или нехватка ресурсов на узле.
2.  **Уровень состояния (Pod Status):** Анализ кодов завершения и метаданных контейнера в API.
3.  **Уровень приложения (Logs):** Изучение стандартного вывода (stdout/stderr) текущей и предыдущей итераций.
4.  **Уровень сетевой связности:** Проверка доступности внешних зависимостей и корректности работы DNS внутри пода.
5.  **Уровень интроспекции (Interactive Debug):** Прямое исследование файловой системы и окружения через эфемерные контейнеры.

## Пошаговый алгоритм диагностики

### Шаг 1: Анализ событий и текущего статуса

Первым делом необходимо проверить события кластера, связанные с подом. Современный способ — использование команды `kubectl events`, которая предоставляет более читаемый вывод, чем `kubectl get events`.

```bash
# Просмотр событий пода в реальном времени
kubectl events --for pod/<pod-name> --watch

# Детальный осмотр статуса и секции Last State
kubectl describe pod <pod-name>
```

```bash
# Структурированный вывод статуса контейнера (для парсинга скриптами)
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].name}{"\t"}{.status.containerStatuses[*].restartCount}{"\t"}{.status.containerStatuses[*].lastState.terminated.reason}{"\t"}{.status.containerStatuses[*].lastState.terminated.exitCode}{"\n"}'
```

```bash
# Проверка ресурсов потребления (требуется Metrics Server)
kubectl top pod <pod-name>
kubectl top node <node-name>
```

# → Результат:
# - Если `Reason: OOMKilled`, проблема в лимитах памяти.
# - Если `Liveness probe failed`, контейнер убивается Kubernetes из-за непрохождения проверок.
# - Если в событиях `FailedMount`, проблема в доступе к ConfigMap/Secret/PVC.
# - Если `Reason: Error` с `exitCode: 1` — смотрите логи приложения.
# - Если `Reason: RuntimeError` с `exitCode: 125` — проверьте манифест и рантайм.

### Шаг 2: Изучение логов (включая предыдущие запуски)

При `CrashLoopBackOff` контейнер часто падает до того, как вы успеете подключиться к логам. Флаг `--previous` позволяет прочитать вывод *уже завершившегося* экземпляра.

```bash
# Чтение логов предыдущей итерации
kubectl logs <pod-name> --previous

# Если в поде несколько контейнеров, укажите нужный
kubectl logs <pod-name> -c <container-name> --previous
```

```bash
# Проверка termination message (если приложение записывает причину в /dev/termination-log)
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.message}'
```

```bash
# Проверка статуса rollout для Deployment/StatefulSet
kubectl rollout status deployment/<name>
kubectl rollout history deployment/<name>
```

**Нюанс:** Если логи пусты, возможно:
- Приложение падает на этапе загрузки динамических библиотек или из-за ошибок в `ENTRYPOINT` (см. Шаг 4).
- Уровень логирования приложения слишком низкий (информация не выводится в stdout).
- Используется буферизация вывода (актуально для Python/Java), которая не успевает сброситься при краше.

### Шаг 3: Проверка Init-контейнеров

Если статус пода `Init:CrashLoopBackOff`, основной контейнер даже не пытался запуститься. Проверьте логи именно подготовительных контейнеров.

```bash
kubectl logs <pod-name> -c <init-container-name>
```

### Шаг 4: Интерактивная отладка через эфемерные контейнеры

Если приложение использует **distroless**-образы (без shell и утилит), используйте `kubectl debug`. Это позволяет запустить «соседний» контейнер с полным набором инструментов в тех же пространствах имен (Network, PID).

```bash
# Запуск отладочного образа netshoot для проверки сети и процессов
kubectl debug -it <pod-name> --image=nicolaka/netshoot --target=<container-name>
```

**Профили отладки (v1.23+):**
Вы можете использовать флаг `--profile` для специфических задач (доступны профили `general`, `baseline`, `restricted`, `sysadmin`, `netadmin`).

**Пример диагностики DNS и связности внутри пода:**
```bash
# Внутри отладочного контейнера
nslookup kubernetes.default.svc.cluster.local
curl -v http://db-service:5432
```

**Пример трассировки системных вызовов (strace):**
```bash
# Запуск отладчика с общей PID namespace и strace
kubectl debug -it <pod-name> --image=nicolaka/netshoot --target=<container-name> --share-processes
# Внутри:
strace -p 1 -f -tt -o /tmp/trace.log
```

**Пример захвата сетевого трафика (tcpdump):**
```bash
# Внутри отладочного контейнера с профилем netadmin
tcpdump -i eth0 -nn port 5430 -w /tmp/capture.pcap
```

### Шаг 5: Диагностика мгновенных крашей (Copy-to)

Если контейнер падает моментально, и `kubectl logs --previous` не дает информации, создайте копию пода с измененной точкой входа, чтобы «заморозить» его.

```bash
# Создание копии пода с заменой команды запуска на бесконечный сон
kubectl debug <pod-name> -it --copy-to=debug-pod --container=<app-container> -- sh
```

**Действия внутри копии:**
1.  **Проверка переменных:** `env | sort`.
2.  **Проверка прав на файлы:** `ls -la /var/run/secrets/`.
3.  **Ручной запуск:** Выполните команду из `ENTRYPOINT` вручную. Это позволит увидеть ошибки линковки (`ldd`), ненайденные конфиги или ошибки сегментации.
4.  **Проверка PID 1 и сигналов:**
    ```bash
    ps -p 1 -o pid,comm,args
    # Если PID 1 — sh, обработка SIGTERM нарушена
    kill -TERM 1 && sleep 5 && ps -p 1
    # Если процесс всё ещё жив — приложение игнорирует SIGTERM
    ```

## Дифференциация причин падения

Определите, кто именно инициировал завершение контейнера:

| Симптом | Вероятная причина | Действие |
| :--- | :--- | :--- |
| `Reason: OOMKilled`, exit 137 | Ядро убило процесс | Увеличить `limits.memory`, проверить `kubectl top pod` |
| `Liveness probe failed` в Events | `kubelet` убил контейнер | Проверить эндпоинт проб, увеличить таймауты |
| `Reason: Error`, exit 1 | Приложение завершилось с ошибкой | Смотреть логи, переменные окружения, конфиги |
| `Reason: Error`, exit 125 | Ошибка CRI (runtime) | Проверить манифест, SELinux/AppArmor, `crictl` |
| `Reason: Error`, exit 127 | Команда не найдена | Проверить `command`, `args`, `$PATH` в образе |
| `Reason: Error`, exit 139 | Segmentation Fault | Проверить библиотеки, архитектуру образа (arm/amd64) |
| `Reason: Error`, exit 143 | SIGTERM без корректного завершения | Проверить PID 1, использовать tini/dumb-init |
| Нет `Reason`, но `restartCount` растёт | Провал Startup Probe | Увеличить `failureThreshold` и `periodSeconds` |

## Диагностика RBAC и ServiceAccount

```bash
# Проверка ServiceAccount, назначенного поду
kubectl get pod <pod-name> -o jsonpath='{.spec.serviceAccountName}'

# Проверка прав конкретного ServiceAccount
kubectl auth can-i get pods --as=system:serviceaccount:<ns>:<sa>
kubectl auth can-i get configmaps --as=system:serviceaccount:<ns>:<sa>
kubectl auth can-i create pods --as=system:serviceaccount:<ns>:<sa>

# Если под упал с Forbidden, проверьте ClusterRole/RoleBinding
kubectl describe rolebinding <ns>
kubectl describe clusterrolebinding <binding-name>
```

## Валидация конфигурации (ConfigMap/Secret)

```bash
# Проверка наличия и содержимого ConfigMap
kubectl get configmap <name> -o yaml
kubectl get configmap <name> -o jsonpath='{.data}' | base64 -d

# Проверка Secrets
kubectl get secret <name> -o jsonpath='{.data}' | base64 -d

# Проверка, что ConfigMap/Secret существуют в нужном namespace
kubectl get configmap,secret -n <ns> | grep <name>

# Проверка монтирования volumes (subPath проблемы)
kubectl get pod <pod-name> -o yaml | grep -A 10 "volumeMounts"
kubectl get pod <pod-name> -o yaml | grep -A 10 "volumes"
```

## Диагностика проб (Probes)

```bash
# Проверка, есть ли в манифесте Startup Probe (защита от преждевременного перезапуска)
kubectl get pod <pod-name> -o yaml | grep -A 15 "startupProbe"

# Проверка Liveness Probe
kubectl get pod <pod-name> -o yaml | grep -A 15 "livenessProbe"

# Ручная проверка эндпоинта health изнутри пода (если есть exec)
kubectl exec <pod-name> -- curl -sf http://localhost:<port>/healthz
kubectl exec <pod-name> -- wget -qO- http://localhost:<port>/ready

# Если exec не работает (distroless), используйте ephemeral контейнер
kubectl debug -it <pod-name> --image=nicolaka/netshoot --target=<container-name>
# Внутри:
curl -sf http://localhost:<port>/healthz
```

## Проверка PID 1 и обработки сигналов

```bash
# Проверить, кто является PID 1
kubectl exec <pod-name> -- ps -p 1 -o pid,comm,args

# Если PID 1 — sh/bash, обработка сигналов нарушена
# Используйте tini или dumb-init в Dockerfile:
# ENTRYPOINT ["/sbin/tini", "--"]
# CMD ["my-app"]

# Проверка обработки SIGTERM
kubectl exec <pod-name> -- /bin/sh -c "kill -TERM 1 && sleep 2 && ps -p 1"
```

## Взаимодействие с PodDisruptionBudget и выселением

При `CrashLoopBackOff` под не считается `healthy` для PDB. Это может блокировать `kubectl drain` или rolling update, если `minAvailable` превышает количество здоровых подов.

```bash
# Проверка PDB в namespace
kubectl get pdb -n <ns>

# Включение принудительного выселения нездоровых подов (Kubernetes v1.31+)
# В спецификации PDB добавьте:
# spec:
#   unhealthyPodEvictionPolicy: AlwaysAllow
```

Полное описание механизма: **[PodDisruptionBudget](../../../Autoscaling/pod_disruption_budget.md)**.

## Дополнительные инструменты и методы

### Использование kubectl events (Modern CLI)

Команда `kubectl events` (появилась в новых версиях как замена `get events`) позволяет фильтровать события более гибко.

```bash
# Показать только ошибки (Warnings) для конкретного Namespace
kubectl events --types=Warning -n my-app
```

### Проверка на уровне узла (для SRE)

Если логи Kubernetes не дают ответа, проблема может быть на уровне Container Runtime (CRI). Это актуально при ошибках `RuntimeError` (код 125).

```bash
# На узле, где запущен под (через SSH)
crictl ps -a | grep <pod-id>
crictl logs <container-id>

# Проверка состояния kubelet на узле
journalctl -u kubelet -n 100 --no-pager

# Проверка места на диске и inodes
df -h /
df -i /

# Проверка pids-limit (количество процессов)
cat /sys/fs/cgroup/pids/kubepods/pod<uid>/pids.max
cat /sys/fs/cgroup/pids/kubepods/pod<uid>/pids.current
```

### Проверка на уровне cgroup и PSI (Cgroup v2)

```bash
# Внутри отладочного контейнера или на узле
cat /sys/fs/cgroup/kubepods.slice/kubepods-besteffort.slice/kubepods-besteffort-pod<uid>.slice/ Memory.current
cat /sys/fs/cgroup/kubepods.slice/kubepods-besteffort.slice/kubepods-besteffort-pod<uid>.slice/ memory.pressure
```

## Белые пятна: когда стандартная диагностика не помогает

1.  **Проблемы с MTU/Сетью:** Если приложение падает при попытке передать большой пакет данных в БД, проверьте настройки MTU в CNI-плагине. Симптом: «зависание» соединения перед крашем.
2.  **Исчерпание Inodes/Disk Space:** Если узел переполнен, контейнер может не запуститься, но статус в K8s может быть нечетким. Проверьте `df -h` и `df -i` на узле.
3.  **Zombie-процессы:** Если приложение порождает много дочерних процессов и не очищает их, оно может достичь `pids-limit` (настраивается в kubelet).
4.  **Race Condition при запуске:** Если несколько контейнеров в поде зависят друг от друга, но не используют Init-контейнеры, они могут падать из-за неготовности соседа.
5.  **Page Cache и ложный OOMKilled:** При высокой I/O-нагрузке page cache может занимать значительную часть лимита памяти, приводя к преждевременному OOMKill. Мониторьте `memory.stat` и `memory.current` в cgroup.
6.  **SIGPIPE и broken pipe:** Приложения, которые не игнорируют `SIGPIPE`, могут завершаться при разрыве соединения с downstream-сервисом. Используйте `trap` в shell-обёртках или настройте рантайм на игнорирование сигнала.
7.  **Слишком строгий Security Context:** `readOnlyRootFilesystem: true` без соответствующих `emptyDir` для `/tmp` и `/var/run` приводит к крашу при попытке записи. Проверьте `securityContext` в манифесте.
8.  **Несовпадение архитектуры (platform):** Образ собран для `linux/amd64`, а узел — `linux/arm64`. Контейнер не запустится. Проверьте `kubectl get node -o wide` и `imagePullPolicy`.

## Типичные причины по доменам (Сводная таблица)

| Домен | Типичные симптомы | Команды диагностики |
| :--- | :--- | :--- |
| **Конфигурация** | Exit 1, `file not found`, `missing env` | `kubectl get configmap/secret -o yaml`, `kubectl logs --previous` |
| **Сеть / DNS** | `connection refused`, `no such host`, таймауты | `kubectl debug --image=nicolaka/netshoot`, `nslookup`, `curl` |
| **RBAC** | `Forbidden`, `cannot get resource` | `kubectl auth can-i`, `kubectl describe rolebinding` |
| **Ресурсы** | Exit 137, `OOMKilled`, `Evicted` | `kubectl top pod`, `kubectl describe node` |
| **Пробы** | `Liveness probe failed`, `Startup probe failed` | `kubectl get pod -o yaml`, `curl localhost:<port>/healthz` |
| **Runtime / CRI** | Exit 125, `RuntimeError` | `crictl ps`, `crictl logs`, `journalctl -u kubelet` |
| **Хранилище** | `FailedMount`, `Volume node mismatch` | `kubectl get pv,pvc`, `kubectl describe pod | grep Events` |
| **Безопасность** | `SysctlForbidden`, `permission denied` | `kubectl get pod -o yaml | grep securityContext`, `kubectl logs --previous` |

## Типовые сценарии по стекам технологий

### Java / JVM

```yaml
# Для JVM укажите процент от лимита контейнера вместо фиксированного Xmx
env:
- name: JAVA_OPTS
  value: "-XX:MaxRAMPercentage=75.0 -XX:+UseContainerSupport"
```

- **Симптом:** OOMKilled (exit 137) при старте или после нагрузки.
- **Причина:** JVM по умолчанию использует фиксированный `Xmx` и не видит лимиты cgroup.
- **Решение:** Используйте `-XX:MaxRAMPercentage` (JDK 8u191+, JDK 10+) или `-XX:+UseContainerSupport`.

### Go

```bash
# В Go panic выводится в stderr. Если логи пусты — проверьте:
# 1. GOMEMLIMIT (Go 1.19+) задан ниже лимита контейнера
# 2. GOTRACEBACK=crash для дампа памяти при панике
# 3. NDEBUG или сигналы, подавляющие panic
```

- **Симптом:** Exit 2 или 137, логи содержат `panic: runtime error`.
- **Решение:** Настройте `GOMEMLIMIT` и `GOTRACEBACK`, добавьте `tini` для корректной обработки сигналов.

### .NET

```yaml
env:
- name: DOTNET_GCHeapHardLimit
  value: "0x38400000"  # 900 MiB в hex
# Или автоматически (современные рантаймы):
# DOTNET_GCHeapHardLimitPercent=70
```

- **Симптом:** Ошибка `System.OutOfMemoryException` или OOMKilled перед тем, как .NET GC успевает сработать.
- **Решение:** Начиная с .NET 8/9, рантайм автоматически подстраивается под cgroup-лимиты. Для резких скачков явно ограничьте кучу.

### Python

```bash
# Буферизация вывода (зависит от переменной окружения)
export PYTHONUNBUFFERED=1
```

- **Симптом:** Логи пусты при падении, exit 1.
- **Причина:** Python буферизирует stdout/stderr. При краше буфер не сбрасывается.
- **Решение:** Установите `PYTHONUNBUFFERED=1` или используйте `-u` для запуска интерпретатора.

## Remediation и восстановление

### Остановка циклических перезапусков

```bash
# 1. Масштабирование Deployment до 0 (останавливает цикл)
kubectl scale deployment/<name> --replicas=0

# 2. Исправление конфигурации / образа
kubectl set image deployment/<name> app=<name>:<fixed-tag>
kubectl set env deployment/<name> DB_HOST=<correct-db>

# 3. Возврат реплик
kubectl scale deployment/<name> --replicas=1

# 4. Или откат на предыдущую ревизию
kubectl rollout undo deployment/<name>
kubectl rollout undo deployment/<name> --to-revision=2
```

### Drain узла с подами в CrashLoopBackOff

Если поды в `CrashLoopBackOff` блокируют drain:

```bash
# Проверка PDB
kubectl get pdb -n <ns>

# Вариант 1: Включение AlwaysAllow (Kubernetes v1.31+)
kubectl patch pdb <name> -p '{"spec":{"unhealthyPodEvictionPolicy":"AlwaysAllow"}}'

# Вариант 2: Принудительное удаление пода (контроллер создаст новый)
kubectl delete pod <pod-name> --grace-period=0 --force

# Drain с игнорирование PDB (не рекомендуется в production без анализа)
kubectl drain <node-name> --ignore-daemonsets --delete-local-data --force
```

## Мониторинг и алертинг

### Prometheus метрики

```promql
# Контейнеры в CrashLoopBackOff
kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"} == 1

# Перезапуски за последние 15 минут
increase(kube_pod_container_status_restarts_total[15m]) > 5

# Процент подов в CrashLoopBackOff
count(kube_pod_status_reason{reason="CrashLoopBackOff"}) / count(kube_pod_status_phase{phase="Running"}) * 100

# OOMKilled события
kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1

# Давление памяти на узле (Cgroup v2, PSI)
avg_over_time(node_memory_pressure[5m]) > 0.1
```

### PrometheusRule пример

```yaml
groups:
- name: pod-health
  rules:
  - alert: PodCrashLooping
    expr: increase(kube_pod_container_status_restarts_total[15m]) > 5
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Pod {{ $labels.pod }} в namespace {{ $labels.namespace }} циклично перезапускается"
      runbook_url: "https://wiki.example.com/runbooks/crashloopbackoff"

  - alert: PodOOMKilled
    expr: kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Pod {{ $labels.pod }} завершён по OOMKilled"
      runbook_url: "https://wiki.example.com/runbooks/oomkilled"
```

### Grafana панели (ключевые визуализации)

- **Таблица рестартов:** `namespace`, `pod`, `restartCount`, `last_reason`, `age`
- **Timeline перезапусков:** график `rate(kube_pod_container_status_restarts_total[1h])` по времени
- **Top Pods по restartCount:** bar chart с лидерами по нестабильности
- **OOMKilled vs Eviction:** pie chart причин принудительного завершения

## Дополнительная информация

### Коды завершения (практическая справка)

| Код | Значение / Сигнал | Вероятная причина | Действие |
|:---|:---|:---|:---|
| **0** | **Success** | Для Deployment это ошибка: процесс завершился слишком рано. | Проверить CMD/ENTRYPOINT, Deployment предназначен для long-running. |
| **1** | **Error** | Общая ошибка приложения (stacktrace в логах). | Смотреть `logs --previous`, переменные окружения, ConfigMap. |
| **2** | **Misuse** | Ошибка синтаксиса shell-команд. | Проверить `command` и `args` в манифесте. |
| **125** | **Runtime Error** | Ошибка запуска со стороны CRI. | Проверить `crictl logs`, манифест, SELinux/AppArmor. |
| **127** | **Command not found** | Утилита не найдена в `$PATH`. | Проверить `command`, `ENTRYPOINT`, установку в Dockerfile. |
| **128** | **Invalid Argument** | Некорректные параметры запуска. | Проверить сигналы, UID/GID, команду. |
| **130** | **SIGINT** | Прерывание (Ctrl+C). | Проверить shell-обёртки, `terminationGracePeriod`. |
| **137** | **OOMKilled / SIGKILL** | Превышение `limits.memory` или `kill -9`. | Увеличить `limits.memory`, проверить `kubectl top pod`. |
| **139** | **Segmentation Fault** | Ошибка сегментации (библиотеки, архитектура). | Проверить `ldd`, соответствие arm/amd64. |
| **143** | **SIGTERM** | Корректное завершение, но не успело за `terminationGracePeriod`. | Настроить `terminationGracePeriodSeconds`, добавить tini. |

## Post-mortem анализ

После устранения `CrashLoopBackOff` рекомендуется провести анализ для предотвращения повторения.

### Формат post-mortem

1. **Временная шкала:** Когда обнаружен, когда устранен, сколько длился инцидент.
2. **Корневая причина:** Что именно вызвало проблему (код, конфигурация, инфраструктура).
3. **Влияние:** Сколько пользователей/сервисов пострадало.
4. **Что сработало:** Какие алерты/Runbook помогли.
5. **Что не сработало:** Какие шаги оказались неэффективными.
6. **Рекомендации:** Как предотвратить повторение.

### Сбор данных для post-mortem

```bash
# 1. Сбор логов и событий
kubectl describe pod <pod-name> > pod-describe.txt
kubectl get events -n <ns> --field-selector involvedObject.name=<pod-name> --sort-by='.lastTimestamp' > events.txt
kubectl logs <pod-name> --previous > logs-previous.txt

# 2. Сбор метрик потребления ресурсов
kubectl top pod <pod-name> > pod-top.txt

# 3. Проверка конфигурации
kubectl get pod <pod-name> -o yaml > pod-manifest.yaml

# 4. Проверка PDB и ResourceQuota
kubectl get pdb -n <ns> > pdb-status.txt
kubectl describe resourcequota -n <ns> > resourcequota.txt
```

### Метрики качества

| Метрика | Описание | Целевое значение |
|:--------|:---------|:-----------------|
| **MTTR** | Среднее время восстановления | <30 минут (SEV1) |
| **Runbook Coverage** | Доля алертов с runbook | 100% (SEV1/SEV2) |
| **Freshness Score** | % runbook, обновленных за 90 дней | >90% |

### Ссылки

- **[Определения и концепции CrashLoopBackOff](./definitions_and_concepts.md)** — теория, BackOff, RestartPolicy, коды завершения.
- **[Распространенные решения](./common_cases_and_solutions.md)** — разбор типовых кейсов (ConfigMap, RBAC, БД).
- **[Продвинутые темы](./advanced_topics.md)** — автоматизация, eBPF, Cgroup v2, Native Sidecars.
- **[Runbook: CrashLoopBackOff](./runbook.md)** — шаблон для дежурного инженера.
- **[Перезапуск Pod в Kubernetes](../../../Base/Pod/pod_restarts.md)** — разница между перезапуском и пересозданием.
- **[Эфемерные контейнеры](../../../Base/Pod/ephemeral_containers.md)** — глубокая отладка через `kubectl debug`.
- **[Пробы (Probes) в Kubernetes](../../../Base/probes.md)** — Liveness, Readiness, StartupProbe.
- **[Диагностика OOMKilled](../oomkilled_pods.md)** — детально о проблемах с памятью.
- **[Обзор диагностики Kubernetes](../../troubleshooting_overview.md)** — общие принципы.
- **[PodDisruptionBudget](../../../Autoscaling/pod_disruption_budget.md)** — взаимодействие с выселением подов.
