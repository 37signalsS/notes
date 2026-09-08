# Продвинутые темы и лучшие практики: CrashLoopBackOff

## Определения

**Продвинутая диагностика CrashLoopBackOff** — применение глубоких методов анализа приоритетов ядра (OOM Score), метрик давления на ресурсы (PSI), cgroup v2, CRI-рантайма, системных вызовов через eBPF и механизмов жизненного цикла контейнеров для выявления скрытых причин нестабильности, выходящих за рамки стандартного `kubectl logs --previous`.

Полное описание базовых механизмов и пошаговый алгоритм поиска неисправностей представлены в разделах:
- **[Определения и концепции](./definitions_and_concepts.md)** — SSoT по теории.
- **[Диагностика и чек-лист](./diagnostics.md)** — основной алгоритм.

---

## Основные концепции

### Механизм oom_score_adj и приоритеты выживания

Kubernetes управляет вероятностью завершения процесса при нехватке памяти через параметр ядра `/proc/self/oom_score_adj`. В контексте `CrashLoopBackOff` это позволяет отличить **системный OOM** (узел в целом) от **внутреннего OOM контейнера** (превышение `limits.memory`).

| Класс QoS | Значение oom_score_adj | Приоритет выживания |
| :--- | :--- | :--- |
| **Guaranteed** | -997 | Максимальный (убиваются последними при системном OOM) |
| **Burstable** | `min(max(2, 1000 - (1000 * memoryRequest) / memoryCapacity), 999)` | Средний |
| **BestEffort** | 1000 | Минимальный (убиваются первыми) |

**Продвинутый инсайт:** Если под в классе `Guaranteed` попадает в `CrashLoopBackOff` с кодом 137, значит, он превысил *свой собственный* лимит. Если падает `BestEffort`, он мог быть принесен в жертву ради стабильности узла, даже если не потреблял много памяти.

**Практическая диагностика:**

```bash
# Проверка oom_score_adj внутри работающего пода
kubectl exec <pod-name> -- cat /proc/1/oom_score_adj
# → -997 (Guaranteed), 500 (Burstable), 1000 (BestEffort)

# Проверка текущего oom_score (рейтинг смерти, 0-1000)
kubectl exec <pod-name> -- cat /proc/1/oom_score
# → Чем выше, тем вероятнее убийство при системном OOM

# Проверка, был ли процесс убит OOM Killer
dmesg | grep -i "oom\|killed process"
# → [12345.678] oom-kill:constraint=CONSTRAINT_MEMCG,nodemask=(null),cpuset=...,mems=...,oom_memcg=...,task=...,uid=0,pid=1234,oom_score_adj=1000
```

**Важно:** Компоненты kubelet и контейнерного рантайма имеют `oom_score_adj = -999`, что защищает их даже от процессов `Guaranteed`.

### Мониторинг давления на ресурсы (PSI — Pressure Stall Information)

В средах с **Cgroup v2** (Kubernetes 1.25+) диагностика смещается от «сколько использовано» к «сколько времени потеряно на ожидание». Метрики PSI позволяют предсказать краш до его наступления.

- **`memory.pressure`**: Показывает процент времени, когда процессы ожидали освобождения или подкачки памяти. Резкий рост `full` pressure — предвестник OOMKilled.
- **`cpu.pressure`**: Показывает конкуренцию за процессорное время. Высокие значения могут приводить к нарушению таймаутов `livenessProbe` и последующему циклу перезапусков.
- **`io.pressure`**: Показывает время ожидания завершения операций ввода-вывода. Высокое значение может указывать на проблемы с хранилищем, приводящие к зависанию приложения.

Подробнее о механизме: **[Pressure Stall Information (PSI)](../../../../Linux/Core/kernel/psi.md)**.

**Практическая диагностика PSI в Kubernetes:**

```bash
# Системный PSI на узле (хосте)
cat /proc/pressure/memory
# → some avg10=2.46 avg60=1.82 avg300=1.21 total=748381
# → full avg10=0.91 avg60=0.65 avg300=0.45 total=280381

# Проверка давления на CPU
cat /proc/pressure/cpu
# → some avg10=12.50 avg60=8.30 avg300=5.10 total=45678901

# PSI для конкретного пода (через ephemeral контейнер с доступом к хосту)
POD_UID=$(kubectl get pod <pod_name> -o jsonpath='{.metadata.uid}')
kubectl debug node/$(kubectl get pod <pod_name> -o jsonpath='{.spec.nodeName}') \
  -it --image=busybox --quiet -- \
  chroot /host cat /sys/fs/cgroup/kubepods.slice/kubepods-pod${POD_UID}.slice/memory.pressure

# Проверка троттлинга CPU (cgroups v2)
cat /sys/fs/cgroup/kubepods.slice/kubepods-besteffort.slice/kubepods-besteffort-pod<uid>.slice/cpu.stat
# → nr_periods=12345
# → nr_throttled=500    ← высокое значение = проблемы
# → throttled_usec=25000000
```

**Связь PSI с CrashLoopBackOff:**
- `cpu.pressure` → нарушение таймаутов `livenessProbe` → перезапуск
- `memory.pressure full` → impending OOM → `OOMKilled` (exit 137)
- `io.pressure` → зависание на `fsync`/`open` → таймаут инициализации → `startupProbe` failed

### Нюансы Cgroup v2

В отличие от v1, cgroup v2 реализует **единую иерархию**. Для `CrashLoopBackOff` это означает:

1.  **OOM-группа:** По умолчанию, если один процесс в контейнере убит по OOM, ядро убивает все процессы в этой cgroup (весь контейнер). Это исключает ситуацию «зомби-контейнеров», где основной процесс жив, а вспомогательные упали.
2.  **Точность лимитов:** Cgroup v2 корректнее учитывает память Page Cache, что снижает количество ложных срабатываний OOM при активной работе с диском.
3.  **CPU Throttling:** В cgroups v2 метрика `cpu.stat` показывает `nr_throttled` и `throttled_usec`. Высокое троттлинг приводит к задержкам, нарушению `livenessProbe` и последующему `CrashLoopBackOff`.
4.  **Memory Reclaim:** Файл `memory.reclaim` позволяет вручную запустить reclaim страниц. Если приложение часто попадает в `memory.high` (мягкий лимит), ядро постоянно вызывает reclaim, что создает `memory.pressure` и замедляет приложение.

---

## Практические сценарии

### Сценарий 1: Native Sidecars (K8s 1.29+ GA)

Механизм нативных sidecar-контейнеров решает проблему Race Condition, когда основное приложение падает из-за неготовности прокси или агента.

```yaml
spec:
  initContainers:
  - name: network-proxy
    image: envoyproxy/envoy:v1.28
    restartPolicy: Always # Ключевой параметр для Native Sidecar
    startupProbe:
      httpGet:
        path: /ready
        port: 8001
  containers:
  - name: app
    image: my-app:latest
    # Запустится ТОЛЬКО после того, как network-proxy станет Ready
```

**Преимущество:** Нативный sidecar гарантированно получает сигнал `SIGTERM` *после* основного контейнера, что критично для корректного завершения сетевых соединений в Service Mesh.

**Взаимодействие с CrashLoopBackOff:**
- Если Native Sidecar не проходит `startupProbe` — основной контейнер **не стартует**.
- Если Native Sidecar падает во время работы — он перезапускается независимо, основной контейнер **не трогается**.
- Если основной контейнер падает — Native Sidecar завершается после него.

Подробнее: **[Паттерны Sidecar в Kubernetes](../../../../Kubernetes/Base/Pod/pod_sidecar_patterns.md)**.

### Сценарий 2: Глубокая eBPF-трассировка (Inspektor Gadget)

Если приложение падает «тихо» (без логов), используйте eBPF для отслеживания системных вызовов.

```bash
# 1. Трассировка попыток открытия файлов (поиск отсутствующих конфигов)
kubectl gadget trace open -n my-ns --pod <pod-name>

# 2. Мониторинг сигналов (кто именно отправляет SIGKILL/SIGTERM)
kubectl gadget trace signal -n my-ns --pod <pod-name>

# 3. Трассировка exit-кодов (кто завершает процесс)
kubectl gadget trace exit -n my-ns --pod <pod-name>

# 4. Сетевые соединения (поиск зависших подключений)
kubectl gadget trace tcp -n my-ns --pod <pod-name>
```

# → Результат: Вы можете увидеть, что приложение упало с ошибкой `ENOENT` при попытке открыть `/etc/config/secret.json`, даже если само приложение не успело вывести эту ошибку в логи.

**Альтернатива bpftrace (на узле):**

```bash
# Трассировка всех execve в контейнере (через cgroup)
sudo bpftrace -e '
cgroup/sys/fs/cgroup/kubepods.slice/kubepods-pod<uid>.slice/ {
  tracepoint:syscalls:sys_enter_execve { printf("%s %d\n", comm, pid); }
}'
```

Подробнее: **[eBPF в Kubernetes](../../../../Kubernetes/Networking/Network/CNI/ebpf.md)**, **[eBPF-инструменты](../../../../Networking/ServicesAndTools/Wireshark/ebpf_diagnostics_tools.md)**.

### Сценарий 3: Использование termination-log для богатой диагностики

Kubernetes может считывать причину падения напрямую из файла внутри контейнера. Это позволяет передать детали ошибки в API, которые будут видны в `kubectl describe pod`.

```yaml
spec:
  containers:
  - name: app
    image: my-app
    terminationMessagePath: /dev/termination-log
    terminationMessagePolicy: FallbackToLogsOnError
```

**Рекомендация:** Настройте ваше приложение так, чтобы при критическом сбое (panic, unhandled exception) оно записывало краткую причину в `/dev/termination-log`. Это избавит от необходимости копаться в гигабайтах логов.

**Просмотр termination message:**

```bash
# Быстрая диагностика без логов
kubectl get pod error-app -o jsonpath='{.status.containerStatuses[*].lastState.terminated.message}'
# → ERROR: Database connection refused on port 5432
#   Stack: ConnectionPool.connect() failed

# Просмотр exit code
kubectl get pod error-app -o jsonpath='{.status.containerStatuses[*].lastState.terminated.exitCode}'
# → 1
```

**Кастомный путь (для пуристых образов без /dev):**

```yaml
containers:
- name: app
  image: my-app:1.0
  terminationMessagePath: /tmp/termination-log
  terminationMessagePolicy: FallbackToLogsOnError
  volumeMounts:
  - name: tmp
    mountPath: /tmp
volumes:
- name: tmp
  emptyDir: {}
```

Подробнее: **[Жизненный цик Pod](../../../../Kubernetes/Base/Pod/pod_advanced_topics.md#пример-3-диагностика-через-termination-message)**.

### Сценарий 4: Диагностика на уровне CRI (Container Runtime Interface)

Exit Code 125 (`RuntimeError`) указывает на проблему на уровне контейнерного рантайма (containerd, CRI-O), а не приложения.

```bash
# На узле, где запущен под (через SSH)
# 1. Проверка статуса containerd
systemctl status containerd
# → containerd.service - containerd container runtime
#    Active: active (running)

# 2. Логи containerd
journalctl -u containerd -n 100 --no-pager
# → time="2026-09-04T17:35:00.123456789Z" level=error msg="failed to create container" error="oci runtime error: ..."

# 3. Проверка CRI-O
journalctl -u crio -n 100 --no-pager

# 4. Использование crictl для диагностики
crictl pods -n <namespace>
crictl ps -a --pod <pod-id>
crictl logs <container-id>

# 5. Проверка конфигурации containerd
cat /etc/containerd/config.toml | grep -A 10 "runtime"
```

**Типичные причины exit 125:**
- Несовместимость версии containerd и Kubernetes
- Ошибка доступа к образу (SELinux/AppArmor)
- Недостаточно места в `/var/lib/containerd`
- Ошибка в `runtime_class`

### Сценарий 5: Расширенный скрипт сбора данных (Post-Mortem)

Скрипт для автоматического сбора данных при обнаружении `CrashLoopBackOff`.

```bash
#!/bin/bash
# collect-crashloop-data.sh <pod-name> <namespace>
# Использование: bash collect-crashloop-data.sh my-app default

set -euo pipefail

POD=$1
NS=${2:-default}
NODE=$(kubectl get pod $POD -n $NS -o jsonpath='{.spec.nodeName}')
POD_UID=$(kubectl get pod $POD -n $NS -o jsonpath='{.metadata.uid}')
OUTDIR="crashloop-${POD}-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUTDIR"

echo "=== Сбор данных о CrashLoopBackOff: $POD ==="

echo "--- Описание пода ---"
kubectl describe pod $POD -n $NS > "$OUTDIR/pod-describe.txt" 2>&1

echo "--- События ---"
kubectl get events -n $NS --field-selector involvedObject.name=$POD --sort-by='.lastTimestamp' > "$OUTDIR/events.txt" 2>&1

echo "--- Логи предыдущего запуска ---"
kubectl logs $POD -n $NS --previous > "$OUTDIR/logs-previous.txt" 2>&1 || true

echo "--- Статус контейнеров (JSON) ---"
kubectl get pod $POD -n $NS -o json > "$OUTDIR/pod-status.json" 2>&1

echo "--- Проверка oom_score_adj ---"
kubectl exec $POD -n $NS -- cat /proc/1/oom_score_adj > "$OUTDIR/oom_score_adj.txt" 2>&1 || true
kubectl exec $POD -n $NS -- cat /proc/1/oom_score > "$OUTDIR/oom_score.txt" 2>&1 || true

echo "--- Проверка PID 1 ---"
kubectl exec $POD -n $NS -- ps -p 1 -o pid,comm,args > "$OUTDIR/pid1.txt" 2>&1 || true

echo "--- Проверка переменных окружения ---"
kubectl exec $POD -n $NS -- env | sort > "$OUTDIR/env.txt" 2>&1 || true

echo "--- Проверка диска на узле ---"
ssh $NODE "df -h / && df -i /" > "$OUTDIR/node-disk.txt" 2>&1 || true

echo "--- Проверка pids-limit ---"
ssh $NODE "cat /sys/fs/cgroup/pids/kubepods.slice/kubepods-pod${POD_UID}.slice/pids.max && cat /sys/fs/cgroup/pids/kubepods.slice/kubepods-pod${POD_UID}.slice/pids.current" > "$OUTDIR/pids-limit.txt" 2>&1 || true

echo "--- Проверка PSI Memory ---"
ssh $NODE "cat /sys/fs/cgroup/kubepods.slice/kubepods-pod${POD_UID}.slice/memory.pressure" > "$OUTDIR/psi-memory.txt" 2>&1 || true

echo "--- Проверка cpu.stat (троттлинг) ---"
ssh $NODE "cat /sys/fs/cgroup/kubepods.slice/kubepods-pod${POD_UID}.slice/cpu.stat" > "$OUTDIR/cpu-stat.txt" 2>&1 || true

echo "--- Данные собраны в $OUTDIR ==="
```

### Сценарий 6: Chaos-тестирование CrashLoopBackOff

Для проверки наблюдаемости и реагирования алертов можно преднамеренно вызывать `CrashLoopBackOff`:

```bash
# 1. Создание пода, который падает мгновенно
kubectl run chaos-crash --image=busybox:1.36 --restart=Always -- sh -c 'exit 1'

# 2. Проверка, что алерт сработал
kubectl get alerts --watch

# 3. Очистка
kubectl delete pod chaos-crash --grace-period=0 --force
```

**Безопасность:** Выполняйте только в изолированном namespace (например, `chaos-testing`) и убедитесь, что PDB и resource quotas не допустят влияния на production.

---

## Дополнительная информация

### Лучшие практики (Best Practices)

1.  **Startup Boost:** Используйте `requests.cpu` < `limits.cpu`. В моменты инициализации (JIT-компиляция в Java, прогрев кэшей) приложение может легально потреблять больше ресурсов. Throttling на старте — частая причина `CrashLoopBackOff` по таймауту проб.
2.  **Идемпотентность Init-контейнеров:** Помните, что Init-контейнеры могут перезапускаться. Их действия (миграции БД, создание папок) должны быть безопасными при повторном вызове.
3.  **Использование preStop Hooks:** Для отладки «зависающих» завершений добавьте в `preStop` команду сбора дампов: `preStop: exec: command: ["/bin/sh", "-c", "gcore -o /dumps/app.core 1"]`.
4.  **Наблюдаемость PSI:** Включите сбор PSI-метрик в node_exporter и настройте алерты на `memory.pressure full` > 3% и `cpu.pressure some` > 10%.
5.  **eBPF для production:** Inspektor Gadget можно запускать как DaemonSet для постоянной наблюдаемости. Это не требует изменений в подах и работает с любыми образами (включая distroless).
6.  **Управление oom_score_adj:** Для критичных подов используйте QoS `Guaranteed` (`requests == limits`). Это минимизирует риск жертвования подом при системном OOM.

### Ссылки

- **[KEP-3839: Sidecar Containers](https://github.com/kubernetes/enhancements/tree/master/keps/sig-node/3839-sidecar-containers)** — история и детали реализации нативных сайдкаров.
- **[Inspektor Gadget](https://www.inspektor-gadget.io/)** — eBPF-инструмент для Kubernetes.
- **[eBPF в Kubernetes](../../../../Kubernetes/Networking/Network/CNI/ebpf.md)** — kube-proxy replacement, Hubble, Cilium.
- **[eBPF-инструменты](../../../../Networking/ServicesAndTools/Wireshark/ebpf_diagnostics_tools.md)** — pwru, bpftrace, dropwatch.
- **[Pressure Stall Information (PSI)](../../../../Linux/Core/kernel/psi.md)** — теория и практика PSI.
- **[eBPF (ядро Linux)](../../../../Linux/Core/kernel/ebpf.md)** — архитектура eBPF.
- **[QoS и управление ресурсами](../../../../Kubernetes/Scheduling/qos_limit_and_requests.md)** — расчет oom_score_adj и классов QoS.
- **[Оптимизация JVM в Kubernetes](https://www.overops.com/blog/how-to-optimize-java-within-docker-containers/)** — решение проблем с памятью и процессором.

---

### Связанные файлы

- **[Диагностика и чек-лист](./diagnostics.md)** — практические шаги отладки.
- **[Распространенные решения](./common_cases_and_solutions.md)** — база знаний по типовым ошибкам.
- **[Определения и концепции](./definitions_and_concepts.md)** — теоретическая база.
