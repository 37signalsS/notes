# Container Runtime в Kubernetes

**Актуально для:** Kubernetes 1.31 / containerd 1.7.x–2.0.x / CRI-O 1.31

## Определения

* **Container Runtime (Среда выполнения контейнеров)** — системное программное обеспечение на рабочем узле, отвечающее за загрузку образов, создание изолированного окружения и управление жизненным циклом контейнеров через механизмы ядра Linux (`namespaces`, `cgroups`, `capabilities`, `seccomp`).
* **CRI (Container Runtime Interface)** — спецификация API на базе gRPC, стандартизирующая взаимодействие между агентом `kubelet` и высокоуровневыми средами выполнения контейнеров.
* **OCI (Open Container Initiative)** — проект Linux Foundation по разработке открытых промышленных стандартов контейнеризации:
  * **Image Spec** — спецификация формата контейнерных образов (манифест, конфигурация, tar-слои файловой системы).
  * **Runtime Spec** — спецификация конфигурации (`config.json`), окружения и жизненного цикла исполнения контейнера на уровне ОС.
* **High-Level Runtime (CRI Runtime)** — высокоуровневый демон (`containerd`, `CRI-O`), принимающий gRPC-запросы от kubelet, управляющий хранилищем образов, распаковкой слоев, сетевыми пространствами имен (через CNI) и передающий управление низкоуровневому рантайму.
* **Low-Level Runtime (OCI Runtime)** — легковесная утилита (`runc`, `crun`), получающая готовую директорию с файловой системой (`rootfs`) и `config.json`, создающая процессы с изоляцией в ядре Linux и сразу завершающая свою работу.
* **containerd-shim / conmon** — промежуточный процесс-демон («прокладка»), запускаемый на каждый контейнер/под. Удерживает открытыми файловые дескрипторы стандартных потоков ввода-вывода (stdio), сохраняет код завершения процесса и позволяет перезапускать основной демон рантайма (`containerd` или `CRI-O`) без остановки работающих контейнеров.
* **Pause Container (Sandbox Container)** — инфраструктурный контейнер (образ `registry.k8s.io/pause:3.10`), запускаемый первым в каждом Pod. Удерживает общие пространства имен (`network`, `ipc`, опционально `uts`), настраиваемые CNI, и выполняет роль процесса-жнеца (`PID 1 reaper`) для сбора зомби-процессов.
* **Snapshotter** — подсистема управления графом слоев файловой системы в `containerd` (на базе `overlayfs`, `btrfs`, `zfs`), объединяющая неизменяемые слои образов и доступный для записи слой контейнера (`upperdir`).
* **RuntimeClass** — встроенный ресурс Kubernetes API (`node.k8s.io/v1`), позволяющий декларативно переопределять обработчик OCI-рантайма на узле для запуска изолированных песочниц (`gVisor`, `Kata Containers`) или альтернативных легковесных рантаймов (`crun`).

---

## Архитектура и принципы работы

### Эволюция рантаймов и удаление dockershim

Исторически Kubernetes запускал контейнеры исключительно через Docker Engine. Так как Docker был монолитным инструментом для разработчиков и не поддерживал API Kubernetes, в код `kubelet` был встроен транслятор — **dockershim**.

```
До Kubernetes 1.24:
[kubelet] → [dockershim (внутри kubelet)] → [dockerd] → [containerd] → [containerd-shim] → [runc] → [Контейнер]

Начиная с Kubernetes 1.24+:
[kubelet] ──(gRPC / CRI)──► [containerd] ────────► [containerd-shim-v2] ──► [runc / crun] ──► [Контейнер]
                      ИЛИ ──► [CRI-O] ──────────────► [conmon] ────────────► [runc / crun] ──► [Контейнер]
```

**Причины отказа от Docker и dockershim:**
1. **Накладные расходы:** Запрос на запуск контейнера проходил длинную цепочку из нескольких демонов, потребляя лишнюю оперативную память и увеличивая время отклика.
2. **Лишний функционал:** Демон `dockerd` содержал функции сборки образов (`docker build`), управления томами и роями (Swarm), ненужные оркестратору.
3. **Архитектурная связанность:** Поддержка `dockershim` непосредственно в кодовой базе Kubernetes связывала релизный цикл K8s с изменениями в Docker.
4. **Стандартизация:** Вся индустрия перешла на единый контракт **CRI** поверх стандартов **OCI**.

### Архитектура интерфейса CRI (Container Runtime Interface)

Интерфейс CRI разделен на два независимых gRPC-сервиса, работающих через локальный Unix-сокет:

1. **`RuntimeService`**:
   * Управление песочницами подов: `RunPodSandbox`, `StopPodSandbox`, `RemovePodSandbox`, `PodSandboxStatus`.
   * Управление контейнерами: `CreateContainer`, `StartContainer`, `StopContainer`, `RemoveContainer`, `ContainerStatus`.
   * Интерактивные сессии: `ExecSync`, `Exec`, `Attach`, `PortForward`.
   * Метрики и статистика: `ContainerStats`, `ListContainerStats`.
2. **`ImageService`**:
   * Операции с образами: `ListImages`, `ImageStatus`, `PullImage`, `RemoveImage`.
   * Статистика хранилища: `ImageFsInfo`.

```
                        ┌──────────────────────────────────────────────────┐
                        │                     Kubelet                      │
                        └─────────┬──────────────────────────────┬─────────┘
                                  │                              │
                    CRI RuntimeService             CRI ImageService
                     (gRPC Unix Socket)             (gRPC Unix Socket)
                                  │                              │
                        ┌─────────▼──────────────────────────────▼─────────┐
                        │     High-Level Runtime (containerd / CRI-O)      │
                        ├──────────────────────────────┬───────────────────┤
                        │         Image Store          │    CNI Plugin     │
                        │    (Content + Snapshotter)   │   (Сеть пода)     │
                        └──────────────┬───────────────┴───────────────────┘
                                       │
                              OCI Shim API (v2)
                                       │
                        ┌──────────────▼───────────────────────────────────┐
                        │      containerd-shim-v2 / conmon                 │
                        └──────────────┬───────────────────────────────────┘
                                       │
                              OCI Runtime Spec
                                       │
                        ┌──────────────▼───────────────────────────────────┐
                        │         runc / crun (Low-Level Runtime)          │
                        └──────────────┬───────────────────────────────────┘
                                       │ clone() / unshare() / setns()
                        ┌──────────────▼───────────────────────────────────┐
                        │   Linux Kernel (Namespaces, cgroups v2, LSM)     │
                        └──────────────────────────────────────────────────┘
```

### Детальная цепочка вызовов при создании Pod

Полный путь создания пода от API-сервера до процессов в ядре:

1. **Планирование:** `kube-scheduler` назначает Pod на конкретный узел.
2. **Получение спецификации:** `kubelet` узла через sync-loop обнаруживает новый Pod.
3. **Создание Sandbox:** `kubelet` отправляет gRPC-вызов `RuntimeService.RunPodSandbox`:
   * High-level рантайм резервирует ресурсы и подготавливает сетевой namespace (`/proc/$PID/ns/net` или `/var/run/netns/...`).
   * Вызывается **CNI-плагин**, который выделяет IP-адрес (IPAM) и настраивает сетевые интерфейсы (veth-пару).
   * Запускается **Pause-контейнер** (`registry.k8s.io/pause:3.10`), удерживающий сетевые и IPC пространства имен.
4. **Подготовка образа:** `kubelet` вызывает `ImageService.PullImage` (если образ отсутствует на узле или политика `imagePullPolicy: Always`).
5. **Распаковка слоев:** Snapshotter монтирует слои образа в режиме read-only (`lowerdir`), создавая временный слой для записи (`upperdir`) через `overlayfs`.
6. **Генерация спецификации OCI:** Рантайм компилирует `config.json` на основе спецификации Pod, параметров cgroup, профилей Seccomp, AppArmor/SELinux и Capabilities.
7. **Запуск через Shim:**
   * High-level рантайм запускает экземпляр `containerd-shim-v2` (или `conmon` в CRI-O).
   * Shim запускает низкоуровневый рантайм: `runc create` / `crun create`.
   * Low-level рантайм настраивает cgroup v2, изолирует пространства имен через системный вызов `clone()` с флагами `CLONE_NEWNS`, `CLONE_NEWPID`, `CLONE_NEWIPC`, `CLONE_NEWNET`, подключается к namespace паузы и выполняет `pivot_root`.
   * По команде `runc start` запускается целевой процесс контейнера (`execve`).
   * Процесс `runc` завершает работу, а управление контейнером остаётся на процессе `containerd-shim-v2`.

### Роль процессов Shim и Pause

#### Зачем нужен containerd-shim-v2 / conmon:
* **Daemonless-архитектура:** Если упал, перезапустился или обновляется демон `containerd`/`crio`, контейнеры продолжают работать без сбоев.
* **Удержание файловых дескрипторов:** Shim удерживает открытыми пайпы `stdout` и `stderr`. При перезапуске рантайма логирование не прерывается.
* **Сбор статусов выхода:** Когда процесс приложения завершается, shim ловит `SIGCHLD`, сохраняет код выхода (`exit code`) контейнера и передает его в CRI, предотвращая появление зомби-процессов на хосте.

#### Зачем нужен Pause-контейнер:
1. **Точка привязки пространств имен:** Контейнеры внутри одного пода должны иметь общий IP-адрес, сетевые порты и IPC. Если бы эти пространства имен были привязаны к первому контейнеру приложения, его перезапуск привел бы к уничтожению всей сети пода. Pause-контейнер работает в цикле `pause()` и никогда не перезапускается, пока жив Pod.
2. **Сборщик зомби (PID 1 Reaper):** При включении `shareProcessNamespace: true` процесс pause становится PID 1 для всего пода и забирает себе осиротевшие дочерние процессы (orphaned child processes), корректно очищая таблицу процессов.

### Сравнение Low-Level рантаймов: runc vs crun

| Критерий | `runc` (стандарт OCI) | `crun` (современная альтернатива) |
| :--- | :--- | :--- |
| **Язык разработки** | Go | C |
| **Потребление памяти на контейнер** | ~10–15 MiB | ~1.5–2 MiB |
| **Время запуска процесса** | ~30–50 мс | ~2–5 мс (в 5–10 раз быстрее) |
| **Поддержка cgroups v2** | Полная | Нативная, оптимизированная |
| **Поддержка WebAssembly (Wasm)** | Через внешние плагины | Нативная интеграция (wasmedge, wasmtime) |
| **Использование по умолчанию** | containerd, Kubernetes bare-metal | CRI-O, Fedora/RHEL, OpenShift, Podman |

---

## Установка и практическая настройка

### Подготовка узла Linux (Prerequisites)

Перед настройкой любого CRI-рантайма на уровне операционной системы необходимо включить необходимые модули ядра и сетевую маршрутизацию.

```bash
# 1. Загрузка модулей ядра при старте системы
cat <<EOF | sudo tee /etc/modules-load.d/k8s-cri.conf
overlay
br_netfilter
EOF

sudo modprobe overlay
sudo modprobe br_netfilter

# Проверка загрузки модулей
lsmod | grep -E "overlay|br_netfilter"
# → overlay               ...  ...
# → br_netfilter          ...  ...

# 2. Настройка параметров sysctl для CNI и iptables
cat <<EOF | sudo tee /etc/sysctl.d/99-kubernetes-cri.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF

sudo sysctl --system

# Проверка примененных параметров
sysctl net.bridge.bridge-nf-call-iptables net.ipv4.ip_forward
# → net.bridge.bridge-nf-call-iptables = 1
# → net.ipv4.ip_forward = 1
```

### Настройка containerd для Production

Файл конфигурации: `/etc/containerd/config.toml`.
Стандартный сокет: `unix:///run/containerd/containerd.sock`.

#### Конфигурация для containerd 1.7.x (актуальная ветка LTS)

```toml
version = 2

[plugins."io.containerd.grpc.v1.cri"]
  sandbox_image = "registry.k8s.io/pause:3.10"
  max_concurrent_downloads = 10

  [plugins."io.containerd.grpc.v1.cri".containerd]
    snapshotter = "overlayfs"
    default_runtime_name = "runc"

    [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc]
      runtime_type = "io.containerd.runc.v2"
      [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
        SystemdCgroup = true

    # Альтернативный рантайм crun
    [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.crun]
      runtime_type = "io.containerd.runc.v2"
      runtime_engine = "/usr/bin/crun"
      [plugins."io.containerd.grpc.v1.cri".containerd.runtimes.crun.options]
        SystemdCgroup = true

  # Путь к зеркалам и сертификатам (новый формат certs.d)
  [plugins."io.containerd.grpc.v1.cri".registry]
    config_path = "/etc/containerd/certs.d"
```

#### Конфигурация для containerd 2.0.x (современный релиз)

В containerd 2.0 плагин `io.containerd.grpc.v1.cri` разделен на независимые модули `io.containerd.cri.v1.runtime` и `io.containerd.cri.v1.images`:

```toml
version = 2

[plugins."io.containerd.cri.v1.runtime"]
  sandbox_image = "registry.k8s.io/pause:3.10"

  [plugins."io.containerd.cri.v1.runtime".containerd]
    default_runtime_name = "runc"

    [plugins."io.containerd.cri.v1.runtime".containerd.runtimes.runc]
      runtime_type = "io.containerd.runc.v2"
      [plugins."io.containerd.cri.v1.runtime".containerd.runtimes.runc.options]
        SystemdCgroup = true

[plugins."io.containerd.cri.v1.images"]
  snapshotter = "overlayfs"
  max_concurrent_downloads = 10
  [plugins."io.containerd.cri.v1.images".registry]
    config_path = "/etc/containerd/certs.d"
```

#### Настройка зеркал и приватных реестров через `certs.d`

Вместо устаревшего блока `mirrors` в `config.toml`, в production используется каталог конфигурации `/etc/containerd/certs.d/`:

```bash
# 1. Зеркало для Docker Hub с локальным кешем Harbor
sudo mkdir -p /etc/containerd/certs.d/docker.io

cat <<EOF | sudo tee /etc/containerd/certs.d/docker.io/hosts.toml
server = "https://docker.io"

[host."https://harbor.local/v2/docker.io"]
  capabilities = ["pull", "resolve"]

[host."https://registry-1.docker.io"]
  capabilities = ["pull", "resolve"]
EOF

# 2. Корпоративный приватный реестр с самоподписанным CA
sudo mkdir -p /etc/containerd/certs.d/harbor.local

cat <<EOF | sudo tee /etc/containerd/certs.d/harbor.local/hosts.toml
server = "https://harbor.local"

[host."https://harbor.local"]
  capabilities = ["pull", "resolve", "push"]
  ca = "/etc/containerd/certs.d/harbor.local/ca.crt"
EOF

# Применение настроек containerd
sudo systemctl restart containerd
sudo systemctl status containerd --no-pager
# → Active: active (running)
```

---

### Настройка CRI-O для Production

Файл конфигурации: `/etc/crio/crio.conf` (или модули в `/etc/crio/crio.conf.d/`).
Стандартный сокет: `unix:///var/run/crio/crio.sock` (симлинк на `/run/crio/crio.sock`).

```toml
# /etc/crio/crio.conf.d/10-k8s.conf
[crio]
  [crio.runtime]
    # Использование crun для минимального расхода RAM
    default_runtime = "crun"
    cgroup_manager = "systemd"
    conmon_cgroup = "system.slice"
    pause_image = "registry.k8s.io/pause:3.10"
    pause_command = "/pause"

    [crio.runtime.runtimes.crun]
      runtime_path = "/usr/bin/crun"
      runtime_type = "oci"

  [crio.image]
    pause_image = "registry.k8s.io/pause:3.10"
    insecure_registries = []
```

Настройка реестров и зеркал для CRI-O выполняется через системный файл `/etc/containers/registries.conf`:

```toml
# /etc/containers/registries.conf
unqualified-search-registries = ["docker.io"]

[[registry]]
prefix = "docker.io"
location = "docker.io"

[[registry.mirror]]
location = "harbor.local/v2/docker.io"
insecure = false
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart crio
sudo systemctl status crio --no-pager
# → Active: active (running)
```

---

### Настройка RuntimeClass в Kubernetes

Ресурс `RuntimeClass` связывает имя класса в спецификации Pod с конфигурационным именем обработчика (`handler`) в рантайме.

```yaml
# runtimeclass-crun.yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: crun
handler: crun
---
# pod-using-crun.yaml
apiVersion: v1
kind: Pod
metadata:
  name: nginx-crun
spec:
  runtimeClassName: crun
  containers:
  - name: nginx
    image: nginx:1.27-alpine
```

```bash
# Применение манифеста
kubectl apply -f runtimeclass-crun.yaml
# → runtimeclass.node.k8s.io/crun created
# → pod/nginx-crun created

# Проверка назначенного рантайма
kubectl get pod nginx-crun -o jsonpath='{.spec.runtimeClassName}'
# → crun
```

> **Безопасность и изоляция:** Настройка песочниц (gVisor `runsc`, Kata Containers `kata`), профилей Seccomp, AppArmor, SELinux и привилегий Capabilities подробно описана в специализированном руководстве [Безопасность рантайма контейнеров](../Security/container_runtime_security.md). Архитектура запуска узла без root-прав описана в [Rootless Kubernetes](../Security/rootless_kubernetes.md).

---

## Операции и команды

### Настройка утилиты crictl

Утилита `crictl` разработана специально для отладки любых CRI-совместимых рантаймов на узле без участия API-сервера.

```bash
# Создание конфигурационного файла /etc/crictl.yaml
cat <<EOF | sudo tee /etc/crictl.yaml
runtime-endpoint: unix:///run/containerd/containerd.sock
image-endpoint: unix:///run/containerd/containerd.sock
timeout: 10
debug: false
EOF

# Проверка связи с CRI рантаймом
sudo crictl info
# → {
# →   "status": {
# →     "conditions": [
# →       {
# →         "type": "RuntimeReady",
# →         "status": true
# →       },
# →       {
# →         "type": "NetworkReady",
# →         "status": true
# →       }
# →     ]
# →   }
# → }
```

### Справочник команд crictl

| Команда | Описание | Пример использования |
| :--- | :--- | :--- |
| `crictl pods` | Список Pod Sandboxes на узле | `sudo crictl pods --name nginx` |
| `crictl ps` | Список запущенных контейнеров | `sudo crictl ps -a` |
| `crictl inspect <ID>` | Детальное состояние контейнера / PID | `sudo crictl inspect <id> \| jq .info.pid` |
| `crictl logs <ID>` | Чтение логов контейнера напрямую с диска | `sudo crictl logs --tail=50 <id>` |
| `crictl exec -it <ID> <cmd>` | Выполнение команды в контейнере | `sudo crictl exec -it <id> sh` |
| `crictl stats` | Использование CPU/RAM контейнерами | `sudo crictl stats` |
| `crictl images` / `img` | Список загруженных образов | `sudo crictl img -v` |
| `crictl pull <image>` | Принудительная загрузка образа | `sudo crictl pull registry.k8s.io/pause:3.10` |
| `crictl stop <ID>` | Остановка зависшего контейнера | `sudo crictl stop <id>` |
| `crictl rm <ID>` | Удаление контейнера | `sudo crictl rm <id>` |
| `crictl rmi --prune` | Очистка неиспользуемых образов | `sudo crictl rmi --prune` |

#### Практические примеры с ожидаемым выводом:

```bash
# 1. Поиск контейнера и его хостового PID
sudo crictl ps --name nginx
# → CONTAINER           IMAGE               CREATED             STATE               NAME                ATTEMPT             POD ID
# → 4a9f1b2c3d4e        nginx:1.27-alpine   10 minutes ago      Running             nginx               0                   a1b2c3d4e5f6

# Получение PID основного процесса в пространстве имен хоста
sudo crictl inspect 4a9f1b2c3d4e | jq -r '.info.pid'
# → 248912

# 2. Инспекция сетевого namespace контейнера через nsenter
sudo nsenter -t 248912 -n ip addr show eth0
# → 2: eth0@if14: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP group default
# →     inet 10.244.1.45/24 brd 10.244.1.255 scope global eth0

# 3. Список образов с их размером на диске
sudo crictl images
# → IMAGE                                TAG                 IMAGE ID            SIZE
# → docker.io/library/nginx              1.27-alpine         91738378b1b0f       43.2MB
# → registry.k8s.io/pause                3.10                873ed76b02977       748kB
```

---

### Низкоуровневая отладка через ctr (containerd CLI)

Утилита `ctr` работает напрямую с демоном `containerd` в обход CRI. Критически важно указывать пространство имен `-n k8s.io`, так как Kubernetes изолирован от стандартного пространства `default`.

```bash
# Список задач (запущенных процессов OCI) в k8s.io
sudo ctr -n k8s.io tasks ls
# → TASK            PID       STATUS
# → 4a9f1b2c3d4e    248912    RUNNING

# Просмотр слоев образа
sudo ctr -n k8s.io images check
# → REF                                TYPE                                                      DIGEST                                                                  STATUS
# → registry.k8s.io/pause:3.10         application/vnd.docker.distribution.manifest.v2+json      sha256:75551f0c0e3ca3f1c95b61fa9c09a2418044fd5089b88f71c977bb2572ea3e4e complete

# Аварийная остановка задачи, если crictl завис
sudo ctr -n k8s.io tasks kill -s SIGKILL 4a9f1b2c3d4e
# → killed
```

---

## Диагностика и устранение неполадок

### 1. Kubelet перешел в NotReady / PLEG is unhealthy

* **Симптомы:** `kubectl get nodes` показывает узел в статусе `NotReady`. В логах kubelet (`journalctl -u kubelet -e`):
  `PLEG is unhealthy: pleg was last seen active 3m20s ago; threshold is 3m0s`.
* **Причина:** Рантайм завис и перестал отвечать на gRPC-запросы инспекции контейнеров. Чаще всего вызвано перегрузкой дисковой подсистемы (I/O wait), сбоем демона `containerd-shim`, исчерпанием файловых дескрипторов или блокировкой ядра на файловой системе `overlayfs`.
* **Диагностика:**
  ```bash
  # 1. Проверка отклика CRI сокета
  sudo crictl info --timeout=5s
  # → context deadline exceeded  ← сокет заблокирован

  # 2. Проверка статуса службы и последних системных ошибок
  sudo systemctl status containerd
  sudo journalctl -u containerd -n 100 --no-pager | grep -iE "error|timeout|panic"

  # 3. Проверка наличия процессов в состоянии uninterruptible sleep (D-state)
  ps aux | awk '$8 ~ /D/ {print $0}'
  # → root 249012 0.0 0.1 ... D ... containerd-shim-runc-v2
  ```
* **Решение:**
  1. Если в D-state находятся shim-процессы из-за сетевого диска (NFS, CSI) — разблокировать сетевой I/O.
  2. Перезапустить демон containerd: `sudo systemctl restart containerd`. Запущенные контейнеры не упадут благодаря shim-v2.
  3. Если сокет поврежден: `sudo rm -f /run/containerd/containerd.sock && sudo systemctl restart containerd`.

Подробный разбор сценариев сбоя узлов: [Недоступность узла: Проблемы среды выполнения (Runtime)](../Troubleshooting/Common_Errors/NodeUnavailability/runtime_issues.md).

---

### 2. Ошибка несоответствия cgroup-драйвера (SystemdCgroup mismatch)

* **Симптомы:** Поды не запускаются, оставаясь в статусе `ContainerCreating` или `CreateContainerError`.
  В логах `crictl`:
  `Failed to create containerd task: OCI runtime create failed: container_linux.go: mounting "cgroup" to rootfs: mount point ... invalid argument`.
* **Причина:** В дистрибутивах с `cgroups v2` (Ubuntu 22.04+, Debian 12+, RHEL 9+) `systemd` является единственным законным менеджером дерева cgroups. Если `kubelet` использует `cgroupDriver: systemd`, а в containerd задано `SystemdCgroup = false`, оба компонента пытаются одновременно управлять структурой каталогов `/sys/fs/cgroup`, что приводит к конфликту.
* **Диагностика:**
  ```bash
  # Проверка версии cgroups на хосте
  stat -fc %T /sys/fs/cgroup/
  # → cgroup2fs  ← включены cgroups v2

  # Проверка настройки containerd
  grep -A3 "SystemdCgroup" /etc/containerd/config.toml
  # → SystemdCgroup = false  ← ОШИБКА
  ```
* **Решение:**
  ```bash
  # Включение SystemdCgroup
  sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/g' /etc/containerd/config.toml
  sudo systemctl restart containerd
  ```

---

### 3. Ошибки загрузки Pause-образа (Failed to pull sandbox image)

* **Симптомы:** Все новые поды на узле застревают в `ContainerCreating`.
  `kubectl describe pod <name>`:
  `FailedCreatePodSandBox: failed to get sandbox image "registry.k8s.io/pause:3.10": failed to pull image`.
* **Причина:** Узел не имеет прямого доступа в интернет (air-gapped среда), DNS не резолвит `registry.k8s.io`, либо в конфигурации рантайма указана устаревшая версия, отсутствующая в локальном реестре.
* **Диагностика:**
  ```bash
  # Проверка текущего настроенного sandbox_image
  grep "sandbox_image" /etc/containerd/config.toml
  # → sandbox_image = "registry.k8s.io/pause:3.9"

  # Попытка ручной загрузки
  sudo crictl pull registry.k8s.io/pause:3.10
  # → failed to pull image: rpc error: code = Unknown desc = failed to resolve reference
  ```
* **Решение:**
  1. В air-gapped окружении загрузить образ в локальный реестр Harbor: `harbor.local/k8s/pause:3.10`.
  2. Указать локальный адрес в конфигурации `/etc/containerd/config.toml`:
     ```toml
     [plugins."io.containerd.grpc.v1.cri"]
       sandbox_image = "harbor.local/k8s/pause:3.10"
     ```
  3. Перезапустить containerd: `sudo systemctl restart containerd`.

Диагностика изолированных сред: [Ошибки загрузки образов: Air-gapped](../Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md).

---

### 4. Исчерпание места на диске и сбои Snapshotter

* **Симптомы:** Узел переходит в статус `DiskPressure`. Новые образы не распаковываются с ошибкой:
  `failed to extract layer ... no space left on device` или `failed to get parent snapshot`.
* **Причина:** Каталог `/var/lib/containerd` (или `/var/lib/containers/storage`) расположен на корневом разделе `/`, который переполнился из-за накопления неиспользуемых слоев образов, аварийно завершившихся контейнеров или объемных логов.
* **Диагностика:**
  ```bash
  # Проверка занятого места на разделах
  df -h /var/lib/containerd
  # → Filesystem      Size  Used Avail Use% Mounted on
  # → /dev/sda1        50G   48G  2.0G  96% /

  # Проверка расхода inodes
  df -i /var/lib/containerd
  # → Use% 99%  ← исчерпание инодов из-за мелких файлов в overlayfs
  ```
* **Решение:**
  ```bash
  # Принудительная очистка неиспользуемых образов через crictl
  sudo crictl rmi --prune

  # Проверка зависших временных директорий snapshotter
  sudo ls -la /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/
  ```

---

### 5. Зависший контейнер и процессы containerd-shim

* **Симптомы:** Команда `crictl stop <id>` завершается по таймауту (`context deadline exceeded`). Pod зависает в статусе `Terminating`.
* **Причина:** Процесс приложения внутри контейнера завис в ядре (D-state) из-за зависшего сетевого сокета или операции монтирования, либо процесс игнорирует сигналы `SIGTERM` и `SIGKILL`.
* **Диагностика:**
  ```bash
  # Поиск PID контейнера
  CONTAINER_PID=$(sudo crictl inspect <id> | jq -r '.info.pid')
  echo $CONTAINER_PID
  # → 250119

  # Проверка стека ядра процесса
  cat /proc/$CONTAINER_PID/stack
  # → [<0>] call_rwsem_down_read_failed+0x18/0x30
  ```
* **Решение:**
  1. Попробовать послать SIGKILL напрямую хостовому PID: `sudo kill -9 $CONTAINER_PID`.
  2. Если процесс не завершается, найти и завершить обслуживающий его процесс shim:
     ```bash
     ps aux | grep containerd-shim | grep <id>
     # → root 250100 ... containerd-shim-runc-v2 -id <id> ...
     sudo kill -9 250100
     ```
  3. После завершения shim удалить контейнер принудительно: `sudo crictl rm -f <id>`.

---

## Рекомендации и Best Practices

1. **Выделенный диск для хранения данных рантайма:**
   Размещайте `/var/lib/containerd` (или `/var/lib/containers/storage`) на отдельном блочном устройстве, LVM-томе или NVMe-накопителе. Это исключает падение ОС узла и остановку системных служб (`systemd`, `sshd`, `journald`) при переполнении диска контейнерными образами.
2. **Используйте cgroup v2 и SystemdCgroup:**
   В современных ядрах Linux всегда используйте `cgroups v2` и параметр `SystemdCgroup = true` в `containerd` (или `cgroup_manager = "systemd"` в CRI-O). Это предотвращает утечки памяти и рассинхронизацию между ядром, `systemd` и `kubelet`.
3. **Согласование версии Pause-контейнера:**
   Версия образа `sandbox_image` должна быть актуальной (`registry.k8s.io/pause:3.10` для Kubernetes 1.30–1.32+) и предварительно прогрета (`pre-pulled`) на всех узлах кластера во время подготовки образа ОС.
4. **Организация зеркал через certs.d:**
   Откажитесь от устаревшей настройки `mirrors` в теле `config.toml`. Используйте модульную структуру `/etc/containerd/certs.d/<registry>/hosts.toml`. Это позволяет обновлять сертификаты и адреса зеркал без перезапуска демона `containerd`.
5. **Использование crun в высоконагруженных узлах:**
   На воркер-нодах с большим числом подов (микросервисы, CI/CD раннеры) переходите на `crun`. Это освобождает до 10–15 MiB RAM на каждый контейнер и сокращает задержку при создании подов в 5–10 раз.
6. **Ограничение параллельных загрузок образов:**
   В больших кластерах устанавливайте `max_concurrent_downloads = 3`–`5`, чтобы массовый рестарт подов не вызывал насыщение сетевого канала и дисковых очередей (I/O latency) на узлах.
7. **Автоматическая ротация логов контейнеров:**
   Настраивайте лимиты ротации логов на уровне `kubelet` (`containerLogMaxSize: "50Mi"`, `containerLogMaxFiles: 5`), чтобы избежать переполнения `/var/log/pods`.

---

## Связанные ресурсы

* **[Kubelet — агент Kubernetes на узле](./kubelet.md)** — архитектура цикла синхронизации Kubelet и вызовы CRI.
* **[Архитектура Control Plane](./control_plane_architecture.md)** — место Container Runtime в общей архитектуре кластера.
* **[Недоступность узла: Проблемы среды выполнения (Runtime)](../Troubleshooting/Common_Errors/NodeUnavailability/runtime_issues.md)** — руководство SSoT по устранению аварийных сбоев рантаймов.
* **[Безопасность рантайма контейнеров](../Security/container_runtime_security.md)** — настройка Seccomp, AppArmor, SELinux, Capabilities и RuntimeClass.
* **[Rootless Kubernetes](../Security/rootless_kubernetes.md)** — запуск компонентов Kubernetes и рантайма без привилегий суперпользователя.
* **[Ошибки загрузки образов: Air-gapped](../Troubleshooting/Common_Errors/PodImagePullErrors/airgapped.md)** — управление образами и настройка локальных реестров в изолированных сетях.
* **[Альтернативные среды выполнения и инструменты контейнеризации](../../Docker/alternative_runtimes_and_tools.md)** — обзор и сравнение runc, crun, Podman, Buildah, Skopeo.
* **[Архитектура Docker](../../Docker/docker_overview.md)** — история выделения containerd и runc из состава Docker.
