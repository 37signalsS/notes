# Безопасность контейнерного рантайма в Kubernetes

## Определения

**Container Runtime Security** — комплекс мер по защите среды выполнения контейнеров на уровне ядра Linux: ограничение системных вызовов (seccomp), контроль доступа к файловой системе и сети (AppArmor/SELinux), управление привилегиями (capabilities) и изоляция через sandboxed runtimes (gVisor, Kata Containers).

**Seccomp (Secure Computing Mode)** — механизм ядра Linux, ограничивающий набор системных вызовов (syscall), которые может выполнять процесс. В Kubernetes используется для сужения поверхности атаки на ядро: по умолчанию контейнер может вызывать ~300 из ~450 существующих syscall. Профиль `RuntimeDefault` блокирует наиболее опасные (например, `mount`, `ptrace`, `kexec_load`).

**AppArmor (Application Armor)** — модуль LSM (Linux Security Module), ограничивающий доступ процесса к файлам, сетевым операциям и системным вызовам на основе профилей. В Kubernetes профили применяются через `appArmorProfile` в SecurityContext (GA с 1.31) или аннотации (beta).

**SELinux (Security-Enhanced Linux)** — модуль LSM, реализующий mandatory access control (MAC) через систему меток (labels). Каждый процесс и файл получают контекст безопасности; ядро проверяет допустимость операций на основе правил политики. Используется в RHEL/CentOS/Fedora.

**Linux Capabilities** — механизм декомпозиции привилегий root на отдельные droits (например, `NET_BIND_SERVICE`, `SYS_PTRACE`, `CAP_NET_ADMIN`). Позволяет предоставлять контейнеру только необходимые привилегии вместо полного root.

**RuntimeClass** — Kubernetes-ресурс, определяющий среду выполнения для подов (runc, gVisor, Kata). Позволяет применять разные уровни изоляции к разным рабочим нагрузкам.

**Sandboxed Runtime** — альтернативный контейнерный рантайм, обеспечивающий дополнительную изоляцию: gVisor (userspace-ядро Sentry) или Kata Containers (микро-ВМ через Cloud-Hypervisor/QEMU).

---

## Основные концепции

### Seccomp в Kubernetes

**Режимы работы seccomp:**
- **Strict:** запрещает ВСЕ syscall кроме разрешённых ( Whitelist). Контейнер завершается с ошибкой при попытке вызвать неразрешённый syscall.
- **Filter (BPF):** используется фильтр Berkeley Packet Filter для проверки каждого syscall. Действия: `ALLOW`, `KILL`, `ERRNO`, `TRACE`, `LOG`.
- **RuntimeDefault:** профиль, встроенный в рантайм (containerd/CRI-O). Блокирует ~44 опасных syscall (mount, ptrace, kexec_load, userfaultfd и др.).

**Структура профиля seccomp:**
```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "architectures": ["SCMP_ARCH_X86_64"],
  "syscalls": [
    {
      "names": ["read", "write", "open", "close", "stat", "fstat",
                "mmap", "mprotect", "munmap", "brk", "exit_group",
                "futex", "epoll_wait", "accept", "socket", "connect"],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
```

**Применение в Kubernetes:**
```yaml
securityContext:
  seccompProfile:
    type: RuntimeDefault          # встроенный профиль рантайма
```
```yaml
securityContext:
  seccompProfile:
    type: Localhost
    localhostProfile: profiles/my-app.json  # кастомный профиль
```

**Создание кастомного профиля:**
1. Запуск контейнера в режиме `LOG` (логирование syscall без блокировки)
2. Сбор логов через `strace` или `auditd`
3. Генерация профиля из логов (инструмент `oci-seccomp-bpf-hook`)
4. Тестирование в complain mode (логирование без блокировки)
5. Развёртывание через Secret + `localhostProfile`

**Рекомендации:**
- Всегда используйте `RuntimeDefault` как минимум
- Кастомные профили — только для приложений с нестандартными syscall (Java JNI, eBPF-программы)
- Не используйте `Unconfined` — это отключает все ограничения

### AppArmor в Kubernetes

**Типы профилей:**
- **Enforce:** блокирует неразрешённые операции, логирует нарушения
- **Complain:** только логирует (для тестирования)
- **Kill:** завершает процесс при нарушении

**Применение в Kubernetes (GA с 1.31):**
```yaml
securityContext:
  appArmorProfile:
    type: RuntimeDefault
```
```yaml
securityContext:
  appArmorProfile:
    type: Localhost
    localhostProfile: custom/my-app
```

**Ранние версии (аннотации, beta):**
```yaml
metadata:
  annotations:
    container.apparmor.security.beta.kubernetes.io/<container>: runtime/default
```

**Создание профиля:**
```bash
# Генерация профиля из логов
aa-genprof /usr/bin/my-app

# Мониторинг нарушений
aa-logprof
```

**Ограничения AppArmor:**
- Работает только на Ubuntu, SUSE, Debian (не на RHEL/CentOS)
- Не защищает от kernel exploits (ограничивает пользовательское пространство)
- Не изолирует сетевой трафик (для этого нужен NetworkPolicy)

### SELinux в контейнерах

**Контекст безопасности (label):**
```
system_u:system_r:container_t:s0:c123,c456
│          │        │           │   └── MCS categories
│          │        │           └────── Level (sensitivity)
│          │        └────────────────── Type (процесс)
│          └─────────────────────────── Role
└────────────────────────────────────── User
```

**Применение в Kubernetes:**
```yaml
securityContext:
  seLinuxOptions:
    user: "system_u"
    role: "system_r"
    level: "s0:c123,c456"    # MCS изоляция
```

**MCS (Multi-Category Security):**
- Каждый под получает уникальные категории (c123,c456)
- Процессы в разных подах не могут взаимодействовать через SELinux
- Автоматически применяется при `PodSecurity Admission: restricted`

**SELinux в Podman (rootless):**
- Контекст: `system_u:system_r:container_t:s0`
- Дополнительные метки: `:Z` (одиночный под), `:z` (общий для нескольких подов)
- Rootless: ослабленные ограничения (нет `CAP_SYS_ADMIN`)

### Linux Capabilities

**Типичные capabilities и их опасность:**

| Capability | Назначение | Опасность |
|:---|:---|:---|
| `NET_BIND_SERVICE` | Привязка к портам <1024 | Низкая |
| `SYS_PTRACE` | Tracing процессов | Высокая |
| `NET_ADMIN` | Управление сетью (iptables, interfaces) | Высокая |
| `SYS_ADMIN` | Почти все привилегии root | Критическая |
| `SYS_MODULE` | Загрузка ядерных модулей | Критическая |
| `SYS_RAWIO` | Доступ к устройствам ввода/вывода | Критическая |
| `SYS_BOOT` | Перезагрузка системы | Высокая |
| `AUDIT_WRITE` | Запись в audit log | Средняя |
| `CHOWN` | Смена владельца файлов | Средняя |
| `DAC_OVERRIDE` | Обход DAC-разрешений | Высокая |

**Безопасный контейнер:**
```yaml
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
    add: ["NET_BIND_SERVICE"]   # только если нужен порт <1024
  readOnlyRootFilesystem: true
```

**Почему `drop: ["ALL"]` важен:**
- Даже `CHOWN` может быть использован для эскалации (смена владельца `/etc/passwd`)
- `DAC_OVERRIDE` обходит все Linux-разрешения
- `SYS_PTRACE` позволяет трейсить другие процессы и читать их память

### Sandboxed Runtimes

**gVisor:**
- Архитектура: userspace-ядро Sentry, перехватывающее syscall контейнера
- Изоляция: контейнер не взаимодействует напрямую с ядром хоста
- Overhead: 5-15% CPU, 30-50 MB RAM
- Ограничения: не все syscall поддерживаются (проблемы с某些 приложениями)

**Kata Containers:**
- Архитектура: микро-ВМ (Cloud-Hypervisor/QEMU) для каждого пода
- Изоляция: hardware-level (VT-x/AMD-V)
- Overhead: 25-40% CPU, 30-50 MB RAM
- Преимущество: полная изоляция ядра (свое ядро для каждого пода)

**Применение в Kubernetes:**
```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: gvisor          # containerd handler
---
apiVersion: v1
kind: Pod
spec:
  runtimeClassName: gvisor
```

**Сравнение:**

| Параметр | runc | gVisor | Kata |
|:---|:---|:---|:---|
| Изоляция | namespaces, cgroups | userspace-ядро | микро-ВМ |
| Overhead | Минимальный | 5-15% CPU | 25-40% CPU |
| Совместимость | Полная | Ограниченная | Почти полная |
| Защита от kernel exploit | Нет | Частичная | Полная |
| Запуск от root | Возможен | Невозможен | Невозможен |

---

## Практические сценарии

### Применение RuntimeDefault для всех подов в namespace

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: monitoring
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

### Кастомный seccomp-профиль для Prometheus

```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "architectures": ["SCMP_ARCH_X86_64"],
  "syscalls": [
    {
      "names": [
        "read", "write", "open", "close", "stat", "fstat", "lstat",
        "poll", "lseek", "mmap", "mprotect", "munmap", "brk",
        "ioctl", "access", "pipe", "select", "sched_yield",
        "mremap", "msync", "mincore", "madvise", "dup", "dup2",
        "nanosleep", "getpid", "clone", "fork", "execve",
        "exit", "wait4", "kill", "uname", "semget", "semop",
        "shmat", "shmget", "msgget", "msgrcv", "msgsnd",
        "fcntl", "flock", "fsync", "fdatasync", "truncate",
        "ftruncate", "getdents", "getcwd", "chdir", "fchdir",
        "rename", "mkdir", "rmdir", "creat", "link", "unlink",
        "symlink", "readlink", "chmod", "fchmod", "chown",
        "fchown", "lchown", "umask", "gettimeofday", "getrlimit",
        "getrusage", "sysinfo", "times", "ptrace", "getuid",
        "getgid", "setuid", "setgid", "geteuid", "getegid",
        "setpgid", "getppid", "getpgrp", "setsid", "setreuid",
        "setregid", "getgroups", "setgroups", "setresuid",
        "getresuid", "setresgid", "getresgid", "getpgid",
        "setfsuid", "setfsgid", "getsid", "capget", "capset",
        "rt_sigpending", "rt_sigtimedwait", "rt_sigaction",
        "rt_sigprocmask", "rt_sigtreturn", "rt_sigqueueinfo",
        "rt_sigsuspend", "sigaltstack", "utime", "mknod",
        "uselib", "personality", "ustat", "statfs", "fstatfs",
        "sysfs", "getpriority", "setpriority", "sched_setparam",
        "sched_getparam", "sched_setscheduler", "sched_getscheduler",
        "sched_get_priority_max", "sched_get_priority_min",
        "sched_rr_get_interval", "mlock", "munlock", "mlockall",
        "munlockall", "vhangup", "modify_ldt", "pivot_root",
        "_sysctl", "prctl", "arch_prctl", "adjtimex", "setrlimit",
        "chroot", "sync", "acct", "settimeofday", "mount",
        "umount2", "swapon", "swapoff", "reboot", "sethostname",
        "setdomainname", "iopl", "ioperm", "create_module",
        "init_module", "delete_module", "get_kernel_syms",
        "query_module", "quotactl", "nfsservctl", "getpmsg",
        "putpmsg", "afs_syscall", "tuxcall", "security",
        "gettid", "readahead", "setxattr", "lsetxattr",
        "fsetxattr", "getxattr", "lgetxattr", "fgetxattr",
        "listxattr", "llistxattr", "flistxattr", "removexattr",
        "lremovexattr", "fremovexattr", "tkill", "time",
        "futex", "sched_setaffinity", "sched_getaffinity",
        "set_thread_area", "io_setup", "io_destroy", "io_getevents",
        "io_submit", "io_cancel", "get_thread_area", "lookup_dcookie",
        "epoll_create", "epoll_ctl_old", "epoll_wait_old",
        "remap_file_pages", "getdents64", "set_tid_address",
        "restart_syscall", "semtimedop", "fadvise64",
        "timer_create", "timer_settime", "timer_gettime",
        "timer_getoverrun", "timer_delete", "clock_settime",
        "clock_gettime", "clock_getres", "clock_nanosleep",
        "exit_group", "epoll_wait", "epoll_ctl", "tgkill",
        "utimes", "vserver", "mbind", "set_mempolicy",
        "get_mempolicy", "mq_open", "mq_unlink", "mq_timedsend",
        "mq_timedreceive", "mq_notify", "mq_getsetattr",
        "kexec_load", "waitid", "add_key", "request_key",
        "keyctl", "ioprio_set", "ioprio_get", "inotify_init",
        "inotify_add_watch", "inotify_rm_watch", "migrate_pages",
        "openat", "mkdirat", "mknodat", "fchownat", "futimesat",
        "newfstatat", "unlinkat", "renameat", "linkat",
        "symlinkat", "readlinkat", "fchmodat", "faccessat",
        "pselect6", "ppoll", "unshare", "set_robust_list",
        "get_robust_list", "splice", "tee", "sync_file_range",
        "vmsplice", "move_pages", "utimensat", "epoll_pwait",
        "signalfd", "timerfd_create", "eventfd", "fallocate",
        "timerfd_settime", "timerfd_gettime", "accept4",
        "signalfd4", "eventfd2", "epoll_create1", "dup3",
        "pipe2", "inotify_init1", "preadv", "pwritev",
        "rt_tgsigqueueinfo", "perf_event_open", "recvmmsg",
        "fanotify_init", "fanotify_mark", "prlimit64",
        "name_to_handle_at", "open_by_handle_at", "clock_adjtime",
        "syncfs", "sendmmsg", "setns", "getcpu",
        "process_vm_readv", "process_vm_writev", "kcmp",
        "finit_module", "sched_setattr", "sched_getattr",
        "renameat2", "seccomp", "getrandom", "memfd_create",
        "kexec_file_load", "bpf", "execveat", "userfaultfd",
        "membarrier", "mlock2", "copy_file_range",
        "preadv2", "pwritev2", "pkey_mprotect", "pkey_alloc",
        "pkey_free", "statx", "io_pgetevents", "rseq",
        "kexec_file_load"
      ],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
```

### Мониторинг seccomp-нарушений

```yaml
# PrometheusRule для алертов при seccomp-нарушениях
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: seccomp-alerts
spec:
  groups:
    - name: seccomp
      rules:
        - alert: SeccompViolationDetected
          expr: |
            increase(node_seccomp_filtered_syscalls_total[5m]) > 0
          for: 1m
          labels:
            severity: warning
          annotations:
            summary: "Seccomp нарушение обнаружено"
            description: "Контейнер {{ $labels.container }} пытается вызвать заблокированный syscall"
```

### Сравнение SecurityContext для разных сценариев

**Минимально безопасный (Baseline):**
```yaml
securityContext:
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault
```

**Строгий (Restricted):**
```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 2000
  seccompProfile:
    type: RuntimeDefault
  appArmorProfile:
    type: RuntimeDefault
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
  readOnlyRootFilesystem: true
```

**Для monitoring-компонентов (Prometheus, Alertmanager):**
```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 2000
  seccompProfile:
    type: RuntimeDefault
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
  readOnlyRootFilesystem: true
  # tmpDir и dataDir должны быть volumeMounts с правами записи
```

---

## Дополнительная информация

### Инструменты для профилирования

| Инструмент | Назначение | Тип |
|:---|:---|:---|
| `oci-seccomp-bpf-hook` | Генерация seccomp-профилей из syscall | Runtime |
| `strace` | Трассировка syscall процесса | Debug |
| `aa-genprof` | Генерация AppArmor-профилей | Runtime |
| `aa-logprof` | Мониторинг нарушений AppArmor | Audit |
| `Falco` | Детекция аномалий в syscall | Runtime |
| `Tetragon` | eBPF-мониторинг и enforcement | Runtime |
| `Inspektor Gadget` | eBPF-отладка в Kubernetes | Debug |

### Ссылки

- [Security Context в Kubernetes](./pod_security_context.md) — настройки Pod/Container SecurityContext
- [Pod Security Standards](../Base/Pod/pod_security_labels.md) — привилегированные/базовые/строгие профили
- [Falco](../../Security/Tools/falco.md) — мониторинг syscall в реальном времени
- [RuntimeClass](../Concepts/container_runtime.md) — выбор контейнерного рантайма

### Частые ошибки на собеседованиях

1. **"Seccomp и AppArmor — одно и то же"** — Нет. Seccomp ограничивает syscall (ядро), AppArmor — доступ к файлам/сети (LSM). Они дополняют друг друга.
2. **"RuntimeDefault полностью защищает от escape"** — Нет. Он блокирует опасные syscall, но не защищает от kernel exploits. Для полной изоляции нужен sandboxed runtime (gVisor/Kata).
3. **"SELinux и AppArmor можно использовать одновременно"** — Формально да (оба LSM), но в practice выбирают один. На RHEL — SELinux, на Ubuntu — AppArmor.
4. **"drop: ["ALL"] ломает приложения"** — Редко. Большинство приложений не нуждаются в privileged capabilities. Проблемы возникают с приложениями, привязывающимся к портам <1024 (`NET_BIND_SERVICE`) или использующими `ptrace` (отладчики).
5. **"gVisor — это виртуальная машина"** — Нет. gVisor — это userspace-ядро (Sentry), работающее как процесс в хостовом ядре. Kata — это микро-ВМ с собственным ядром.
