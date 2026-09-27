# Состояние `CrashLoopBackOff` в Kubernetes: Определения и концепции

## Определения

**CrashLoopBackOff** — состояние Pod в Kubernetes, указывающее на то, что контейнер многократно запускается, падает и перезапускается с экспоненциальной задержкой. Это не ошибка сама по себе, а защитный механизм (индикатор), сигнализирующий о неспособности контейнера выйти в стабильный режим работы.

**Back-off (Задержка)** — механизм экспоненциальной задержки между перезапусками. Kubernetes увеличивает время ожидания перед каждой следующей попыткой, чтобы предотвратить бесполезную трату ресурсов узла (CPU/IO) и API-сервера на запуск заведомо неисправного приложения.
- **Интервалы:** Начинаются с 10 секунд и удваиваются: 10s → 20s → 40s → 80s → 160s.
- **Максимальная задержка:** 300 секунд (5 минут).
- **Сброс счетчика:** Если контейнер успешно проработал более 10 минут в состоянии `Running`, счетчик задержки сбрасывается.
- **Джиттер (Jitter):** Для предотвращения синхронизации перезапусков в кластере Kubernetes добавляет случайную вариацию (±3 секунды) к базовым интервалам.

**Init:CrashLoopBackOff** — аналог состояния для init-контейнеров. Если подготовительный контейнер падает, основной контейнер даже не получает шанс запуститься. Kubernetes применяет тот же механизм Back-off к последовательности init-контейнеров.

**Container Runtime Interface (CRI)** — стандартный gRPC-интерфейс Kubernetes для взаимодействия с средами выполнения контейнеров (`containerd`, `CRI-O`). Ошибки на уровне CRI (например, `RuntimeError` с exit code 125) также могут привести к `CrashLoopBackOff`, если контейнер не может быть создан.

**terminationMessagePath** — путь внутри контейнера, по которому приложение может записать причину своего завершения. Kubernetes читает этот файл и сохраняет содержимое в `status.containerStatuses.lastState.terminated.message`, что доступно через `kubectl describe pod` или `kubectl get pod -o jsonpath`.

**terminationMessagePolicy** — политика сбора сообщения о завершении:
- `File` (дефолт): читает из `terminationMessagePath`.
- `FallbackToLogsOnError`: если файл пуст, берет последние строки stderr контейнера.

**Native Sidecar (Kubernetes 1.29+)** — механизм определения вспомогательных контейнеров как init-контейнеров с `restartPolicy: Always`. Если Native Sidecar не проходит `startupProbe`, основной контейнер не стартует, что может привести к `CrashLoopBackOff` на уровне Pod.

**Pressure Stall Information (PSI)** — механизм ядра Linux (≥4.20), измеряющий процент времени, когда процессы ждали доступа к ресурсам (CPU, память, I/O). Рост `memory.pressure full` или `cpu.pressure some` может предшествовать `CrashLoopBackOff` за счет нарушения таймаутов `livenessProbe`.

**Silent OOM** — ситуация в cgroups v2, когда ядро убивает отдельный дочерний процесс внутри контейнера, превысивший лимит памяти, но PID 1 остается жив. Контейнер продолжает работать в деградированном состоянии, что может проявляться как `CrashLoopBackOff` или нестабильная работа.

**Pod Disruption Budget (PDB)** — механизм защиты подов от добровольного выселения. Поды в `CrashLoopBackOff` не считаются `healthy` для PDB, что может блокировать `kubectl drain` или rolling update, если `minAvailable` превышает количество здоровых подов. Начиная с Kubernetes 1.30, `unhealthyPodEvictionPolicy: AlwaysAllow` позволяет принудительно выселять нездоровые поды.

## Основные концепции

### Механика переходов состояний

Когда контейнер падает, он проходит через цепочку статусов, фиксируемую в `status.containerStatuses`:
1.  **Terminated:** Контейнер завершился. В поле `reason` указывается `Error` или `OOMKilled`, фиксируется `exitCode` и `finishedAt`.
2.  **Waiting:** Контейнер ожидает перезапуска. В поле `reason` появляется **CrashLoopBackOff**, а в `message` — время до следующей попытки запуска.
3.  **Running:** Повторный запуск процесса. Если приложение снова падает, цикл повторяется.

Для init-контейнеров используется статус **Init:CrashLoopBackOff**, который блокирует запуск всех последующих init-контейнеров и основных контейнеров пода.

### Архитектура цикла перезапуска

```text
┌─────────────────┐
│  Запуск         │
│  контейнера     │
└────────┬────────┘
          │
          ▼
┌─────────────────┐
│  Падение        │
│  контейнера     │
│  (Exit Code ≠0) │
└────────┬────────┘
          │
          ▼
┌─────────────────┐
│  Увеличение     │
│  Restart Count  │
└────────┬────────┘
          │
          ▼
┌─────────────────┐
│  Задержка       │
│  (BackOff)      │
│  (10s → 300s)   │
└────────┬────────┘
          │
          ▼
┌─────────────────┐
│  Повторная      │
│  попытка        │
└─────────────────┘
```

### Причины возникновения CrashLoopBackOff

Контейнер переходит в это состояние, когда основной процесс (PID 1) завершается. Основные группы причин:

1.  **Ошибка приложения** — баг в коде, необработанное исключение или паника (Panic в Go, Segmentation Fault в C++).
2.  **Неверная конфигурация** — отсутствие необходимых ConfigMap, Secret, опечатки в именах переменных окружения или путях монтирования.
3.  **Проблемы с зависимостями** — недоступность базы данных, кэша или внешних API на этапе инициализации.
4.  **Недостаточно прав RBAC (Role-Based Access Control)** — приложение пытается взаимодействовать с Kubernetes API (например, чтение конфигов или листинг подов) без соответствующих разрешений ServiceAccount.
5.  **Неудачные пробы (Liveness/Startup Probes)** — проверка здоровья убивает контейнер, если он не отвечает вовремя.
    - **StartupProbe:** Специально предназначена для долго запускающихся приложений. Если она не проходит за отведенное время, контейнер уходит в перезапуск.
    - *Важно:* Ошибка **Readiness Probe** НЕ вызывает `CrashLoopBackOff`, она лишь исключает под из трафика сервисов.
6.  **OOMKilled (Out Of Memory Killed)** — процесс превышает лимит памяти (`limits.memory`) и убивается ядром ОС (Exit Code 137).
7.  **Ошибки CRI Runtime** — проблемы на уровне containerd/CRI-O (несовместимость версий, нехватка места в `/var/lib/containerd`, ошибки SELinux/AppArmor) приводят к exit code 125.
8.  **Native Sidecar не готов** — если вспомогательный контейнер (Envoy, Vault Agent) не проходит `startupProbe`, основной контейнер не стартует, и Pod зависает в ожидании.

### Политика перезапуска (RestartPolicy)

Поведение `CrashLoopBackOff` напрямую зависит от поля `spec.restartPolicy` в манифесте Pod:

| Политика | Описание | Поведение при падении |
|:---------|:---------|:----------------------|
| **Always** (дефолт) | Перезапускать всегда. | Входит в цикл `CrashLoopBackOff`. |
| **OnFailure** | Перезапускать только при Exit Code ≠ 0. | Входит в цикл только при ошибках. |
| **Never** | Никогда не перезапускать. | Остается в статусе `Error` или `Completed`, в `CrashLoopBackOff` не переходит. |

### Поведение контроллеров: Deployment vs Job

Механизм перезапуска зависит от того, какой объект управляет подом:

| Характеристика | Deployment / StatefulSet | Job / CronJob |
| :--- | :--- | :--- |
| **Цель** | Поддержание постоянного количества реплик. | Успешное выполнение задачи до конца. |
| **Лимит попыток** | Неограничен (цикл идет бесконечно). | Ограничен параметром `backoffLimit` (дефолт: 6). |
| **Terminal State** | Не достигает (всегда перезапускается). | После исчерпания лимита Job помечается как `Failed`. |

### Коды завершения (Exit Codes) и сигналы

| Код | Значение / Сигнал | Вероятная причина |
|:----|:---------|:------------------|
| **0** | **Success** | Для сервисов — это ошибка: процесс завершился слишком рано (не должен был выходить). |
| **1** | **Error** | Общая ошибка приложения (stacktrace в логах), необработанное исключение. |
| **2** | **Misuse** | Ошибка синтаксиса shell-команд или встроенных утилит внутри `command`. |
| **125** | **Runtime Error** | Ошибка запуска контейнера со стороны CRI (Container Runtime Interface). |
| **127** | **Command not found** | Утилита, указанная в `ENTRYPOINT` или `command`, не найдена в образе или в `$PATH`. |
| **128** | **Invalid Argument** | Некорректные параметры запуска (например, неверный UID пользователя или невалидная команда). |
| **130** | **SIGINT** | Прерывание процесса (Ctrl+C). Часто возникает при работе через shell-обертки. |
| **137** | **OOMKilled / SIGKILL** | Процесс убит за превышение лимитов памяти или по `kill -9` (немедленное завершение). |
| **139** | **Segmentation Fault** | Ошибка сегментации (обращение к защищенной памяти, баг в бинарном файле или библиотеках). |
| **143** | **SIGTERM** | Процесс убит корректно, но не успел завершиться за время `terminationGracePeriod`. |

> **Совет по собеседованию: Проверка жизнеспособности (Probe) vs Сбой приложения**
> **Вопрос:** Под перезагружается. Как определить, вызвано ли это сбоем Liveness Probe или приложение падает само по себе?
> **Ответ:** Необходимо изучить раздел `Events` в выводе `kubectl describe pod`.
> 1. Если проверка жизнеспособности не удалась, Kubernetes сгенерирует конкретное событие: `Liveness probe failed`. Это означает, что `kubelet` сам убивает контейнер.
> 2. Если такого события нет, но поле `Last State` показывает ненулевой `Exit Code` (например, 1 или 137), значит, сам процесс приложения завершился с ошибкой или был убит ядром.

## Практические сценарии

### Быстрая диагностика через kubectl

```bash
# 1. Статус пода и количество перезапусков
kubectl get pod <pod-name> -o wide
# → NAME   READY   STATUS            RESTARTS   AGE   IP           NODE
# → app    0/1     CrashLoopBackOff  12         45m   10.244.1.5   worker-1

# 2. Причина последнего завершения и exit code
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].lastState.terminated}'
# → map[exitCode:1 reason:Error finishedAt:2024-01-15T10:30:00Z]

# 3. Текущий статус всех контейнеров (включая init)
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].name}{"\t"}{.status.containerStatuses[*].state}{"\n"}'
# → app     Waiting
# → istio-proxy  Running

# 4. События пода (фильтрация по типу Warning)
kubectl events --for pod/<pod-name> --types=Warning --watch

# 5. Проверка, является ли под Init:CrashLoopBackOff
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[0].ready}{"\t"}{.status.containerStatuses[*].state}'
# Если все контейнеры Waiting с reason=CrashLoopBackOff — проверяйте init-контейнеры:
kubectl logs <pod-name> -c <init-container-name> --previous

# 6. Просмотр termination message (если приложение записывает причину в /dev/termination-log)
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[*].lastState.terminated.message}'
```

### Проверка влияния на PDB и Drain

```bash
# Если CrashLoopBackOff блокирует drain узла
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data

# Проверка PDB для приложения
kubectl get pdb -n <namespace>
# → Если Available < MinAvailable — поды в CrashLoopBackOff блокируют выселение

# Для K8s 1.30+: разрешение выселения нездоровых подов
# Добавьте в PDB: unhealthyPodEvictionPolicy: AlwaysAllow
```

### Проверка Native Sidecars

```bash
# Проверка статуса нативного сайдкара
kubectl get pod <pod-name> -o jsonpath='{.status.containerStatuses[?(@.name=="envoy-proxy")].state}'
# → Waiting (CrashLoopBackOff)

# Проверка startupProbe сайдкара
kubectl describe pod <pod-name> | grep -A 10 "envoy-proxy"
# Если startupProbe не проходит — основной контейнер не стартует
```

### Проверка через CRI (на узле)

```bash
# На узле, где запущен под (через SSH)
# 1. Поиск контейнера
crictl ps -a --name <container-name>
# → abc123def456  my-app:latest  Exited (1) 2m ago

# 2. Логи контейнера
crictl logs <container-id>
# → ERROR: Database connection refused

# 3. Детальная информация (exit code, PID)
crictl inspect <container-id> | jq '.info.pid, .info.runtimeType'
# → 12345
# → "io.containerd.runc.v2"

# 4. Проверка статуса containerd
systemctl status containerd
journalctl -u containerd -n 50 --no-pager
```

### Проверка PSI и cgroup v2

```bash
# На хосте или через ephemeral контейнер
# 1. Системное давление на память
cat /proc/pressure/memory
# → some avg10=2.46 avg60=1.82 avg300=1.21 total=748381
# → full avg10=0.91 avg60=0.65 avg300=0.45 total=280381

# 2. Давление на CPU
cat /proc/pressure/cpu
# → some avg10=12.50 avg60=8.30 avg300=5.10 total=45678901

# 3. Статистика CPU throttling для пода
POD_UID=$(kubectl get pod <pod-name> -o jsonpath='{.metadata.uid}')
cat /sys/fs/cgroup/kubepods.slice/kubepods-pod${POD_UID}.slice/cpu.stat
# → nr_periods=12345
# → nr_throttled=500    ← высокое значение = проблемы
# → throttled_usec=25000000
```

### Проверка oom_score_adj и приоритетов выживания

```bash
# 1. Проверка QoS-класса пода
kubectl get pod <pod-name> -o jsonpath='{.status.qosClass}'
# → Guaranteed / Burstable / BestEffort

# 2. Проверка oom_score_adj внутри работающего пода
kubectl exec <pod-name> -- cat /proc/1/oom_score_adj
# → -997 (Guaranteed), 500 (Burstable), 1000 (BestEffort)

# 3. Проверка текущего oom_score (рейтинг смерти)
kubectl exec <pod-name> -- cat /proc/1/oom_score
# → Чем выше, тем вероятнее убийство при системном OOM

# 4. Проверка событий OOM в dmesg
dmesg | grep -i "oom\|killed process"
# → [12345.678] oom-kill:constraint=CONSTRAINT_MEMCG,nodemask=(null),cpuset=...,mems=...,oom_memcg=...,task=...,uid=0,pid=1234,oom_score_adj=1000
```

## Дополнительная информация

### Связанные концепции

- **[Liveness и Readiness Probes](../../../Base/probes.md)** — механизмы проверки жизнеспособности.
- **[Управление ресурсами (Requests/Limits)](../../../Scheduling/qos_limit_and_requests.md)** — настройка CPU и RAM.
- **[Логирование в Kubernetes](../../../MonitoringLogging/kubernetes-monitoring-logging-architecture.md)** — принципы сбора stdout/stderr.
- **[Перезапуск Pod](../../../Base/Pod/pod_restarts.md)** — разница между перезапуском и пересозданием.
- **[Container Runtime](../../../Concepts/container_runtime.md)** — CRI, containerd, CRI-O.
- **[Паттерны Sidecar](../../../Base/Pod/pod_sidecar_patterns.md)** — Native Sidecars и их влияние на жизненный цикл.
- **[Классы QoS и oom_score_adj](../../../Troubleshooting/Common_Errors/PodEvicted/qos_and_eviction.md)** — детальный расчет приоритетов выживания.
- **[OOM Killer в контейнерах](../../../../Linux/Core/processes/oom_killer_containers.md)** — Silent OOM и cgroups v2.
- **[Pressure Stall Information (PSI)](../../../../Linux/Core/kernel/psi.md)** — мониторинг давления на ресурсы.
- **[eBPF в Kubernetes](../../../../Kubernetes/Networking/Network/CNI/ebpf.md)** — глубокая трассировка через Inspektor Gadget.
- **[terminationMessage и диагностика](../../../Base/Pod/pod_advanced_topics.md)** — запись причины падения в файл.
- **[NetworkPolicy](../../../../Kubernetes/Networking/Network/NetworkPolicy/definitions.md)** — сетевая изоляция подов.
- **[ResourceQuota и LimitRange](../../../../Kubernetes/Scheduling/qos_limit_and_requests.md)** — управление квотами ресурсов.
- **[Pod Security Standards (PSS/PSA)](../../../../Kubernetes/Base/secrets/pod_security_and_secrets.md)** — контроль безопасности подов.
- **[Admission Controllers](../../../../Kubernetes/Concepts/admission_controllers.md)** — вебхуки допуска подов.
- **[Service Mesh: Концепции](../../../../Service_Mesh/service_mesh_concepts.md)** — архитектура sidecar, mTLS.
- **[Helm: Безопасность](../../../../Kubernetes/ToolsUtilities/Helm/Advanced/security_best_practices.md)** — best practices для production.
- **[ArgoCD: Установка](../../../../GitOps/ArgoCD/argocd_installation_and_setup.md)** — базовая настройка GitOps.
- **[Graceful Termination](../../../../Kubernetes/Networking/Network/traffic_path.md)** — настройка drain и PreStop hooks.

---

### Ссылки

- **[Диагностика CrashLoopBackOff](./diagnostics.md)** — пошаговый алгоритм поиска неисправностей.
- **[Распространенные решения](./common_cases_and_solutions.md)** — разбор типовых кейсов (30 сценариев).
- **[Продвинутые темы](./advanced_topics.md)** — автоматизация и глубокая отладка (eBPF, Cgroup v2, Native Sidecars).
- **[Runbook: CrashLoopBackOff](./runbook.md)** — шаблон для дежурного инженера.
