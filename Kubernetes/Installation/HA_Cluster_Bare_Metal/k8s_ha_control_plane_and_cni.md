# Настройка Control Plane и CNI в HA кластере

## Определения

**Control Plane Endpoint** — стабильная точка входа (VIP:PORT) для доступа к API-серверу через балансировщик нагрузки.

**CNI (Container Network Interface)** — стандартный плагин для обеспечения сетевой связности между подами на разных узлах кластера.

**Calico** — популярный CNI-плагин с поддержкой NetworkPolicy, BGP-маршрутизации и policy-based управления сетью.

**kubeadm init** — команда инициализации Control Plane на первом мастер-узле.

**kubeadm join** — команда присоединения узла к существующему кластеру.

---

## Основные концепции

### Архитектура инициализации HA кластера

1. **Первый мастер-узел** — инициализирует кластер через `kubeadm init`
2. **Остальные мастера** — присоединяются через `kubeadm join` с флагом `--control-plane`
3. **Worker узлы** — присоединяются через `kubeadm join` без флагов мастера
4. **CNI плагин** — устанавливается после инициализации первого мастера

### Ключевые флаги kubeadm

| Флаг | Назначение | Пример |
| :--- | :--- | :--- |
| `--control-plane-endpoint` | VIP балансировщика для HA | `192.168.1.100:6443` |
| `--upload-certs` | Загрузка сертификатов в кластер для других мастеров | — |
| `--pod-network-cidr` | Диапазон IP для подов (требуется CNI) | `192.168.0.0/16` |

### Почему CNI устанавливается отдельно?

Kubernetes не включает сетевой плагин по умолчанию. Администратор выбирает CNI в зависимости от требований:
- **Calico** — баланс функциональности и производительности
- **Flannel** — простой, минималистичный
- **Cilium** — eBPF-based, продвинутая безопасность
- **Weave Net** — автоматическая настройка

---

## Практические сценарии

### Шаг 1: Инициализация первого мастер-узла

На **первом** мастер-узле выполните:

```bash
# Замените LOAD_BALANCER_VIP на VIP вашего балансировщика
# --pod-network-cidr требуется для Calico и многих других CNI
sudo kubeadm init \
  --control-plane-endpoint "LOAD_BALANCER_VIP:6443" \
  --pod-network-cidr=192.168.0.0/16 \
  --upload-certs
```

**Параметры**:
- `--control-plane-endpoint` — адрес балансировщика (Keepalived + HAProxy)
- `--pod-network-cidr` — диапазон для подов (должен совпадать с выбранным CNI)
- `--upload-certs` — загружает сертификаты в Secret для других мастеров

**Результат**:
- `kubeadm` выведет **две команды `join`**:
  1. Для других мастер-узлов (с `--control-plane` и `--certificate-key`)
  2. Для worker-узлов (без дополнительных флагов)

> **Важно**: Сохраните вывод команды! Команды `join` содержат одноразовые токены.

### Шаг 2: Настройка kubectl на первом мастере

```bash
# Создать директорию для конфигурации
mkdir -p $HOME/.kube

# Скопировать admin.conf (учетные данные кластера)
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config

# Установить права владельца
sudo chown $(id -u):$(id -g) $HOME/.kube/config

# Проверка доступа
kubectl cluster-info
kubectl get nodes
```

### Шаг 3: Присоединение остальных мастер-узлов

На **втором и третьем** мастер-узлах выполните команду `kubeadm join` для мастеров:

```bash
sudo kubeadm join LOAD_BALANCER_VIP:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane \
  --certificate-key <key>
```

**После выполнения**:
- Мастер присоединяется к кластеру
- Запускаются компоненты Control Plane как статические поды
- `etcd` формирует кластер (3 узла)

### Шаг 4: Присоединение worker-узлов

На **каждом** worker-узле выполните команду `kubeadm join` для воркеров:

```bash
sudo kubeadm join LOAD_BALANCER_VIP:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash>
```

### Шаг 5: Установка CNI плагина (Calico)

Установка выполняется **один раз** с любого мастер-узла после инициализации кластера:

```bash
# Применить манифест Calico
# ⚠️ ВЕРСИЯ: v3.31.0 указана в оригинале — проверить совместимость
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.31.0/manifests/calico.yaml
```

> **Важно**: Проверяйте совместимость версии Calico с вашей версией Kubernetes в [официальной документации Calico](https://docs.tigera.io/calico/latest/about/supported-releases).

**Альтернативные CNI**:
- **Cilium**: `kubectl apply -f https://raw.githubusercontent.com/cilium/cilium/master/install/kubernetes/quick-install.yaml`
- **Flannel**: `kubectl apply -f https://raw.githubusercontent.com/flannel-io/flannel/master/Documentation/kube-flannel.yml`

### Шаг 6: Проверка состояния кластера

```bash
# Проверка системных подов (все должны быть Running)
kubectl get pods -n kube-system

# Проверка узлов (все должны быть Ready)
kubectl get nodes

# Проверка компонентов Control Plane
kubectl get pods -n kube-system -l component=kube-apiserver
kubectl get pods -n kube-system -l component=kube-controller-manager
kubectl get pods -n kube-system -l component=kube-scheduler
kubectl get pods -n kube-system -l component=etcd

# Проверка CNI подов (Calico)
kubectl get pods -n kube-system -l k8s-app=calico-node
```

**Ожидаемый результат**:
- Все системные поды в статусе `Running`
- Все узлы в статусе `Ready`
- 3 пода `etcd`, 3 пода `kube-apiserver`, и т.д.

---

## Дополнительная информация

### Troubleshooting

#### Поды не запускаются

```bash
# Проверка логов kubelet
sudo journalctl -u kubelet -f

# Проверка логов контейнеров
kubectl logs -n kube-system <pod-name>

# Описание проблемного пода
kubectl describe pod -n kube-system <pod-name>
```

#### CNI не работает

```bash
# Проверка подов CNI
kubectl get pods -n kube-system -l k8s-app=calico-node

# Пересоздание подов CNI
kubectl delete pod -n kube-system -l k8s-app=calico-node
```

#### Мастер не присоединяется

- Проверьте доступность балансировщика (VIP)
- Убедитесь, что `--certificate-key` корректен
- Проверьте логи `kubeadm join`

### Связанные документы

- **Обзор HA**: [HA Cluster Overview](./k8s_ha_cluster_overview.md)
- **Компоненты**: [Component Installation](./k8s_ha_component_installation.md)
- **Проверка**: [Cluster Verification](./k8s_ha_cluster_verification.md)
- **Keepalived + HAProxy**: [HA с kubeadm](../kudeadm/kubeadm_ha_with_keepalived_haproxy.md)
- **CNI**: [CNI Overview](../../Networking/Network/cni_overview.md)
- **Calico**: [Calico Documentation](https://docs.tigera.io/calico/latest/)

### Версии (требует проверки)

| Компонент | Версия в файле | Статус | Примечание |
| :--- | :--- | :--- | :--- |
| **Calico** | v3.31.0 | ⚠️ Проверить | Поддерживает K8s 1.28-1.32 |

### Надежность

| Раздел | Confidence |
| :--- | :--- |
| kubeadm init | Этот файл + официалка | 10 |
| kubeadm join | Этот файл + официалка | 10 |
| Calico установка | Требует проверки версии | 7 |
| CNI концепции | [CNI Overview](../../Networking/Network/cni_overview.md) | 10 |
