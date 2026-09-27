# Настройка внешнего etcd для kubeadm

## Определения

**External etcd (Внешний etcd)** — топология развёртывания etcd, при которой распределённое хранилище запускается на отдельной группе выделенных узлов, не являющихся частью Control Plane. Используется для максимальной изоляции ресурсов и производительности в крупных кластерах. В отличие от Stacked-топологии, где etcd работает на тех же узлах, что и API-сервер, External etcd позволяет масштабировать хранилище независимо.

**Stacked etcd (Совмещённая топология)** — стандартный способ для kubeadm, при котором etcd размещается на каждом Control Plane узле как Static Pod. Проще в настройке, но не обеспечивает полной изоляции ресурсов.

**etcd cluster (Кластер etcd)** — группа из нечётного количества узлов etcd (обычно 3 или 5), работающих по алгоритму консенсуса Raft. Обеспечивает отказоустойчивость: кластер продолжает работу при потере `(N-1)/2` узлов.

**Peer certificates (Сертификаты пиров)** — TLS-сертификаты для взаимодействия между узлами etcd (порт 2380). Обеспечивают шифрование и аутентификацию внутри etcd-кластера.

**Client certificates (Клиентские сертификаты)** — TLS-сертификаты для доступа клиентов (kube-apiserver) к etcd (порт 2379). Каждый компонент Control Plane, обращающийся к etcd, должен иметь клиентский сертификат.

---

## Основные концепции

### Зачем использовать внешний etcd

| Преимущество | Описание |
| :--- | :--- |
| **Изоляция ресурсов** | etcd не конкурирует с API-сервером за CPU, RAM и диск |
| **Масштабируемость** | etcd-кластер масштабируется независимо от Control Plane |
| **Производительность** | Выделенные узлы с NVMe SSD обеспечивают низкую задержку `fsync` |
| **Безопасность** | etcd можно разместить в изолированной сети |
| **Обслуживание** | Обновление etcd не влияет на компоненты Control Plane |

### Когда использовать

- **Кластеры > 5000 узлов** — высокая нагрузка на запись
- **Требования к производительности** — etcd требует SSD с задержкой < 10 мс
- **Изоляция безопасности** — etcd хранит все секреты кластера
- **Отдельная команда** — etcd обслуживается инфраструктурной командой

### Когда НЕ использовать

- **Малые кластеры (< 100 узлов)** — Stacked etcd достаточно
- **Ограниченные ресурсы** — требует минимум 3 дополнительных сервера
- **Простота** — Stacked топология проще в настройке и обслуживании

### Топология кластера

```
┌─────────────────────────────────────────────────────────┐
│                   External etcd cluster                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │  etcd-1     │  │  etcd-2     │  │  etcd-3     │     │
│  │  :2379/2380 │  │  :2379/2380 │  │  :2379/2380 │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
└─────────────────────────────────────────────────────────┘
                         │
                         │ TLS (клиентские сертификаты)
                         ▼
┌─────────────────────────────────────────────────────────┐
│                 Kubernetes Control Plane                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │  master-1   │  │  master-2   │  │  master-3   │     │
│  │  API Server │  │  API Server │  │  API Server │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
└─────────────────────────────────────────────────────────┘
```

### Порты etcd

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| **2379** | TCP | Клиентский API (для kube-apiserver и etcdctl) |
| **2380** | TCP | Пир-пир (для взаимодействия между узлами etcd) |

### Требования к узлам etcd

| Ресурс | Минимум | Рекомендуется |
| :--- | :--- | :--- |
| **CPU** | 2 ядра | 4+ ядра |
| **RAM** | 4 ГБ | 8+ ГБ |
| **Disk** | 50 ГБ SSD | 100+ ГБ NVMe SSD |
| **Сеть** | 1 Гбит/с | 10 Гбит/с |
| **Задержка диска** | < 50 мс | < 10 мс (NVMe) |

---

## Практические сценарии

### Шаг 1: Подготовка узлов etcd

На каждом узле etcd выполните базовую настройку:

```bash
# 1. Установка необходимых пакетов
sudo apt update && sudo apt install -y curl wget jq

# 2. Отключение swap
sudo swapoff -a
sudo sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab

# 3. Настройка hostname (уникальный на каждом узле)
sudo hostnamectl set-hostname etcd-1  # etcd-2, etcd-3

# 4. Настройка /etc/hosts (для всех узлов etcd)
cat <<EOF | sudo tee -a /etc/hosts
192.168.1.21   etcd-1
192.168.1.22   etcd-2
192.168.1.23   etcd-3
EOF
```

### Шаг 2: Генерация сертификатов etcd

Создайте CA и сертификаты для etcd-кластера. Выполняется на **одном** узле (мастере kubeadm или отдельном):

```bash
# Создание директории для сертификатов
mkdir -p ~/etcd-certs && cd ~/etcd-certs

# 1. Генерация CA для etcd
cat <<EOF > ca-csr.json
{
  "CN": "etcd-ca",
  "key": {
    "algo": "ecdsa",
    "size": 256
  },
  "names": [
    {
      "O": "etcd",
      "OU": "etcd-cluster"
    }
  ]
}
EOF

# Установка cfssl (если не установлен)
curl -L https://github.com/cloudflare/cfssl/releases/download/v1.6.5/cfssl_1.6.5_linux_amd64 -o /usr/local/bin/cfssl
curl -L https://github.com/cloudflare/cfssl/releases/download/v1.6.5/cfssljson_1.6.5_linux_amd64 -o /usr/local/bin/cfssljson
chmod +x /usr/local/bin/cfssl*

# Генерация CA
cfssl gencert -initca ca-csr.json | cfssljson -bare ca
# → ca.pem, ca-key.pem, ca.csr

# 2. Генерация серверных сертификатов для каждого узла
for i in 1 2 3; do
  cat <<EOF > etcd-${i}-csr.json
{
  "CN": "etcd-${i}",
  "hosts": [
    "etcd-${i}",
    "192.168.1.2${i}",
    "localhost",
    "127.0.0.1"
  ],
  "key": {
    "algo": "ecdsa",
    "size": 256
  },
  "names": [
    {
      "O": "etcd",
      "OU": "etcd-cluster"
    }
  ]
}
EOF
  cfssl gencert -ca=ca.pem -ca-key=ca-key.pem -config=ca-config.json -profile=server etcd-${i}-csr.json | cfssljson -bare etcd-${i}
done

# 3. Генерация peer-сертификатов (для взаимодействия между узлами)
for i in 1 2 3; do
  cat <<EOF > etcd-${i}-peer-csr.json
{
  "CN": "etcd-peer-${i}",
  "hosts": [
    "etcd-${i}",
    "192.168.1.2${i}"
  ],
  "key": {
    "algo": "ecdsa",
    "size": 256
  },
  "names": [
    {
      "O": "etcd",
      "OU": "etcd-cluster"
    }
  ]
}
EOF
  cfssl gencert -ca=ca.pem -ca-key=ca-key.pem -config=ca-config.json -profile=peer etcd-${i}-peer-csr.json | cfssljson -bare etcd-${i}-peer
done

# 4. Генерация клиентского сертификата (для API-сервера)
cat <<EOF > apiserver-etcd-client-csr.json
{
  "CN": "apiserver-etcd-client",
  "hosts": [""],
  "key": {
    "algo": "ecdsa",
    "size": 256
  },
  "names": [
    {
      "O": "system:masters",
      "OU": "kube-system"
    }
  ]
}
EOF
cfssl gencert -ca=ca.pem -ca-key=ca-key.pem -config=ca-config.json -profile=client apiserver-etcd-client-csr.json | cfssljson -bare apiserver-etcd-client
```

### Шаг 3: Распределение сертификатов

Скопируйте сертификаты на соответствующие узлы:

```bash
# На etcd-1
scp ca.pem etcd-1.pem etcd-1-key.pem etcd-1-peer.pem etcd-1-peer-key.pem etcd-1:/etc/etcd/pki/

# На etcd-2
scp ca.pem etcd-2.pem etcd-2-key.pem etcd-2-peer.pem etcd-2-peer-key.pem etcd-2:/etc/etcd/pki/

# На etcd-3
scp ca.pem etcd-3.pem etcd-3-key.pem etcd-3-peer.pem etcd-3-peer-key.pem etcd-3:/etc/etcd/pki/

# На все master-узлы (для API-сервера)
scp ca.pem apiserver-etcd-client.pem apiserver-etcd-client-key.pem master-1:/etc/kubernetes/pki/etcd/
scp ca.pem apiserver-etcd-client.pem apiserver-etcd-client-key.pem master-2:/etc/kubernetes/pki/etcd/
scp ca.pem apiserver-etcd-client.pem apiserver-etcd-client-key.pem master-3:/etc/kubernetes/pki/etcd/
```

### Шаг 4: Установка и конфигурация etcd на узлах

На каждом узле etcd:

```bash
# 1. Скачивание etcd
ETCD_VER=v3.5.15
curl -L https://github.com/etcd-io/etcd/releases/download/${ETCD_VER}/etcd-${ETCD_VER}-linux-amd64.tar.gz -o /tmp/etcd.tar.gz
sudo tar xzf /tmp/etcd.tar.gz -C /usr/local/bin/ --strip-components=1 etcd-${ETCD_VER}-linux-amd64/etcd etcd-${ETCD_VER}-linux-amd64/etcdctl

# 2. Создание пользователя etcd
sudo useradd -r -s /bin/false etcd

# 3. Создание директорий
sudo mkdir -p /etc/etcd /var/lib/etcd
sudo chown etcd:etcd /var/lib/etcd
sudo chmod 700 /var/lib/etcd

# 4. Конфигурация (на etcd-1)
cat <<EOF | sudo tee /etc/etcd/etcd.conf.yml
name: etcd-1
data-dir: /var/lib/etcd

# Peer (взаимодействие между узлами)
listen-peer-urls: https://192.168.1.21:2380
initial-advertise-peer-urls: https://192.168.1.21:2380
initial-cluster: etcd-1=https://192.168.1.21:2380,etcd-2=https://192.168.1.22:2380,etcd-3=https://192.168.1.23:2380
initial-cluster-state: new
initial-cluster-token: etcd-cluster-prod-2026

# Client (доступ для API-сервера)
listen-client-urls: https://192.168.1.21:2379,https://127.0.0.1:2379
advertise-client-urls: https://192.168.1.21:2379

# TLS
peer-trusted-ca-file: /etc/etcd/pki/ca.pem
peer-cert-file: /etc/etcd/pki/etcd-1-peer.pem
peer-key-file: /etc/etcd/pki/etcd-1-peer-key.pem
client-trusted-ca-file: /etc/etcd/pki/ca.pem
client-cert-file: /etc/etcd/pki/etcd-1.pem
client-key-file: /etc/etcd/pki/etcd-1-key.pem

# Производительность
auto-compaction-retention: "5"
quota-backend-bytes: 8589934592  # 8 GB
snapshot-count: 10000
heartbeat-interval: 100
election-timeout: 1000

# Логирование
log-level: info
logger: zap
EOF

# 5. Создание systemd-юнита
cat <<EOF | sudo tee /etc/systemd/system/etcd.service
[Unit]
Description=etcd key-value store
After=network.target

[Service]
Type=notify
User=etcd
Environment=ETCD_CONF=/etc/etcd/etcd.conf.yml
ExecStart=/usr/local/bin/etcd --config-file ${ETCD_CONF}
Restart=always
RestartSec=5s
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

# 6. Запуск
sudo systemctl daemon-reload
sudo systemctl enable etcd
sudo systemctl start etcd
```

**Важно:** На узлах etcd-2 и etcd-3 измените `name`, `listen-peer-urls`, `initial-advertise-peer-urls`, `listen-client-urls`, `advertise-client-urls` и пути к сертификатам соответствующим образом.

### Шаг 5: Проверка кластера etcd

На любом узле etcd:

```bash
# Проверка здоровья кластера
sudo ETCDCTL_API=3 etcdctl endpoint health \
  --endpoints=https://192.168.1.21:2379,https://192.168.1.22:2379,https://192.168.1.23:2379 \
  --cacert=/etc/etcd/pki/ca.pem \
  --cert=/etc/etcd/pki/etcd-1.pem \
  --key=/etc/etcd/pki/etcd-1-key.pem

# Просмотр статуса кластера
sudo ETCDCTL_API=3 etcdctl endpoint status \
  --endpoints=https://192.168.1.21:2379,https://192.168.1.22:2379,https://192.168.1.23:2379 \
  --cacert=/etc/etcd/pki/ca.pem \
  --cert=/etc/etcd/pki/etcd-1.pem \
  --key=/etc/etcd/pki/etcd-1-key.pem \
  --write-out=table

# Просмотр участников
sudo ETCDCTL_API=3 etcdctl member list \
  --endpoints=https://192.168.1.21:2379 \
  --cacert=/etc/etcd/pki/ca.pem \
  --cert=/etc/etcd/pki/etcd-1.pem \
  --key=/etc/etcd/pki/etcd-1-key.pem \
  --write-out=table
```

### Шаг 6: Инициализация kubeadm с внешним etcd

На **первом** master-узле создайте конфигурационный файл:

```yaml
# kubeadm-config.yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
kubernetesVersion: "v1.36.0"
controlPlaneEndpoint: "192.168.1.100:7443"  # VIP или DNS балансировщика
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
etcd:
  external:
    endpoints:
      - https://192.168.1.21:2379
      - https://192.168.1.22:2379
      - https://192.168.1.23:2379
    caFile: /etc/kubernetes/pki/etcd/ca.pem
    certFile: /etc/kubernetes/pki/etcd/apiserver-etcd-client.pem
    keyFile: /etc/kubernetes/pki/etcd/apiserver-etcd-client-key.pem
```

**Важно:** Убедитесь, что клиентский сертификат `apiserver-etcd-client.pem` скопирован в `/etc/kubernetes/pki/etcd/` на **всех** master-узлах.

Запустите инициализацию:

```bash
sudo kubeadm init --config kubeadm-config.yaml --upload-certs
```

### Шаг 7: Присоединение дополнительных master-узлов

На каждом дополнительном master-узле:

```bash
# Убедитесь, что клиентский сертификат etcd скопирован
ls -la /etc/kubernetes/pki/etcd/
# → ca.pem, apiserver-etcd-client.pem, apiserver-etcd-client-key.pem

# Присоединение (токен и ключ будут выведены после init)
sudo kubeadm join 192.168.1.100:7443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash> \
  --control-plane \
  --certificate-key <certificate-key>
```

### Шаг 8: Проверка работоспособности

```bash
# Статус узлов
kubectl get nodes -o wide

# Поды в kube-system (не должно быть etcd подов!)
kubectl get pods -n kube-system -o wide

# Проверка etcd через API-сервер
kubectl exec -n kube-system etcd-master-1 -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  endpoint health
```

---

## Дополнительная информация

### Отказоустойчивость

- **Кворум:** 3 узла переживают отказ 1, 5 узлов — отказ 2.
- **Split-brain:** При сетевом разделении кворум предотвращает разделение данных.
- **Восстановление:** Используйте `etcdctl snapshot restore` при потере узла.

### Мониторинг

- **Метрики:** `etcd_server_has_leader`, `etcd_disk_wal_fsync_duration_seconds`, `etcd_network_peer_round_trip_time_seconds`.
- **Алерты:** Потеря лидера, высокий latency, недостаточно свободного места.

### Бэкапы

- **Автоматические:** CronJob с `etcdctl snapshot save` каждые 2-6 часов.
- **Хранение:** На внешнем носителе (NAS, S3-совместимое хранилище).
- **Проверка:** Регулярно тестируйте восстановление из снапшотов.

### Обновление etcd

- **Версионная совместимость:** Проверяйте [ compatibility matrix](https://github.com/etcd-io/etcd/blob/main/Documentation/upgrades/upgrade_3_5.md).
- **Порядок:** Обновляйте по одному узлу, проверяя кворум после каждого.

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `failed to dial peer` | TLS-сертификаты не совпадают | Проверьте `peer-cert-file` и `peer-trusted-ca-file` |
| `no leader` | Все узлы etcd недоступны или loss of quorum | Проверьте сеть и доступность узлов |
| `etcd cluster ID mismatch` | Разные `initial-cluster-token` | Переустановите кластер с одинаковым токеном |
| `wal file mismatch` | Повреждение WAL-файлов | Восстановите из снапшота |

### См. также

- **[etcd: конфигурация и развёртывание](../../../etcd/configuration_and_deployment.md)** — детали по настройке etcd.
- **[Кластеризация и восстановление](../../../etcd/clustering_and_recovery.md)** — управление кластером etcd.
- **[Концепции HA](./ha_concepts.md)** — сравнение Stacked vs External топологий.
- **[Управление сертификатами](../../Operations/certificate_management.md)** — ротация сертификатов.