# Container Runtime в Kubernetes

## Определение

В контексте Kubernetes **Среда выполнения контейнеров (Container Runtime)** — это низкоуровневое программное обеспечение, отвечающее за распаковку образа, запуск, остановку и управление жизненным циклом контейнеров на рабочем узле. Она напрямую взаимодействует с ядром операционной системы (через `cgroups` и `namespaces`) для создания изолированных окружений.

Рантаймы не являются специфичными для Kubernetes и могут использоваться автономно. Однако Kubernetes делегирует им всю фактическую работу с контейнерами, выступая лишь как оркестратор (управляющий слой).

---

## История развития и стандарты

В начале эпохи контейнеризации Docker был доминирующим инструментом, и Kubernetes изначально создавался для оркестрации именно Docker-контейнеров. Со временем возникла потребность в поддержке других рантаймов (например, Rocket), что привело к стандартизации.

### Стандарты OCI (Open Container Initiative)
Фундамент, на котором строятся все современные инструменты:
*   **Image Spec:** Спецификация того, как должен быть собран образ.
*   **Runtime Spec:** Стандарты разработки среды выполнения контейнеров.
*   **Результат:** Любой образ, собранный Docker, будет работать в любом OCI-совместимом рантайме (например, `containerd`).

### CRI (Container Runtime Interface)
Kubernetes ввел интерфейс **CRI**, чтобы любой вендор мог создать рантайм, совместимый с K8s, следуя стандартам OCI.
*   **Проблема Docker:** Docker был создан до появления CRI и не поддерживал его напрямую.
*   **Docker Shim:** Временный "костыль" (hack), встроенный в `kubelet` для трансляции CRI-вызовов в Docker API.
*   **Удаление (v1.24):** Поддержка Docker через `dockershim` была удалена. Теперь Kubernetes работает напрямую с CRI-совместимыми рантаймами, такими как `containerd` или `CRI-O`.

---

## Основные концепции

### CRI (Container Runtime Interface)
Kubernetes не работает с рантаймами напрямую. Он использует **CRI** — стандартный программный интерфейс (API), основанный на gRPC. 
*   **Цель:** Отвязать исходный код Kubernetes от конкретных реализаций рантаймов (как это было раньше с Docker).
*   **Механика:** Агент `kubelet` выступает как CRI-клиент, а рантайм (например, `containerd`) запускает у себя CRI-сервер.
*   CRI описывает два сервиса: `RuntimeService` (управление подами и песочницами) и `ImageService` (загрузка и удаление образов).

### High-Level vs Low-Level Runtimes
Архитектура запуска контейнеров делится на два уровня:

1.  **High-Level Runtimes (CRI-совместимые):**
    Управляют жизненным циклом на высоком уровне: скачивают образы, распаковывают их, подготавливают сеть (через CNI) и вызывают низкоуровневый рантайм.
    *   **Примеры:** `containerd`, `CRI-O`.
2.  **Low-Level Runtimes (OCI-совместимые):**
    Получают готовую файловую систему и конфигурацию (JSON), и их единственная задача — создать процесс контейнера в ядре Linux, используя `namespaces` и `cgroups`.
    *   **Примеры:** `runc` (стандарт), `crun` (быстрый, на C), `gVisor` (песочница), `Kata Containers` (микро-ВМ).

### Цепочка вызовов при запуске контейнера

Полный путь от создания Pod до запуска процесса в контейнере:

```
kubectl apply -f pod.yaml
    ↓
API Server → Scheduler → Kubelet
    ↓
kubelet → CRI gRPC (RuntimeService.RunPodSandbox)
    ↓
containerd/CRI-O → резолвинг образа → pull слоёв → распаковка в rootfs
    ↓
OCI Runtime (runc/crun) → настройка namespaces + cgroups → clone() → exec()
    ↓
Процесс приложения запущен
```

Каждый этап можно отладить:
- `kubectl describe pod` — статус Pod, события (Image Pulled, Started)
- `crictl pods` / `crictl ps` — состояние на уровне рантайма
- `ctr -n k8s.io images ls` — список образов в containerd
- `ctr -n k8s.io task ls` — низкоуровневый список задач (pid/статус) когда kubelet или CRI не отвечает
- `runc list` — активные контейнеры OCI runtime

---

## Популярные среды выполнения (High-Level)

### 1. containerd
*   **Статус:** Стандарт де-факто в индустрии. Выделен из исходного кода Docker в отдельный проект CNCF.
*   **Особенности:** Легковесный, стабильный, поддерживает все современные фичи Kubernetes.
*   **Цепочка запуска:** `kubelet` → `containerd` (через плагин CRI) → `runc`.
*   **Сокет:** `/run/containerd/containerd.sock` (стандарт) или `/run/k3s/containerd/containerd.sock` (k3s).
*   **Пространства имен:** containerd использует namespaces для изоляции: `k8s.io` — для Kubernetes, `moby` — для Docker-совместимости.

**Конфигурация containerd (`/etc/containerd/config.toml`):**

```toml
# Генерация конфигурации по умолчанию:
# containerd config default > /etc/containerd/config.toml

# Песочница (pause image) — обязательна для Kubernetes
[plugins."io.containerd.grpc.v1.cri"]
  sandbox_image = "registry.k8s.io/pause:3.9"

# Драйвер cgroup — должен быть systemd в современных системах
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
  SystemdCgroup = true

# Логирование контейнеров
[plugins."io.containerd.grpc.v1.cri".containerd]
  discard_unpacked_layers = true  # экономия диска

# Регистры образов (зеркала)
[plugins."io.containerd.grpc.v1.cri".registry]
  [plugins."io.containerd.grpc.v1.cri".registry.mirrors]
    [plugins."io.containerd.grpc.v1.cri".registry.mirrors."docker.io"]
      endpoint = ["https://harbor.local", "https://docker.io"]
  [plugins."io.containerd.grpc.v1.cri".registry.configs]
    [plugins."io.containerd.grpc.v1.cri".registry.configs."docker.io".tls]
      ca_file = "/etc/containerd/ca.crt"
      cert_file = "/etc/containerd/client.crt"
      key_file = "/etc/containerd/client.key"
```

После изменения: `sudo systemctl restart containerd`

### 2. CRI-O
*   **Статус:** Популярная альтернатива, созданная Red Hat специально для Kubernetes.
*   **Особенности:** Абсолютный минимализм — умеет делать только то, что требует CRI. Строго привязан к релизным циклам Kubernetes. Используется в OpenShift.
*   **Цепочка запуска:** `kubelet` → `CRI-O` → `runc` (или `crun`).
*   **Сокет:** `/var/run/crio/crio.sock`.
*   **Конфигурация:** `/etc/crio/crio.conf` — единый TOML-файл.

**Ключевые различия containerd vs CRI-O:**

| Критерий | containerd | CRI-O |
| :--- | :--- | :--- |
| Назначение | Универсальный рантайм | Только для Kubernetes |
| Версионирование | Собственные релизы | Привязан к версии K8s (1.29 → CRI-O 1.29) |
| CLI-утилиты | ctr, nerdctl | crictl (только) |
| Поддержка Windows | Да | Нет (только Linux) |
| Multitenancy | Namespace-based | Pod sandbox isolation |
| Сборка образов | nerdctl build | Нет (используйте Buildah/Kaniko) |

### Почему убрали Docker? (Deprecation of dockershim)
Docker Engine — это огромный комбайн, созданный для людей, а не для машин. Исторически он не поддерживал протокол CRI. Чтобы K8s мог им управлять, в код `kubelet` был встроен "костыль" — **dockershim**, который переводил запросы CRI в Docker API.
Начиная с версии v1.24 Kubernetes удалил `dockershim`. Кластеры перешли на прямую работу с `containerd` (который и так работает внутри Docker), сократив накладные расходы, улучшив безопасность и производительность.

---

## Инструменты командной строки (CLI)

С переходом на `containerd` появились специфические инструменты для взаимодействия с рантаймом.

| Инструмент | Источник | Назначение | Особенности |
| :--- | :--- | :--- | :--- |
| **`ctr`** | containerd community | Отладка `containerd` | Низкоуровневый, недружелюбный интерфейс, ограниченный набор фич. Только для отладки самого рантайма. |
| **`nerdctl`** | containerd community | Общее управление (замена Docker) | "Docker-like" интерфейс. Поддерживает namespaces K8s, ленивую загрузку, P2P, шифрование и подпись образов. |
| **`crictl`** | Kubernetes community | Отладка CRI-рантаймов | **Рекомендуется для K8s.** Умеет работать с концепцией Pods. Предназначен для диагностики на узлах кластера. |

### 1. crictl (cry control)
Универсальная утилита для отладки **любых** CRI-совместимых рантаймов.
*   **Сходство с Docker:** Многие команды идентичны (`attach`, `exec`, `images`, `info`, `inspect`, `logs`, `ps`, `stats`).
*   **Знание о Pods:** Команда `crictl pods` позволяет выводить список подов, что невозможно в Docker.
*   **Настройка эндпоинта:** Если в системе несколько рантаймов, нужно указать путь к сокету через флаг `--runtime-endpoint` или переменную окружения `CONTAINER_RUNTIME_ENDPOINT` (например, `unix:///run/containerd/containerd.sock`).
*   **Важно:** Не используйте `crictl` для создания контейнеров вручную — `kubelet` удалит их, так как они созданы вне его контроля.

### 2. nerdctl (nerd control)
Утилита, созданная как полноценная замена `docker` CLI для `containerd`.
*   Синтаксис почти полностью совпадает: `nerdctl run`, `nerdctl build`, `nerdctl ps`.
*   Позволяет использовать продвинутые фичи `containerd`, недоступные в Docker (например, нативные пространства имен).
*   Работает с Kubernetes namespaces: `nerdctl --namespace k8s.io ps` — покажет контейнеры, управляемые kubelet.
*   **Compose на containerd:** `nerdctl --namespace k8s.io compose up -d` — запускает docker-compose.yml прямо на containerd без демона Docker.

---

## Безопасность рантаймов

Безопасность контейнеров на уровне рантайма — это многослойная система ограничений, которая определяет, **что** процесс внутри контейнера может делать в системе. Ключевое отличие от Pod Security Context (Kubernetes-уровень): настройки рантайма действуют до запуска приложения и не могут быть обойдены Pod-манифестом.

### Seccomp (Secure Computing Mode)

Фильтрация системных вызовов ядра Linux. Рантайм применяет JSON-профиль, который whitelist/blacklist определенные syscall'ы.

**По умолчанию:**
- `runc`: применяет профиль `runc-default` (блокирует ~44 опасных вызовов: `mount`, `reboot`, `ptrace`, `kexec_load`)
- `containerd`: наследует профиль от CRI (обычно `RuntimeDefault`)
- Kubernetes 1.19+: `seccompProfile.type: RuntimeDefault` — автоматически применяет профиль рантайма

**Применение через Pod Security Context:**
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: secure-pod
spec:
  securityContext:
    seccompProfile:
      type: RuntimeDefault  # использует профиль по умолчанию
  containers:
  - name: app
    image: nginx:1.27
    securityContext:
      seccompProfile:
        type: LocalCustom
        localhostProfile: profiles/my-seccomp.json  # кастомный профиль
```

**Кастомный seccomp-профиль (минимальный пример):**
```json
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "architectures": ["SCMP_ARCH_X86_64"],
  "syscalls": [
    {
      "names": ["read", "write", "open", "close", "stat", "fstat",
                "mmap", "mprotect", "munmap", "brk", "exit_group",
                "futex", "nanosleep", "epoll_wait", "accept",
                "socket", "connect", "bind", "listen", "sendto", "recvfrom"],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
```

### AppArmor

Mandatory Access Control (MAC) система, ограничивающая файловую систему, сеть и capabilities.

```yaml
# Включение AppArmor через аннотацию Pod
apiVersion: v1
kind: Pod
metadata:
  name: apparmor-pod
  annotations:
    container.apparmor.security.beta.kubernetes.io/app: localhost/k8s-apparmor-default
spec:
  containers:
  - name: app
    image: nginx:1.27
```

```bash
# Проверка активного профиля AppArmor на контейнере
kubectl exec <pod> -- cat /proc/1/attr/current
# → nginx (enforce)

# Проверка на хосте (containerd)
sudo crictl inspect <container_id> | grep -A5 apparmor
```

### SELinux

Mandatory Access Control для Red Hat/CentOS/Fedora. В отличие от AppArmor (по умолчанию в Ubuntu/Debian), SELinux работает с метками файлов и процессов.

```yaml
# Маппинг SELinux меток в Pod
apiVersion: v1
kind: Pod
metadata:
  name: selinux-pod
spec:
  securityContext:
    seLinuxOptions:
      level: "s0:c123,c456"
      type: "container_t"
      user: "system_u"
  containers:
  - name: app
    image: nginx:1.27
```

### Linux Capabilities

Вместо.binary "всё или ничего" (root vs non-root), Capabilities разбивают привилегии root на отдельные флаги:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: capabilities-pod
spec:
  containers:
  - name: app
    image: nginx:1.27
    securityContext:
      capabilities:
        drop: ["ALL"]           # сначала убираем всё
        add: ["NET_BIND_SERVICE", "CHOWN"]  # добавляем только необходимое
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      runAsNonRoot: true
      runAsUser: 1000
```

**Часто используемые capabilities:**

| Capability | Разрешает | Когда нужна |
| :--- | :--- | :--- |
| `NET_BIND_SERVICE` | Привязка к портам < 1024 | Веб-серверы на порту 80/443 |
| `CHOWN` | Смена владельца файлов | Init-контейнеры, миграции |
| `SETUID` / `SETGID` | Смена UID/GID процесса | Приложения, меняющие пользователя |
| `SYS_PTRACE` | Отладка других процессов | Sidecar-отладчики |
| `SYS_ADMIN` | Широкий набор операций | **Избегать** — эквивалент privileged |
| `NET_ADMIN` | Управление сетью | NetworkPolicy-плагины, CNI |
| `IPC_LOCK` | mlock() для памяти | Высокопроизводительные приложения |

**Полезные команды для диагностики capabilities:**
```bash
# Просмотр текущих capabilities контейнера
kubectl exec <pod> -- capsh --print
# → Current: = cap_chown,cap_net_bind_service+ep

# Проверка capabilities на хосте (containerd)
sudo crictl inspect <container_id> | jq '.info.spec.runtimeSpec.process.capabilities'
```

### RuntimeClass и политики рантайма

`RuntimeClass` позволяет назначать разным Pod'ам разные рантаймы (например, runc для обычных, gVisor для изолированных):

```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: runsc  # имя OCI runtime в конфигурации containerd
---
apiVersion: v1
kind: Pod
metadata:
  name: isolated-pod
spec:
  runtimeClassName: gvisor
  containers:
  - name: app
    image: nginx:1.27
```

**Пример RuntimeClass для Kata Containers (микро-ВМ):**
```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: kata
handler: kata
overhead:
  podFixed:
    memory: "160Mi"
    cpu: "250m"
scheduling:
  nodeSelector:
    kata-containers: "true"
```

*Подробнее о Pod Security Context и PSS:* **[Безопасность Pod](./pod_security_context.md)** (если существует).

---

## Практические сценарии

### 1. Проверка используемого рантайма

Самый быстрый способ узнать, что используется в кластере:
```bash
kubectl get nodes -o wide
# Смотреть колонку CONTAINER-RUNTIME
# Пример вывода: containerd://1.7.18 или cri-o://1.29.0
```

### 2. Настройка containerd для Kubernetes

Для корректной работы с Kubernetes, `containerd` должен использовать драйвер cgroup от `systemd` (это стандарт в современных Linux-системах, предотвращающий конфликты между Kubelet и ядром).

Настройка в `/etc/containerd/config.toml`:
```toml
# Убедитесь, что плагин CRI включен
[plugins."io.containerd.grpc.v1.cri"]
  sandbox_image = "registry.k8s.io/pause:3.9"

# Включение SystemdCgroup
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
  SystemdCgroup = true
```
После изменения не забудьте перезапустить сервис: `sudo systemctl restart containerd`.

### 3. Отладка застрявшего контейнера через crictl
Если kubelet перешел в статус NotReady, часто проблема на стороне рантайма.
```bash
# 1. Подключаемся к проблемной ноде
# 2. Проверяем доступность CRI
sudo crictl info
# → {"containerd": {"version": "1.7.18", ...}}

# 3. Находим зависший под или контейнер
sudo crictl pods
sudo crictl ps -a  # -a включает остановленные контейнеры

# 4. Проверяем логи контейнера напрямую в обход API-сервера
sudo crictl logs <container_id>

# 5. Проверяем образы и их размер
sudo crictl images -v
# → IMAGE                                     TAG                 IMAGE ID            SIZE
# → docker.io/library/nginx                   1.27                abc123...           187MB

# 6. Остановка и удаление застрявшего контейнера
sudo crictl stop <container_id>
sudo crictl rm <container_id>
```

### 4. Настройка зеркал образов (Registry Mirrors)
В air-gapped или медленных сетях настройка зеркал критична для производительности.

**containerd (`/etc/containerd/config.toml`):**
```toml
[plugins."io.containerd.grpc.v1.cri".registry]
  [plugins."io.containerd.grpc.v1.cri".registry.mirrors]
    [plugins."io.containerd.grpc.v1.cri".registry.mirrors."docker.io"]
      endpoint = [
        "https://harbor.local",
        "https://mirror.gcr.io",
        "https://docker.io"
      ]
  [plugins."io.containerd.grpc.v1.cri".registry.configs]
    [plugins."io.containerd.grpc.v1.cri".registry.configs."harbor.local".tls]
      ca_file = "/etc/containerd/ca.crt"
```

**CRI-O (`/etc/crio/crio.conf`):**
```toml
[crio.image]
  pause_image = "registry.k8s.io/pause:3.9"
  image_pull_policy = "IfNotPresent"

[crio.image.registry]
  [crio.image.registry.mirrors]
    [crio.image.registry.mirrors."docker.io"]
      url = ["https://harbor.local", "https://docker.io"]
```

```bash
# Проверка работы зеркал
sudo crictl pull docker.io/library/alpine:3.20
# → Ранний pull должен пойти через harbor.local, если доступен

# Просмотр конфигурации containerd (без перезапуска)
containerd config dump | grep -A10 "registry.mirrors"
```

### 5. Управление образами на узле

```bash
# Просмотр всех образов с размером
sudo crictl images -v
# → IMAGE                                     TAG                 IMAGE ID            SIZE
# → docker.io/library/nginx                   1.27                abc123def456...     187.4MB

# Удаление неиспользуемых образов (gc по умолчанию)
sudo crictl rmi --prune

# Проверка конфигурации garbage collection
containerd config dump | grep -A5 "gc"
# → [plugins."io.containerd.grpc.v1.cri".containerd]
#   discard_unpacked_layers = true

# Принудительная очистка образов containerd (осторожно!)
sudo ctr -n k8s.io images ls | grep -v "pause" | xargs -I{} sudo ctr -n k8s.io images rm {}

# Просмотр слоёв образа
sudo crictl inspecti <image_id> | jq '.info.spec.image.layers'
```

### 6. Диагностика сети контейнера

```bash
# Проверка сетевого namespace контейнера
CONTAINER_PID=$(sudo crictl inspect <container_id> | jq -r '.info.pid')
nsenter -t $CONTAINER_PID -n ip addr show

# Проверка DNS-резолва из контейнера
nsenter -t $CONTAINER_PID -n nslookup kubernetes.default.svc.cluster.local

# Проверка CNI-конфигурации на хосте
ls /etc/cni/net.d/
cat /etc/cni/net.d/10-mynet.conflist | jq .

# Проверка iptables правил для контейнера
sudo iptables -t nat -L -v | grep $CONTAINER_IP
```

---

## Rootless контейнеры в Kubernetes

Традиционно контейнеры в Kubernetes запускаются от root на хосте. Rootless-режим позволяет запускать контейнеры без привилегий root, повышая безопасность за счет ограничения последствий container breakout.

### Зачем нужен rootless

- **Контейнер не может стать root на хосте** — даже если приложение скомпрометировано
- **Соответствие PSS `restricted`** — профиль безопасности Kubernetes
- **Снижение поверхности атаки** — ограничение системных вызовов на уровне ядра

### containerd в rootless-режиме

```bash
# Проверка: запущен ли containerd от root
ps aux | grep containerd
# → root 1234 ... containerd (rootless: нет)
# → myuser 5678 ... containerd (rootless: да)

# Настройка rootless containerd (пользователь)
containerd-rootless-setuptool.sh install
# → Создаёт systemd user unit для containerd

# Конфигурация: ~/.config/containerd/config.toml
# Основные отличия от rootful:
# - Сокет: /run/user/$(id -u)/containerd/containerd.sock
# - Хранилище: ~/.local/share/containerd/
# - Ограничение: нет доступа к портам < 1024 без sysctl
```

### Rootless в Kubernetes (KinD, k3s)

```bash
# k3s с rootless (rc2+)
curl -sfL https://get.k3s.io | sh -s - server --rootless

# Проверка rootless k3s
k3s check-config
# → [WARN] rootless: enabled

# KinD с rootless (macOS/Linux)
kind create cluster --name rootless --config - <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraMounts:
  - hostPath: /var/run/containerd/containerd.sock
    containerPath: /var/run/containerd/containerd.sock
EOF
```

**Ограничения rootless-режима:**
- Порты < 1024 требуют `net.ipv4.ip_unprivileged_port_start=80` в sysctl
- OverlayFS может не работать на старых ядрах (< 5.11) — нужен `fuse-overlayfs`
- Некоторые CSI-плагины требуют privileged (block storage, NFS)
- NetworkPolicy работает, но CNI-плагин может требовать root для настройки iptables

---

## Мониторинг и метрики рантайма

containerd и CRI-O предоставляют метрики через Prometheus Endpoint.

### Ключевые метрики containerd

```bash
# Эндпоинт метрик containerd (по умолчанию)
curl -s http://localhost:1338/v1/metrics
# или через Prometheus:
curl -s http://localhost:9090/metrics | grep containerd_
```

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `containerd_containers_total` | Gauge | Общее количество контейнеров |
| `containerd_tasks_total` | Gauge | Количество активных задач (OCI tasks) |
| `containerd_image_pulls_bytes_total` | Counter | Суммарный трафик загрузки образов |
| `containerd_cri_container_pulls_bytes_total` | Counter | Трафик pull через CRI |
| `containerd_cri_container_starts_total` | Counter | Количество запусков контейнеров |
| `containerd_cri_container_exits_total` | Counter | Количество остановок (с кодом выхода) |
| `containerd_gc_stauge_errors_total` | Counter | Ошибки garbage collection |

### Настройка скрейпинга containerd в Prometheus

```yaml
# В kube-prometheus-stack: values.yaml
prometheus:
  prometheusSpec:
    additionalScrapeConfigs:
    - job_name: 'containerd'
      static_configs:
      - targets: ['<node_ip>:1338']
      # Или через Kubernetes SD (DaemonSet)
      kubernetes_sd_configs:
      - role: node
      relabel_configs:
      - source_labels: [__address__]
        regex: '(.*):\d+'
        replacement: '$1:1338'
        target_label: __address__
```

**Мониторинг через cAdvisor (встроен в kubelet):**
```bash
# cAdvisor автоматически собирает метрики containerd
curl -s http://localhost:10250/metrics/cadvisor | grep container_

# Полезные метрики:
# container_cpu_usage_seconds_total
# container_memory_usage_bytes
# container_network_receive_bytes_total
# container_fs_usage_bytes
```

### Диагностика проблем рантайма через метрики

```promql
# Контейнеры в CrashLoopBackOff (pod restarts > 5 за 10 минут)
sum by (pod) (rate(kube_pod_container_status_restarts_total[10m])) > 5

# Образы не могут быть загружены (pull errors)
sum by (node) (rate(containerd_cri_image_pulls_errors_total[5m])) > 0

# Контейнеры потребляют > 90% лимита памяти
container_memory_usage_bytes / container_spec_memory_limit_bytes > 0.9

# Disk pressure на узле (связано с storage рантайма)
node_filesystem_avail_bytes{mountpoint="/var/lib/containerd"} / node_filesystem_size_bytes < 0.1
```

*Подробнее:* **[Мониторинг Kubernetes](../MonitoringLogging/)** — общий раздел по метрикам и алертам.

---

## Best Practices для production-среды

1.  **Используйте containerd, а не Docker** — Docker Engine добавляет ненужный слой (dockerd + dockershim). containerd работает напрямую через CRI, уменьшая задержку и поверхность атаки.
2.  **Всегда настраивайте `SystemdCgroup = true`** — иначе Kubernetes не сможет корректно управлять лимитами ресурсов (cgroups v1). В modern Linux (cgroups v2) это критично.
3.  **Настройте `sandbox_image`** — pause-контейнер (`registry.k8s.io/pause:3.9`) используется для каждого Pod Sandbox. Укажите его в конфигурации, чтобы не скачивать при каждом запуске.
4.  **Используйте Registry Mirrors** — зеркала ускоряют pull образов и снижают нагрузку на публичные реестры. Особенно критично в air-gapped средах.
5.  **Применяйте seccomp и AppArmor** — включите `RuntimeDefault` профиль для всех Pod'ов через Pod Security Standards (PSS `restricted`).
6.  **Не используйте privileged контейнеры** — если приложению действительно нужны привилегии, используйте `capabilities` с `drop: ["ALL"]` и `add` только необходимых.
7.  **Настройте garbage collection** — containerd удаляет неиспользуемые образы автоматически, но проверьте интервалы: `containerd config dump | grep gc`.
8.  **Используйте RuntimeClass для изоляции** — назначайте gVisor или Kata для ненадежных workload (мультитеннантность, CI/CD раннеры).
9.  **Мониторьте disk usage** — образы и контейнеры разрастаются. Настройте алерт на `/var/lib/containerd` (> 80%).
10. **Не редактируйте containerd config вручную без проверки** — используйте `containerd config dump` для валидации.

---

## Edge Cases и известные особенности

*   **Image Pull ImagePullBackOff на всех узлах:** Проверьте DNS-резолв реестра (`nslookup registry.k8s.io`), сертификаты TLS и сетевые правила (firewall/proxy). Часто — проблема с `/etc/resolv.conf` в containerd.
*   **Kubelet NotReady (containerd):** `systemctl status containerd` → если демон упал, проверьте логи: `journalctl -u containerd -f`. Частые причины: испорченный config.toml, нехватка disk space, повреждённый сокет.
*   **Контейнер не останавливается (uninterruptible sleep):** Если `crictl stop` не помогает — процесс блокирован в ядре (I/O wait). Проверьте `ddev` на ошибки диска. Решение: `kill -9 <PID>` или перезагрузка узла.
*   **containerd потребляет过多 памяти:** Максимальный кэш образов — настраивается через `containerd config dump | grep -A3 "image"`. По умолчанию: 2GB. Увеличьте при большом количестве образов.
*   **Разные версии containerd на узлах:** Кластер поддерживает до 3 минорных версий разницы. Проверяйте: `kubectl get nodes -o wide | grep CONTAINER-RUNTIME`.
*   **Wasted disk space ('lost layers"):** После `crictl rmi` слои могут оставаться. Используйте containerd garbage collection: `ctr -n k8s.io images gc` или перезапустите containerd.
*   **CIDR конфликт:** Если Pod CIDR совпадает с сетью хоста — контейнеры не смогут связаться с хостом. Проверьте `--cluster-cidr` в kubelet и `--pod-cidr` в kubeadm.
*   **Rootless и порты < 1024:** В rootless-режиме контейнер не может слушать порт 80/443 без `net.ipv4.ip_unprivileged_port_start=80` в sysctl.

**Связанные ресурсы:**
*   **[Архитектура Control Plane](./control_plane_architecture.md)** — место Container Runtime в общей схеме компонентов.
*   **[Kubelet — агент Kubernetes](./kubelet.md)** — инициатор вызовов к среде выполнения.
*   **[Управление образами (Image Management)](../Troubleshooting/Common_Errors/PodImagePullErrors/definitions.md)** — imagePullPolicy, imagePullBackOff, imagePullSecrets.
*   **[Альтернативные рантаймы (Docker/Podman)](../../Docker/alternative_runtimes_and_tools.md)** — сравнение инструментов экосистемы.
*   **[Устранение неполадок Runtime](../Troubleshooting/Common_Errors/NodeUnavailability/runtime_issues.md)** — диагностика проблем с `containerd` и `CRI-O` (сценарии NotReady).
