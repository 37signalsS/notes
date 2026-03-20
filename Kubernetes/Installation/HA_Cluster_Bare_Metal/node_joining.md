# Присоединение узлов к HA кластеру

## Определения

**kubeadm join** — команда присоединения узла к существующему кластеру.

**Control Plane Endpoint** — стабильная точка входа (VIP:PORT или DNS) для доступа к API-серверу через балансировщик нагрузки.

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
| `--pod-network-cidr` | Диапазон IP для подов (требуется CNI) | `100.64.0.0/16` |
| `--service-cidr` | Диапазон IP для сервисов | `100.65.0.0/16` |
| `--apiserver-advertise-address` | IP-адрес для публикации API | `192.168.1.1` |
| `--apiserver-bind-port` | Порт API-сервера | `6443` |
| `--cri-socket` | CRI-сокет среды выполнения | `unix:///run/containerd/containerd.sock` |

---

## Практические сценарии

### Шаг 7: Присоединение остальных мастер-узлов

На **втором и третьем** мастер-узлах выполните команду `kubeadm join` для мастеров (из вывода `kubeadm init`):

```bash
sudo kubeadm join LOAD_BALANCER_VIP:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane \
  --certificate-key <key>
```

**Параметры**:

- `--control-plane` — указывает, что узел присоединяется как мастер
- `--certificate-key` — ключ для загрузки сертификатов из кластера (генерируется при `kubeadm init` с `--upload-certs`)

**После выполнения**:

- Мастер присоединяется к кластеру
- Запускаются компоненты Control Plane как статические поды
- `etcd` формирует кластер (3 узла для кворума)

### Шаг 8: Присоединение worker-узлов

**На master-ноде (получение токена):**

```bash
# Создаём новый токен (если старый истёк или не сохранили)
kubeadm token create --print-join-command
```

**Вывод:**
```bash
kubeadm join k8s-node1:6443 --token xmyjho.oi5i30jgskg5esi3 \
  --discovery-token-ca-cert-hash sha256:d3e0fa38c572bbed10f3e67fa709769b1cd9bed80f0d2c80a87d7db45b8ea75a
```

> **Важно:** Добавляем флаг `--cri-socket`, так как используем containerd:
> ```bash
> --cri-socket=unix:///run/containerd/containerd.sock
> ```

**На каждом worker-узле:**

```bash
sudo kubeadm join LOAD_BALANCER_VIP:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --cri-socket=unix:///run/containerd/containerd.sock
```

> **Примечание:** Worker-узлы не требуют дополнительных флагов, так как не запускают компоненты Control Plane.

---

### Шаг 9: Мониторинг присоединения на master-ноде

**На control-plain ноде следим за появлением новых нод:**

```bash
# В реальном времени
kubectl get nodes -w
```

**Через некоторое время** (когда Calico развернётся на worker-нодах):
```
NAME       STATUS   ROLES           AGE   VERSION
k8s-node1  Ready    control-plane   42m   v1.34.3
k8s-node2  Ready    <none>          7m    v1.34.3
k8s-node3  Ready    <none>          6m    v1.34.3
```

> **Обратите внимание:** У worker-нод роль `<none>` — это нормально, они просто workers.

---

### Шаг 10: Проверка состояния кластера

**Детальная информация о нодах:**
```bash
kubectl get nodes -o wide
```

**Ожидаемый вывод:**
```
NAME       STATUS   ROLES           AGE   VERSION   INTERNAL-IP    EXTERNAL-IP
k8s-node1  Ready    control-plane   42m   v1.34.3   192.168.1.1    <none>
k8s-node2  Ready    <none>          7m    v1.34.3   192.168.1.2    <none>
k8s-node3  Ready    <none>          6m    v1.34.3   192.168.1.3    <none>
```

**Проверка системных подов:**
```bash
kubectl get pods -n kube-system -o wide
```

**Должны увидеть:**
- На каждой ноде — `calico-node-xxx` (по одному на ноду)
- На master — поды control-plane (apiserver, etcd, scheduler, controller-manager)
- `CoreDNS` (2 реплики) — распределены по нодам
- `kube-proxy` на каждой ноде

**Проверка Calico на worker-нодах:**
```bash
# Проверяем поды Calico на всех нодах
kubectl get pods -n kube-system -l k8s-app=calico-node -o wide

# Проверяем логи Calico на конкретной ноде
kubectl logs -n kube-system -l k8s-app=calico-node --tail=50
```

Должны увидеть по одному поду на каждой ноде со статусом `Running`.

---

## Дополнительная информация

### Связанные документы

- **Обзор HA**: [HA Cluster Overview](./k8s_ha_cluster_overview.md)
- **Компоненты**: [Component Installation](./k8s_ha_component_installation.md)
- **Проверка**: [Cluster Verification](./k8s_ha_cluster_verification.md)
- **Control Plane**: [Control Plane Initialization](./control_plane_initialization.md)
- **CNI Installation**: [CNI Installation](./cni_installation.md)
- **Keepalived + HAProxy**: [HA с kubeadm](../kubeadm/ha_keepalived_haproxy/index.md)
