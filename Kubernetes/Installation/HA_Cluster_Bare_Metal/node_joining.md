# Присоединение узлов к HA кластеру

## Определения

**kubeadm join** — команда присоединения узла к существующему кластеру.

**Control Plane Endpoint** — стабильная точка входа (VIP:PORT или DNS) для доступа к API-серверу через балансировщик нагрузки.

---

## Основные концепции

### Процесс присоединения узлов

Присоединение выполняется после [инициализации Control Plane](./control_plane_initialization.md) на первом мастер-узле. Команды `kubeadm join` получаются из вывода `kubeadm init`:

1. Остальные мастера присоединяются через `kubeadm join --control-plane --certificate-key`
2. Worker-узлы присоединяются через `kubeadm join` без дополнительных флагов
3. CNI-плагин разворачивается на всех узлах автоматически (DaemonSet)

Подробнее об архитектуре инициализации — в [руководстве по control plane initialization](./control_plane_initialization.md).

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
k8s-node1  Ready    control-plane   42m   v1.35.x
k8s-node2  Ready    <none>          7m    v1.35.x
k8s-node3  Ready    <none>          6m    v1.35.x
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
k8s-node1  Ready    control-plane   42m   v1.35.x   192.168.1.1    <none>
k8s-node2  Ready    <none>          7m    v1.35.x   192.168.1.2    <none>
k8s-node3  Ready    <none>          6m    v1.35.x   192.168.1.3    <none>
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

## Дополнительная информация

### Отладка проблем присоединения

```bash
# Логи kubelet на присоединяемом узле
sudo journalctl -u kubelet -f

# Проверка токена (на master)
kubeadm token list

# Пересоздание токена если истёк
kubeadm token create --print-join-command

# Проверка сертификатов
sudo kubeadm init phase upload-certs --upload-certs
```

**Типичные проблемы:**

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `token expired` | Токен устарел (>24ч) | `kubeadm token create --print-join-command` |
| `certificate-key invalid` | Неправильный ключ | Пересоздать: `kubeadm init phase upload-certs` |
| `connection refused` | Балансировщик не работает | Проверить HAProxy/Keepalived |
| `node already exists` | Узел уже в кластере | `kubeadm reset` на узле |

### Интеграция с процессом развёртывания

Присоединение узлов — **шаг 7–8** после [инициализации Control Plane](./control_plane_initialization.md) и [установки CNI](./cni_installation.md). Проверка состояния кластера описана в [руководстве по верификации](./k8s_ha_cluster_verification.md), настройка балансировщика — в [документации по HA с kubeadm](../kubeadm/ha_keepalived_haproxy/ha_concepts.md).
