# CreateContainerConfigError: Container Runtime Interface (CRI) и containerd

## Определения

**Container Runtime Interface (CRI)** — gRPC API, определяющий стандарт взаимодействия `kubelet` со средой выполнения контейнеров. CRI позволяет `kubelet` работать с различными рантаймами (containerd, CRI-O) без изменения кода Kubernetes. Понимание CRI критично для диагностики `CreateContainerConfigError`, так как эта ошибка возникает **до** вызова CRI-метода `CreateContainer`.

**containerd** — высокопроизводительный демон управления контейнерами, реализующий CRI через встроенный плагин. Является стандартным рантаймом в большинстве Kubernetes-дистрибутивов (kubeadm, EKS, GKE, AKS).

**CRI-O** — минималистичный рантайм, разработанный исключительно для Kubernetes. Строго следует спецификации CRI, без дополнительных функций (в отличие от containerd, который поддерживает Docker CLI и другие сценарии).

**OCI Runtime** — низкоуровневый исполняитель (runc, crun, kata-containers), который непосредственно создает процессы контейнеров, используя namespaces и cgroups ядра Linux. containerd/CRI-O вызывают OCI-рантайм для создания контейнера.

### Связь с другими файлами серии

| Файл | Фокус |
| :--- | :--- |
| [definitions.md](./definitions.md) | Общие определения CreateContainerConfigError, жизненный цикл, таймауты |
| [diagnostics.md](./diagnostics.md) | Общий алгоритм диагностики всех причин CreateContainerConfigError |
| [configmap_issues.md](./configmap_issues.md) | Проблемы с ConfigMap |
| [secret_issues.md](./secret_issues.md) | Проблемы с Secret |
| [rbac_issues.md](./rbac_issues.md) | Проблемы с RBAC и ServiceAccount |
| [volume_issues.md](./volume_issues.md) | Проблемы с томами |
| [pvc_issues.md](./pvc_issues.md) | Проблемы с PersistentVolumeClaim |
| [prevention.md](./prevention.md) | Профилактика, CI/CD валидация, Admission-политики |
| **Данный файл** | CRI, containerd, взаимодействие kubelet с рантаймом |

---

## Основные концепции

### Архитектура взаимодействия kubelet и CRI

```
Pod Spec (API-сервер)
    │
    ▼
kubelet (Pod Worker)
    │
    ├── 1. SyncPod Loop
    │   ├── Dependency Resolution (ConfigMap, Secret, Volumes)
    │   │   └── Если ошибка → CreateContainerConfigError (ДО вызова CRI)
    │   │
    │   └── CRI Config Generation
    │       └── Создание ContainerConfig
    │
    └── 2. CRI Call: RunPodSandbox
        │
        ▼
    containerd / CRI-O
        │
        ├── 3. Pod Sandbox (pause container)
        │   ├── Создание namespaces (net, pid, ipc, uts, mount)
        │   ├── Настройка сети через CNI
        │   └── Монтирование volumes
        │
        ├── 4. CreateContainer
        │   ├── Подготовка rootfs (overlayfs)
        │   ├── Применение security context
        │   └── Запуск OCI runtime (runc/crun)
        │
        └── 5. StartContainer
            └── Запуск PID 1 в контейнере
```

**Ключевой момент:** `CreateContainerConfigError` возникает на **шаге 1** (Dependency Resolution), когда `kubelet` не может разрешить зависимости (ConfigMap, Secret, Volumes). Если зависимости разрешены успешно, `kubelet` переходит к **шагу 2** (CRI Call). Поэтому логи containerd/CRI-O **не содержат** информации об этой ошибке — диагностика полностью полагается на Events API-сервера.

### Архитектура containerd

```
containerd
    │
    ├── CRI Plugin (gRPC сервер)
    │   ├── RunPodSandbox
    │   ├── CreateContainer
    │   ├── StartContainer
    │   ├── StopContainer
    │   └── RemoveContainer
    │
    ├── Content Store (хранилище образов)
    │   └── /var/lib/containerd/io.containerd.content.v1.content/
    │
    ├── Snapshotter (управление снимками)
    │   ├── overlayfs (по умолчанию)
    │   ├── btrfs
    │   └── devmapper
    │
    ├── Shim (прослойка для каждого контейнера)
    │   └── containerd-shim-runc-v2
    │       └── Управление жизненным циклом OCI runtime
    │
    └── Plugins
        ├── CRI (для Kubernetes)
        ├── Docker (для Docker CLI) — deprecated
        └── Metrics (Prometheus)
```

### Архитектура CRI-O

```
CRI-O
    │
    ├── CRI Server (gRPC)
    │   ├── RunPodSandbox
    │   ├── CreateContainer
    │   └── ... (только CRI методы)
    │
    ├── Image Store
    │   └── /var/lib/containers/storage/
    │
    ├── Storage Driver (overlay)
    │
    └── Conmon (монитор контейнеров)
        └── Отслеживание PID и логов
```

### Сравнение containerd и CRI-O

| Характеристика | containerd | CRI-O |
| :--- | :--- | :--- |
| **Назначение** | Универсальный рантайм (K8s + Docker + др.) | Только для Kubernetes |
| **CRI** | Встроенный плагин | Единственный API |
| **Docker CLI** | Поддерживается (deprecated) | Не поддерживается |
| **Размер** | ~150 МБ | ~50 МБ |
| **Плагины** | Модульная система | Минимализм |
| **Версии Kubernetes** | 1.24+ (нативно) | 1.25+ |
| **Использование** | K3s, GKE, EKS, AKS, Rancher | OpenShift, Fedora, RHEL |

### Процесс создания контейнера в containerd

```
1. kubelet → CRI API: RunPodSandbox
   │
   ├── Создание Pod Sandbox (pause container)
   ├── Настройка namespaces
   ├── Вызов CNI для настройки сети
   └── Монтирование volumes (hostPath, emptyDir, etc.)

2. kubelet → CRI API: CreateContainer
   │
   ├── Загрузка образа (image pull если нужно)
   ├── Подготовка rootfs (overlayfs snapshot)
   ├── Применение:
   │   ├── Security Context (capabilities, seccomp, SELinux)
   │   ├── Resource Limits (cgroups)
   │   ├── Environment Variables
   │   └── Volume Mounts
   └── Возврат container ID

3. kubelet → CRI API: StartContainer
   │
   ├── Запуск OCI runtime (runc/crun)
   │   └── Создание namespaces, cgroups
   └── Запуск PID 1 в контейнере
```

### Где возникает CreateContainerConfigError в контейнерном стеке

```
Приложение
    ↑
OCI Runtime (runc)          ← CreateContainerError (монтирование /proc, capabilities)
    ↑
containerd / CRI-O          ← Runtime ошибки (image pull, sandbox creation)
    ↑
kubelet CRI Config          ← CreateContainerConfigError (ConfigMap, Secret, Volumes)
    ↑
kubelet Dependency Resolution ← 404/403 от API-сервера
    ↑
API-сервер                  ← RBAC, Admission, etcd
```

**Важно:** `CreateContainerConfigError` — это ошибка **kubelet**, а не containerd/CRI-O. Рантайм еще не получил команду на создание контейнера.

### Типичные ошибки CRI-рантайма (отличие от CreateContainerConfigError)

| Ошибка | Источник | Причина | Отличие от CreateContainerConfigError |
| :--- | :--- | :--- | :--- |
| `CreateContainerError` | OCI Runtime | Монтирование `/proc`, capabilities, cgroups | Возникает **после** успешного разрешения зависимостей |
| `ImagePullBackOff` | containerd/CRI-O | Невозможно скачать образ | До этапа Dependency Resolution |
| `PodSandboxConfigError` | containerd/CRI-O | Ошибка настройки sandbox | До этапа Dependency Resolution |
| `CreateContainerConfigError` | kubelet | 404/403 от API-сервера (ConfigMap, Secret) | **До** вызова CRI |

### Diagnosing CRI-проблем (отдельно от CreateContainerConfigError)

```bash
# 1. Проверка статуса CRI-рантайма
crictl info
# → Если ошибка — CRI-рантайм не запущен

# 2. Проверка подов CRI
crictl pods
# → Список Pod Sandbox

# 3. Проверка контейнеров
crictl ps -a
# → Все контейнеры (включая остановленные)

# 4. Проверка логов CRI-рантайма
journalctl -u containerd --since "5 min ago"
# → Ошибки containerd

# 5. Проверка сокета CRI
ls -la /run/containerd/containerd.sock
# → Сокет должен существовать

# 6. Проверка конфигурации CRI
cat /etc/containerd/config.toml | grep -A 5 "plugins.\"io.containerd.grpc.v1.cri\""
```

### Взаимодействие kubelet с API-сервером при разрешении зависимостей

```
kubelet SyncPod Loop
    │
    ├── GET /api/v1/namespaces/{ns}/configmaps/{name}
    │   ├── 200 OK → данные получены
    │   ├── 404 NotFound → CreateContainerConfigError ("configmap not found")
    │   └── 403 Forbidden → CreateContainerConfigError ("forbidden")
    │
    ├── GET /api/v1/namespaces/{ns}/secrets/{name}
    │   ├── 200 OK → данные получены
    │   ├── 404 NotFound → CreateContainerConfigError ("secret not found")
    │   └── 403 Forbidden → CreateContainerConfigError ("forbidden")
    │
    └── GET /api/v1/namespaces/{ns}/persistentvolumeclaims/{name}
        ├── 200 OK → PVC найден, проверка Bound status
        ├── 404 NotFound → CreateContainerConfigError ("pvc not found")
        └── 403 Forbidden → CreateContainerConfigError ("forbidden")
```

**Ключевой момент:** Все запросы к API-серверу выполняются параллельно для оптимизации. Если один из ресурсов недоступен — только этот запрос завершится ошибкой, но `kubelet` не может создать контейнер до успешного разрешения **всех** зависимостей.

---

## Практические сценарии

### Сценарий 1: containerd не запущен на узле

Если containerd не запущен, `kubelet` не может подключиться к CRI-сокету. Это приводит к `ContainerRuntimeUnhealthy`, а не `CreateContainerConfigError`.

**Диагностика:**
```bash
# Проверка статуса containerd
systemctl status containerd
# → Active: inactive (dead)

# Проверка сокета
ls -la /run/containerd/containerd.sock
# → No such file or directory

# Проверка логов
journalctl -u containerd --since "10 min ago"
```

**Решение:**
```bash
# Запуск containerd
sudo systemctl start containerd
sudo systemctl enable containerd
```

### Сценарий 2: Версия containerd несовместима с Kubernetes

Старые версии containerd могут не поддерживать новые функции CRI.

**Диагностика:**
```bash
# Проверка версии containerd
containerd --version
# → containerd github.com/containerd/containerd v1.6.26

# Проверка версии Kubernetes
kubectl version --short
# → Server Version: v1.29.3

# Проверка поддерживаемых CRI API
crictl info | jq '.version'
```

**Решение:**
```bash
# Обновление containerd (Ubuntu/Debian)
sudo apt-get update
sudo apt-get install -y containerd.io
sudo systemctl restart containerd
```

### Сценарий 3: Ошибка в конфигурации containerd

Некорректный конфигурационный файл может вызвать проблемы с CRI.

**Диагностика:**
```bash
# Проверка конфигурации
containerd config dump | head -50

# Проверка CRI плагина
containerd config dump | grep -A 10 "plugins.\"io.containerd.grpc.v1.cri\""

# Проверка runtime
containerd config dump | grep -A 5 "runc"
```

**Типичные ошибки:**
```bash
# Невалидный путь к сокету в kubelet
# /var/lib/kubelet/config.yaml:
# containerRuntimeEndpoint: unix:///run/containerd/containerd.sock

# Невалидный путь к сокету в containerd
# /etc/containerd/config.toml:
# [plugins."io.containerd.grpc.v1.cri"]
#   sandbox_image = "registry.k8s.io/pause:3.9"
```

**Решение:**
```bash
# Перегенерация конфигурации containerd
sudo containerd config default | sudo tee /etc/containerd/config.toml
sudo systemctl restart containerd
```

### Сценарий 4: Проблемы с overlayfs

Если overlayfs не поддерживается, containerd не может создавать снимки образов.

**Диагностика:**
```bash
# Проверка поддержки overlayfs
lsmod | grep overlay
# → overlay

# Проверка файловой системы
stat -fc %T /var/lib/containerd/
# → ext2/ext3 (должно быть overlay для overlayfs)

# Проверка логов containerd
journalctl -u containerd | grep -i "overlay\|snapshotter"
```

**Решение:**
```bash
# Установка модуля ядра
sudo modprobe overlay

# Для persistent:
echo "overlay" | sudo tee /etc/modules-load.d/overlay.conf
```

### Сценарий 5: CreateContainerConfigError vs CreateContainerError

Важно различать эти ошибки для корректной диагностики.

**CreateContainerConfigError:**
```bash
# Симптом: Pod в статусе CreateContainerConfigError
kubectl describe pod <pod-name> | grep -A 5 "State:"
# → Waiting:
# →   Reason: CreateContainerConfigError
# →   Message: ...

# Причина: kubelet не может разрешить зависимости
# → Проверить ConfigMap, Secret, PVC, RBAC
```

**CreateContainerError:**
```bash
# Симптом: Pod в статусе CreateContainerError
kubectl describe pod <pod-name> | grep -A 5 "State:"
# → Waiting:
# →   Reason: CreateContainerError
# →   Message: ...

# Причина: CRI/OCI runtime не может создать контейнер
# → Проверить логи containerd, security context, cgroups
```

### Сценарий 6: Диагностика через crictl (на узле)

Если есть SSH-доступ к узлу, можно использовать `crictl` для глубокой диагностики.

```bash
# SSH на узел
ssh <node-name>

# Проверка Pod Sandbox
crictl pods --id <pod-id>
# → ID: abc123def456
# → State: SANDBOX_READY

# Проверка контейнеров
crictl ps --pod <pod-id>
# → CONTAINER ID: xyz789
# → STATE: RUNNING

# Проверка логов контейнера
crictl logs <container-id>
# → Логи приложения

# Проверка образов
crictl images | grep <image-name>
# → IMAGE: nginx:1.25
# → SIZE: 187MB
```

### Сценарий 7: Проблемы с DNS в containerd

containerd использует DNS-настройки хоста для контейнеров.

**Диагностика:**
```bash
# Проверка DNS внутри контейнера
crictl exec <container-id> cat /etc/resolv.conf
# → nameserver 10.96.0.10 (CoreDNS)

# Проверка DNS снаружи
crictl exec <container-id> nslookup kubernetes.default
# → Если ошибка — проблема с CoreDNS или CNI
```

---

## Список проверок (Checklist)

### CRI-рантайм
- [ ] containerd/CRI-O запущен: `systemctl status containerd`
- [ ] CRI-сокет доступен: `ls -la /run/containerd/containerd.sock`
- [ ] Версия containerd совместима с Kubernetes
- [ ] Конфигурация containerd корректна: `containerd config dump`

### kubelet
- [ ] kubelet подключен к CRI: `journalctl -u kubelet | grep -i "cri"`
- [ ] Путь к CRI-сокету корректен в конфигурации kubelet

### Образы
- [ ] Образы доступны в containerd: `crictl images`
- [ ] Проблемы с pull образов: `journalctl -u containerd | grep -i "pull"`

### Сеть
- [ ] CNI плагин работает: `ls -la /opt/cni/bin/`
- [ ] Сетевые плагины containerd настроены: `containerd config dump | grep -A 5 "cni"`

### Логи
- [ ] Логи containerd: `journalctl -u containerd --since "10 min ago"`
- [ ] Логи kubelet: `journalctl -u kubelet --since "10 min ago"`

---

## Дополнительная информация

### Мониторинг CRI-рантайма

```yaml
# Prometheus метрики containerd
- job_name: 'containerd'
  static_configs:
  - targets: ['node-exporter:9100']
  # Метрики:
  # - containerd_container_tasks_handle_total
  # - containerd_containers_total
  # - containerd_image_pulls_total
```

### Полезные команды

```bash
# Информация о CRI
crictl info

# Список Pod Sandbox
crictl pods

# Список контейнеров
crictl ps -a

# Список образов
crictl images

# Логи контейнера
crictl logs <container-id>

# Выполнение команды в контейнере
crictl exec -it <container-id> /bin/sh

# Остановка контейнера
crictl stop <container-id>

# Удаление контейнера
crictl rm <container-id>

# Удаление Pod Sandbox
crictl rmp <pod-id>
```

### Связанные ресурсы

- [Общая диагностика CreateContainerConfigError](./diagnostics.md)
- [Определения CreateContainerConfigError](./definitions.md)
- [Проблемы с ConfigMap](./configmap_issues.md)
- [Проблемы с Secret](./secret_issues.md)
- [Проблемы с RBAC](./rbac_issues.md)
- [Архитектура Control Plane](../../../Concepts/control_plane_architecture.md)
- [Контейнерная сетевая модель](../../../Networking/OSI_TCP_IP_Model/container_networking.md)
- [Docker vs containerd](../../../../Docker/docker_overview.md)
