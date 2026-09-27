# Инициализация кластера через kubeadm

## Определения

**kubeadm init** — команда для инициализации первого узла Control Plane. Выполняет предварительные проверки системы, генерирует удостоверяющий центр (CA), выпускает TLS-сертификаты, создаёт конфигурационные файлы (kubeconfig) и запускает компоненты Kubernetes в виде статических подов. Является первым шагом в развёртывании кластера.

**kubeadm join** — команда для расширения кластера. Присоединяет новые узлы (Control Plane с флагом `--control-plane` или Worker) к существующему кластеру через Bootstrap Token. Подробнее: [Присоединение узлов](../../Installation/HA_Cluster_Bare_Metal/node_joining.md).

**Control Plane Endpoint** — стабильная точка входа (VIP, DNS-имя или адрес балансировщика), через которую все компоненты кластера (kubelet, kube-proxy, kubectl) и внешние клиенты обращаются к API-серверу. Задаётся через флаг `--control-plane-endpoint` или в YAML-конфигурации. В HA-кластерах это通常 VIP:Port (например, `192.168.1.100:7443`). Подробнее: [HA концепции](./ha_concepts.md).

**Bootstrap Token** — временный симметричный HMAC-токен для аутентификации новых узлов при `kubeadm join`. Формируется из двух частей: `token-id` (6 hex-символов) и `token-secret` (16 hex-символов). По умолчанию действует 24 часа. Хранится как Kubernetes Secret типа `bootstrap.kubernetes.io/token` в namespace `kube-public`. Подробнее: [Bootstrap Tokens в Kubernetes](../../Security/authentication.md).

**Discovery-token-ca-cert-hash** — SHA-256 хэш публичного ключа CA, используемый узлом для проверки подлинности кластера при присоединении. Предотвращает подмену API-сервера (MITM-атака). Генерируется автоматически при `kubeadm init`.

**Certificate Key** — AES-CBC ключ для шифрования сертификатов Control Plane при их загрузке в Secret `kubeadm-certs` (через `--upload-certs`). Необходим для автоматического присоединения дополнительных мастеров. Действителен 2 часа; по истечении необходимо выполнить `kubeadm init phase upload-certs --upload-certs` повторно.

**pod-network-cidr** — диапазон IP-адресов для сетевой подсети подов (Pod Network CIDR). Задаётся через `--pod-network-cidr` при инициализации. Значение зависит от выбранного CNI-плагина: Calico обычно `10.244.0.0/16` или `192.168.0.0/16`, Cilium — `10.0.0.0/8`. Этот CIDR **не** должен пересекаться с `service-cidr` и физической сетью узлов.

**service-cidr** — диапазон IP-адресов для ClusterIP сервисов (по умолчанию `10.96.0.0/12`). Эти IP-адреса виртуальные и маршрутизируются только внутри кластера через `kube-proxy`. Кластерные DNS-имена (например, `kubernetes.default.svc.cluster.local`) резолвятся в адреса из этого диапазона.

**Static Pods** — поды, управляемые напрямую `kubelet` на конкретном узле через манифесты в `/etc/kubernetes/manifests/`, без участия API-сервера. Используются для запуска компонентов Control Plane (apiserver, etcd, scheduler, controller-manager). При падении Static Pod автоматически перезапускается. Подробнее: [Static Pods](../../Concepts/control_plane_architecture.md).

**kubeadm-config** — ConfigMap `kubeadm-config` в namespace `kube-system`, содержащий полную конфигурацию кластера. Загружается автоматически при `kubeadm init` и используется при обновлениях (`kubeadm upgrade`) и повторной загрузке сертификатов.

---

## Основные концепции

### Требования к инфраструктуре (Pre-flight)

Перед запуском `kubeadm init` все узлы должны соответствовать минимальным требованиям:

| Ресурс | Control Plane | Worker |
| :--- | :--- | :--- |
| CPU | 2 ядра минимум | 1 ядро минимум |
| RAM | 2 ГБ минимум | 2 ГБ минимум |
| Disk | 50 ГБ (NVMe рекомендуется для etcd) | 20 ГБ |
| Сеть | Порты 6443, 2379-2380, 10250 открыты | Порт 10250 |
| OS | Ubuntu 22.04+, RHEL 9+, Debian 12+ | Аналогично |
| Kernel | 5.15+ (6.x рекомендуется) | Аналогично |
| Runtime | containerd v2.0+ / CRI-O | Аналогично |

**Обязательная подготовка узлов (выполняется на всех узлах):**
1. Отключение Swap: `sudo swapoff -a` + удаление из `/etc/fstab`
2. Загрузка модулей ядра: `overlay`, `br_netfilter`
3. Активация `net.ipv4.ip_forward=1` и `net.bridge.bridge-nf-call-iptables=1`
4. Установка containerd с включённым `SystemdCgroup`
5. Установка пакетов `kubeadm`, `kubelet`, `kubectl`

Полное руководство по подготовке: [Установка kubeadm](./kubeadm_installation_guide.md).

### Фазы инициализации (kubeadm init)

При выполнении `kubeadm init` выполняется 10 атомарных фаз. Каждую фазу можно запускать отдельно для отладки:

```bash
# Просмотр доступных фаз
kubeadm init --help | grep phase

# Запуск отдельной фазы
kubeadm init phase preflight
kubeadm init phase certs
```

| # | Фаза | Описание | Результат |
| :--- | :--- | :--- | :--- |
| 1 | **Preflight** | Проверка системы (ядро, RAM, CPU, порты, swap, CRI) | Отчёт о готовности |
| 2 | **Certs** | Создание TLS-сертификатов (CA, apiserver, etcd, front-proxy) | `/etc/kubernetes/pki/` |
| 3 | **Kubeconfig** | Генерация конфигов для компонентов | `admin.conf`, `kubelet.conf`, `controller-manager.conf`, `scheduler.conf` |
| 4 | **Control plane** | Создание манифестов статических подов | `/etc/kubernetes/manifests/*.yaml` |
| 5 | **etcd** | Запуск локального etcd (или подключение внешнего) | etcd-кластер инициализирован |
| 6 | **Wait** | Ожидание готовности API-сервера (healthz) | API доступен |
| 7 | **Upload-config** | Загрузка конфигурации в ConfigMap `kubeadm-config` | ConfigMap создан |
| 8 | **Upload-certs** | Загрузка сертификатов в Secret (опционально, с `--upload-certs`) | Secret `kubeadm-certs` |
| 9 | **Mark-control-plane** | Установка меток (`node-role.kubernetes.io/control-plane`) и Taints | Узел помечен как master |
| 10 | **Addon** | Деплой CoreDNS и kube-proxy | Сеть и DNS работают |

**Важно**: Фазы 5-6 (etcd + wait) критичны — если API-сервер не запустится за отведённое время, инициализация завершится ошибкой.

### Ключевые параметры инициализации

| Флаг | Назначение | Пример | Обязательность |
| :--- | :--- | :--- | :--- |
| `--control-plane-endpoint` | Адрес балансировщика/VIP | `k8s-api.example.com:7443` | Обязателен для HA |
| `--upload-certs` | Загрузка сертификатов для других мастеров | — | Для HA |
| `--pod-network-cidr` | Сеть для подов (зависит от CNI) | `10.244.0.0/16` | Обязателен |
| `--service-cidr` | Сеть для сервисов | `10.96.0.0/12` | Опциональный |
| `--apiserver-advertise-address` | IP для доступа других узлов к API | `192.168.1.10` | Рекомендуется |
| `--cri-socket` | Путь к сокету Runtime | `unix:///run/containerd/containerd.sock` | Опциональный |
| `--kubernetes-version` | Конкретная версия Kubernetes | `v1.36.0` | Опциональный |
| `--certificates-key` | Ключ для шифрования сертификатов | Случайный AES-CBC ключ | Для HA |

### Конфигурация через YAML (Рекомендуется)

YAML-конфигурация обеспечивает воспроизводимость, версионирование и доступ к параметрам, недоступным через флаги.

#### InitConfiguration

Настраивает поведение самого kubeadm при инициализации (адрес API-сервера, CRI, регистрация узла):

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: InitConfiguration
localAPIEndpoint:
  advertiseAddress: "192.168.1.10"
  bindPort: 6443
nodeRegistration:
  criSocket: "unix:///run/containerd/containerd.sock"
  imagePullPolicy: IfNotPresent
  taints:
    - key: "node-role.kubernetes.io/control-plane"
      effect: "NoSchedule"
```

#### ClusterConfiguration

Настраивает параметры самого кластера (версия, сеть, etcd, API-сервер):

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
kubernetesVersion: "v1.36.0"
controlPlaneEndpoint: "192.168.1.100:7443"
networking:
  podSubnet: "10.244.0.0/16"
  serviceSubnet: "10.96.0.0/12"
  dnsDomain: "cluster.local"
apiServer:
  certSANs:
    - "192.168.1.100"
    - "k8s-api.example.com"
    - "192.168.1.11"
    - "192.168.1.12"
    - "192.168.1.13"
  extraArgs:
    audit-log-path: "/var/log/kubernetes/audit/audit.log"
    audit-log-maxage: "30"
    audit-log-maxbackup: "10"
controllerManager:
  extraArgs:
    terminated-pod-gc-threshold: "100"
scheduler:
  extraArgs:
    profiling: "false"
etcd:
  local:
    dataDir: "/var/lib/etcd"
    extraArgs:
      heartbeat-interval: "500"
      election-timeout: "2500"
```

**Ключевые параметры ClusterConfiguration:**

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `controlPlaneEndpoint` | Стабильный адрес API (VIP/DNS) | Адрес первого мастера |
| `networking.podSubnet` | CIDR для подов | Зависит от CNI |
| `networking.serviceSubnet` | CIDR для ClusterIP сервисов | `10.96.0.0/12` |
| `networking.dnsDomain` | Домен кластерного DNS | `cluster.local` |
| `apiServer.certSANs` | Дополнительные SAN для сертификата API | Пусто |
| `etcd.local.dataDir` | Директория данных etcd | `/var/lib/etcd` |

#### JoinConfiguration (для мастеров)

Конфигурация присоединения дополнительного Control Plane-узла:

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: JoinConfiguration
discovery:
  bootstrapToken:
    apiServerEndpoint: "192.168.1.100:7443"
    token: "abc123.xyz789"
    caCertHashes:
      - "sha256:abc123def456..."
controlPlane:
  localAPIEndpoint:
    advertiseAddress: "192.168.1.12"
    bindPort: 6443
  certificateKey: "abcd1234..."
nodeRegistration:
  criSocket: "unix:///run/containerd/containerd.sock"
```

#### Объединение в один файл

Для single-node кластера можно объединить `InitConfiguration` и `ClusterConfiguration`:

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: InitConfiguration
localAPIEndpoint:
  advertiseAddress: "192.168.1.10"
nodeRegistration:
  criSocket: "unix:///run/containerd/containerd.sock"
---
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
kubernetesVersion: "v1.36.0"
controlPlaneEndpoint: "192.168.1.10:6443"
networking:
  podSubnet: "10.244.0.0/16"
  serviceSubnet: "10.96.0.0/12"
```

### Что происходит после kubeadm init

После успешной инициализации kubeadm выполняет следующие действия:

1. **Генерация CA**: корневой CA (`ca.crt`/`ca.key`) и подписанные им сертификаты для apiserver, etcd, front-proxy.
2. **Создание kubeconfig**: файлы `admin.conf`, `kubelet.conf`, `controller-manager.conf`, `scheduler.conf` в `/etc/kubernetes/`.
3. **Запуск Static Pods**: манифесты для `kube-apiserver`, `kube-controller-manager`, `kube-scheduler`, `etcd` размещаются в `/etc/kubernetes/manifests/`.
4. **Настройка kubelet**: создание `/var/lib/kubelet/config.yaml` и `/etc/kubernetes/kubelet.conf`.
5. **Регистрация в etcd**: создание записи об узле в etcd-кластере.
6. **Установка Taints**: `node-role.kubernetes.io/control-plane:NoSchedule` — по умолчанию поды не запускаются на мастере.
7. **Деплой CoreDNS и kube-proxy**: сетевые компоненты и DNS начинают работать.
8. **Вывод команды join**: kubeadm выводит команду для присоединения других узлов.

**Вывод kubeadm init содержит:**
- `kubeadm join` команду с токеном и хэшем CA
- Инструкцию по настройке `kubectl`
- Инструкцию по установке CNI-плагина
- Инструкцию по снятию Taints (для single-node)

---

## Практические сценарии

### 1. Single-node кластер (для разработки и тестирования)

Для развёртывания кластера на одном узле без HA:

```bash
# Инициализация (CNI ещё не установлен, поды будут в Pending)
sudo kubeadm init \
  --pod-network-cidr=10.244.0.0/16 \
  --cri-socket=unix:///run/containerd/containerd.sock \
  --kubernetes-version=v1.36.0
```

**Настройка kubectl:**
```bash
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
```

**Установка CNI** (Calico через Tigera Operator — рекомендуется):
```bash
kubectl apply -f https://raw.githubusercontent.com/projectcalico/calico/v3.33.0/manifests/tigera-operator.yaml

cat <<EOF | kubectl apply -f -
apiVersion: operator.tigera.io/v1
kind: Installation
metadata:
  name: default
spec:
  calicoNetwork:
    ipPools:
    - blockSize: 26
      cidr: 10.244.0.0/16
      encapsulation: VXLANCrossSubnet
      natOutgoing: Enabled
      nodeSelector: all()
EOF
```

Подробнее: [Установка CNI в HA кластере](../../Installation/HA_Cluster_Bare_Metal/cni_installation.md).

**Снятие Taints (для запуска подов на мастере):**
```bash
kubectl taint nodes --all node-role.kubernetes.io/control-plane-
# → node/MASTER untainted
```

**Проверка работоспособности:**
```bash
# Статус узла
kubectl get nodes -o wide
# → NAME     STATUS   ROLES           AGE   VERSION   INTERNAL-IP     ...
# → master   Ready    control-plane   5m    v1.36.0   192.168.1.10    ...

# Все поды в kube-system
kubectl get pods -n kube-system -o wide
# → NAME                                       READY   STATUS    RESTARTS   AGE   IP             NODE
# → coredns-5d78c9869d-xxxxx                   1/1     Running   0          5m    10.244.0.2     master
# → etcd-master                                1/1     Running   0          5m    192.168.1.10   master
# → kube-apiserver-master                      1/1     Running   0          5m    192.168.1.10   master
# → kube-controller-manager-master             1/1     Running   0          5m    192.168.1.10   master
# → kube-proxy-xxxxx                           1/1     Running   0          5m    192.168.1.10   master
# → kube-scheduler-master                      1/1     Running   0          5m    192.168.1.10   master
# → calico-node-xxxxx                          1/1     Running   0          3m    192.168.1.10   master
# → calico-kube-controllers-5fxxxxx-xxxxx      1/1     Running   0          3m    10.244.0.3     master

# Тест DNS и сетевой связности
kubectl run test --image=busybox --restart=Never -- sleep 3600
kubectl exec test -- nslookup kubernetes.default
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.96.0.1

kubectl exec test -- ping -c 3 10.244.0.1
# → 3 packets transmitted, 3 received, 0% packet loss
```

### 2. Инициализация первого мастера (HA-кластер)

Для production-среды с отказоустойчивым Control Plane:

```bash
sudo kubeadm init \
  --control-plane-endpoint "192.168.1.100:7443" \
  --pod-network-cidr=10.244.0.0/16 \
  --upload-certs \
  --cri-socket=unix:///run/containerd/containerd.sock \
  --apiserver-advertise-address=192.168.1.10
```

**Что делает `--upload-certs`:**
- Шифрует сертификаты Control Plane AES-CBC ключом
- Загружает их в Secret `kubeadm-certs` в namespace `kube-system`
- Ключ для расшифровки выводится в конце инициализации
- Ключ действителен **2 часа** — по истечении необходимо повторить: `kubeadm init phase upload-certs --upload-certs`

**Настройка kubectl (на первом мастере):**
```bash
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
```

Подробнее: [HA концепции](./ha_concepts.md), [Настройка балансировщика](./keepalived_haproxy_setup.md).

### 3. Управление токенами и ключами

Если вывод `kubeadm init` был потерян или токены истекли:

```bash
# Генерация новой команды join (токен действителен 24 часа)
kubeadm token create --print-join-command
# → kubeadm join 192.168.1.100:7443 --token abc123.xyz789 --discovery-token-ca-cert-hash sha256:abc123...

# Повторная загрузка сертификатов для новых мастеров
kubeadm init phase upload-certs --upload-certs
# → [upload-certs] Storing the configuration in secrets in the "kube-system" Namespace
# → [upload-certs] Using certificate key abcd1234ef5678...

# Список активных токенов
kubeadm token list
# → TOKEN                     TTL         EXPIRES                USAGES                   DESCRIPTION
# → abc123.xyz789             23h         2026-09-01T12:00:00Z   signing,authentication    The default bootstrap token

# Создание токена с нестандартным TTL
kubeadm token create --ttl 2h
```

### 4. Присоединение узлов

#### Control Plane (дополнительные мастера для HA)

```bash
sudo kubeadm join 192.168.1.100:7443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane \
  --certificate-key <key> \
  --cri-socket=unix:///run/containerd/containerd.sock
```

**Параметры:**
- `--control-plane` — узел будет частью Control Plane (запустит apiserver, scheduler, controller-manager, etcd)
- `--certificate-key` — ключ для расшифровки сертификатов из Secret `kubeadm-certs`

Подробнее: [Присоединение узлов к HA кластеру](../../Installation/HA_Cluster_Bare_Metal/node_joining.md).

#### Worker Nodes (рабочие узлы)

```bash
sudo kubeadm join 192.168.1.100:7443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --cri-socket=unix:///run/containerd/containerd.sock
```

**Worker-узлы не требуют** `--certificate-key`, так как не запускают компоненты Control Plane.

### 5. Верификация после инициализации

#### Базовая проверка

```bash
# Список узлов
kubectl get nodes -o wide

# Все поды в kube-system
kubectl get pods -n kube-system -o wide

# Здоровье API-сервера
kubectl get --raw /healthz
# → ok

# Готовность API-сервера
kubectl get --raw /readyz
# → ok
```

#### Проверка etcd (на Control Plane узлах)

```bash
# Здоровье etcd
ETCDCTL_API=3 etcdctl endpoint health \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key
# → https://127.0.0.1:2379 is healthy: committed proposal may be applied

# Статус etcd (кворум, размер данных)
ETCDCTL_API=3 etcdctl endpoint status \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  --write-out=table
# → ENDPOINT                    ID        VERSION   DB SIZE   IS LEARNER   IS LEADER   IS LEARNER   RAFT TERM   RAFT INDEX   RAFT APPLIED INDEX   COMMITS   ERRORS   HEALTH
# → https://127.0.0.1:2379      abc123    3.5.x     5 MB      false        true        false        2           100          100                   100                true

# Список участников etcd
ETCDCTL_API=3 etcdctl member list \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  --write-out=table
```

#### Проверка сертификатов

```bash
# Проверка сроков действия всех сертификатов
sudo kubeadm certs check-expiration
# → CERTIFICATE                EXPIRES                  RESIDUAL TIME   ...
# → admin.conf                 Sep 01, 2027 12:00 UTC   364d
# → apiserver                  Sep 01, 2027 12:00 UTC   364d
# → apiserver-etcd-client      Sep 01, 2027 12:00 UTC   364d
# → ...
```

#### Проверка DNS и сетевой связности

```bash
# Тест DNS-резолвинга
kubectl run dns-test --image=busybox --restart=Never -- sleep 3600
kubectl exec dns-test -- nslookup kubernetes.default
# → Name:      kubernetes.default.svc.cluster.local
# → Address:   10.96.0.1

kubectl exec dns-test -- nslookup kube-dns.kube-system.svc.cluster.local
# → Name:      kube-dns.kube-system.svc.cluster.local
# → Address:   10.96.0.10

# Тест сетевой связности между подами
kubectl run test1 --image=busybox --restart=Never -- sleep 3600
kubectl run test2 --image=nginx --restart=Never -- sleep 3600

# Дождаться готовности подов
kubectl wait --for=condition=Ready pod/test1 pod/test2 --timeout=60s

# Пинг между подами
kubectl exec test1 -- ping -c 3 $(kubectl get pod test2 -o jsonpath='{.status.podIP}')
# → 3 packets transmitted, 3 received, 0% packet loss

# Удаление тестовых подов
kubectl delete pod dns-test test1 test2 --grace-period=0 --force
```

### 6. Типичные ошибки при инициализации

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `[ERROR CRI]: container runtime is not running` | CRI-сокет недоступен | Проверить статус containerd: `systemctl status containerd` |
| `[ERROR Port-6443]: Port 6443 is in use` | Другой процесс слушает порт | `ss -tulpn \| grep 6443` — убить конфликтующий процесс |
| `[ERROR Port-2379]: Port 2379 is in use` | Предыдущий etcd не остановлен | `systemctl stop etcd` или удалить `/var/lib/etcd/` |
| `etcd cluster unhealthy` | Проблемы с диском или сетью | Проверить I/O: `iostat -x 1`, задержки: `etcdctl endpoint health` |
| `unable to get CA cert` | Отсутствуют файлы CA | Удалить `/etc/kubernetes/pki/` и попробовать снова |
| `[ERROR FileAvailable]`: `/etc/kubernetes/pki/ca.crt` | Кластер уже установлен | `sudo kubeadm reset --force` перед повторной инициализацией |
| `[ERROR ImagePull]`: не удаётся скачать образ | Нет доступа к реестру | Настроить прокси или mirror registry |
| `[ERROR kubelet]`: kubelet не запускается | Не отключён Swap или неверный cgroup | `swapoff -a`, проверить `config.toml` containerd |
| `token expired` | Прошло >24 часов с создания токена | `kubeadm token create --print-join-command` |
| `CA hash mismatch` | CA был пересоздан | Получить актуальный хэш: `openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt \| openssl rsa -pubin -outform der 2>/dev/null \| openssl dgst -sha256 -hex` |

**Команды отладки:**
```bash
# Логи kubelet
sudo journalctl -u kubelet -f --since "5 minutes ago"

# Логи API-сервера (через kubectl, если доступен)
kubectl logs -n kube-system kube-apiserver-$(hostname) -f

# Логи etcd
kubectl logs -n kube-system etcd-$(hostname) -f

# Просмотр запущенных контейнеров через CRI
sudo crictl ps -a
sudo crictl pods -a

# Проверка манифестов Static Pods
ls -la /etc/kubernetes/manifests/

# Запуск только preflight проверок (без инициализации)
kubeadm init phase preflight
```

### 7. Очистка и сброс узла

Если необходимо начать установку заново или удалить кластер:

```bash
# Сброс через kubeadm
sudo kubeadm reset --force

# Ручная очистка (если kubeadm reset не помог)
sudo rm -rf /etc/kubernetes/ /var/lib/etcd/ /var/lib/kubelet/ /var/lib/cni/ /etc/cni/net.d/

# Очистка правил сети
sudo iptables -F && sudo iptables -t nat -F && sudo iptables -t mangle -F && sudo iptables -X

# Удаление виртуальных интерфейсов CNI
sudo ip link delete cni0 2>/dev/null
sudo ip link delete flannel.1 2>/dev/null
sudo ip link delete tunl0 2>/dev/null
sudo ip link delete veth.calico0 2>/dev/null

# Перезапуск containerd
sudo systemctl restart containerd
```

**Внимание**: Этот процесс необратим. Все данные кластера (поды, сервисы, конфигурации) будут удалены.

### 8. Одновременная инициализация через YAML-файл

Для production-сред рекомендуется использовать YAML-конфигурацию:

```bash
# Сохранение конфигурации
cat <<EOF > kubeadm-init.yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: InitConfiguration
localAPIEndpoint:
  advertiseAddress: "192.168.1.10"
  bindPort: 6443
nodeRegistration:
  criSocket: "unix:///run/containerd/containerd.sock"
---
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
kubernetesVersion: "v1.36.0"
controlPlaneEndpoint: "192.168.1.100:7443"
networking:
  podSubnet: "10.244.0.0/16"
  serviceSubnet: "10.96.0.0/12"
  dnsDomain: "cluster.local"
apiServer:
  certSANs:
    - "192.168.1.100"
    - "k8s-api.example.com"
    - "192.168.1.11"
    - "192.168.1.12"
    - "192.168.1.13"
  extraArgs:
    audit-log-path: "/var/log/kubernetes/audit/audit.log"
    audit-log-maxage: "30"
    audit-log-maxbackup: "10"
controllerManager:
  extraArgs:
    terminated-pod-gc-threshold: "100"
scheduler:
  extraArgs:
    profiling: "false"
etcd:
  local:
    dataDir: "/var/lib/etcd"
    extraArgs:
      heartbeat-interval: "500"
      election-timeout: "2500"
EOF

# Инициализация с YAML-конфигурацией
sudo kubeadm init --config kubeadm-init.yaml --upload-certs
```

**Преимущества YAML-подхода:**
- Версионирование конфигурации (Git)
- Воспроизводимость (один и тот же файл на разных узлах)
- Доступ к параметрам, недоступным через флаги (extraArgs, extraVolumes)
- Объединение `InitConfiguration` и `ClusterConfiguration` в одном файле

---

## Дополнительная информация

### Ограничения и особенности kubeadm

- **Версионная совместимость**: `kubeadm` поддерживает установку Kubernetes версии N и N-1 (где N — версия самой утилиты).
- **Один etcd-кластер**: При `kubeadm init` на каждом Control Plane-узле запускается локальный etcd (Stacked-топология). Для внешнего etcd используйте `ClusterConfiguration.etcd.external`.
- **Не управляет CNI**: kubeadm не устанавливает CNI-плагин — это делается вручную после инициализации.
- **Не управляет CRI**: Container Runtime должен быть установлен до запуска `kubeadm init`.
- **Только Linux**: kubeadm не поддерживает Windows и macOS.
- **Поддержка SHA-256**: Discovery-token-ca-cert-hash всегда использует SHA-256.

### Best Practices для инициализации

1. **Используйте YAML вместо флагов** — обеспечивает воспроизводимость и версионирование.
2. **Указывайте `--apiserver-advertise-address`** — явно задайте IP-адрес для доступа других узлов.
3. **Для HA — всегда `--control-plane-endpoint`** — стабильный адрес API через балансировщик.
4. **Храните `admin.conf` безопасно** — файл содержит привилегии `cluster-admin`. Никогда не копируйте его разработчикам.
5. **Проверяйте preflight заранее** — `kubeadm init phase preflight` покажет все проблемы до начала инициализации.
6. **Регулярно проверяйте сертификаты** — `kubeadm certs check-expiration`.
7. **Делайте бэкапы etcd** — перед каждой инициализацией и обновлением.
8. **Включайте Audit Logging** — для отслеживания запросов к API-серверу.

### См. также

- **[Подготовка узлов](./kubeadm_installation_guide.md)** — установка containerd, kubeadm, kubelet.
- **[HA концепции](./ha_concepts.md)** — архитектура отказоустойчивого Control Plane.
- **[Присоединение узлов](../../Installation/HA_Cluster_Bare_Metal/node_joining.md)** — подробное руководство по join.
- **[Управление сертификатами](../../Operations/certificate_management.md)** — ротация и проверка сертификатов.
- **[Обновление кластеров](../../Operations/upgrading_clusters.md)** — бесшовное обновление версий Kubernetes.
- **[Внешний etcd](./external-etcd-setup.md)** — настройка внешнего etcd-кластера для kubeadm.
