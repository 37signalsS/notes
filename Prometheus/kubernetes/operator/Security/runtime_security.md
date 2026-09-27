# Безопасность контейнерного рантайма в Prometheus Operator

## Определения

**Runtime Security Prometheus Operator** — комплекс мер по защите среды выполнения контейнеров Prometheus, Alertmanager и Operator-процесса на уровне ядра Linux: ограничение системных вызовов (seccomp), контроль доступа к файловой системе (AppArmor/SELinux), управление привилегиями (capabilities) и изоляция через sandboxed runtimes.

**Threat Model для рантайма** — модель угроз, специфичная для контейнеров мониторинга:
- **Цель:** компрометация контейнера Prometheus для доступа к метрикам всех подов в кластере, использование PromQL для DoS, lateral movement через ServiceAccount tokens.
- **Активы:** TSDB данные, метрики всех неймспейсов, секреты (Bearer tokens, Basic Auth пароли), конфигурация scraping.
- **Векторы атак:** escape из контейнера, эксплойт syscall через seccomp-дыры, загрузка вредоносного модуля, доступ к /proc и /sys.

**Defense in Depth для контейнеров** — стратегия, при которой каждый слой защиты (seccomp + AppArmor + capabilities + read-only FS) независимо ограничивает поверхность атаки; компрометация одного слоя не приводит к полному захвату.

> **Навигация:** [Главная Security](./index.md) | [Контроль доступа](./access_control.md) | [Секреты](./secrets_best_practices.md)

---

## Основные концепции

### Специфика контейнеров мониторинга

Контейнеры Prometheus и Alertmanager имеют отличия от типичных приложений:

| Компонент | Особенности | Риски |
|:---|:---|:---|
| **Prometheus** | Чтение метрик со всех подов (ServiceAccount tokens), запись в TSDB, scraping network | Доступ ко всем неймспейсам, высокий I/O, PromQL DoS |
| **Alertmanager** | Приём алертов, отправка webhook (Slack, PagerDuty), кластер gossip (порт 9094) | Утечка алертов, подмена алертов, DoS на webhook |
| **Operator** | Управление CRD, создание конфигурации, валидация webhook (порт 9443) | SSRF через tokenUrl, управление конфигурацией всех Prometheus |
| **config-reloader** | Sidecar, мониторинг Secret/ConfigMap, HTTP POST на /-/reload | Доступ к секретам, SSRF на /-/reload |
| **Thanos Sidecar** | gRPC (порт 10901), запись в объектное хранилище | Утечка метрик, компрометация объектного хранилища |

### SecurityContext для компонентов Operator

**Prometheus:**
```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 2000
    seccompProfile:
      type: RuntimeDefault
  podMetadata:
    annotations:
      container.apparmor.security.beta.kubernetes.io/prometheus: runtime/default
  containers:
    - name: prometheus
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
        readOnlyRootFilesystem: true
      volumeMounts:
        - name: data
          mountPath: /prometheus
        - name: config-volume
          mountPath: /etc/prometheus
        - name: secret-volume
          mountPath: /etc/prometheus/secrets
          readOnly: true
  volumes:
    - name: data
      emptyDir: {}
    - name: config-volume
      emptyDir: {}
    - name: secret-volume
      secret:
        secretName: prometheus-secrets
```

**Alertmanager:**
```yaml
apiVersion: monitoring.coreos.com/v1
kind: Alertmanager
metadata:
  name: main
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 2000
    seccompProfile:
      type: RuntimeDefault
  podMetadata:
    annotations:
      container.apparmor.security.beta.kubernetes.io/alertmanager: runtime/default
  containers:
    - name: alertmanager
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
        readOnlyRootFilesystem: true
      volumeMounts:
        - name: data
          mountPath: /alertmanager
        - name: config-volume
          mountPath: /etc/alertmanager
  volumes:
    - name: data
      emptyDir: {}
    - name: config-volume
      emptyDir: {}
```

**Operator Deployment:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: prometheus-operator
  namespace: monitoring
spec:
  template:
    spec:
      serviceAccountName: prometheus-operator
      securityContext:
        runAsNonRoot: true
        runAsUser: 65534        # nobody
        fsGroup: 65534
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: prometheus-operator
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
            readOnlyRootFilesystem: true
          volumeMounts:
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: tmp
          emptyDir: {}
```

### Seccomp для компонентов мониторинга

**Профиль по умолчанию (RuntimeDefault) блокирует:**
- `mount` — монтирование файловых систем
- `ptrace` — трассировка процессов
- `kexec_load` — загрузка нового ядра
- `userfaultfd` — управление страницами памяти
- `perf_event_open` — профилирование
- `bpf` — загрузка eBPF-программ
- `keyctl` — управление kernel keyring

**Кастомный профиль для Prometheus (если RuntimeDefault слишком строгий):**
```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "architectures": ["SCMP_ARCH_X86_64"],
  "syscalls": [
    {
      "names": [
        "read", "write", "open", "close", "stat", "fstat",
        "mmap", "mprotect", "munmap", "brk", "ioctl",
        "access", "pipe", "select", "sched_yield",
        "mremap", "msync", "mincore", "madvise",
        "dup", "dup2", "nanosleep", "getpid", "clone",
        "fork", "execve", "exit", "wait4", "kill",
        "fcntl", "flock", "fsync", "fdatasync",
        "getdents", "getcwd", "chdir", "readlink",
        "epoll_create", "epoll_ctl", "epoll_wait",
        "eventfd2", "epoll_create1", "pipe2",
        "clock_gettime", "clock_getres", "clock_nanosleep",
        "exit_group", "openat", "mkdirat", "newfstatat",
        "unlinkat", "readlinkat", "faccessat",
        "pselect6", "ppoll", "splice", "tee",
        "sync_file_range", "vmsplice",
        "accept4", "epoll_pwait", "eventfd",
        "inotify_init1", "inotify_add_watch",
        "prlimit64", "getrandom", "memfd_create",
        "copy_file_range", "preadv", "pwritev"
      ],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
```

### AppArmor для контейнеров мониторинга

**Профиль для Prometheus:**
```
#include <tunables/global>

profile prometheus flags=(attach_disconnected) {
  #include <abstractions/base>

  # Сеть — разрешить только outgoing connections
  network inet tcp,
  network inet udp,
  network inet6 tcp,
  network inet6 udp,

  # Файлы — разрешить только Prometheus-специфичные пути
  /prometheus/** rw,
  /etc/prometheus/** r,
  /etc/prometheus/secrets/** r,
  /tmp/** rw,

  # Запретить доступ к критичным путям
  deny /proc/** w,
  deny /sys/** w,
  deny /etc/shadow r,
  deny /etc/passwd w,
}
```

**Применение:**
```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
spec:
  podMetadata:
    annotations:
      container.apparmor.security.beta.kubernetes.io/prometheus: localhost/prometheus
  containers:
    - name: prometheus
```

**Загрузка профиля на ноды:**
```bash
# Через DaemonSet или init-container
kubectl create configmap prometheus-apparmor \
  --from-file=prometheus=<(cat prometheus-profile) \
  -n monitoring

# На каждой ноде (init-container)
apparmor_parser -r /etc/apparmor.d/prometheus
```

### Capabilities для компонентов

**Prometheus:**
```yaml
securityContext:
  capabilities:
    drop: ["ALL"]
    # Prometheus не нуждается ни в одной capability
    # Даже NET_BIND_SERVICE не нужен (порт 9090 > 1024)
```

**Alertmanager:**
```yaml
securityContext:
  capabilities:
    drop: ["ALL"]
    # Аналогично — порт 9093 > 1024
```

**Operator:**
```yaml
securityContext:
  capabilities:
    drop: ["ALL"]
    # Operator не привязывается к портам <1024
    # Порт 9443 > 1024
```

**config-reloader:**
```yaml
securityContext:
  capabilities:
    drop: ["ALL"]
    # Sidecar, не требует привилегий
```

### Sandbox runtimes для мониторинга

**gVisor для Prometheus (если критична изоляция):**
```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: gvisor
---
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: main
spec:
  containers:
    - name: prometheus
```

**Ограничения gVisor для Prometheus:**
- Некоторые syscall могут не поддерживаться (проблемы с mmap, epoll)
- Overhead: 5-15% CPU (критично для high-cardinality метрик)
- TSDB может работать медленнее из-за userspace-ядра

**Kata Containers:**
- Избыточны для мониторинга (overhead 25-40% CPU)
- Рекомендуются только для极高敏感ных сред (FINRA, PCI-DSS Level 1)

---

## Практические сценарии

### Полный SecurityContext для Production Prometheus Stack

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Prometheus
metadata:
  name: production
  namespace: monitoring
spec:
  replicas: 2
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 2000
    seccompProfile:
      type: RuntimeDefault
  podMetadata:
    labels:
      security: hardened
    annotations:
      container.apparmor.security.beta.kubernetes.io/prometheus: runtime/default
  containers:
    - name: prometheus
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
        readOnlyRootFilesystem: true
      resources:
        limits:
          memory: 4Gi
          cpu: 2
        requests:
          memory: 2Gi
          cpu: 1
      volumeMounts:
        - name: data
          mountPath: /prometheus
        - name: config-volume
          mountPath: /etc/prometheus
        - name: secret-volume
          mountPath: /etc/prometheus/secrets
          readOnly: true
  storage:
    volumeClaimTemplate:
      spec:
        accessModes: ["ReadWriteOnce"]
        resources:
          requests:
            storage: 50Gi
  volumes:
    - name: config-volume
      emptyDir: {}
    - name: secret-volume
      secret:
        secretName: prometheus-scrape-secrets
```

### Мониторинг нарушений безопасности контейнеров

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: container-security-alerts
spec:
  groups:
    - name: container-security
      rules:
        - alert: ContainerPrivilegeEscalation
          expr: |
            kube_pod_container_status_last_terminated_reason{reason="Error"} > 0
            and on(pod, namespace)
            kube_pod_labels{label_app=~"prometheus|alertmanager"}
          for: 5m
          labels:
            severity: critical
          annotations:
            summary: "Привилегированный контейнер в стеке мониторинга"

        - alert: SeccompProfileMissing
          expr: |
            kube_pod_container_status_last_terminated_reason{reason="Error"} > 0
            and on(pod, namespace)
            kube_pod_labels{label_app=~"prometheus|alertmanager"}
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Контейнер мониторинга запущен без seccomp-профиля"

        - alert: UnauthorizedSyscallDetected
          expr: |
            increase(falco_events_total{
              rule=~".*Unauthorized syscall.*",
              container=~"prometheus|alertmanager"
            }[5m]) > 0
          for: 1m
          labels:
            severity: critical
          annotations:
            summary: "Несанкционированный syscall в контейнере мониторинга"
```

### Диагностика проблем рантайма

```bash
# Проверка seccomp-профиля пода
kubectl get pod <pod> -n monitoring -o jsonpath='{.spec.containers[*].securityContext.seccompProfile}'

# Проверка AppArmor-профиля
kubectl get pod <pod> -n monitoring -o jsonpath='{.metadata.annotations}'

# Проверка capabilities
kubectl get pod <pod> -n monitoring -o jsonpath='{.spec.containers[*].securityContext.capabilities}'

# Просмотр audit log для seccomp-нарушений
kubectl logs -n kube-system <node>-audit | grep -i seccomp

# Проверка что контейнер запущен от non-root
kubectl exec -n monitoring <pod> -- id

# Проверка read-only filesystem
kubectl exec -n monitoring <pod> -- touch /test 2>&1  # Ожидается: Read-only file system
```

---

## Дополнительная информация

### Связанные файлы

| Файл | Содержание |
|:---|:---|
| [container_runtime_security.md](../../../Kubernetes/Security/container_runtime_security.md) | Общий гайд по безопасности контейнерного рантайма (seccomp, AppArmor, SELinux, capabilities, sandboxed runtimes) |
| [pod_security_context.md](../../../Kubernetes/Security/pod_security_context.md) | Настройки Pod/Container SecurityContext |
| [index.md](./index.md) | Обзор безопасности Prometheus Operator |
| [access_control.md](./access_control.md) | RBAC и NetworkPolicy для компонентов |
| [secrets_best_practices.md](./secrets_best_practices.md) | Управление секретами в Operator |

### Частые ошибки на собеседованиях

1. **"Prometheus требует root для работы"** — Нет. Prometheus корректно работает от UID 1000. Чтение метрик через ServiceAccount tokens не требует root.
2. **"config-reloader нуждается в特权ном доступе"** — Нет. Sidecar только мониторит Secret/ConfigMap и отправляет POST на /-/reload.
3. **"read-only FS ломает Prometheus"** — Нет. Данные пишутся в volume (emptyDir или PVC), а не в корневую FS. Конфигурация монтируется как read-only.
4. **"seccomp блокирует scraping"** — Нет. Scraping — это сетевые syscall (read/write/socket), которые разрешены в RuntimeDefault.
5. **"AppArmor и SELinux конфликтуют"** — На практике используется один LSM. На Ubuntu — AppArmor, на RHEL — SELinux.
