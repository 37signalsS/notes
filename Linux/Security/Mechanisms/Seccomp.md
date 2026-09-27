# Seccomp (Secure Computing Mode)

## Определения и терминология

**Seccomp (Secure Computing Mode)** — механизм безопасности ядра Linux, предназначенный для фильтрации системных вызовов (syscalls) процесса. Он позволяет ограничить поверхность атаки на ядро, запрещая выполнение потенциально опасных или ненужных вызовов.

**Принцип:** Процесс добровольно (или через супервизора) переходит в состояние, где его взаимодействие с ядром жестко ограничено. Если процесс пытается выполнить запрещенный вызов, ядро может немедленно завершить его, вернуть ошибку или отправить уведомление внешнему менеджеру.

### История и эволюция

Seccomp появился в ядре Linux 2.6.12 (2005) как упрощенный вариант, ограничивавший процесс четырьмя системными вызовами (`read`, `write`, `_exit`, `sigreturn`). В 2012 году в ядре 3.5 была добавлена поддержка **seccomp-bpf** (режим `filter`), позволяющая использовать классический BPF (cBPF) для создания гибких правил. В 2014 году Docker включил seccomp-профили по умолчанию, что сделало механизм стандартом для контейнерной индустрии. В 2024–2025 годах в ядро 6.x добавлены действия `SCMP_ACT_STRDUP`, `SCMP_ACT_STRERR` и флаг `SECCOMP_USER_NOTIF_FD_SYNC_WAKE_UP` для снижения задержек уведомлений.

### Ключевые термины

| Термин | Описание |
| :--- | :--- |
| **Syscall (системный вызов)** | Интерфейс между пользовательским пространством и ядром (например, `open()`, `mount()`, `ptrace()`). |
| **BPF (Berkeley Packet Filter)** | Виртуальная машина в ядре для выполнения фильтров. В Seccomp используется классический cBPF. |
| **no_new_privs** | Флаг ядра, запрещающий процессу получать новые привилегии через `execve()`. Обязателен для Seccomp в режиме `filter`. |
| **TSYNC** | Флаг синхронизации: применение одного и того же фильтра ко всем потокам процесса атомарно. |
| **USER_NOTIF** | Механизм приостановки syscall и уведомления внешнего супервизора для принятия решения. |
| **libseccomp** | Пользовательская библиотека для генерации BPF-фильтров из высокоуровневых правил. |
| **CIL (Common Intermediate Language)** | Язык политик, используемый в современных дистрибутивах (RHEL 8+, Fedora). |
| **AVC (Access Vector Cache)** | Кэш проверок доступа в LSM. Seccomp работает на более низком уровне, до вызова LSM. |

### Компоненты контекста безопасности (связь с LSM)

| Компонент | Описание | Пример |
| :--- | :--- | :--- |
| **User** | Пользователь SELinux (не UID ОС) | `system_u`, `unconfined_u` |
| **Role** | Роль, определяющая доступные домены (RBAC) | `system_r`, `object_r` |
| **Type/Domain** | Тип для объектов, домен для процессов | `httpd_t`, `httpd_sys_content_t` |
| **Level** | Уровень чувствительности и категории (MLS/MCS) | `s0`, `s0:c0.c1023` |

## Основные концепции

### Режимы работы

| Режим | Описание | Применение |
| :--- | :--- | :--- |
| **`strict` (Mode 1)** | Разрешает только 4 вызова: `read()`, `write()`, `_exit()`, `sigreturn()`. Любой другой вызов → `SIGKILL`. | Исторический режим, крайне ограниченное применение. |
| **`filter` (Mode 2 / seccomp-bpf)** | Позволяет создавать сложные правила фильтрации на основе классического BPF (cBPF). | Стандарт для Docker, Kubernetes, браузеров, systemd. |

### Действия фильтра (Seccomp Actions)

При совпадении правила фильтр может вернуть одно из следующих действий:

*   **`SCMP_ACT_ALLOW`**: Разрешить выполнение системного вызова.
*   **`SCMP_ACT_KILL_PROCESS`**: Немедленно завершить весь процесс (стандарт для безопасности).
*   **`SCMP_ACT_ERRNO`**: Запретить вызов и вернуть процессу ошибку (например, `EPERM`). Позволяет приложению корректно обработать отказ.
*   **`SCMP_ACT_LOG`**: Разрешить вызов, но зафиксировать его в системном логе (удобно для отладки).
*   **`SCMP_ACT_TRAP`**: Отправить процессу сигнал `SIGSYS` для самодиагностики.
*   **`SCMP_ACT_NOTIFY` (v5.0+)**: Приостановить вызов и отправить уведомление в пользовательское пространство (User Notification).
*   **`SCMP_ACT_STRDUP` (v6.0+)**: Заменить строковый аргумент вызова на пустую строку. Используется для скрытия чувствительных данных (путей, доменов) от ядра без блокировки самого вызова.
*   **`SCMP_ACT_STRERR` (v6.0+)**: Заменить строковый аргумент на ошибку `EINVAL` и продолжить выполнение вызова. Полезно для перехвата путей к конфиденциальным файлам.

### Архитектура и интеграция в ядро

Seccomp работает на стыке двух подсистем ядра:

1.  **Точка входа:** Системный вызов `prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, ...)` или `seccomp()` переводит процесс в режим `filter`. Ядро устанавливает флаг `SECCOMP` в `task_struct` потока.
2.  **Проверка:** При каждом системном вызове ядро проверяет флаг `SECCOMP`. Если активен режим `filter`, syscall передается на выполнение BPF-программы, загруженной процессом.
3.  **Выполнение BPF:** Виртуальная машина cBPF анализирует номер syscall, архитектуру и аргументы. В отличие от eBPF, cBPF имеет ограниченный набор инструкций, но работает стабильнее для данной задачи.
4.  **Действие:** В зависимости от результата BPF-программы ядро разрешает, блокирует или уведомляет о вызове.
5.  **no_new_privs:** Перед загрузкой фильтра ядро проверяет флаг `no_new_privs`. Если он не установлен, `prctl(PR_SET_SECCOMP)` завершится ошибкой `EINVAL` (начиная с ядра 3.8). Это предотвращает обход seccomp через `execve()` SUID-бинарника.

### Сравнение с современными механизмами (2026)

| Характеристика | Seccomp | Landlock (ABI v7+) | BPF LSM |
| :--- | :--- | :--- | :--- |
| **Уровень** | Номера syscall (Поверхностный) | Объекты: файлы, порты (Средний) | Глубокий контекст ядра |
| **Инспекция указателей** | Нет (Риск TOCTOU) | **Да** (Пути файлов) | **Да** (Внутренние структуры) |
| **Привилегии** | Не требуются (no_new_privs) | **Не требуются** | Требуется CAP_BPF / Root |
| **Назначение** | Снижение поверхности атаки | Песочница приложения | Системный аудит и EDR |

## Практические сценарии

### 1. Проверка статуса Seccomp

```bash
# Проверка режима для процесса (PID 123)
grep Seccomp /proc/123/status
# → Seccomp: 2 (Filter)

# Проверка флага no_new_privs
grep NoNewPriv /proc/123/status
# → NoNewPrivs: 1
```

### 2. Нативная фильтрация через libseccomp (C/Python)

Прямое использование libseccomp без контейнеров:

```c
#include <seccomp.h>
#include <unistd.h>

int main() {
    scmp_filter_ctx ctx = seccomp_init(SCMP_ACT_KILL_PROCESS);
    seccomp_rule_add(ctx, SCMP_ACT_ALLOW, SCMP_SYS(read), 0);
    seccomp_rule_add(ctx, SCMP_ACT_ALLOW, SCMP_SYS(write), 0);
    seccomp_rule_add(ctx, SCMP_ACT_ALLOW, SCMP_SYS(exit), 0);
    seccomp_rule_add(ctx, SCMP_ACT_ALLOW, SCMP_SYS(rt_sigreturn), 0);
    seccomp_load(ctx);
    seccomp_release(ctx);
    execl("/bin/cat", "cat", "/etc/passwd", NULL);
}
```

### 3. systemd: SystemCallFilter и секционирование сервисов

systemd предоставляет встроенную фильтрацию syscall через `SystemCallFilter=`:

```ini
# /etc/systemd/system/nginx.service.d/security.conf
[Service]
SystemCallFilter=@system-service
SystemCallErrorNumber=EPERM
SystemCallLog=@system-service
```

*   **`@system-service`**: Набор безопасных syscall для сервисов (определен в systemd).
*   **`SystemCallErrorNumber=EPERM`**: При попытке запрещенного вызова вернуть `EPERM` вместо убийства процесса.
*   **`SystemCallLog=`**: Логировать все запрещенные вызовы в journald.

Для сервисов, требующих специфических вызовов:

```ini
[Service]
SystemCallFilter=@system-service ~@mount ~@reboot ~@clock
SystemCallErrorNumber=EPERM
SystemCallLog=@system-service
```

*   **`~@mount`**: Убрать из набора группу `mount`.
*   **`~@reboot`**: Убрать группу `reboot`.

Проверка:

```bash
# Проверка активных фильтров journald
journalctl -u nginx | grep -i "seccomp\|systemcall"
# → "System call filter is active"
```

### 4. Генерация профилей из аудита (audit2seccomp и strace)

Создание профиля на основе реального выполнения приложения:

```bash
# Запуск приложения под strace с логированием syscalls
strace -f -e trace=%syscall -o trace.log ./my-app

# Фильтрация только уникальных вызовов
cut -d'(' -f1 trace.log | sort -u > syscalls.txt

# Формирование JSON-профиля (ручной метод)
# Или использование audit2seccomp (если установлен):
ausearch -m SECCOMP -i | audit2seccomp -o my-profile.json
```

### 5. Ручное создание JSON/CIL профилей

Минимальный профиль для веб-сервера:

```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "architectures": ["SCMP_ARCH_X86_64", "SCMP_ARCH_AARCH64"],
  "syscalls": [
    {
      "names": ["read", "write", "open", "openat", "close", "stat",
                "fstat", "mmap", "mprotect", "munmap", "brk",
                "exit_group", "futex", "nanosleep", "epoll_wait",
                "accept", "socket", "connect", "bind", "listen",
                "sendto", "recvfrom", "getsockopt", "setsockopt"],
      "action": "SCMP_ACT_ALLOW"
    },
    {
      "names": ["mount", "umount2", "ptrace", "kexec_load", "reboot"],
      "action": "SCMP_ACT_KILL_PROCESS"
    }
  ]
}
```

### 6. Валидация и отладка профилей

```bash
# Валидация JSON-синтаксиса
python3 -m json.tool my-profile.json

# Проверка с помощью scmp (seccomp-tools)
scmp-syscall-resolver x86_64 read
# → 0

# Загрузка профиля вручную (C через libseccomp)
# Проверка работы: strace -f ./my-app
```

### 7. Использование в контейнерах (runc, Docker, Podman)

По умолчанию контейнерные рантаймы применяют профили:

*   **runc**: применяет профиль `runc-default` (блокирует ~44 опасных вызовов: `mount`, `reboot`, `ptrace`, `kexec_load`).
*   **Docker**: наследует профиль от runc; можно переопределить через `--security-opt seccomp=/path/to/profile.json`.
*   **Podman**: применяет профиль из `/usr/share/containers/seccomp.json` (блокирует ~30+ вызовов). Подробнее: [**Изоляция в Podman**](../../../Podman/linux_isolation.md).

### 8. Kubernetes: SeccompDefault и кастомные профили

В 2026 году функция **SeccompDefault** является стабильной (GA). Feature gate удален, функционал встроен в ядро K8s.

**Настройка узла (Kubelet):**
Чтобы включить профиль `RuntimeDefault` для всех подов по умолчанию, необходимо настроить Kubelet:
```yaml
# kubelet.conf
seccompDefault: true
```

**Использование в Pod Security Standards:**
Профиль `Restricted` требует явного использования `RuntimeDefault`.
```yaml
spec:
  securityContext:
    seccompProfile:
      type: RuntimeDefault
```

Подробнее: [**Security Context в Kubernetes**](../../../Kubernetes/Security/pod_security_context.md).

### 9. Взаимодействие с User Namespaces

Внутри User Namespace процесс может иметь "полные" capabilities, но для основного ядра (Host) этот процесс остается непривилегированным. Seccomp работает на уровне потока, поэтому фильтры наследуются через `clone()` / `fork()` независимо от User Namespaces.

## Ограничения и архитектурные нюансы

1.  **Аргументы по указателям:** Seccomp не видит содержимое строк (пути, доменные имена). Для этого используйте **Landlock** или **AppArmor/SELinux**. В ядре 6.x действия `STRDUP` и `STRERR` позволяют частично решить эту проблему для строковых аргументов.
2.  **Мультиархитектурность:** Номера системных вызовов различаются между x86_64, ARM64 и RISC-V. Библиотека `libseccomp` помогает абстрагироваться от этого, используя имена вызовов.
3.  **Наследование:** Фильтры Seccomp наследуются всеми дочерними процессами и не могут быть удалены (принцип «замка изнутри»). Исключение: режим `strict` можно включить только один раз.
4.  **Производительность:** Слишком большие фильтры (сотни правил) могут вносить задержки. Рекомендуется размещать наиболее частые вызовы (`read`, `write`, `epoll_wait`) в начале списка.
5.  **TOCTOU:** Seccomp проверяет только скалярные аргументы в регистрах. Он не может безопасно проверять данные по указателям (например, пути файлов), так как они могут быть изменены другим потоком процесса после проверки, но до выполнения вызова.

## Матрица совместимости: Seccomp и Workload

| Workload | Минимальный набор syscall | Требуемые исключения | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Стендовый Go-сервис** | `read`, `write`, `open`, `close`, `futex`, `nanosleep`, `epoll_wait`, `accept`, `socket`, `bind`, `listen`, `sendto`, `recvfrom` | Нет | `RuntimeDefault` + белый список |
| **nginx / Apache** | + `mmap`, `mprotect`, `munmap`, `brk`, `stat`, `fstat`, `getsockopt`, `setsockopt`, `clone` | Нет | `RuntimeDefault` достаточен |
| **PostgreSQL / MySQL** | + `pread64`, `pwrite64`, `lseek`, `fdatasync`, `sync_file_range` | Нет | `RuntimeDefault` + аудит I/O |
| **Node.js / Python** | + `eventfd`, `inotify`, `signalfd`, `timerfd`, `epoll_create`, `epoll_ctl`, `epoll_pwait` | Нет | `RuntimeDefault` + профили eBPF |
| **SSH-сервер** | + `getrandom`, `recvmsg`, `sendmsg`, `shutdown`, `getsockname`, `getpeername` | Нет | `RuntimeDefault` + аудит auth |
| **Java-приложение** | + `futex`, `clone` (с флагами), `rt_sigaction`, `rt_sigprocmask`, `getpid`, `gettid`, `sched_getaffinity`, `sched_setaffinity` | Нет | `RuntimeDefault` + JIT требует `mmap` |
| **Системный сервис (systemd)** | Зависит от `@system-service` | `@mount`, `@reboot`, `@clock` | `SystemCallFilter=@system-service` |
| **Rootless-контейнер** | Зависит от runtime | Нет | Профиль рантайма (runc/crun) |
| **CI/CD раннер (untrusted)** | Минимальный набор | Полный запрет `@reboot`, `@mount`, `@module` | `SCMP_ACT_KILL_PROCESS` + `notify` |

### Уровни совместимости

| Обозначение | Описание |
| :--- | :--- |
| **[OK]** | Стандартный профиль работает без изменений. |
| **[!]** | Требуется добавление 1–5 syscall в белый список. |
| **[BLOCKED]** | Требуется критический syscall (например, `mount`, `kexec_load`), который нельзя безопасно разрешить. |

## Дополнительная информация

### Инструменты и пакеты

| Пакет | Утилиты | Назначение |
| :--- | :--- | :--- |
| `libseccomp` | `seccomp_load`, `seccomp_rule_add` | Программное создание фильтров из C/Python/Go |
| `seccomp-tools` | `scmp-syscall-resolver`, `scmp-bpf-disasm` | Дизассемблирование и валидация BPF-программ |
| `audit2seccomp` | `audit2seccomp` | Генерация JSON-профилей из логов auditd |
| `strace` | `strace`, `ltrace` | Трассировка syscall для профилирования |
| `setools-console` | `seinfo`, `sesearch` | Анализ политик в связке с SELinux/AppArmor |
| `bpftool` | `bpftool prog list`, `bpftool map dump` | Инспекция BPF-программ (eBPF, не cBPF) |

### Дополнительные ссылки по темам

*   **Linux Man-pages:** [seccomp(2)](https://man7.org/linux/man-pages/man2/seccomp.2.html) — системный вызов и режимы.
*   **libseccomp:** [GitHub](https://github.com/seccomp/libseccomp) — исходный код библиотеки и документация.
*   **systemd:** [SystemCallFilter](https://www.freedesktop.org/software/systemd/man/systemd.exec.html#SystemCallFilter=) — фильтрация в unit-файлах.
*   **Kubernetes:** [SeccompDefault](https://kubernetes.io/docs/tutorials/security/seccomp/) — включение RuntimeDefault.

### См. также
- [Обзор механизмов безопасности Linux](../Linux_Security_Mechanisms_Overview.md)
- [Пространства имен (Namespaces)](../../Core/namespaces.md)
- [Привилегии ядра (Capabilities)](./Capabilities.md)
- [eBPF: программируемое ядро](../../Core/kernel/ebpf.md)
- [Landlock: современная песочница ФС](./Landlock.md)
- [Безопасность модулей ядра](./kernel_module_security.md) — подпись и контроль загрузки модулей
- [Укрепление безопасности контейнеров](../../../Docker/Docker_security/container_hardening.md)
- [Security Context в Kubernetes](../../../Kubernetes/Security/pod_security_context.md)
- [Изоляция в Podman](../../../Podman/linux_isolation.md)
