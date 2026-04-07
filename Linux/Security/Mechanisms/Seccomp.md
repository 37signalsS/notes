# Seccomp

## Definitions

**Seccomp (Secure Computing Mode)** — механизм безопасности в ядре Linux, работающий как фильтр системных вызовов (syscalls), доступных процессу. Основная задача — ограничение поверхности атаки на ядро путём запрета процессу выполнять любые системные вызовы, кроме строго определённого набора. Ключевой инструмент для изоляции приложений, особенно в контейнерах.

## Basic Concepts

### Режимы работы

| Режим | Описание | Применение |
| :--- | :--- | :--- |
| **`strict`** | Разрешает только 4 syscall: `read()`, `write()`, `_exit()`, `sigreturn()`. Остальные завершают процесс сигналом `SIGKILL` | Максимальная безопасность, простые программы |
| **`filter` (seccomp-bpf)** | Произвольные правила фильтрации через BPF (Berkeley Packet Filter). Белый/чёрный список syscalls | Docker, Kubernetes, кастомные профили |

### Роль в изоляции контейнеров

Seccomp — один из трёх фундаментальных строительных блоков изоляции контейнеров в Linux:

| Механизм | Что изолирует |
| :--- | :--- |
| **Namespaces** | Ресурсы: файловая система, сеть, IPC |
| **Capabilities** | Привилегии `root` |
| **Seccomp** | Взаимодействие процесса с ядром (syscalls) |

В случае компрометации приложения в контейнере Seccomp значительно снижает риски, ограничивая набор доступных системных вызовов.

## Practical Scenarios

### 1. Проверка режима Seccomp

Информацию о режиме seccomp для конкретного процесса можно найти в файле `/proc/<PID>/status`.

```bash
# Проверить статус seccomp для текущей оболочки
grep Seccomp /proc/$$/status
```

Возможные значения:

| Значение | Режим |
| :--- | :--- |
| `Seccomp: 0` | Отключён |
| `Seccomp: 1` | `strict` |
| `Seccomp: 2` | `seccomp-bpf` (filter) |

### 2. Применение в Docker

Docker по умолчанию использует seccomp-профиль, блокирующий ~44 из 300+ syscalls, считающихся опасными или редко используемыми.

**Запуск с пользовательским профилем:**

```bash
# custom_profile.json — правила seccomp в формате JSON
docker run --security-opt seccomp=/path/to/custom_profile.json alpine
```

**Полное отключение (не рекомендуется):**

```bash
docker run --rm -it --security-opt seccomp=unconfined alpine /bin/sh
```

### 3. Применение в Kubernetes

В Kubernetes профиль seccomp настраивается в контексте безопасности Пода или контейнера (`securityContext`).

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: seccomp-demo
spec:
  securityContext:
    seccompProfile:
      # Использует профиль по умолчанию, предоставляемый средой выполнения контейнеров (Docker, containerd)
      type: RuntimeDefault 
  containers:
  - name: test-container
    image: alpine
    command: ["sleep", "3600"]
    # Можно переопределить профиль на уровне контейнера
    securityContext:
      seccompProfile:
        # Отключает seccomp для этого конкретного контейнера
        type: Unconfined 
```

Доступные типы `seccompProfile`:

* `RuntimeDefault`: Профиль по умолчанию, предоставляемый средой выполнения.
* `Unconfined`: Seccomp не применяется.
* `Localhost`: Используется кастомный профиль, который должен находиться на узле в директории `<kubelet-root-dir>/seccomp/`.

## Additional Information

* **Контекст:** Seccomp — один из механизмов изоляции Linux, описанных в [обзоре механизмов безопасности](../Linux_Security_Mechanisms_Overview.md).
* **Связанные технологии:** [Namespaces](../../Core/namespaces.md), [Capabilities](./Capabilities.md).
