# Инициализация Control Plane в HA кластере

## Определения

**Control Plane Endpoint** — стабильная точка входа (VIP:PORT или DNS) для доступа к API-серверу через балансировщик нагрузки.

**kubeadm init** — команда инициализации Control Plane на первом мастер-узле.

**kubeadm join** — команда присоединения узла к существующему кластеру.

**pod-network-cidr** — диапазон IP-адресов для подов (не должен пересекаться с существующей инфраструктурой).

**service-cidr** — диапазон IP-адресов для сервисов Kubernetes.

---

## Основные концепции

### Процесс инициализации HA кластера

Инициализация выполняется на **первом мастер-узле** через `kubeadm init`. Остальные узлы присоединяются позже через [`kubeadm join`](./node_joining.md):

1. Первый мастер инициализирует кластер через `kubeadm init`
2. Остальные мастера присоединяются через `kubeadm join --control-plane`
3. Worker-узлы присоединяются через `kubeadm join` без флагов мастера
4. CNI-плагин устанавливается после инициализации первого мастера ([инструкция](./cni_installation.md))

### Ключевые флаги kubeadm

Флаги, специфичные для инициализации Control Plane. Полный список флагов `kubeadm join` — в [документации по присоединению узлов](./node_joining.md).

| Флаг | Назначение | Пример |
| :--- | :--- | :--- |
| `--control-plane-endpoint` | VIP балансировщика для HA | `192.168.1.100:6443` |
| `--upload-certs` | Загрузка сертификатов в кластер для других мастеров | — |
| `--pod-network-cidr` | Диапазон IP для подов (требуется CNI) | `100.64.0.0/16` |
| `--service-cidr` | Диапазон IP для сервисов | `100.65.0.0/16` |
| `--apiserver-advertise-address` | IP-адрес для публикации API | `192.168.1.1` |
| `--apiserver-bind-port` | Порт API-сервера | `6443` |
| `--cri-socket` | CRI-сокет среды выполнения | `unix:///run/containerd/containerd.sock` |

### Выбор CIDR для подов и сервисов

При инициализации кластера необходимо выбрать диапазоны, **не пересекающиеся** с существующей сетевой инфраструктурой:

| Диапазон | Назначение | Рекомендуемые CIDR | Примечание |
| :--- | :--- | :--- | :--- |
| `--pod-network-cidr` | IP-адреса для подов | `100.64.0.0/16`, `10.244.0.0/16`, `192.168.0.0/16` | Должен совпадать с настройками CNI |
| `--service-cidr` | IP-адреса для сервисов | `100.65.0.0/16`, `10.96.0.0/12` | Default: `10.96.0.0/12` |

> **Важно**: Изменение CIDR после инициализации кластера невозможно без полной пересоздания.

---

## Практические сценарии

### Шаг 1: Инициализация первого мастер-узла

На **первом** мастер-узле выполните:

```bash
# Важно: выбираем CIDR, не пересекающиеся с вашей сетью
# --pod-network-cidr=100.64.0.0/16 - для pod'ов
# --service-cidr=100.65.0.0/16 - для сервисов

sudo kubeadm init \
  --control-plane-endpoint=k8s-node1:6443 \
  --pod-network-cidr=100.64.0.0/16 \
  --service-cidr=100.65.0.0/16 \
  --upload-certs \
  --apiserver-advertise-address=192.168.1.1 \
  --apiserver-bind-port=6443 \
  --cri-socket=unix:///run/containerd/containerd.sock
```

**Параметры**:

- `--control-plane-endpoint` — адрес балансировщика (Keepalived + HAProxy) или DNS-имя
- `--pod-network-cidr` — диапазон для подов (должен совпадать с выбранным CNI)
- `--service-cidr` — диапазон для сервисов (по умолчанию `10.96.0.0/12`)
- `--upload-certs` — загружает сертификаты в Secret для других мастеров
- `--apiserver-advertise-address` — IP-адрес, который будет использоваться для доступа к API
- `--apiserver-bind-port` — порт, на котором будет слушать API-сервер (по умолчанию `6443`)
- `--cri-socket` — путь к CRI-сокету (для containerd: `/run/containerd/containerd.sock`)

**Результат**:

- `kubeadm` выведет **две команды `join`**:
  1. Для других мастер-узлов (с `--control-plane` и `--certificate-key`)
  2. Для worker-узлов (без дополнительных флагов)

> **Важно**: Сохраните вывод команды! Команды `join` содержат одноразовые токены и хэши сертификатов.

### Что происходит в процессе инициализации

```
[init] Using Kubernetes version: v1.34.3
[preflight] Running pre-flight checks
[certs] Generating certificates...
[kubeconfig] Writing kubeconfig files...
[etcd] Creating static Pod manifest for local etcd
[control-plane] Creating static Pod manifests...
[kubelet-start] Starting the kubelet
[wait-control-plane] Waiting for control plane components...
```

**Этапы**:

1. **Pre-flight checks** — проверка системных требований
2. **Генерация сертификатов** — создание TLS-сертификатов для компонентов
3. **Kubeconfig файлы** — создание файлов доступа к кластеру
4. **etcd** — запуск локального etcd как статического пода
5. **Control Plane** — запуск API server, controller manager, scheduler
6. **Kubelet** — запуск агента узла
7. **Ожидание** — проверка доступности компонентов control plane

### Шаг 2: Настройка kubectl для обычного пользователя

```bash
# Выполняется как обычный пользователь (например, evdovichenko)
mkdir -p $HOME/.kube

# Скопировать admin.conf (учетные данные кластера)
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config

# Установить права владельца
sudo chown $(id -u):$(id -g) $HOME/.kube/config

# Проверка доступа
kubectl cluster-info
kubectl get nodes
```

> **Важно**: Статус `NotReady` — это **нормально** сразу после инициализации. Для перехода в `Ready` требуется установка CNI-плагина.

### Шаг 3: Сохранение команд для подключения нод

Из вывода `kubeadm init` сохраните команды для последующего присоединения узлов.

**Для control-plane нод** (если будут дополнительные мастер-узлы):

```bash
kubeadm join k8s-node1:6443 --token XXX \
  --discovery-token-ca-cert-hash sha256:XXX \
  --control-plane --certificate-key XXX
```

**Для worker-нод**:

```bash
kubeadm join k8s-node1:6443 --token XXX \
  --discovery-token-ca-cert-hash sha256:XXX
```

> **Важно**: Токены действительны 24 часа по умолчанию. Для повторной генерации используйте `kubeadm token create --print-join-command`.

### Шаг 4: Текущее состояние после инициализации

| Компонент | Статус | Примечание |
| :--- | :--- | :--- |
| Control-plane | Инициализирован | Компоненты запущены |
| kubectl | Настроен | Доступ к кластеру |
| Node status | NotReady | Требуется CNI |
| Сеть pod'ов | Не настроена | Следующий шаг |

---

## Дополнительная информация

### Отладка проблем инициализации

```bash
# Логи kubelet (управление подами Control Plane)
sudo journalctl -u kubelet -f

# Логи компонентов Control Plane (статические поды)
sudo crictl ps -a | grep -E 'apiserver|controller|scheduler|etcd'
sudo crictl logs <container-id>

# Проверка сертификатов
sudo ls -la /etc/kubernetes/pki/
sudo kubeadm init phase certs check-expiration
```

**Типичные проблемы:**

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `error execution phase preflight` | Порт 6443 занят | Освободить порт или изменить `--apiserver-bind-port` |
| `etcd cluster unhealthy` | Проблемы с etcd | Проверить логи etcd, время на узлах |
| `certificate-key expired` | Токен устарел (>24ч) | `kubeadm init phase upload-certs --upload-certs` |
| `control-plane-endpoint unreachable` | Балансировщик не работает | Проверить HAProxy/Keepalived |

### Интеграция с процессом развёртывания

Инициализация Control Plane — **шаг 4** после [подготовки узлов](./k8s_ha_node_preparation.md) и перед [установкой CNI](./cni_installation.md). Подробнее об архитектуре — в [обзоре HA кластера](./k8s_ha_cluster_overview.md), о присоединении узлов — в [руководстве по node joining](./node_joining.md). Настройка балансировщика описана в [документации по HA с kubeadm](../kubeadm/ha_concepts.md).
