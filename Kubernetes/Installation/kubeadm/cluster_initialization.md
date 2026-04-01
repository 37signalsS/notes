# Инициализация кластера kubeadm

## Определения

**kubeadm init** — команда инициализации Control Plane на первом мастер-узле.

**kubeadm join** — команда присоединения узла к существующему кластеру.

**Control Plane Endpoint** — стабильная точка входа (VIP:PORT или DNS) для доступа к API-серверу через балансировщик нагрузки.

**pod-network-cidr** — диапазон IP-адресов для подов, указываемый при инициализации кластера. Не должен пересекаться с существующей инфраструктурой.

**service-cidr** — диапазон IP-адресов для сервисов Kubernetes (по умолчанию `10.96.0.0/12`).

---

## Основные концепции

### Процесс инициализации

Инициализация выполняется на **первом мастер-узле** через `kubeadm init`. Остальные узлы присоединяются позже через `kubeadm join`:

1. Первый мастер инициализирует кластер через `kubeadm init`
2. Остальные мастера присоединяются через `kubeadm join --control-plane`
3. Worker-узлы присоединяются через `kubeadm join` без флагов мастера
4. CNI-плагин устанавливается после инициализации первого мастера

### Ключевые флаги kubeadm init

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

### Инициализация первого мастер-узла

```bash
sudo kubeadm init \
  --control-plane-endpoint "192.168.122.189:7443" \
  --pod-network-cidr=100.64.0.0/16 \
  --service-cidr=100.65.0.0/16 \
  --upload-certs \
  --apiserver-advertise-address=192.168.1.1 \
  --apiserver-bind-port=6443 \
  --cri-socket=unix:///run/containerd/containerd.sock
```

**Результат**:

- `kubeadm` выведет **две команды `join`**:
  1. Для других мастер-узлов (с `--control-plane` и `--certificate-key`)
  2. Для worker-узлов (без дополнительных флагов)

> **Важно**: Сохраните вывод команды! Команды `join` содержат одноразовые токены и хэши сертификатов. Токены действительны 24 часа по умолчанию.

### Присоединение узлов

**Control-plane узлы:**
```bash
sudo kubeadm join 192.168.122.189:7443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane \
  --certificate-key <key>
```

**Worker-узлы:**
```bash
sudo kubeadm join 192.168.122.189:7443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --cri-socket=unix:///run/containerd/containerd.sock
```

### Установка CNI (Calico)

Установка выполняется **один раз** после инициализации кластера. До установки CNI узлы находятся в статусе `NotReady`.

```bash
# Скачиваем манифест Calico (версия должна соответствовать Kubernetes)
curl -L https://raw.githubusercontent.com/projectcalico/calico/v3.31.4/manifests/calico.yaml -o calico.yaml

# Заменяем CIDR на ваш pod-network-cidr
sed -i 's|192.168.0.0/16|100.64.0.0/16|g' calico.yaml

# Применяем манифест
kubectl apply -f calico.yaml
```

**Актуальные версии Calico** (на март 2026):

| Версия | Статус | Последняя версия |
| :--- | :--- | :--- |
| **3.31** | Поддерживается | 3.31.4 |
| **3.30** | Поддерживается | 3.30.7 |
| **3.29** | EOL (21 окт 2025) | 3.29.7 |
| **3.28** | EOL (05 мая 2025) | 3.28.5 |

> **Важно**: Calico следует политике N-2 — каждая версия поддерживает текущую и две предыдущие версии Kubernetes. Проверяйте [матрицу совместимости](https://docs.tigera.io/calico/latest/about/supported-releases) перед установкой.

После установки CNI узлы перейдут в статус `Ready`:

```bash
kubectl get nodes
# NAME     STATUS   ROLES           AGE   VERSION
# master   Ready    control-plane   10m   v1.35.x
```

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

# Пересоздание токена если истёк
kubeadm token create --print-join-command

# Пересоздание certificate-key
kubeadm init phase upload-certs --upload-certs
```

**Типичные проблемы:**

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `error execution phase preflight` | Порт 6443 занят | Освободить порт или изменить `--apiserver-bind-port` |
| `etcd cluster unhealthy` | Проблемы с etcd | Проверить логи etcd, время на узлах |
| `certificate-key expired` | Токен устарел (>24ч) | `kubeadm init phase upload-certs --upload-certs` |
| `control-plane-endpoint unreachable` | Балансировщик не работает | Проверить HAProxy/Keepalived |
| `token expired` | Токен устарел (>24ч) | `kubeadm token create --print-join-command` |

### Интеграция с процессом развёртывания HA кластера

Инициализация кластера — **шаг 4** после [подготовки узлов](../HA_Cluster_Bare_Metal/k8s_ha_node_preparation.md) и перед [подключением узлов](../HA_Cluster_Bare_Metal/node_joining.md). Подробнее об архитектуре — в [обзоре HA кластера](../HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md), о настройке балансировщика — в [HA с Keepalived и HAProxy](./ha_concepts.md).
