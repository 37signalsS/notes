# Присоединение узлов к HA кластеру

## Определения

**kubeadm join** — команда для расширения кластера путём присоединения новых узлов (как мастеров, так и воркеров) к существующей среде.

**Bootstrap Token** — временный секрет, используемый для аутентификации узла при первом подключении к кластеру. По умолчанию имеет срок жизни (TTL) 24 часа.

**Control Plane Endpoint** — стабильная точка входа (VIP или DNS-имя балансировщика), через которую узлы обращаются к API-серверу кластера.

**Discovery Token CA Cert Hash** — SHA-256 хэш публичного ключа CA кластера, используемый узлом для проверки подлинности API-сервера при присоединении. Предотвращает атаку «человек посередине» (MITM). Генерируется автоматически при `kubeadm init`.

**Certificate Key** — AES-CBC ключ для шифрования сертификатов Control Plane при загрузке в Secret `kubeadm-certs` (через `--upload-certs`). Необходим для автоматического присоединения дополнительных мастеров. Действителен 2 часа.

**JoinConfiguration** — YAML-ресурс kubeadm (`kubeadm.k8s.io/v1beta4`), описывающий параметры присоединения узла к кластеру. Является альтернативой командной строке и обеспечивает воспроизводимость конфигурации.

---

## Основные концепции

### Предварительные требования

Перед выполнением `kubeadm join` каждый узел должен быть подготовлен:

1. **Установлены компоненты**: `kubeadm`, `kubelet`, `kubectl` и container runtime (containerd или CRI-O).
2. **Настроено ядро**: загружены модули `overlay` и `br_netfilter`, активирован `net.ipv4.ip_forward=1`.
3. **Отключён Swap**: `swapoff -a` и удаление из `/etc/fstab`.
4. **Открыты сетевые порты**:
   - Control Plane: `6443` (API), `2379-2380` (etcd), `10250` (kubelet)
   - Worker: `10250` (kubelet), `30000-32767` (NodePort)
5. **Доступен API-сервер** через Control Plane Endpoint (VIP/DNS).

Полное руководство по подготовке: [Установка компонентов HA кластера](./k8s_ha_component_installation.md).

### Процесс и механизмы присоединения

Присоединение узлов — это многоэтапный процесс, который выполняется после [инициализации Control Plane](../kubeadm/cluster_initialization.md) первого узла.

1. **Аутентификация**: Узел использует Bootstrap Token для проверки подлинности в API-сервере. Токен передаётся в заголовке `Authorization: Bearer <token>` и валидируется контроллером `bootstrap-signer`.
2. **Проверка сертификатов**: Узел получает CA-сертификат кластера и проверяет его соответствие через хэш (`discovery-token-ca-cert-hash`). Если хэш не совпадает — соединение прерывается.
3. **TLS Bootstrap**: Kubelet генерирует ключ и создаёт Certificate Signing Request (CSR). CSR автоматически одобряется контроллером при наличии валидного Bootstrap Token. Подробнее: [TLS Bootstrapping в kubelet](../../Concepts/kubelet.md).
4. **Конфигурация Kubelet**: `kubeadm` генерирует локальные конфигурационные файлы `/etc/kubernetes/kubelet.conf` и `/var/lib/kubelet/config.yaml`, затем запускает kubelet.
5. **Регистрация**: Узел регистрируется в API-сервере как объект `Node`. При регистрации применяются:
   - **Метки**: `kubernetes.io/hostname`, `kubernetes.io/os`, `kubernetes.io/arch`
   - **Taints**: `node.kubernetes.io/not-ready:NoSchedule` (до получения статуса Ready)
6. **Развёртывание системных компонентов**: На узел автоматически назначаются `kube-proxy` (DaemonSet) и CNI-плагин (DaemonSet) после появления статуса Ready.

**Типы узлов:**
- **Control Plane (Мастера)**: Присоединяются с флагом `--control-plane`. Требуют наличия сертификатов кластера (через `--certificate-key` или копирование вручную). Запускают `kube-apiserver`, `kube-controller-manager`, `kube-scheduler` и `etcd` как Static Pods.
- **Worker (Воркеры)**: Присоединяются без специальных флагов. Выполняют только рабочие нагрузки. Не требуют сертификатов Control Plane.

Подробнее об архитектуре — в [руководстве по инициализации кластера](../kubeadm/cluster_initialization.md).

### Безопасность при присоединении

**Проверка CA-хэша** — критически важный механизм безопасности. Без верификации хэша узел может подключиться к подменённому API-серверу (MITM-атака). Хэш генерируется из публичного ключа CA и гарантирует, что узел общается с легитимным кластером.

```bash
# Генерация хэша CA на мастер-узле
openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | \
  openssl rsa -pubin -outform der 2>/dev/null | \
  openssl dgst -sha256 -hex | sed 's/^.* //'
# → abc123def456...
```

**Ограничение времени действия токенов**: Bootstrap Token по умолчанию действует 24 часа. Для production-сред рекомендуется создавать токены с ограниченным TTL:

```bash
# Создание токена с TTL 1 час
kubeadm token create --ttl 1h --print-join-command
```

**Автоматическая очистка**: Истёкшие токены автоматически удаляются контроллером `tokencleaner` (входит в kube-controller-manager). Токены, загруженные в секреты кластера, удаляются через 1 час после истечения срока действия.

---

## Практические сценарии

### Шаг 7: Присоединение дополнительных мастер-узлов

На **втором и третьем** мастер-узлах выполните команду, полученную при инициализации первого мастера.

**Требования:**
- Балансировщик нагрузки должен быть доступен по адресу `LOAD_BALANCER_VIP:6443`.
- Порты `6443`, `2379-2380` (для etcd), `10250` должны быть открыты.
- Certificate Key должен быть действителен (срок жизни — 2 часа).

```bash
sudo kubeadm join LOAD_BALANCER_VIP:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane \
  --certificate-key <key> \
  --cri-socket=unix:///run/containerd/containerd.sock
```

**Разбор параметров**:
- `--control-plane` — указывает, что узел будет частью управляющего слоя. Без этого флага узел присоединится как worker.
- `--certificate-key` — ключ для расшифровки сертификатов, загруженных в секреты кластера во время `kubeadm init --upload-certs`. Ключ действителен 2 часа.
- `--cri-socket` — путь к сокету среды выполнения контейнеров. Обязателен при наличии нескольких CRI на узле. Для containerd: `unix:///run/containerd/containerd.sock`.

**Результат**:
- Узел добавится в кластер etcd как участник (member).
- Запустятся статические поды `kube-apiserver`, `kube-controller-manager`, `kube-scheduler`, `etcd`.
- На узел будет наложен Taint `node-role.kubernetes.io/control-plane:NoSchedule`.
- Узел получит метку `node-role.kubernetes.io/control-plane=""`.

**Проверка успешного присоединения мастера:**

```bash
# На новом мастере — проверка статических подов
sudo crictl pods --name kube-apiserver
sudo crictl pods --name etcd

# Проверка участников etcd (с любого мастера)
kubectl exec -n kube-system etcd-k8s-m1 -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  member list -w table
```

### Шаг 8: Присоединение worker-узлов

Если Bootstrap Token истёк (прошло >24 часов), сгенерируйте новую команду на любом исправном мастере:

```bash
# Генерация команды присоединения с новым токеном
kubeadm token create --print-join-command
# → kubeadm join 192.168.1.100:6443 --token abc123.xyz789 --discovery-token-ca-cert-hash sha256:abc123...
```

**Выполнение на каждом worker-узле:**

```bash
sudo kubeadm join LOAD_BALANCER_VIP:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --cri-socket=unix:///run/containerd/containerd.sock
```

> **Примечание:** Worker-узлы не требуют доступа к сертификатам через `--certificate-key`, так как не запускают компоненты управляющего слоя.

**Результат**:
- Узел регистрируется в API-сервере как объект `Node`.
- Kubelet получает сертификат через TLS Bootstrap.
- На узел автоматически назначаются `kube-proxy` и CNI-плагин (DaemonSet).
- Узел получает метки: `kubernetes.io/hostname=<hostname>`, `kubernetes.io/os=linux`.

### Шаг 8a: Присоединение worker-узлов через YAML-конфигурацию

Для production-сред рекомендуется использовать YAML-конфигурацию вместо командной строки. Это обеспечивает воспроизводимость и версионирование конфигурации.

**Создайте файл `join-config.yaml` на worker-узле:**

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: JoinConfiguration
discovery:
  bootstrapToken:
    apiServerEndpoint: "192.168.1.100:6443"
    token: "abc123.xyz789"
    caCertHashes:
      - "sha256:abc123def456..."
    unsafeSkipCAVerification: false
nodeRegistration:
  criSocket: "unix:///run/containerd/containerd.sock"
  name: "k8s-w1"
  taints: []
  kubeletExtraArgs:
    - name: "node-ip"
      value: "192.168.1.21"
```

**Разбор ключевых параметров:**
- `discovery.bootstrapToken.apiServerEndpoint` — адрес Control Plane Endpoint.
- `discovery.bootstrapToken.token` — Bootstrap Token для аутентификации.
- `discovery.bootstrapToken.caCertHashes` — список SHA-256 хэшей CA для верификации.
- `discovery.unsafeSkipCAVerification` — при `false` (рекомендуется) узел проверяет CA-хэш.
- `nodeRegistration.name` — имя узла в кластере. По умолчанию используется hostname.
- `nodeRegistration.kubeletExtraArgs` — дополнительные аргументы для kubelet (например, `node-ip` для указания IP).

**Выполнение:**

```bash
sudo kubeadm join --config join-config.yaml
```

### Шаг 9: Мониторинг процесса присоединения

Следите за состоянием узлов с мастер-ноды:

```bash
# Наблюдение в реальном времени
kubectl get nodes -w
```

**Типичный жизненный цикл статуса:**
1. `NotReady` — узел зарегистрирован, но сетевой плагин (CNI) ещё не запущен.
2. `Ready` — Calico/Flannel развёрнут, узел готов принимать нагрузку.

**Ожидаемый вид списка узлов (Kubernetes v1.35.x):**

```text
NAME       STATUS   ROLES           AGE   VERSION
k8s-m1     Ready    control-plane   60m   v1.35.x
k8s-m2     Ready    control-plane   15m   v1.35.x
k8s-m3     Ready    control-plane   14m   v1.35.x
k8s-w1     Ready    <none>          5m    v1.35.x
```

**Мониторинг событий присоединения:**

```bash
# Просмотр событий узла
kubectl get events --field-selector involvedObject.name=k8s-w1 --sort-by='.lastTimestamp'

# Ожидаемые события:
# - RegisteredNode — узел зарегистрирован
# - Starting — запуск kubelet
# - NodeReady — узел готов
```

### Шаг 10: Верификация и детальная проверка

Для глубокого анализа состояния узла используйте:

```bash
# Подробная информация о ресурсах, taints и условиях (Conditions)
kubectl describe node k8s-w1
```

**Критические условия узла (Conditions):**

| Условие | Ожидаемое значение | Описание |
| :--- | :--- | :--- |
| `Ready` | `True` | Узел готов принимать поды |
| `MemoryPressure` | `False` | Нет давления на память |
| `DiskPressure` | `False` | Нет давления на диск |
| `PIDPressure` | `False` | Нет давления на количество процессов |
| `NetworkUnavailable` | `False` | Сеть настроена (CNI работает) |

**Проверка системных компонентов:**

```bash
# Убедитесь, что kube-proxy и CNI запущены на всех узлах
kubectl get pods -n kube-system -o wide | grep -E 'kube-proxy|calico-node'

# Проверка DaemonSet — все экземпляры должны быть Running
kubectl get daemonsets -n kube-system
# → NAME          DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR   AGE
# → calico-node   4         4         4       4            4           kubernetes.io/os=linux   10m
# → kube-proxy    4         4         4       4            4           kubernetes.io/os=linux   10m
```

**Проверка связности etcd (на мастерах):**

```bash
# Проверка кворума и списка участников кластера etcd
sudo kubectl exec -n kube-system etcd-k8s-m1 -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint status --cluster -w table
```

**Проверка сертификатов узла:**

```bash
# На узле — проверка выпущенных сертификатов
ls -la /var/lib/kubelet/pki/
# → kubelet-client-<year>.crt — клиентский сертификат kubelet
# → kubelet.crt — серверный сертификат kubelet

# Проверка срока действия
sudo kubeadm certs check-expiration
```

### Шаг 11: Обработка граничных случаев

#### Узел ранее принадлежал другому кластеру

Если узел ранее был частью другого кластера, необходимо выполнить полную очистку перед присоединением:

```bash
# Полный сброс состояния kubeadm
sudo kubeadm reset -f

# Очистка остаточных файлов
sudo rm -rf /etc/kubernetes/ /var/lib/etcd/ /var/lib/kubelet/ /var/lib/cni/ /etc/cni/net.d/

# Очистка правил сети
sudo iptables -F && sudo iptables -t nat -F && sudo iptables -t mangle -F && sudo iptables -X
sudo ip6tables -F && sudo ip6tables -t nat -F && sudo ip6tables -t mangle -F && sudo ip6tables -X

# Удаление виртуальных интерфейсов CNI
sudo ip link delete cni0 2>/dev/null
sudo ip link delete flannel.1 2>/dev/null
sudo ip link delete tunl0 2>/dev/null
sudo ip link delete vxlan.calico 2>/dev/null

# Перезапуск containerd
sudo systemctl restart containerd
```

#### Автоматическое присоединение через cloud-init

Для массового развёртывания worker-узлов можно использовать cloud-init:

```yaml
#cloud-config
package_update: true
packages:
  - containerd
  - kubelet
  - kubeadm
  - kubectl

runcmd:
  - swapoff -a
  - sed -i '/swap/d' /etc/fstab
  - modprobe overlay
  - modprobe br_netfilter
  - sysctl --system
  - systemctl enable --now containerd
  - systemctl enable --now kubelet
  - kubeadm join 192.168.1.100:6443 --token <token> --discovery-token-ca-cert-hash sha256:<hash>
```

---

## Дополнительная информация

### Углублённая отладка

Если команда `kubeadm join` зависает или завершается ошибкой:

1. **Проверка логов kubelet**:
   ```bash
   sudo journalctl -u kubelet -f --since "5 minutes ago"
   ```
2. **Проверка доступности API через VIP**:
   ```bash
   curl -k https://LOAD_BALANCER_VIP:6443/healthz
   # Должно вернуть: ok
   ```
3. **Проверка логов kubeadm**:
   ```bash
   # kubeadm использует стандартный вывод и stderr
   # Для подробного вывода используйте флаг -v
   sudo kubeadm join ... -v=5
   ```
4. **Проверка CSR (Certificate Signing Request)**:
   ```bash
   # Список ожидающих CSR
   kubectl get csr
   
   # Одобрение CSR вручную (если автоматическое не сработало)
   kubectl certificate approve <csr-name>
   ```
5. **Сброс состояния при неудаче**:
   ```bash
   sudo kubeadm reset -f
   sudo rm -rf /etc/cni/net.d
   sudo iptables -F && sudo iptables -t nat -F && sudo iptables -t mangle -F && sudo iptables -X
   ```

### Управление Bootstrap токенами

| Команда | Описание |
| :--- | :--- |
| `kubeadm token list` | Список активных токенов и их TTL |
| `kubeadm token create --ttl 1h` | Создать временный токен на 1 час |
| `kubeadm token create --print-join-command` | Генерация полной команды join |
| `kubeadm init phase upload-certs --upload-certs` | Повторная загрузка сертификатов для новых мастеров |
| `kubeadm token delete <token>` | Удаление конкретного токена |

**Детальная информация о Bootstrap Tokens**: [Аутентификация в Kubernetes](../../Security/authentication.md).

### Типичные проблемы Bare Metal

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `CA hash mismatch` | Изменился CA сертификат или неверный хэш | Получить актуальный хэш: `openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt \| openssl rsa -pubin -outform der 2>/dev/null \| openssl dgst -sha256 -hex` |
| `ETCD_JOIN_ERROR` | Проблемы сети между мастерами | Проверить порты `2379-2380` и время (drift) между узлами |
| `CRI contact error` | Неверный сокет в конфиге | Явно указать `--cri-socket` или проверить статус `containerd` |
| `certificate key expired` | Прошло >2 часов с момента `kubeadm init` | Выполнить `kubeadm init phase upload-certs --upload-certs` повторно |
| `token expired` | Прошло >24 часов с создания токена | `kubeadm token create --print-join-command` |
| `node already exists` | Узел с таким именем уже в кластере | Удалить старый узел: `kubectl delete node <name>` или использовать другое имя |
| `x509 certificate error` | Сертификат API не содержит SAN для VIP | Добавить VIP в `certSANs` при инициализации |
| `connection refused` | Балансировщик не перенаправляет трафик | Проверить статус HAProxy/Keepalived, порты 6443 на мастерах |

### Best Practices для production

1. **Используйте YAML-конфигурацию** — обеспечивает воспроизводимость и версионирование.
2. **Ограничивайте TTL токенов** — создавайте токены с коротким сроком действия для конкретных задач.
3. **Всегда верифицируйте CA-хэш** — никогда не используйте `--discovery-token-ca-cert-hash` без проверки.
4. **Автоматизируйте присоединение** — используйте Ansible, Terraform или cloud-init для массового развёртывания.
5. **Мониторьте процесс** — отслеживайте события присоединения и статус Conditions узла.
6. **Проверяйте сертификаты** — после присоединения убедитесь, что сертификаты выпущены и действительны.
7. **Ограничивайте доступ к admin.conf** — файл содержит привилегии `cluster-admin`. Не копируйте его на worker-узлы.

### Интеграция с процессом развёртывания

Присоединение узлов — **завершающий этап физического развёртывания** (шаги 7–8). Далее следуют этапы настройки [хранилищ (StorageClass)](../../Storage/storageclass.md) и [Ingress-контроллеров](../../Networking/Ingress/overview.md).

Полный цикл проверки работоспособности описан в [руководстве по верификации](./k8s_ha_cluster_verification.md).

### См. также

- [Инициализация кластера](../kubeadm/cluster_initialization.md) — подготовка Control Plane и генерация команд join.
- [HA концепции](../kubeadm/ha_concepts.md) — архитектура отказоустойчивого Control Plane и управление сертификатами.
- [Управление сертификатами](../../Operations/certificate_management.md) — ротация и проверка сертификатов узлов.
- [Обслуживание узлов](../../Operations/node_maintenance.md) — cordon, drain и безопасное выведение узлов из кластера.
