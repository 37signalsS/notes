# User Namespaces в Pod

## Определения

**User Namespace** — механизм ядра Linux, позволяющий маппировать идентификаторы пользователей (UID) и групп (GID) внутри контейнера на другие UID/GID на хосте. Процесс, запущенный от `root` (UID 0) внутри контейнера, работает под непривилегированным пользователем на хосте.

**Host User Namespace** — пользовательское пространство имён, создаваемое Kubernetes для пода при активации фичи User Namespaces.

**ID Map Mount** — механизм файловой системы, позволяющий маппировать UID/GID при монтировании. Требуется для работы User Namespaces в Kubernetes.

---

## Базовые концепции

### Назначение

User Namespaces изолируют пользователя внутри контейнера от пользователя на хосте. Процесс имеет полные привилегии внутри своего user namespace, но непривилегирован для операций за его пределами.

**Основные цели:**

| Цель | Описание |
| :--- | :--- |
| **Снижение ущерба при взломе** | Скомпрометированный контейнер не может напрямую влиять на хост или другие поды на той же ноде |
| **Митигация уязвимостей** | Критичные CVE, позволявшие контейнеру изменять бинарные файлы хоста, эскалировать привилегии или читать/записывать файлы хоста, нейтрализуются |
| **Принцип наименьших привилегий** | Контейнер работает с минимальными правами на уровне хоста, сохраняя функциональность внутри |

### Как работает маппинг

При активации User Namespaces Kubernetes автоматически:

1. Выбирает уникальный диапазон UID/GID на хосте для каждого пода
2. Маппирует UID/GID контейнера (0–65535) на выбранный диапазон хоста
3. Гарантирует, что два пода на одной ноде не используют одинаковый маппинг

```
Контейнер: UID 0 (root) → Хост: UID 500000 (непривилегированный)
Контейнер: UID 1        → Хост: UID 500001
...
```

**Важно:** `runAsUser`, `runAsGroup`, `fsGroup` и аналогичные поля в PodSpec всегда ссылаются на UID/GID **внутри контейнера**, а не на хосте.

### Диапазон UID/GID

| Параметр | Значение |
| :--- | :--- |
| Валидный диапазон UID/GID | 0–65535 |
| Overflow UID (обычно) | 65534 |
| Настройка Overflow | `kernel.overflowuid`, `kernel.overflowgid` |

Файлы с UID/GID вне диапазона 0–65535 отображаются как принадлежащие Overflow UID (по умолчанию 65534). Модификация таких файлов невозможна даже при запуске от Overflow UID.

### Активация

User Namespaces активируются на уровне пода через поле `hostUsers` в спецификации безопасности:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: pod-with-userns
spec:
  hostUsers: false  # ← Активирует User Namespace для пода
  containers:
  - name: app
    image: my-app:1.0
    securityContext:
      runAsUser: 0  # root внутри контейнера → непривилегированный на хосте
```

| Значение `hostUsers` | Описание |
| :--- | :--- |
| `false` | Pod использует свой user namespace с уникальным маппингом UID/GID |
| `true` (по умолчанию) | Pod использует user namespace хоста (без изоляции) |

### Совместимость

#### Kubernetes

| Версия | Статус фичи | Примечание |
| :--- | :--- | :--- |
| 1.25–1.26 | Alpha | Ранняя реализация |
| 1.27–1.29 | Alpha | Уточнять совместимость с containerd в документации версии |
| 1.30+ | — | Проверять актуальный статус в официальной документации |

#### Container Runtime

| Runtime | Версия | Совместимость |
| :--- | :--- | :--- |
| containerd | 1.7.0+ | **Несовместим** с User Namespace support |
| containerd | 1.6.x | Совместим с Kubernetes 1.25–1.26 |
| containerd | 1.7.x (поздние) | Проверять документацию для актуальной совместимости |

Статус поддержки User Namespaces в containerd отслеживается в [issues на GitHub containerd](https://github.com/containerd/containerd/issues).

#### Требования к ядру Linux

| Требование | Минимальная версия |
| :--- | :--- |
| Linux (общее) | 6.3+ |
| Поддержка ID Map Mounts | Требуется для всех файловых систем, используемой для хранения подов (`/var/lib/kubelet/pods` или кастомная директория) |

**Файловые системы с поддержкой ID Map Mounts (Linux 6.3+):**

- ext4
- XFS
- Btrfs
- F2FS
- tmpfs (критично для service account tokens, secrets, configmaps)
- overlayfs

**Почему tmpfs важен:** Несколько фич Kubernetes используют tmpfs по умолчанию — service account tokens, secrets, configmaps монтируются через tmpfs. Без поддержки ID Map Mounts в tmpfs User Namespaces не будет работать корректно.

### Ограничения

| Ограничение | Описание |
| :--- | :--- |
| **Только Linux** | Фича не работает на других ОС |
| **Alpha-статус** | Не включена по умолчанию, требует явной активации feature gate |
| **Совместимость runtime** | Не все container runtime поддерживают; containerd 1.7.0 несовместим |
| **Файловые системы** | Требуется поддержка ID Map Mounts на всех файловых системах пода |
| **Большинство приложений** | Должны продолжать работать без изменений, если запускаются от root и не требуют доступа к ресурсам за пределами user namespace |

---

## Практические сценарии

### Сценарий 1: Pod с изоляцией User Namespace

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: isolated-pod
spec:
  hostUsers: false  # Активирует User Namespace
  containers:
  - name: app
    image: nginx:1.28.0
    securityContext:
      runAsUser: 0       # root внутри контейнера
      runAsGroup: 0
      fsGroup: 0
    ports:
    - containerPort: 80
```

**Результат:** Процесс nginx работает от root внутри контейнера, но на хосте он будет непривилегированным пользователем с уникальным UID, выделенным Kubernetes.

### Сценарий 2: Проверка поддержки ID Map Mounts

```bash
# Проверка версии ядра
uname -r
# → 6.3.0-xxx-generic (требуется 6.3+)

# Проверка поддержки ID Map Mounts для tmpfs
mount | grep tmpfs
# → tmpfs on /run type tmpfs (rw,nosuid,nodev,...,idmap)

# Проверка файловых систем для kubelet
df -hT /var/lib/kubelet
# → Тип файловой системы должен поддерживать ID Map Mounts
```

### Сценарий 3: Диагностика проблем с Overflow UID

Если контейнер работает с файлами, принадлежащими UID/GID вне диапазона 0–65535:

```bash
# Проверка overflowuid на хосте
sysctl kernel.overflowuid
# → 65534

# Проверка владельцев файлов внутри контейнера
ls -ln /path/to/files
# → Файлы с UID > 65535 будут показаны как 65534 (nobody)

# Попытка модификации файлов с Overflow UID завершится ошибкой
# даже при запуске от UID 65534 внутри контейнера
```

---

## Дополнительная информация

**Связанные темы:** [Security Context](../../Security/pod_security_context.md), [Механизмы изоляции Linux](../../../Docker/Concepts/linux_isolation.md), [Rootless режим Podman](../../../Podman/podman_rootless.md), [Защита хоста и демона Docker](../../../Docker/Docker_security/host_daemon_hardening.md).

**Официальная документация:** [User Namespaces in Kubernetes Pods](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/)
