# Установка Kubernetes через kubeadm

Полное руководство по развёртыванию кластера Kubernetes с использованием утилиты `kubeadm`.

## Определения

**kubeadm** — утилита для быстрой установки кластера Kubernetes, реализующая лучшие практики развёртывания. Включает команды `kubeadm init` (инициализация Control Plane), `kubeadm join` (присоединение узлов) и `kubeadm reset` (очистка узла).

**CRI (Container Runtime Interface)** — стандартный интерфейс для взаимодействия kubelet со средой выполнения контейнеров.

**containerd** — среда выполнения контейнеров, поддерживающая CRI. Рекомендуемый runtime для Kubernetes (начиная с версии 1.24, когда dockershim был удалён из kubelet).

---

## Предварительные требования

### Системные требования

| Ресурс | Минимум | Рекомендация | Примечание |
| :--- | :--- | :--- | :--- |
| **RAM** | 2 ГБ | 4+ ГБ | Для продуктовых кластеров — от 8 ГБ на ноду |
| **CPU** | 1 ядро | 2+ ядра | Зависит от нагрузки на Control Plane |
| **Диск** | 20 ГБ | 50+ ГБ | Зависит от количества образов и логов |
| **Сеть** | Полная связность | — | Все ноды должны видеть друг друга |

### Требования к сети

- Уникальные hostname для каждой ноды
- Полная сетевая доступность между нодами (пинг, curl)
- Открытые порты (если Firewall включён):
  - **Control Plane**: 6443 (API Server), 2379-2380 (etcd), 10250 (kubelet), 10259 (kube-scheduler), 10257 (kube-controller-manager)
  - **Worker**: 10250 (kubelet), 30000-32767 (NodePort Services)

> **Важно**: Проверка открытых портов — [Требования к портам в документации Kubernetes](https://kubernetes.io/docs/reference/networking/ports-and-protocols/).

### Отключение swap

Swap должен быть отключён для корректной работы kubelet:

```bash
# Проверка статуса swap
sudo swapon --show

# Временное отключение
sudo swapoff -a

# Постоянное отключение (удалить из /etc/fstab строку с swap)
sudo sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab
```

> **Примечание**: Поддержка swap для cgroups v2 находится в бета-статусе (feature gate `NodeSwap`), но по умолчанию отключена.

---

## Подготовка узлов

### Загрузка модулей ядра

Для корректной работы сетевых функций Kubernetes необходимо загрузить модули ядра и настроить параметры сети:

```bash
# Загрузка модулей
cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF

sudo modprobe overlay
sudo modprobe br_netfilter
```

### Настройка параметров sysctl

Параметры для работы сетевых плагинов и маршрутизации:

```bash
cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF

# Применение настроек
sudo sysctl --system
```

> **Важно**: Параметр `net.ipv4.ip_forward` включает форвардинг IPv4-пакетов, необходимый для связи между подами на разных нодах.

---

## Установка containerd

### Установка через репозиторий Kubernetes

Установка containerd вместе с пакетами Kubernetes:

```bash
# Обновление репозиториев
sudo apt-get update

# Установка containerd и зависимостей
sudo apt-get install -y containerd
```

### Генерация конфигурации containerd

```bash
# Создание директории для конфигурации
sudo mkdir -p /etc/containerd

# Генерация конфигурации по умолчанию
containerd config default | sudo tee /etc/containerd/config.toml

# Перезапуск сервиса
sudo systemctl restart containerd
sudo systemctl enable containerd
```

### Настройка cgroup driver (критично для systemd-based систем)

Начиная с Kubernetes 1.24 kubelet по умолчанию использует `systemd` cgroup driver. Containerd по умолчанию использует `cgroupfs`. Этот рассинхрон вызывает ошибки при запуске подов.

**Для систем инициализации через systemd (Ubuntu, Debian, RHEL и др.)** необходимо включить `SystemdCgroup` в конфигурации containerd:

```bash
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml
```

Или вручную отредактировать `/etc/containerd/config.toml`:

```toml
[plugins."io.containerd.grpc.v1.cri"]
  SystemdCgroup = true
```

**Почему это важно:**

| Система инициализации | Рекомендуемый cgroup driver | Причина |
| :--- | :--- | :--- |
| **systemd** (Ubuntu, Debian, RHEL) | `systemd` | Единый механизм управления cgroups, корректное ограничение ресурсов |
| **sysvinit/openrc** | `cgroupfs` | Прямое управление через файловую систему cgroupfs |

> **Важно**: Если kubelet и containerd используют разные cgroup driver, поды будут падать с ошибками или не запускаться. После изменения `SystemdCgroup` обязательно выполните `sudo systemctl restart containerd`.

### Проверка статуса

```bash
sudo systemctl status containerd
# → active (running)
```

---

## Установка kubeadm, kubelet и kubectl

### Добавление репозитория Kubernetes

```bash
# Создание директории для ключей (для Ubuntu 22.04+)
sudo mkdir -p -m 755 /etc/apt/keyrings

# Загрузка публичного ключа
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key \
  | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

# Добавление репозитория
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' \
  | sudo tee /etc/apt/sources.list.d/kubernetes.list

# Обновление репозиториев
sudo apt-get update
```

> **Важно**: Версия в URL репозитория (`v1.28`) определяет целевую версию Kubernetes. Для установки других версий измените URL соответственно.
>
> **Примечание для Ubuntu 24.04**: На новых версиях Ubuntu могут потребоваться дополнительные зависимости или другие пути для ключей. При проблемах проверяйте наличие `/etc/apt/keyrings/kubernetes-apt-keyring.gpg` и права на директорию.

### Установка пакетов

```bash
sudo apt-get install -y kubelet kubeadm kubectl
```

### Фиксация версий пакетов

Для предотвращения автоматического обновления и поломки кластера:

```bash
sudo apt-mark hold kubelet kubeadm kubectl
```

### Проверка версий

```bash
kubelet --version
kubeadm version
kubectl version --client
```

---

## Инициализация Control Plane

### Базовая инициализация

```bash
sudo kubeadm init
```

> **Примечание**: При базовой инициализации `kubeadm` автоматически определяет параметры. Для контроля рекомендуется использовать флаги.

### Инициализация с указанием сети для подов

```bash
sudo kubeadm init \
  --pod-network-cidr=10.244.0.0/16 \
  --cri-socket=unix:///run/containerd/containerd.sock
```

> **Важно**: Параметр `--pod-network-cidr` должен соответствовать требованиям выбранного CNI-плагина. Для Calico подходит `10.244.0.0/16` или `192.168.0.0/16`, для Flannel — `10.244.0.0/16`.

### Полная инициализация с флагами

| Флаг | Назначение | Пример |
| :--- | :--- | :--- |
| `--pod-network-cidr` | Диапазон IP для подов | `10.244.0.0/16` |
| `--service-cidr` | Диапазон IP для сервисов | `10.96.0.0/12` |
| `--apiserver-advertise-address` | IP для API Server | `192.168.1.10` |
| `--apiserver-bind-port` | Порт API Server | `6443` |
| `--control-plane-endpoint` | VIP/DNS для HA | `k8s.example.com:6443` |
| `--cri-socket` | Путь к CRI-сокету | `unix:///run/containerd/containerd.sock` |
| `--kubernetes-version` | Целевая версия K8s | `v1.28.0` |
| `--upload-certs` | Загрузка сертификатов для других мастеров | — |

### Настройка kubeconfig для пользователя

После успешной инициализации:

```bash
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
```

> **Альтернатива**: Установка переменной окружения `export KUBECONFIG=/etc/kubernetes/admin.conf` (для скриптов и автоматизации).

### Проверка статуса ноды

```bash
kubectl get nodes
# NAME     STATUS     ROLES           AGE   VERSION
# master   NotReady   control-plane   2m    v1.28.0
```

> **Важно**: Статус `NotReady` ожидается до установки CNI-плагина.

---

## Установка CNI-плагина

Без CNI-плагина поды не могут получать IP-адреса и взаимодействовать друг с другом.

### Calico

```bash
# Скачивание манифеста (версия должна соответствовать Kubernetes)
curl -L https://raw.githubusercontent.com/projectcalico/calico/v3.31.4/manifests/calico.yaml -o calico.yaml

# Изменение CIDR на ваш --pod-network-cidr
sed -i 's|192.168.0.0/16|10.244.0.0/16|g' calico.yaml

# Применение манифеста
kubectl apply -f calico.yaml
```

**Актуальные версии Calico** (на март 2026):

| Версия | Статус | Последняя версия |
| :--- | :--- | :--- |
| **3.31** | Поддерживается | 3.31.4 |
| **3.30** | Поддерживается | 3.30.7 |
| **3.29** | EOL (21 окт 2025) | 3.29.7 |

> **Важно**: Calico следует политике N-2 — каждая версия поддерживает текущую и две предыдущие версии Kubernetes. Проверяйте [матрицу совместимости](https://docs.tigera.io/calico/latest/about/supported-releases) перед установкой.

### Flannel

```bash
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml
```

### Проверка статуса после установки CNI

```bash
kubectl get nodes
# NAME     STATUS   ROLES           AGE   VERSION
# master   Ready    control-plane   5m    v1.28.0

kubectl get pods -n kube-system
# Все системные поды в статусе Running
```

---

## Присоединение worker-нод

### Получение команды join

После `kubeadm init` выводится команда для присоединения:

```bash
sudo kubeadm join 192.168.1.10:6443 \
  --token abc123.def456 \
  --discovery-token-ca-cert-hash sha256:hash123
```

> **Важно**: Сохраните вывод команды `kubeadm init`! Токен действителен 24 часа по умолчанию.

### Генерация нового токена

Если токен истёк или был утерян:

```bash
# Создание нового токена и вывод команды join
kubeadm token create --print-join-command

# Список существующих токенов
kubeadm token list
```

### Выполнение join на worker-ноде

На worker-ноде (после установки containerd, kubelet, kubeadm):

```bash
sudo kubeadm join 192.168.1.10:6443 \
  --token abc123.def456 \
  --discovery-token-ca-cert-hash sha256:hash123
```

### Проверка присоединения

На Control Plane:

```bash
kubectl get nodes
# NAME      STATUS   ROLES           AGE   VERSION
# master    Ready    control-plane   10m   v1.28.0
# worker1   Ready    <none>          1m    v1.28.0
```

---

## Диагностика и troubleshooting

### Проверка системных подов

```bash
kubectl get pods -n kube-system -o wide
# Отображает все системные поды с информацией о нодах и IP
```

### Диагностика подов через describe

```bash
kubectl describe pod <pod-name> -n kube-system
# Раздел Events содержит информацию о планировании, ошибках, проблемах с сетью
```

### Диагностика нод

```bash
kubectl describe node <node-name>
```

**Ключевые секции вывода:**

| Секция | Описание |
| :--- | :--- |
| **Conditions** | Состояние ноды (Ready, MemoryPressure, DiskPressure, PIDPressure) |
| **Addresses** | IP-адреса ноды (InternalIP, ExternalIP, Hostname) |
| **Events** | События, связанные с нодой |

**Статусы Conditions:**

| Condition | Status=False означает |
| :--- | :--- |
| `Ready` | Нода не готова (kubelet не отвечает, CNI не инициализирован) |
| `MemoryPressure` | Нет давления на память |
| `DiskPressure` | Нет давления на диск |
| `PIDPressure` | Нет давления на PID |

### Проблема: ноды в статусе NotReady

**Симптомы**:

```bash
kubectl get nodes
# NAME     STATUS     ROLES           AGE   VERSION
# master   NotReady   control-plane   5m    v1.28.0
```

**Диагностика**:

```bash
kubectl describe node master | grep -A 5 "Conditions:"
# Type    Status   Reason
# ----    ------   ------
# Ready   False    KubeletNotReady
# ...
# Network plugin not ready
```

**Причина**: CNI-плагин не установлен или не инициализирован.

**Решение**: Установить CNI-плагин (см. раздел [Установка CNI-плагина](#установка-cni-плагина)).

### Проблема: поды в статусе Pending

**Симптомы**:

```bash
kubectl get pods -n kube-system
# NAME                    READY   STATUS    RESTARTS   AGE
# coredns-xxxx-xxxx       0/1     Pending   0          5m
```

**Диагностика**:

```bash
kubectl describe pod coredns-xxxx-xxxx -n kube-system
# Events:
# Type     Reason            Age   From     Message
# ----     ------            ----  ----     -------
# Warning  FailedScheduling  2m    default  0/1 nodes are available: 1 node(s) had untolerated taint {node-role.kubernetes.io/control-plane: }
```

**Причина**: Ноды не готовы (NotReady) или имеют taint, запрещающий планирование.

**Решение**: Установить CNI-плагин, дождаться перехода нод в статус Ready.

### Проблема: sandbox image не соответствует

**Симптомы**:

```
[ERROR CRI]: container runtime is not running
```

**Причина**: Версия pause-образа в containerd не соответствует ожидаемой.

**Решение**: Обновить containerd или настроить `sandbox_image` в `/etc/containerd/config.toml`:

```toml
[plugins."io.containerd.grpc.v1.cri"]
  sandbox_image = "registry.k8s.io/pause:3.9"
```

### Проблема: cgroup driver mismatch

**Симптомы**:

```
Failed to create pod sandbox: runtime error: failed to start sandbox: containerd shim not running
```

или поды не запускаются, kubelet логи показывают ошибки cgroup.

**Причина**: Kubelet использует `systemd` cgroup driver (по умолчанию с K8s 1.24), а containerd — `cgroupfs`.

**Решение**: Включить `SystemdCgroup = true` в `/etc/containerd/config.toml` (см. раздел [Настройка cgroup driver](#настройка-cgroup-driver-критично-для-systemd-based-систем)).

### Проблема: ошибка прав при kubeadm join

**Симптомы**:

```
error execution phase preflight: unable to fetch the kubeadm-config ConfigMap
```

или ошибка при выполнении `kubeadm join` от имени обычного пользователя.

**Причина**: Команды `kubeadm` требуют прав root для чтения/записи системных файлов.

**Решение**: Всегда используйте `sudo` для `kubeadm join`:

```bash
sudo kubeadm join <control-plane-ip>:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash>
```

### Проблема: CoreDNS в статусе Pending

**Симптомы**:

```bash
kubectl get pods -n kube-system
# NAME                      READY   STATUS    RESTARTS   AGE
# coredns-xxxx-xxxx         0/1     Pending   0          5m
# coredns-yyyy-yyyy         0/1     Pending   0          5m
```

**Причина**: CoreDNS ожидает IP-адреса из pod-network-cidr, но CNI-плагин ещё не установлен и не выделяет IP-адреса.

**Решение**: Установить CNI-плагин (Calico/Flannel). CoreDNS автоматически перейдёт в статус Running после инициализации сети. Это **ожидаемое поведение** до установки CNI.

### kubelet не запускается

```bash
# Проверка статуса kubelet
sudo systemctl status kubelet

# Просмотр логов
sudo journalctl -u kubelet -f
```

**Типичные причины**:

- Swap включён
- Конфликт версий kubelet и containerd
- Не загружены модули ядра (`br_netfilter`, `overlay`)

### Очистка узла (kubeadm reset)

Для полного сброса узла и удаления кластера:

```bash
# На Control Plane
sudo kubeadm reset --force

# На worker-ноде
sudo kubeadm reset --force

# Очистка остаточных данных
sudo rm -rf /etc/kubernetes/*
sudo rm -rf /var/lib/etcd/*
sudo rm -rf /var/lib/kubelet/*
sudo rm -rf /var/lib/cni/*
```

> **Важно**: `kubeadm reset` не удаляет CNI-плагины. Для полной очистки необходимо удалить манифесты CNI: `kubectl delete -f <cni-manifest>`.

### Проверка сертификатов

```bash
sudo kubeadm certs check-expiration
# Отображает сроки действия всех сертификатов Control Plane
```

Подробнее: [Управление сертификатами](../../Operations/certificate_management.md).

---

## Дополнительная информация

### Архитектура компонентов Control Plane

После установки через `kubeadm` компоненты Control Plane (API Server, controller-manager, scheduler, etcd) запускаются как **статические поды** (static pods). Их манифесты находятся в `/etc/kubernetes/manifests/`.

Kubelet работает как **systemd-юнит** и управляет жизненным циклом всех подов на ноде:

```bash
sudo systemctl status kubelet
```

### Сценарии развёртывания

| Сценарий | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Single-node** | Один узел (Control Plane + workloads) | Разработка, тестирование |
| **Single Control Plane + workers** | Одна master-нода + worker-ноды | Небольшие проекты |
| **HA Control Plane** | 3+ master-ноды с балансировщиком | Продуктовые кластеры |

> **HA-кластер**: Подробное руководство — [High Availability API-сервера](./ha_concepts.md), [Инициализация HA кластера](./cluster_initialization.md).

### Установка других версий Kubernetes

Для установки версии, отличной от последней:

```bash
# Измените версию в URL репозитория
# v1.27 → https://pkgs.k8s.io/core:/stable:/v1.27/deb/

# Укажите версию при установке
sudo apt-get install -y kubelet=1.27.0-1.1 kubeadm=1.27.0-1.1 kubectl=1.27.0-1.1
```

### Обновление кластера

Для обновления существующего кластера используйте `kubeadm upgrade`:

```bash
sudo kubeadm upgrade plan
sudo kubeadm upgrade apply v1.28.0
```

Подробнее: [Обновление кластеров](../../Operations/upgrading_clusters.md).

### Port-forward для доступа к приложениям

Для временного доступа к поду извне кластера:

```bash
# Проброс локального порта 8080 на порт 80 пода
kubectl port-forward pod/nginx-xxxx 8080:80

# Проверка доступа
curl http://localhost:8080
```

> **Важно**: Port-forward работает только пока активна команда. Для постоянного доступа используйте Service или Ingress.

### Проверка работоспособности кластера

После инициализации Control Plane, установки CNI и присоединения worker-нод рекомендуется проверить работоспособность кластера:

```bash
# Запуск тестового пода с nginx
kubectl run nginx --image=nginx

# Проверка статуса пода
kubectl get pods -o wide
# NAME    READY   STATUS    RESTARTS   AGE   IP           NODE
# nginx   1/1     Running   0          30s   10.244.x.x   worker1

# Вход в оболочку пода
kubectl exec -it nginx -- bash

# Проверка работы nginx внутри пода
curl localhost
# → HTTP 200 OK, HTML-страница nginx

# Выход из пода
exit
```

> **Примечание**: Если под не переходит в статус Running, используйте `kubectl describe pod nginx` для диагностики.

---

## См. также

- [Инициализация кластера](./cluster_initialization.md) — флаги, HA, тонкости инициализации
- [HA-кластер с Keepalived и HAProxy](./ha_concepts.md) — настройка отказоустойчивого Control Plane
- [Управление сертификатами](../../Operations/certificate_management.md) — продление и проверка сертификатов
- [Обновление кластеров](../../Operations/upgrading_clusters.md) — плановое обновление версий
