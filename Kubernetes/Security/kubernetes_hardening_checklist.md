# Чеклист харденинга Kubernetes кластера

## Определения

**CIS Kubernetes Benchmark** — стандартизированный чеклист безопасности от Center for Internet Security, содержащий рекомендации по настройке всех компонентов Kubernetes (API Server, etcd, kubelet, Control Plane, Policies). Актуальная версия — CIS 1.9/1.10 (2025).

**kube-bench** — инструмент автоматической проверки соответствия CIS Kubernetes Benchmark. Запускается как Job/Pod в кластере, проверяет конфигурацию и выдает отчет в формате text/JSON/JUnit.

**Hardening** — процесс ужесточения настроек системы безопасности по сравнению с настройками по умолчанию. В Kubernetes включает: отключение ненужных компонентов, ограничение привилегий, шифрование, аудит.

**Defense in Depth** — стратегия многоуровневой защиты, при которой компрометация одного уровня не приводит к полной потере контроля.

---

## Основные концепции

### Уровни харденинга

| Уровень | Компонент | Приоритет |
|:---|:---|:---|
| **Control Plane** | API Server, etcd, Controller Manager, Scheduler | Критический |
| **Node** | kubelet, container runtime, ОС | Критический |
| **Network** | CNI, NetworkPolicy, DNS | Высокий |
| **Workload** | Pod Security, RBAC, Admission Controllers | Высокий |
| **Supply Chain** | Образы, SBOM, Signatures | Средний |

### Порядок действий

```
1. Control Plane Hardening
   ├── API Server флаги безопасности
   ├── etcd шифрование и RBAC
   ├── Audit Logging
   └── Admission Controllers

2. Node Hardening
   ├── kubelet аутентификация/авторизация
   ├── Container Runtime (seccomp, AppArmor)
   ├── OS Hardening (firewall, sysctl)
   └── CIS Level 1/2

3. Network Hardening
   ├── Default-deny NetworkPolicy
   ├── DNS изоляция
   ├── API Server сетевая изоляция
   └── CNI security policies

4. Workload Hardening
   ├── Pod Security Admission (restricted)
   ├── RBAC least privilege
   ├── Image scanning
   └── Secret management

5. Monitoring & Audit
   ├── Audit Log → Loki/SIEM
   ├── Falco / Tetragon
   ├── Prometheus алерты
   └── kube-bench CronJob
```

---

## Практические сценарии

### 1. API Server Hardening

```yaml
# /etc/kubernetes/manifests/kube-apiserver.yaml
apiVersion: v1
kind: Pod
metadata:
  name: kube-apiserver
  namespace: kube-system
spec:
  containers:
    - name: kube-apiserver
      command:
        - kube-apiserver

        # === Аутентификация ===
        - --anonymous-auth=false                    # отключить анонимный доступ
        - --authorization-mode=Node,RBAC            # Node + RBAC авторизация
        - --enable-admission-plugins=NodeRestriction,PodSecurity,AlwaysPullImages
        - --disable-admission-plugins=               # отключить ненужные
        - --service-account-lookup=true              # проверять существование SA

        # === Шифрование ===
        - --encryption-provider-config=/etc/kubernetes/encryption-config.yaml
        - --tls-cert-file=/etc/kubernetes/pki/apiserver.crt
        - --tls-private-key-file=/etc/kubernetes/pki/apiserver.key
        - --client-cert-auth=true                   # mTLS для etcd
        - --etcd-cafile=/etc/kubernetes/pki/etcd/ca.crt
        - --etcd-certfile=/etc/kubernetes/pki/apiserver-etcd-client.crt
        - --etcd-keyfile=/etc/kubernetes/pki/apiserver-etcd-client.key

        # === Аудит ===
        - --audit-log-path=/var/log/kubernetes/audit.log
        - --audit-log-maxage=30
        - --audit-log-maxbackup=10
        - --audit-log-maxsize=100
        - --audit-policy-file=/etc/kubernetes/audit-policy.yaml

        # === Ограничения ===
        - --request-timeout=300s                    # таймаут запросов
        - --event-ttl=1h                            # TTL событий
        - --service-account-key-file=/etc/kubernetes/pki/sa.pub
        - --service-account-issuer=https://kubernetes.default.svc
        - --service-account-signing-key-file=/etc/kubernetes/pki/sa.key

        # === Безопасность ===
        - --tls-min-version=VersionTLS12            # минимальная версия TLS
        - --tls-cipher-suites=TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256,TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384
        - --insecure-port=0                         # отключить незащищенный порт
```

### 2. etcd Hardening

```yaml
# /etc/kubernetes/manifests/etcd.yaml
apiVersion: v1
kind: Pod
metadata:
  name: etcd
  namespace: kube-system
spec:
  containers:
    - name: etcd
      command:
        - etcd

        # === TLS ===
        - --client-cert-auth=true                   # требовать клиентский сертификат
        - --trusted-ca-file=/etc/kubernetes/pki/etcd/ca.crt
        - --cert-file=/etc/kubernetes/pki/etcd/server.crt
        - --key-file=/etc/kubernetes/pki/etcd/server.key
        - --peer-client-cert-auth=true              # mTLS для peers
        - --peer-trusted-ca-file=/etc/kubernetes/pki/etcd/ca.crt
        - --peer-cert-file=/etc/kubernetes/pki/etcd/peer.crt
        - --peer-key-file=/etc/kubernetes/pki/etcd/peer.key

        # === Лимиты ===
        - --quota-backend-bytes=8589934592          # 8 GiB (макс 8 GiB)
        - --auto-compaction-mode=periodic           # авто-компакция
        - --auto-compaction-retention=8h

        # === Безопасность ===
        - --cipher-suites=TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256,TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384
```

**EncryptionConfiguration (at rest):**
```yaml
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources: [secrets, configmaps]
    providers:
      - aescbc:
          keys:
            - name: key1
              secret: <base64-encoded-32-byte-key>
      - identity: {}    # fallback для нешифрованных данных
```

### 3. kubelet Hardening

```yaml
# /var/lib/kubelet/config.yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
authentication:
  x509:
    clientCAFile: /etc/kubernetes/pki/ca.crt
  webhook:
    enabled: true
    cacheTTL: 2m0s
  anonymous:
    enabled: false              # отключить анонимный доступ

authorization:
  mode: Webhook                # авторизация через API Server

tlsCertFile: /var/lib/kubelet/pki/kubelet-client-current.pem
tlsPrivateKeyFile: /var/lib/kubelet/pki/kubelet-client-current.pem
serverTLSBootstrap: true       # автоматический запрос сертификата

readOnlyPort: 0                # отключить read-only порт (10255)
protectKernelDefaults: true    # защита kernel параметров
makeIptablesUtilChains: true   # автоматические iptables правила
eventRecordQPS: 5              # лимит событий
```

### 4. Pod Security Admission (restricted)

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    # Enforce: блокирует нарушения
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    # Audit: логирует нарушения
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/audit-version: latest
    # Warn: предупреждает при kubectl apply
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/warn-version: latest
```

**Требования restricted-profile:**
- `runAsNonRoot: true`
- `seccompProfile.type: RuntimeDefault` или `Localhost`
- `allowPrivilegeEscalation: false`
- `capabilities.drop: ["ALL"]`
- `fsGroup` или `supplementalGroups` заданы
- Volume типы: configMap, csi, downwardAPI, emptyDir, persistentVolumeClaim, projected, secret

### 5. Default-deny NetworkPolicy

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: monitoring
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
---
# Разрешить DNS
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: monitoring
spec:
  podSelector: {}
  policyTypes:
    - Egress
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

### 6. CIS Benchmark с kube-bench

```yaml
# Job для проверки
apiVersion: batch/v1
kind: Job
metadata:
  name: kube-bench
spec:
  template:
    spec:
      hostPID: true
      containers:
        - name: kube-bench
          image: aquasec/kube-bench:latest
          command: ["kube-bench", "run", "--targets", "all", "--json"]
          volumeMounts:
            - name: var-lib-kubelet
              mountPath: /var/lib/kubelet
              readOnly: true
            - name: etc-kubernetes
              mountPath: /etc/kubernetes
              readOnly: true
      volumes:
        - name: var-lib-kubelet
          hostPath:
            path: /var/lib/kubelet
        - name: etc-kubernetes
          hostPath:
            path: /etc/kubernetes
      restartPolicy: Never
```

**CronJob (еженедельно):**
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: kube-bench-weekly
spec:
  schedule: "0 2 * * 0"
  jobTemplate:
    spec:
      template:
        spec:
          hostPID: true
          containers:
            - name: kube-bench
              image: aquasec/kube-bench:latest
              command: ["kube-bench", "run", "--targets", "all", "--json", "--outputfile", "/tmp/results.json"]
              volumeMounts:
                - name: var-lib-kubelet
                  mountPath: /var/lib/kubelet
                  readOnly: true
                - name: etc-kubernetes
                  mountPath: /etc/kubernetes
                  readOnly: true
                - name: results
                  mountPath: /tmp
          volumes:
            - name: var-lib-kubelet
              hostPath:
                path: /var/lib/kubelet
            - name: etc-kubernetes
              hostPath:
                path: /etc/kubernetes
            - name: results
              emptyDir: {}
          restartPolicy: Never
```

---

## Дополнительная информация

### CIS Benchmark — ключевые проверки

| Раздел | Проверка | Описание |
|:---|:---|:---|
| **1.1** | `--anonymous-auth=false` | Анонимный доступ отключен |
| **1.2** | `--authorization-mode=Node,RBAC` | Авторизация через Node + RBAC |
| **1.3** | `--kubelet-client-certificate` | mTLS для kubelet |
| **1.4** | `--kubelet-client-key` | Ключ клиента kubelet |
| **1.5** | `--service-account-lookup=true` | Проверка существования SA |
| **1.6** | `--service-account-key-file` | Ключ для проверки SA |
| **1.10** | `--audit-log-path` | Путь к audit log |
| **1.11** | `--audit-log-maxage` | Максимальный возраст логов |
| **1.12** | `--audit-log-maxbackup` | Максимальное количество бэкапов |
| **1.13** | `--audit-policy-file` | Файл аудит-политики |
| **1.14** | `--encryption-provider-config` | Шифрование at rest |
| **1.15** | `--tls-min-version` | Минимальная версия TLS |
| **1.16** | `--tls-cipher-suites` | Шифровальные наборы |
| **2.1** | `--client-cert-auth=true` | mTLS для etcd |
| **2.2** | `--peer-client-cert-auth=true` | mTLS для etcd peers |
| **2.6** | `--auto-compaction-retention` | Автоматическая компакция |
| **2.7** | `--quota-backend-bytes` | Лимит хранилища etcd |
| **4.1** | `--anonymous-auth=false` (kubelet) | Анонимный доступ kubelet |
| **4.2** | `--authorization-mode=Webhook` | Авторизация kubelet |
| **4.3** | `--read-only-port=0` | Отключение read-only порта |
| **4.6** | `--protect-kernel-defaults=true` | Защита kernel параметров |

### Автоматическая ремедиация

```yaml
# Ansible playbook для автоматического исправления CIS-нарушений
- name: Kubernetes CIS Hardening
  hosts: k8s_nodes
  become: true
  tasks:
    - name: Disable anonymous auth for kubelet
      lineinfile:
        path: /var/lib/kubelet/config.yaml
        regexp: 'anonymous:'
        line: '  anonymous:'
      notify: restart kubelet

    - name: Set kubelet authorization mode
      lineinfile:
        path: /var/lib/kubelet/config.yaml
        regexp: 'mode:'
        line: '  mode: Webhook'
      notify: restart kubelet

    - name: Disable kubelet read-only port
      lineinfile:
        path: /var/lib/kubelet/config.yaml
        regexp: 'readOnlyPort:'
        line: 'readOnlyPort: 0'
      notify: restart kubelet

    - name: Enable audit logging
      lineinfile:
        path: /etc/kubernetes/manifests/kube-apiserver.yaml
        insertafter: '--etcd-keyfile.*'
        line: '--audit-log-path=/var/log/kubernetes/audit.log'
      notify: restart kubelet

  handlers:
    - name: restart kubelet
      systemd:
        name: kubelet
        state: restarted
```

### Частые ошибки на собеседованиях

1. **"CIS Benchmark и kube-bench — одно и то же"** — CIS Benchmark — это стандарт (документ), kube-bench — инструмент для его проверки.
2. **"После применения CIS-рекомендаций всё сломается"** — Нет. CIS предлагает Level 1 (рекомендуется) и Level 2 (строго). Начните с Level 1.
3. **"Pod Security Admission заменяет PodSecurityPolicy"** — Да, PSP удалена в 1.25. PSA — его нативная замена.
4. **"kube-bench проверяет только Control Plane"** — Нет. Он проверяет Control Plane, Node (kubelet), Policies, Control Plane Components и etcd.
5. **"Encryption at rest шифрует только Secrets"** — По умолчанию — да. Можно добавить configmaps и другие ресурсы в `EncryptionConfiguration`.
