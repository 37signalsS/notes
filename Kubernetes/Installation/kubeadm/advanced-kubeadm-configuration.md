# Продвинутая конфигурация kubeadm

## Определения

**InitConfiguration** — тип конфигурации kubeadm, настраивающий поведение самой утилиты при инициализации кластера: адрес API-сервера, CRI-сокет, регистрация узла, Taints. Не влияет на параметры компонентов Kubernetes.

**ClusterConfiguration** — тип конфигурации, определяющий параметры самого кластера: версия Kubernetes, сеть (pod/service CIDR), etcd, API-сервер, контроллеры, планировщик. Используется для настройки Control Plane компонентов.

**JoinConfiguration** — тип конфигурации для присоединения новых узлов: discovery tokens, Control Plane параметры (для мастеров), CRI-сокет. Определяет, как узел будет интегрирован в кластер.

**kubeadm config (YAML)** — декларативный формат конфигурации, обеспечивающий воспроизводимость и версионирование. Позволяет настраивать параметры, недоступные через флаги командной строки.

**Feature Gates** — экспериментальные функции Kubernetes, включаемые/выключаемые через специальные флаги. В kubeadm настраиваются через `featureGates` в конфигурации.

**Extra Args** — дополнительные аргументы командной строки, передаваемые компонентам Control Plane (kube-apiserver, kube-controller-manager, kube-scheduler). Позволяют тонко настраивать поведение.

**Extra Volumes** — дополнительные тома, монтируемые в контейнеры компонентов Control Plane. Используются для внешних сертификатов, конфигурационных файлов или логов.

---

## Основные концепции

### Структура конфигурационного файла

kubeadm поддерживает объединение нескольких типов конфигураций в одном YAML-файле через разделитель `---`:

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: InitConfiguration
---
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
---
apiVersion: kubeadm.k8s.io/v1beta4
kind: JoinConfiguration
```

### Приоритет параметров

1. **Флаги командной строки** — highest priority
2. **Конфигурационный файл** (--config)
3. **Значения по умолчанию**

### Версионирование API

| Версия API | Поддерживаемые версии Kubernetes |
| :--- | :--- |
| `kubeadm.k8s.io/v1beta3` | 1.22 - 1.26 |
| `kubeadm.k8s.io/v1beta4` | 1.27+ (рекомендуется) |

---

## Практические сценарии

### 1. Полная конфигурация InitConfiguration

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: InitConfiguration
# Параметры local API endpoint
localAPIEndpoint:
  advertiseAddress: "192.168.1.10"  # IP для доступа других узлов к API
  bindPort: 6443
# Регистрация узла
nodeRegistration:
  criSocket: "unix:///run/containerd/containerd.sock"
  imagePullPolicy: IfNotPresent
  # Дополнительные SAN для сертификата узла (редко)
  taints:
    - key: "node-role.kubernetes.io/control-plane"
      effect: "NoSchedule"
  # К Variant: kubelet extra args
  kubeletExtraArgs:
    - name: "node-labels"
      value: "node-role.kubernetes.io/master="
  # К Variant: CRISocket (deprecated, используйте criSocket)
  # crISocket: ""
# Bootstrap токены (генерируются автоматически, но можно настроить)
bootstrapTokens:
  - groups:
      - "system:bootstrappers:kubeadm:default-node-token"
    token: "abc123.xyz789"  # Оставьте пустым для автоматической генерации
    ttl: "24h0m0s"
    usages:
      - "signing"
      - "authentication"
# Настройка CRI (если требуется)
# cRIRuntimeSocket: ""
```

### 2. Полная конфигурация ClusterConfiguration

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
# Версия Kubernetes
kubernetesVersion: "v1.36.0"
# Control Plane Endpoint (VIP или DNS балансировщика)
controlPlaneEndpoint: "192.168.1.100:7443"
# Имя кластера (для kubeconfig)
clusterName: "production-cluster"
# Сетевая конфигурация
networking:
  podSubnet: "10.244.0.0/16"  # Зависит от CNI (Calico: 192.168.0.0/16, Flannel: 10.244.0.0/16)
  serviceSubnet: "10.96.0.0/12"
  dnsDomain: "cluster.local"
# ДополнительныеSAN для API-сервера
apiServer:
  certSANs:
    - "192.168.1.100"      # VIP
    - "k8s-api.example.com" # DNS VIP
    - "192.168.1.11"       # IP master1
    - "192.168.1.12"       # IP master2
    - "192.168.1.13"       # IP master3
    - "127.0.0.1"          # Localhost
  # Дополнительные volumes для API-сервера
  extraVolumes:
    - name: "audit-log"
      hostPath: "/var/log/kubernetes/audit"
      mountPath: "/var/log/kubernetes/audit"
      readOnly: false
      pathType: "DirectoryOrCreate"
    - name: "ssh-keys"
      hostPath: "/root/.ssh"
      mountPath: "/root/.ssh"
      readOnly: true
      pathType: "Directory"
  # Дополнительные аргументы (extraArgs)
  extraArgs:
    audit-log-path: "/var/log/kubernetes/audit/audit.log"
    audit-log-maxage: "30"
    audit-log-maxbackup: "10"
    audit-log-maxsize: "100"
    audit-policy-file: "/etc/kubernetes/audit/audit-policy.yaml"
    enable-admission-plugins: "NodeRestriction,PodSecurity,AlwaysPullImages"
    disable-admission-plugins: ""
    encryption-provider-config: "/etc/kubernetes/encryption-config.yaml"
    service-account-lookup: "true"
    tls-min-version: "VersionTLS12"
    tls-cipher-suites: "TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256,TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384"
    # Дляubbleе allows log all requests
    v: "2"
# Конфигурация контроллера
controllerManager:
  extraArgs:
    terminated-pod-gc-threshold: "100"
    node-monitor-period: "5s"
    node-monitor-grace-period: "40s"
    pod-eviction-timeout: "5m0s"
    profile: "false"  # Отключение profiling для безопасности
    bind-address: "0.0.0.0"
  extraVolumes:
    - name: "kubeconfig"
      hostPath: "/etc/kubernetes/controller-manager.conf"
      mountPath: "/etc/kubernetes/controller-manager.conf"
      readOnly: true
      pathType: "File"
# Конфигурация планировщика
scheduler:
  extraArgs:
    profiling: "false"
    bind-address: "0.0.0.0"
  extraVolumes:
    - name: "kubeconfig"
      hostPath: "/etc/kubernetes/scheduler.conf"
      mountPath: "/etc/kubernetes/scheduler.conf"
      readOnly: true
      pathType: "File"
# Конфигурация etcd (локальная или внешняя)
etcd:
  # Вариант 1: Локальный etcd (stacked)
  local:
    dataDir: "/var/lib/etcd"
    extraArgs:
      heartbeat-interval: "500"
      election-timeout: "2500"
      quota-backend-bytes: "8589934592"  # 8 GB
      auto-compaction-retention: "5"
      snapshot-count: "10000"
  # Вариант 2: Внешний etcd
  # external:
  #   endpoints:
  #     - https://etcd-1:2379
  #     - https://etcd-2:2379
  #     - https://etcd-3:2379
  #   caFile: "/etc/kubernetes/pki/etcd/ca.crt"
  #   certFile: "/etc/kubernetes/pki/etcd/apiserver-etcd-client.crt"
  #   keyFile: "/etc/kubernetes/pki/etcd/apiserver-etcd-client.key"
# Центр сертификации (CA)
certificatesDir: "/etc/kubernetes/pki"
# Директория для манифестов статических подов
imageRepository: "registry.k8s.io"  # Зеркало: registry.aliyuncs.com/google_containers
# DNS (CoreDNS)
dns:
  imageRepository: "registry.k8s.io/coredns"
  imageTag: "v1.12.0"
# Контроллеры для управления подами (kubeadm)
# controllerManager: {}  # Уже определено выше
# Feature Gates
featureGates:
  - "ServerSideApply=true"
  - "RotateKubeletServerCertificate=true"
  # - "CustomResourceValidationExpressions=true"  # Experimental
# Адреса API-сервера (для HA)
# apiServer: {}  # Уже определено выше
```

### 3. Конфигурация JoinConfiguration (для Worker)

```yaml
apiVersion: kubeadm.k8s.io/v1beta4
kind: JoinConfiguration
# Discovery (как узел найдет API-сервер)
discovery:
  bootstrapToken:
    apiServerEndpoint: "192.168.1.100:7443"
    token: "abc123.xyz789"
    caCertHashes:
      - "sha256:abc123def456..."  # Хэш CA сертификата
    unsafeSkipCAVerification: false  # НЕ используйте true в production!
  # Вариант 2: TLS Bootstrap (для автоматического обновления сертификатов)
  # tlsBootstrap:
  #   token: "abc123.xyz789"
# CRI Socket
nodeRegistration:
  criSocket: "unix:///run/containerd/containerd.sock"
  # kubelet extra args
  kubeletExtraArgs:
    - name: "node-labels"
      value: "node-role.kubernetes.io/worker="
# Control Plane (не указывать для worker-узлов)
# controlPlane: {}
```

### 4. Конфигурация JoinConfiguration (для Control Plane)

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
    advertiseAddress: "192.168.1.12"  # IP этого мастера
    bindPort: 6443
  certificateKey: "abcd1234..."  # Ключ для расшифровки сертификатов из Secret
  # Дополнительные SAN для этого мастера
  # apiEndpoint: {}  # Уже определено выше
nodeRegistration:
  criSocket: "unix:///run/containerd/containerd.sock"
```

### 5. Примеры Extra Args для типичных сценариев

#### Безопасность

```yaml
apiServer:
  extraArgs:
    # Ограничение TLS
    tls-min-version: "VersionTLS12"
    tls-cipher-suites: "TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256,TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384"
    # Аудит
    audit-log-path: "/var/log/kubernetes/audit/audit.log"
    audit-log-maxage: "30"
    audit-log-maxbackup: "10"
    audit-log-maxsize: "100"
    audit-policy-file: "/etc/kubernetes/audit/audit-policy.yaml"
    # Аутентификация
    service-account-lookup: "true"
    # Admission Controllers
    enable-admission-plugins: "NodeRestriction,PodSecurity,AlwaysPullImages,ServiceAccount"
    disable-admission-plugins: ""
```

#### Производительность

```yaml
apiServer:
  extraArgs:
    # Кэширование
    watch-cache: "true"
    max-requests-inflight: "400"
    max-mutating-requests-inflight: "200"
    # Timeout
    request-timeout: "300s"
    # Profiling (отключить в production)
    profiling: "false"
controllerManager:
  extraArgs:
    # Garbage Collection
    terminated-pod-gc-threshold: "100"
    # Конкурентность
    concurrent-deployment-syncs: "5"
    concurrent-replicaset-syncs: "10"
    concurrent-namespace-syncs: "10"
    # Taints
    # disable-attach-detachers: "true"  # Deprecated
```

#### Мониторинг

```yaml
apiServer:
  extraArgs:
    # Метрики
    enable-metrics: "true"
    # Profiling (для pprof)
    profiling: "true"  # Только в development!
    bind-address: "0.0.0.0"  # Для доступа к метрикам
```

### 6. Использование kubeadm config

```bash
# Экспорт текущей конфигурации кластера
sudo kubeadm config view > current-config.yaml

# Просмотр конфигурации по умолчанию
sudo kubeadm config print init-defaults

# Миграция конфигурации на новую версию API
sudo kubeadm config migrate --old-config old-config.yaml --new-config new-config.yaml

# Валидация конфигурации
sudo kubeadm init --config config.yaml --dry-run=client

# Генерация конфигурации дляjoin
sudo kubeadm token create --print-join-command
```

### 7. Конфигурация для разных CNI

#### Calico

```yaml
networking:
  podSubnet: "192.168.0.0/16"  # Calico по умолчанию
  serviceSubnet: "10.96.0.0/12"
```

#### Cilium

```yaml
networking:
  podSubnet: "10.0.0.0/8"  # Cilium рекомендует большой CIDR
  serviceSubnet: "10.96.0.0/12"
```

#### Flannel

```yaml
networking:
  podSubnet: "10.244.0.0/16"  # Flannel по умолчанию
  serviceSubnet: "10.96.0.0/12"
```

### 8. ДополнительныеVolumes для сертификатов

```yaml
apiServer:
  extraVolumes:
    - name: "external-ca"
      hostPath: "/etc/ssl/certs/external-ca.pem"
      mountPath: "/etc/ssl/certs/external-ca.pem"
      readOnly: true
      pathType: "File"
    - name: "webhook-config"
      hostPath: "/etc/kubernetes/webhook/config.yaml"
      mountPath: "/etc/kubernetes/webhook/config.yaml"
      readOnly: true
      pathType: "File"
```

### 9. Feature Gates

```yaml
featureGates:
  # Стабильные
  - "ServerSideApply=true"
  - "RotateKubeletServerCertificate=true"
  - "CriticalPodAddons=true"
  # Experimental (использовать с осторожностью)
  # - "EphemeralContainers=true"
  # - "PodSecurity=true"
  # - "CSIStorageCapacity=true"
```

### 10. Конфигурация DNS

```yaml
dns:
  imageRepository: "registry.k8s.io/coredns"
  imageTag: "v1.12.0"
  # Дополнительные параметры (через extraArgs у CoreDNS deployment)
  # Настройка CoreDNS через ConfigMap (после установки):
  # kubectl -n kube-system edit configmap coredns
```

---

## Дополнительная информация

### Лучшие практики

1. **Всегда используйте YAML** — обеспечивает воспроизводимость и версионирование.
2. **Включайте `--upload-certs`** для HA — упрощает присоединение мастеров.
3. **Указывайте `--apiserver-advertise-address`** — явно задайте IP.
4. **Настройте `certSANs`** — включите все адреса, по которым будет доступен API.
5. **Используйте Feature Gates** только для действительно необходимых функций.
6. **Тестируйте конфигурацию** — `--dry-run=client` перед реальной инициализацией.
7. **Версионируйте конфиги** — храните в Git для отслеживания изменений.

### Безопасность

- **Extra Args:** Не добавляйте незнакомые флаги без проверки документации.
- **Extra Volumes:** Монтируйте только необходимые тома с минимальными правами.
- **TLS:** Всегда настраивайте `tls-min-version` и `tls-cipher-suites`.
- **Audit:** Включайте аудит для отслеживания запросов к API.

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `unknown field "xxx"` | Опечатка в имени поля или старая версия API | Проверьте `kubeadm config migrate` |
| `unable to decode config` | Невалидный YAML | Используйте `yamllint` для проверки |
| `flag provided but not defined` | ExtraArgs с неверным именем | Проверьте документацию компонента |
| `certificate key invalid` | Неверный `certificate-key` | Сгенерируйте новый: `kubeadm init phase upload-certs` |

### См. также

- **[Инициализация кластера](./cluster_initialization.md)** — использование конфигурации на практике.
- **[Подготовка узлов](./kubeadm_installation_guide.md)** — установка пакетов перед инициализацией.
- **[Концепции HA](./ha_concepts.md)** — настройка Control Plane Endpoint.
- **[Обновление кластеров](../../Operations/upgrading_clusters.md)** — миграция конфигурации при обновлении.