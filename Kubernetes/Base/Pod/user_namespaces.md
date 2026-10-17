# User Namespaces в Pod

**Актуально для:** Kubernetes 1.36 (GA)

## Определения

**User Namespace (Пользовательское пространство имён)** — механизм изоляции ядра Linux, разделяющий пространства идентификаторов пользователей (UID) и групп (GID). Позволяет сопоставлять идентификаторы внутри пространства имён (например, UID 0 — `root`) с непривилегированным диапазоном идентификаторов на хосте (например, UID 100000–165535). Процесс с полными правами внутри контейнера на уровне хост-системы остаётся обычным непривилегированным пользователем.

**Host User Namespace** — базовое пространство имён пользователей хоста. По умолчанию в Kubernetes поды используют именно его (`hostUsers: true`), что означает полное совпадение UID/GID внутри контейнера и на родительском узле.

**ID-mapped Mount (Монтирование с сопоставлением ID)** — функциональность VFS ядра Linux (начиная с ядра 5.12, для `tmpfs` — с 6.3), позволяющая прозрачно переназначать владельцев файлов и каталогов при монтировании файловой системы без рекурсивного изменения прав (`chown`). Реализуется через системный вызов `mount_setattr(2)` с флагом `MOUNT_ATTR_IDMAP`. Это фундаментальный механизм, обеспечивающий работу томов в User Namespaces.

**Subordinate UID/GID (subuid/subgid)** — диапазоны вспомогательных идентификаторов пользователей и групп, выделяемые непривилегированным пользователям или системным демонам в файлах `/etc/subuid` и `/etc/subgid`. Формат записи: `пользователь:начальный_ID:количество`. Kubelet использует диапазон пользователя `kubelet` для автоматического назначения непересекающихся пространств имён каждому поду.

**Container Breakout (Побег из контейнера)** — вектор атаки, при котором процесс преодолевает барьеры изоляции контейнера и получает несанкционированный доступ к хост-системе. Использование User Namespaces предотвращает эскалацию привилегий до `root` на хосте при побеге.

---

## Архитектура и принцип работы

### Назначение и модель безопасности

User Namespaces в Kubernetes изолируют пользователей контейнера от пользователей операционной системы узла. Механизм нейтрализует последствия выхода за пределы контейнера (Container Breakout): даже если атакующий эксплуатирует уязвимость приложения или рантайма и выходит на хост с правами `UID 0`, его эффективные привилегии на узле соответствуют непривилегированному диапазону (например, UID 100000).

```text
+-------------------------------------------------------------------------+
|                               Узел (Host)                               |
|                                                                         |
|  Процессы хоста:                                                        |
|  UID 0 (root), UID 1000 (admin), UID 65534 (nobody)                     |
|                                                                         |
|  Выделенный диапазон для Pod 1: Host UID 100000 - 165535                |
|  Выделенный диапазон для Pod 2: Host UID 165536 - 231071                |
|                                                                         |
|  +---------------------------+       +-------------------------------+  |
|  |           Pod 1           |       |             Pod 2             |  |
|  | (User Namespace 1)        |       | (User Namespace 2)            |  |
|  |                           |       |                               |  |
|  |  UID 0 (внутри ns)        |       |  UID 0 (внутри ns)            |  |
|  |     │                     |       |     │                         |  |
|  |     ▼ Маппинг             |       |     ▼ Маппинг                 |  |
|  |  Host UID 100000          |       |  Host UID 165536              |  |
|  |                           |       |                               |  |
|  |  UID 1000 (внутри ns)     |       |  UID 1000 (внутри ns)         |  |
|  |     │                     |       |     │                         |  |
|  |     ▼ Маппинг             |       |     ▼ Маппинг                 |  |
|  |  Host UID 101000          |       |  Host UID 166536              |  |
|  +---------------------------+       +-------------------------------+  |
+-------------------------------------------------------------------------+
```

**Ключевые преимущества:**
- **Защита хоста от компрометации:** UID 0 внутри контейнера не обладает правами суперпользователя на файлы, устройства и сокеты хоста.
- **Взаимная изоляция подов:** Kubelet выделяет каждому поду с `hostUsers: false` непересекающиеся диапазоны UID/GID на одном узле, исключая межконтейнерные атаки через общие идентификаторы.
- **Безопасный запуск root-процессов:** Утилиты сборки пакетов, сетевые сервисы, требующие привязки к портам ниже 1024, и веб-серверы могут работать от `root` внутри контейнера без риска для кластера.

### Механизм трансляции идентификаторов (UID/GID Mapping)

При создании пода с `hostUsers: false` kubelet и CRI-рантайм создают трансляционную таблицу в `/proc/[pid]/uid_map` и `/proc/[pid]/gid_map`:

```text
[ID внутри пространства имён] [Начальный ID на хосте] [Размер диапазона]
```

**Пример отображения:**
```bash
# Чтение таблицы маппинга изнутри контейнера или через /proc на хосте:
cat /proc/1/uid_map
# →          0     100000      65536
```
- `0` — начальный идентификатор внутри контейнера (UID 0, root).
- `100000` — соответствующий начальный идентификатор на хосте.
- `65536` — количество отображаемых идентификаторов (диапазон 0–65535 внутри контейнера мапится на 100000–165535 на хосте).

Параметры спецификации `pod.spec.securityContext` (`runAsUser`, `runAsGroup`, `fsGroup`) всегда указывают идентификаторы **внутри** пространства имён контейнера.

### Взаимодействие с Linux Capabilities

Linux Capabilities внутри User Namespace изолированы:
- Процесс с `UID 0` внутри пользовательского пространства имён может обладать полным набором привилегий (включая `CAP_SYS_ADMIN`, `CAP_NET_ADMIN`, `CAP_SETUID`), но эти привилегии действуют **исключительно** на ресурсы данного пространства имён.
- На хосте и в родительских пространствах имён процесс полностью лишён привилегий.
- Потенциально опасные привилегии хоста нейтрализуются: например, `CAP_SYS_MODULE` (загрузка модулей ядра) полностью аннулируется и не работает даже внутри контейнера.

### Тома и ID-mapped Mounts

Для монтирования томов в изолированный под ядро использует технологию **idmap mounts**:
1. Файловая система узла монтируется в контейнер с применением атрибута `MOUNT_ATTR_IDMAP`.
2. Ядро динамически транслирует UID/GID при операциях чтения и записи.
3. Inode файлов на диске хранят идентификаторы в стандартном виде (например, UID 1000 внутри контейнера записывается на хостовую ФС как UID 1000, а не как хостовый 101000).
4. Благодаря этому под может переключаться между `hostUsers: false` и `hostUsers: true`, а также делить тома с обычными подами без необходимости рекурсивного `chown`.

---

## Требования к системе и рантаймам

### Статус поддержки в Kubernetes

| Версия Kubernetes | Статус | Feature Gate | Описание |
| :--- | :--- | :--- | :--- |
| **1.25** | Alpha | `UserNamespacesStatelessPodsSupport` | Поддержка только stateless-подов без постоянных томов. |
| **1.28** | Alpha | `UserNamespacesSupport` | Расширение поддержки на тома. |
| **1.30** | Beta | `UserNamespacesSupport=true` | Поддержка StatefulSet и большинства типов томов; выключено по умолчанию. |
| **1.33** | Beta | `UserNamespacesSupport=true` | Добавлен параметр `idsPerPod` в `KubeletConfiguration`. |
| **1.36** | **GA** | Заблокирован (всегда активен) | Полная стабильность механизма. Флаг заблокирован, выключение невозможно. |

### Системные требования

| Компонент | Минимальная версия | Рекомендуемая версия | Назначение |
| :--- | :--- | :--- | :--- |
| **Ядро Linux** | 6.3+ | 6.8+ | Поддержка `idmap mounts` для `tmpfs` (критично для Secret, ConfigMap, projected томов). |
| **OCI Runtime** | runc 1.2+ / crun 1.9+ | runc 1.2+ / crun 1.13+ | Низкоуровневая настройка таблиц трансляции UID/GID. |
| **CRI Runtime** | containerd 2.0+ / CRI-O 1.25+ | containerd 2.0+ / CRI-O 1.30+ | Поддержка User Namespaces через интерфейс CRI v1. |
| **Системные утилиты** | `shadow-utils` (содержит `getsubids`) | Актуальная из репозитория дистрибутива | Поиск доступных диапазонов в `/etc/subuid` и `/etc/subgid`. |

### Поддерживаемые файловые системы

Для монтирования томов и создания rootfs контейнера файловая система узла обязана поддерживать `idmap mounts`:
- **Поддерживаются:** `ext4`, `XFS`, `Btrfs`, `tmpfs`, `overlayfs`, `vfat`.
- **НЕ поддерживаются:** `NFS` (клиент NFS в ядре Linux пока не поддерживает монтирование с сопоставлением идентификаторов).
- **Ограничение на блочные устройства:** Поды с `hostUsers: false` не могут использовать `volumeDevices` (raw block volumes).

---

## Настройка узла и CRI-рантаймов

### 1. Настройка subordinate диапазонов (subuid/subgid)

Kubelet распределяет диапазоны на основе записей для пользователя `kubelet` в системных файлах конфигурации.

#### Правила формирования диапазонов для kubelet
1. Пользователь в строке должен называться строго `kubelet`.
2. Начальный идентификатор (`firstID`) обязан быть **кратен 65536** и быть **не менее 65536** (диапазон 0–65535 зарезервирован хостом).
3. Количество выделяемых идентификаторов (`count`) обязано быть кратным 65536.
4. Минимальный объём: `count >= 65536 * maxPods`, где `maxPods` — максимальное количество подов на узле (по умолчанию 110).
   $$110 \times 65536 = 7\,208\,960$$
5. Конфигурация в `/etc/subuid` и `/etc/subgid` должна состоять строго из **одной** строки и совпадать по параметрам.
6. Диапазоны не должны пересекаться с системными пользователями и рантаймами.

#### Настройка файлов конфигурации
```bash
# 1. Проверка наличия системного пользователя kubelet
id -u kubelet &>/dev/null || sudo useradd --system --no-create-home kubelet

# 2. Проверка наличия утилиты getsubids в PATH
which getsubids
# → /usr/bin/getsubids

# 3. Назначение диапазона на 110 подов (7 208 960 идентификаторов)
sudo tee /etc/subuid << 'EOF'
kubelet:65536:7208960
EOF

sudo tee /etc/subgid << 'EOF'
kubelet:65536:7208960
EOF

# 4. Проверка корректности записей через getsubids
getsubids kubelet
# → 0: kubelet 65536 7208960
```

> [!WARNING]
> **Переконфигурация рабочего узла:** Если на узле уже запущены поды с `hostUsers: false`, перед изменением `/etc/subuid` или `/etc/subgid` необходимо выполнить `kubectl drain <node-name>`. Kubelet завершится с фатальной ошибкой при перезапуске, если активные поды используют идентификаторы вне нового назначенного диапазона.

### 2. Конфигурация Kubelet

Начиная с Kubernetes 1.33, количество идентификаторов на один под настраивается через секцию `userNamespaces` в файле конфигурации kubelet.

```yaml
# /var/lib/kubelet/config.yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
userNamespaces:
  idsPerPod: 65536  # Значение должно быть кратно 65536 (по умолчанию 65536)
```

### 3. Конфигурация CRI-рантаймов

#### containerd (версия 2.0+)

В `containerd` версии 2.0+ поддержка User Namespaces активна на уровне плагина CRI:

```toml
# /etc/containerd/config.toml
version = 3

[plugins."io.containerd.cri.v1.runtime"]
  enable_cdi = true

[plugins."io.containerd.cri.v1.runtime".containerd.runtimes.runc]
  runtime_type = "io.containerd.runc.v2"

[plugins."io.containerd.cri.v1.runtime".containerd.runtimes.runc.options]
  # Для runc требуется версия не ниже 1.2
  SystemdCgroup = true
```

Перезапуск службы:
```bash
sudo systemctl restart containerd
```

#### CRI-O (версия 1.25+)

В CRI-O режим маппинга настраивается в блоке `[crio.runtime]`:

```toml
# /etc/crio/crio.conf.d/10-userns.conf
[crio.runtime]
# Режим автоназначения диапазонов на основе subuid/subgid
userns_run_as = "auto"
```

Перезапуск службы:
```bash
sudo systemctl restart crio
```

---

## Практические сценарии и манифесты Pod

### Сценарий 1: Запуск сервиса от root с изоляцией на хосте

Приложению требуется запуск от `root` для привязки к привилегированному порту `80/TCP` или выполнения внутренних административных задач. С `hostUsers: false` процесс безопасно выполняется от непривилегированного UID на хосте.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: isolated-nginx
  namespace: default
spec:
  hostUsers: false  # Активация изолированного User Namespace
  containers:
  - name: nginx
    image: nginx:1.27-alpine
    ports:
    - containerPort: 80
    securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: false
      runAsUser: 0  # root внутри пространства имён пода
```

**Проверка изоляции на узле:**
```bash
# 1. Определение PID процесса контейнера на хосте
PID=$(kubectl get pod isolated-nginx -o jsonpath='{.status.containerStatuses[0].containerID}' | sed 's/.*:\/\///')

# 2. Проверка отображения пользователей в /proc
cat /proc/$(pgrep -f "nginx: master")/uid_map
# →          0     100000      65536

# 3. Проверка пользователя в выводе ps на хосте
ps -eo pid,user,uid,comm | grep nginx
# → 284192 100000 100000 nginx
# → 284240 100101 100101 nginx
```
Процесс виден на хосте от пользователя с UID `100000`, не имеющего никаких системных привилегий на узле.

### Сценарий 2: Pod с PersistentVolumeClaim (idmapped storage)

Демонстрация работы томов с сохранением стандартных прав без конфликтов UID:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: app-data-pvc
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: stateful-secure-app
spec:
  hostUsers: false
  securityContext:
    fsGroup: 2000
  containers:
  - name: app
    image: alpine:3.20
    command: ["sh", "-c", "touch /data/testfile && ls -ln /data && sleep 3600"]
    volumeMounts:
    - name: storage
      mountPath: /data
  volumes:
  - name: storage
    persistentVolumeClaim:
      claimName: app-data-pvc
```

Внутри контейнера файл `/data/testfile` принадлежит группе `2000`. На базовой файловой системе хоста благодаря механизму `idmap mount` файл физически сохраняет владение группой `2000`, а не смещённой группой `102000`.

### Сценарий 3: Взаимодействие с Pod Security Admission (PSA)

Для подов с `hostUsers: false` контроллер допуска Pod Security Admission (PSA) автоматически смягчает проверки в профилях `baseline` и `restricted`:

| Поле Pod Security Context | Стандартное поведение (restricted) | Поведение при `hostUsers: false` |
| :--- | :--- | :--- |
| `runAsNonRoot` | Обязательно `true` (запрет UID 0) | **Не проверяется** (разрешён UID 0 внутри) |
| `runAsUser` | Запрещён `0` | **Не проверяется** (разрешён UID 0 внутри) |
| `procMount` | Только `Default` | В профиле `baseline` проверка смягчена |
| `allowPrivilegeEscalation` | Обязательно `false` | По-прежнему обязательно `false` в `restricted` |
| `capabilities` | Запрещены опасные возможности | Требуется явный сброс `drop: ["ALL"]` в `restricted` |

Пример манифеста, успешно проходящего проверку в namespace с политикой `pod-security.kubernetes.io/enforce: restricted`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: restricted-root-app
  namespace: secure-apps
spec:
  hostUsers: false  # Смягчает проверки runAsNonRoot / runAsUser для PSA
  containers:
  - name: worker
    image: alpine:3.20
    command: ["sh", "-c", "id && sleep 3600"]
    securityContext:
      runAsUser: 0  # Разрешено благодаря hostUsers: false
      allowPrivilegeEscalation: false
      capabilities:
        drop:
        - ALL
      seccompProfile:
        type: RuntimeDefault
```

---

## Ограничения и несовместимости

При установке `hostUsers: false` ядро и Kubernetes накладывают строгие ограничения для предотвращения эскалации привилегий:

1. **Запрет пространств имён хоста:**
   Категорически запрещено совместное использование со следующими флагами:
   - `hostNetwork: true`
   - `hostIPC: true`
   - `hostPID: true`
   Попытка применить такой манифест будет отклонена валидатором API-сервера.

2. **Блочные устройства (Raw Block Volumes):**
   Поле `volumeDevices` запрещено во всех типах контейнеров (`containers`, `initContainers`, `ephemeralContainers`).

3. **Сетевые файловые системы (NFS):**
   Монтирование томов NFS завершается ошибкой рантайма, так как драйвер NFS в ядре Linux не поддерживает системный вызов `mount_setattr(2)` с сопоставлением идентификаторов.

4. **Системные компоненты и CSI-драйверы:**
   CSI Node Plugins и демоны мониторинга хоста, которым требуются прямые системные вызовы к устройствам узла или управление томами на уровне ОС хоста, не могут функционировать с `hostUsers: false`.

---

## Мониторинг и метрики (SRE)

Kubelet экспортирует встроенные Prometheus-метрики для мониторинга жизненного цикла подов с User Namespaces.

### Доступные метрики

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `started_user_namespaced_pods_total` | Counter | Общее количество попыток запуска подов с User Namespaces. |
| `started_user_namespaced_pods_errors_total` | Counter | Количество ошибок при попытке запуска подов с User Namespaces. |

### Диагностические PromQL-запросы

**1. Текущий темп ошибок запуска изолированных подов:**
```promql
sum by (instance) (rate(started_user_namespaced_pods_errors_total[5m]))
```

**2. Процент неудачных запусков (Failure Rate):**
```promql
(
  sum(rate(started_user_namespaced_pods_errors_total[5m]))
  /
  sum(rate(started_user_namespaced_pods_total[5m]))
) * 100 > 5
```

### Пример правила PrometheusAlert

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: kubelet-userns-alerts
  namespace: monitoring
spec:
  groups:
  - name: user-namespaces.rules
    rules:
    - alert: KubeletUserNamespacePodStartFailures
      expr: rate(started_user_namespaced_pods_errors_total[5m]) > 0
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "Ошибки запуска подов с User Namespaces на узле {{ $labels.instance }}"
        description: "На узле {{ $labels.instance }} фиксируются ошибки инициализации User Namespaces. Проверьте subuid/subgid и поддержку idmap mounts."
```

---

## Диагностика и устранение неполадок (Troubleshooting)

### Пошаговый скрипт проверки готовности узла (Sysadmin)

Выполните скрипт на целевом рабочем узле для комплексной проверки окружения:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "=== [1] Проверка версии ядра ==="
KERNEL_VER=$(uname -r)
echo "Версия ядра: ${KERNEL_VER}"
KERNEL_MAJOR=$(uname -r | cut -d. -f1)
KERNEL_MINOR=$(uname -r | cut -d. -f2)
if [ "${KERNEL_MAJOR}" -lt 6 ] || ([ "${KERNEL_MAJOR}" -eq 6 ] && [ "${KERNEL_MINOR}" -lt 3 ]); then
    echo "[-] ОШИБКА: Требуется ядро 6.3+ (для поддержки idmap mounts на tmpfs)"
else
    echo "[+] Ядро удовлетворяет требованиям (6.3+)"
fi

echo "=== [2] Проверка конфигурации ядра ==="
if [ -f /proc/config.gz ]; then
    zgrep -q "CONFIG_USER_NS=y" /proc/config.gz && echo "[+] CONFIG_USER_NS=y" || echo "[-] CONFIG_USER_NS отключен"
fi

echo "=== [3] Проверка утилиты getsubids ==="
if which getsubids >/dev/null 2>&1; then
    echo "[+] getsubids найден: $(which getsubids)"
else
    echo "[-] ОШИБКА: Утилита getsubids отсутствует. Установите shadow-utils."
fi

echo "=== [4] Проверка диапазонов subuid/subgid для kubelet ==="
if [ -f /etc/subuid ] && grep -q "^kubelet:" /etc/subuid; then
    echo "[+] Запись в /etc/subuid: $(grep '^kubelet:' /etc/subuid)"
else
    echo "[-] ОШИБКА: Запись для пользователя kubelet в /etc/subuid не найдена"
fi

if [ -f /etc/subgid ] && grep -q "^kubelet:" /etc/subgid; then
    echo "[+] Запись в /etc/subgid: $(grep '^kubelet:' /etc/subgid)"
else
    echo "[-] ОШИБКА: Запись для пользователя kubelet в /etc/subgid не найдена"
fi

echo "=== [5] Проверка файловой системы /var/lib/kubelet ==="
KUBELET_FS=$(findmnt -n -o FSTYPE /var/lib/kubelet || findmnt -n -o FSTYPE /)
echo "Файловая система: ${KUBELET_FS}"
case "${KUBELET_FS}" in
    ext4|xfs|btrfs|overlay)
        echo "[+] Файловая система поддерживает idmap mounts"
        ;;
    *)
        echo "[-] ПРЕДУПРЕЖДЕНИЕ: ФС ${KUBELET_FS} может не поддерживать idmap mounts"
        ;;
esac
```

### Типичные ошибки и способы решения

#### 1. Ошибка создания shim: `failed to set MOUNT_ATTR_IDMAP invalid argument`

**Симптом:** Под переходит в состояние `CreateContainerError` или `CrashLoopBackOff`.
```text
Warning  Failed  1s  kubelet  Error: failed to create containerd task: failed to create shim task:
OCI runtime create failed: runc create failed: unable to start container process:
error during container init: failed to fulfil mount request: failed to set MOUNT_ATTR_IDMAP
on /var/lib/kubelet/pods/.../volumes/...: invalid argument
```
**Причины:**
1. Версия ядра ниже 6.3, а в поде монтируются Secret, ConfigMap или токен ServiceAccount (смонтированные на `tmpfs`).
2. Попытка смонтировать том сетевой файловой системы (например, NFS), не поддерживающей idmapping.
3. Каталог `/var/lib/kubelet` расположен на неподдерживаемой ФС.

**Решение:**
- Обновить ядро Linux на узле до версии 6.3 или выше.
- Исключить монтирование NFS-томов в поды с `hostUsers: false`.

#### 2. Ошибка: `No subordinate user/group ranges found for user "kubelet"`

**Симптом:** Kubelet регистрирует событие ошибки при планировании пода с `hostUsers: false`.
```text
Warning  FailedCreatePodSandBox  3s  kubelet  Failed to create pod sandbox:
failed to get subordinate ID range for kubelet: user "kubelet" has no range in /etc/subuid
```
**Причины:**
- В `/etc/subuid` или `/etc/subgid` отсутствует запись для пользователя `kubelet`.
- Утилита `getsubids` не найдена в системных путях `PATH` процесса kubelet.

**Решение:**
- Добавить корректную строку диапазона в `/etc/subuid` и `/etc/subgid`.
- Установить пакет `shadow-utils` (`dnf install shadow-utils` или `apt install uidmap`).
- Перезапустить демон `systemctl restart kubelet`.

#### 3. Некорректное отображение владельца файлов: `nobody` (UID 65534)

**Симптом:** Файлы на смонтированном томе внутри контейнера отображаются с владельцем `65534` (`nobody` / `nogroup`), запись запрещена.
**Причина:** UID файла на носителе выходит за рамки выделенного диапазона `idsPerPod` (по умолчанию 0–65535 внутри контейнера).
**Решение:**
- Настроить `fsGroup` в спецификации пода для автоматического назначения поддерживаемого GID.
- Начиная с K8s 1.33, при необходимости расширить диапазон `idsPerPod` в `KubeletConfiguration` (например, до 1048576).

---

## Рекомендации и Best Practices

1. **Массовый аудит подов без User Namespaces:**
   ```bash
   kubectl get pods -A -o json | jq -r '
     .items[] |
     select(.spec.hostUsers != false) |
     "\(.metadata.namespace)/\(.metadata.name)"
   '
   ```

2. **Стандартизация подходов к безопасности:**
   - Для приложений общего назначения активируйте `hostUsers: false` в сочетании со сбросом capabilities (`drop: ["ALL"]`) и `readOnlyRootFilesystem: true`.
   - Не запускайте привилегированные служебные агенты (DaemonSet с доступом к сети хоста) с флагом `hostUsers: false`.

3. **Соблюдение шагов ротации диапазонов на узлах:**
   - Не редактируйте `/etc/subuid` «на лету» без предварительного перевода узла в режим обслуживания (`drain`).

---

## Связанные материалы

- [Обзор Pod в Kubernetes](./pod_overview.md) — базовые концепции и архитектура Pod.
- [Security Context в Kubernetes](../../Security/pod_security_context.md) — управление правами, UID/GID и возможностями контейнера.
- [Rootless Kubernetes](../../Security/rootless_kubernetes.md) — изоляция компонентов плоскости управления и узла в user namespace.
- [Механизмы изоляции в Linux](../../../Docker/Concepts/linux_isolation.md) — теория Namespaces и Cgroups в ядре Linux.
- [Официальная документация Kubernetes: User Namespaces in Pods](https://kubernetes.io/docs/concepts/workloads/pods/user-namespaces/)
