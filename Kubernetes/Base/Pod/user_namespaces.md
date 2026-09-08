# User Namespaces в Pod

## Определения

**User Namespace (Пользовательское пространство имен)** — механизм ядра Linux, обеспечивающий изоляцию идентификаторов пользователей (UID) и групп (GID). Он позволяет сопоставлять идентификаторы внутри контейнера (например, UID 0 — `root`) с другими идентификаторами на хосте. Таким образом, процесс с правами суперпользователя в Pod фактически выполняется от имени обычного непривилегированного пользователя на узле.

**Host User Namespace** — пространство имен пользователей хост-системы. По умолчанию Pod используют именно его (`hostUsers: true`), что означает полное совпадение UID/GID внутри и снаружи контейнера.

**ID-mapped Mount (Монтирование с сопоставлением ID)** — технология файловой системы Linux (ядро 5.12+), позволяющая динамически переназначать владельцев файлов при монтировании без рекурсивного `chown`. Реализуется через системный вызов `mount_setattr()` с флагом `MOUNT_ATTR_IDMAP`. Это ключевой компонент для работы User Namespaces в Kubernetes.

**Subordinate UID/GID (subuid/subgid)** — диапазоны вспомогательных идентификаторов, определяемые в файлах `/etc/subuid` и `/etc/subgid`. Формат записи: `пользователь:начальный_ID:количество`. Kubernetes использует эти диапазоны для выделения уникальных пространств имён каждому Pod на узле.

**Container Breakout (Побег из контейнера)** — атака, при которой злоумышленник выходит за пределы изоляции контейнера для получения доступа к хост-системе. User Namespaces являются одним из ключевых механизмов защиты от此类 атак.

---

## Базовые концепции

### Назначение и преимущества

User Namespaces являются критическим слоем защиты от **Container Breakout** (выхода за пределы контейнера). Даже если злоумышленник получит права `root` внутри Pod, его возможности на уровне узла будут ограничены правами обычного пользователя.

**Ключевые преимущества:**

| Преимущество | Описание |
| :--- | :--- |
| **Снижение риска компрометации** | UID 0 в контейнере мапится на UID (например) 100000 на хосте. У такого пользователя нет доступа к системным файлам узла. |
| **Безопасный запуск root-приложений** | Позволяет запускать приложения, требующие `root` внутри (например, для настройки VPN или установки пакетов), без реальных привилегий на хосте. |
| **Изоляция между Pod** | Kubernetes назначает уникальные диапазоны UID для разных Pod на одном узле, изолируя их друг от друга на уровне ядра. |
| **Совместимость с PSA/PSS** | User Namespaces позволяют соблюдать политики `restricted` PSS, сохраняя возможность запуска приложений, требующих root внутри контейнера. |

### Механизм сопоставления (Mapping)

При активации User Namespaces Kubernetes автоматически выполняет следующие действия:

1. Выделяет уникальный диапазон UID/GID на Node для каждого Pod.
2. Сопоставляет внутренний диапазон container (обычно 0–65535) с выделенным диапазоном Host.
3. Обеспечивает непересекаемость диапазонов для разных Pod на одной Node.

**Формат записи маппинга в `/proc/[pid]/uid_map`:**
```
ID-внутри-ns ID-снаружи-ns длина
```

**Пример:**
```
# Внутри контейнера (PID namespaces):
cat /proc/1/uid_map
         0     100000      65536
```
- `0` — root в контейнере (UID 0)
- `100000` — соответствующий UID на хосте
- `65536` — размер диапазона

**Важно:** Параметры `runAsUser`, `runAsGroup` и `fsGroup` в спецификации Pod всегда относятся к идентификаторам **внутри container**.

### Требования и статус поддержки

#### Статус в Kubernetes

| Версия | Статус | Feature Gate | Примечание |
| :--- | :--- | :--- | :--- |
| **1.30** | Beta | `UserNamespacesSupport=true` | Поддержка томов и StatefulSet. |
| **1.33+** | **GA** | Включено по умолчанию | Полная стабилизация механизма. |

#### Системные требования

| Компонент | Требование | Примечание |
| :--- | :--- | :--- |
| **Ядро Linux** | 6.3 или выше | Необходима поддержка `idmap mounts`. |
| **Runtime** | `containerd` 2.0+ или `CRI-O` 1.25+ | Поддержка взаимодействия через CRI. |
| **Файловая система** | ext4, XFS, Btrfs, tmpfs | ФС должна поддерживать сопоставление идентификаторов. |

**Особенности tmpfs:** Поддержка в `tmpfs` критична, так как Kubernetes использует её для монтирования Secret, ConfigMap и токенов ServiceAccount.

#### Настройка подuid/subgid на ноде

Kubernetes выделяет диапазоны UID/GID для Pod на основе конфигурации ноды. Управление диапазонами осуществляется через:

**Файлы `/etc/subuid` и `/etc/subgid`:**
```bash
# Формат: пользователь:начальный_ID:количество
# Пример для kubelet или CRI runtime:
containerd:100000:65536
cri-o:165536:65536
```

**Проверка выделенных диапазонов:**
```bash
# Просмотр всех выделенных диапазонов
cat /etc/subuid
cat /etc/subgid

# Проверка для конкретного пользователя (kubelet)
grep kubelet /etc/subuid

# Просмотр текущих маппингов для Pod
# (внутри контейнера с user namespace)
cat /proc/1/uid_map
cat /proc/1/gid_map
```

**Важно:** Диапазоны должны быть уникальными для разных CRI runtime и не пересекаться. При установке containerd или CRI-O пакеты обычно автоматически добавляют записи в `/etc/subuid` и `/etc/subgid`.

### Конфигурация CRI рантаймов

#### containerd

```toml
# /etc/containerd/config.toml
[plugins."io.containerd.grpc.v1.cri"]
  # Включение User Namespaces для Pod
  enable_userns = true
  
  # Путь к файлу с маппингами (опционально)
  # userns_mapping_file = "/etc/containerd/userns_mapping"
```

**Проверка поддержки containerd:**
```bash
# Проверка версии containerd (требуется 2.0+)
containerd --version

# Проверка конфигурации
containerd config dump | grep userns
```

#### CRI-O

```toml
# /etc/crio/crio.conf
[crio.runtime]
  # Включение User Namespaces
  userns_run_as = "auto"
  
  # Диапазон UID для Pod (если не указан в subuid)
  # uid_mappings = [{"container_id": 0, "host_id": 100000, "size": 65536}]
```

**Проверка CRI-O:**
```bash
# Проверка версии (требуется 1.25+)
crio --version

# Проверка конфигурации
cat /etc/crio/crio.conf | grep -A 5 userns
```

### Активация и использование

Функция активируется в спецификации Pod через поле `hostUsers`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secure-app
spec:
  hostUsers: false  # Активирует выделенное User Namespace для Pod
  containers:
  - name: web-server
    image: nginx:latest
    securityContext:
      runAsUser: 0  # root внутри -> непривилегированный снаружи
```

| Значение `hostUsers` | Результат |
| :--- | :--- |
| `false` | Pod изолирован в собственном пользовательском пространстве имён. |
| `true` (по умолчанию) | Pod использует пространство имён Host (изоляция UID/GID отсутствует). |

**Взаимодействие с Pod Security Admission (PSA):**

| Профиль PSS | Требование | `hostUsers: false` |
| :--- | :--- | :--- |
| **privileged** | Без ограничений | Разрешает root без маппинга |
| **baseline** | Запрет privileged, hostPID, hostIPC | Разрешает, но требует non-root снаружи |
| **restricted** | Запрет root в контейнере | **Позволяет root внутри** (UID мапится на non-root на хосте) |

**Важно:** Для профиля `restricted` PSS параметр `runAsNonRoot: true` в `securityContext` проверяет UID **внутри контейнера**. Если установлен `runAsUser: 0`, политика отклонит Pod. Однако `hostUsers: false` позволяет обойти это ограничение, так как root внутри контейнера не является root на хосте.

---

## Взаимодействие с другими механизмами изоляции

### Сравнение механизмов защиты

| Механизм | Уровень | Тип защиты | Ограничения |
| :--- | :--- | :--- | :--- |
| **User Namespaces** | Ядро Linux | Изоляция UID/GID | Требует ядро 6.3+, CRI runtime с поддержкой |
| **AppArmor** | Ядро Linux | MAC (Mandatory Access Control) | Ограничивает файловую систему, сеть, capabilities |
| **SELinux** | Ядро Linux | MAC + label-based | Более сложная настройка, требует policy |
| **seccomp** | Ядро Linux | Фильтрация syscall | Ограничивает системные вызовы |
| **Capabilities** | Ядро Linux | Декомпозиция root | Разбивает root на отдельные привилегии |

**User Namespaces + AppArmor/seccomp:** При `hostUsers: false` профили AppArmor и seccomp применяются **внутри** user namespace. Это означает, что ограничения действуют для процесса внутри контейнера, но не для реального UID на хосте.

**User Namespaces + seccomp:** При использовании User Namespaces с seccomp-профилями убедитесь, что профиль не блокирует вызовы, необходимые для работы с user namespace (`unshare`, `clone` с флагами `CLONE_NEWUSER`).

### Interaction с Linux Capabilities

Внутри User Namespace процесс может получить **все** capabilities (включая `CAP_SYS_ADMIN`), но только в пределах этого namespace. На хосте эти capabilities не действуют.

```yaml
apiVersion: v1
kind: Pod
spec:
  hostUsers: false
  containers:
  - name: app
    image: alpine:3.19
    securityContext:
      capabilities:
        add: ["SYS_ADMIN"]  # Внутри user namespace, не на хосте
    command: ["sh", "-c", "cat /proc/1/status | grep Cap"]
```

**Результат:**
```
CapPrm: 0000003fffffffff  # Все capabilities внутри user namespace
CapBnd: 0000003fffffffff
```

На хосте процесс работает от имени непривилегированного UID без каких-либо capabilities.

---

## Файловые системы и тома

### Rootfs контейнера

При `hostUsers: false` ядро использует **idmap mounts** для корневой ФС контейнера:
- overlayfs: Поддерживает idmap mounts нативно (ядро 5.11+)
- ext4/XFS: Поддерживают idmap mounts через `mount_setattr()`
- tmpfs: Используется для Secret/ConfigMap/ServiceAccount token

### Persistent Volumes (PV/PVC)

**Проблема:** PV/PVC монтируются с UID/GID, указанными в `fsGroup` или `runAsGroup`. При `hostUsers: false` маппинг UID изменился, и файлы могут стать недоступны.

**Решение 1: Установка fsGroup в манифесте Pod**
```yaml
apiVersion: v1
kind: Pod
spec:
  hostUsers: false
  securityContext:
    fsGroup: 1000  # UID внутри контейнера
    fsGroupChangePolicy: "OnRootMismatch"
  containers:
  - name: app
    image: alpine:3.19
    volumeMounts:
    - name: data
      mountPath: /data
  volumes:
  - name: data
    persistentVolumeClaim:
      claimName: my-pvc
```

**Решение 2: Использование init-контейнера для настройки прав**
```yaml
initContainers:
- name: fix-permissions
  image: busybox:1.36
  command: ["sh", "-c", "chown -R 1000:1000 /data"]
  volumeMounts:
  - name: data
    mountPath: /data
```

**Решение 3: Настройка StorageClass с поддержкой fsGroup**
```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: secure-storage
provisioner: kubernetes.io/aws-ebs
parameters:
  type: gp3
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
# Для совместимости с user namespace рекомендуется
# использовать provisioner, поддерживающий fsGroup
```

### Overlayfs и rootfs контейнера

При `hostUsers: false` containerd/CRI-O создают overlayfs с idmap mount:
```bash
# Проверка типа монтирования rootfs контейнера
# (на узле)
mount | grep overlay
# → overlay on /var/lib/containerd/io.containerd.runtime.v2.task/moby/.../rootfs type overlay (... idmapped ...)
```

### tmpfs для Secret/ConfigMap

tmpfs автоматически поддерживает user namespace (ядро 5.13+):
```bash
# Проверка монтирования Secret внутри контейнера
mount | grep tmpfs
# → tmpfs on /var/run/secrets/kubernetes.io/serviceaccount type tmpfs (..., idmapped)
```

---

## Практические сценарии

### Сценарий 1: Изолированный Pod с веб-сервером

Запуск приложения, которому требуются права `root` для прослушивания стандартных портов (например, 80), в безопасном режиме:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: isolated-web
spec:
  hostUsers: false  # Изоляция включена
  containers:
  - name: nginx
    image: nginx:1.27
    ports:
    - containerPort: 80
```

**Проверка:**
```bash
# Внутри контейнера:
cat /proc/1/uid_map
# →          0     100000      65536

# На хосте:
ps -eo pid,user,comm | grep nginx
# → 12345  100000  nginx: worker
```

### Сценарий 2: Проверка готовности узла

Перед внедрением необходимо убедиться, что Node поддерживает необходимые технологии:

```bash
# Проверка версии ядра (требуется 6.3+)
uname -r

# Проверка поддержки idmap mounts для файловой системы kubelet
findmnt -n -o FSTYPE /var/lib/kubelet
# Результат должен быть ext4, xfs или btrfs с поддержкой idmap

# Проверка поддержки idmap в ядре
zgrep CONFIG_USER_NS /proc/config.gz
# → CONFIG_USER_NS=y

# Проверка поддержки mount_setattr
zgrep CONFIG_TMPFS /proc/config.gz
# → CONFIG_TMPFS=y

# Проверка выделенных subuid/subgid диапазонов
cat /etc/subuid | grep -E "kubelet|containerd|cri-o"
cat /etc/subgid | grep -E "kubelet|containerd|cri-o"
```

### Сценарий 3: Диагностика Overflow UID (nobody)

Если идентификатор файла на диске не входит в диапазон, выделенный поду, ядро отобразит его как **Overflow UID** (обычно 65534, `nobody`).

**Причины:**
- Файл принадлежит пользователю вне диапазона subuid/subgid
- Несоответствие между маппингом Pod и правами на файле

**Решение:**
```bash
# Проверка владельца файла на хосте
ls -ln /path/to/volume
# → -rw-r--r-- 1 100000 100000 4096 ... file.txt

# Если UID не входит в диапазон subuid:
# 1. Проверьте /etc/subuid и /etc/subgid
cat /etc/subuid | grep containerd
# → containerd:100000:65536

# 2. Убедитесь, что файлы принадлежат пользователю из диапазона
# 3. Или используйте fsGroup для установки прав
```

**Модификация файлов, отображаемых как `nobody` из-за ограничений диапазона, обычно запрещена на уровне ядра для предотвращения утечек прав.**

### Сценарий 4: Безопасный запуск CSI-драйвера с привилегиями

CSI-драйверы часто требуют доступа к файловой системе хоста. User Namespaces позволяют изолироватьCSI-драйвер без реальных привилегий:

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: csi-driver
spec:
  selector:
    matchLabels:
      app: csi-driver
  template:
    metadata:
      labels:
        app: csi-driver
    spec:
      hostUsers: false  # Изоляция на уровне user namespace
      containers:
      - name: csi-plugin
        image: my-csi-driver:latest
        securityContext:
          privileged: false  # Не требует privileged на хосте
          capabilities:
            add: ["SYS_ADMIN"]  # Внутри user namespace
        volumeMounts:
        - name: host-path
          mountPath: /mnt/host
          mountPropagation: Bidirectional
      volumes:
      - name: host-path
        hostPath:
          path: /mnt/host
          type: Directory
```

### Сценарий 5: Миграция существующего приложения на User Namespaces

**Пошаговая процедура:**

1. **Аудит текущей конфигурации:**
```bash
# Проверить, использует ли приложение root
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].securityContext.runAsUser}'
# → 0 (или не указано = root)

# Проверить, требует ли приложение привилегии
kubectl get pod <pod-name> -o jsonpath='{.spec.containers[*].securityContext.privileged}'
```

2. **Тестирование на dev-кластере:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: test-userns
spec:
  hostUsers: false
  containers:
  - name: app
    image: my-app:latest
    securityContext:
      runAsUser: 0  # Тестируем с root
```

3. **Валидация на узле:**
```bash
# Проверить, что UID маппится корректно
kubectl exec test-userns -- cat /proc/1/uid_map
# →          0     100000      65536

# Проверить, что приложение работает
kubectl exec test-userns -- id
# → uid=0(root) gid=0(root) groups=0(root)
```

4. **Обновление Deployment:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 3
  strategy:
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    spec:
      hostUsers: false  # Добавлено
      containers:
      - name: app
        image: my-app:latest
```

5. **Rolling update:**
```bash
kubectl rollout restart deployment/my-app
kubectl rollout status deployment/my-app
```

---

## Дополнительная информация

### Диагностический workflow

```text
Pod не запускается с hostUsers: false
     ↓
[1] Проверка ядра
uname -r
     ├─ < 6.3 → Обновить ядро
     └─ >= 6.3 → [2]

[2] Проверка CRI runtime
containerd --version / crio --version
     ├─ containerd < 2.0 / CRI-O < 1.25 → Обновить CRI runtime
     └─ Версия поддерживается → [3]

[3] Проверка subuid/subgid
cat /etc/subuid | grep <cri-runtime>
     ├─ Нет записи → Добавить: echo "containerd:100000:65536" | sudo tee -a /etc/subuid
     └─ Запись есть → [4]

[4] Проверка файловой системы
findmnt -n -o FSTYPE /var/lib/kubelet
     ├─ ntfs, vfat → ФС не поддерживает idmap mounts
     └─ ext4, xfs, btrfs → [5]

[5] Проверка поддержки idmap в ядре
zgrep CONFIG_USER_NS /proc/config.gz
     ├─ CONFIG_USER_NS=n → Пересобрать ядро с CONFIG_USER_NS=y
     └─ CONFIG_USER_NS=y → [6]

[6] Проверка логов CRI runtime
journalctl -u containerd | grep -i userns
     ├─ Ошибки → Исправить конфигурацию CRI
     └─ Нет ошибок → Проверить Pod Events
kubectl describe pod <pod-name>
```

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **"UserNs is not supported"** | CRI runtime не поддерживает user namespaces | Обновить containerd до 2.0+ или CRI-O до 1.25+ |
| **"No subuid ranges found"** | Отсутствует запись в `/etc/subuid` | Добавить диапазон для CRI runtime |
| **"Permission denied" на volume** | UID внутри контейнера не маппится на владельца PV | Установить `fsGroup` или `runAsGroup` в Pod spec |
| **"overlayfs: mount failed"** | ФС не поддерживает idmap mounts | Перейти на ext4/xfs/btrfs или обновить ядро |
| **Pod в CrashLoopBackOff** | Приложение не ожидает маппинга UID | Проверить логи: `kubectl logs <pod> --previous` |

### Мониторинг User Namespaces

```bash
# Просмотр User Namespace для Pod
kubectl get pod <pod-name> -o jsonpath='{.spec.hostUsers}'
# → false (user namespace включен)

# Просмотр всех Pod с включенным user namespace
kubectl get pods --all-namespaces -o json | \
  jq -r '.items[] | select(.spec.hostUsers == false) | "\(.metadata.namespace)/\(.metadata.name)"'

# Проверка маппингов на узле
# (на узле через SSH)
ls -la /proc/<containerd-pid>/uid_map
cat /proc/<containerd-pid>/uid_map
```

### Профилактика

1. **Включение User Namespaces по умолчанию:** Рассмотрите возможность включения `hostUsers: false` для всех Pod через Admission Webhook или OPA/Gatekeeper.
2. **Мониторинг диапазонов:** Отслеживание использования subuid/subgid диапазонов для предотвращения исчерпания.
3. **Регулярное тестирование:** Периодическая проверка совместимости приложений с user namespaces.
4. **Документирование исключений:** Ведение списка Pod, которые не могут работать с user namespaces, и документирование причин.

---

**Связанные темы:**

- [Security Context в Kubernetes](../../Security/pod_security_context.md) — управление правами и изоляцией.
- [Pod Security Standards (PSS)](../../Security/pod_security_context.md#pod-security-standards-pss-и-pod-security-admission-psa) — профили безопасности Pod.
- [Механизмы изоляции в Linux (Namespaces и Cgroups)](../../../Docker/Concepts/linux_isolation.md) — теоретическая база.
- [Rootless режим в Podman](../../../Podman/podman_rootless.md) — аналогичная технология для контейнеров без демона.

**Официальная документация:** [User Namespaces in Kubernetes Pods](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/)
