# Безопасность Kubelet в Kubernetes

## Определения

**Kubelet** — агент, работающий на каждом узле кластера, отвечающий за запуск подов, управление контейнерами (через CRI) и поддержание desired state, объявленного в PodSpec. Kubelet предоставляет REST API на порту 10250, доступ к которому является критической поверхностью атаки.

**NodeRestriction** — валидирующий admission controller, ограничивающий kubelet возможностью изменять только объекты (Pod, Node, Secret, ConfigMap, PersistentVolumeClaim, Endpoint), принадлежащие его узлу. Предотвращает lateral movement через kubelet API.

**TLS Bootstrapping** — механизм автоматического получения kubelet'ом клиентского и серверного TLS-сертификатов через Bootstrap Token и CSR (Certificate Signing Request) workflow. Реализуется через `--bootstrap-kubeconfig` и `--kubeconfig`.

**Node Authorizer** — модуль авторизации в API-сервере, специализированный для kubelet. Разрешает kubelet'у доступ только к ресурсам на его узле (Pod, Service, Endpoint, Node, Secret, ConfigMap, PersistentVolumeClaim), связанным с его именем узла.

**Server TLS Bootstrap** — механизм автоматического получения и ротации серверного сертификата kubelet для порта 10250. Активируется через `serverTLSBootstrap: true` в KubeletConfiguration. Сертификат хранится в `/var/lib/kubelet/pki/kubelet-server-current.pem`.

---

## Основные концепции

### Порты и протоколы Kubelet

| Порт | Протокол | Назначение | Доступ |
|:---|:---|:---|:---|
| **10250** | HTTPS | Kubelet API (exec, logs, port-forward, run) | Требует X.509 аутентификации |
| **10255** | HTTP | Read-only API (deprecated, в K8s 1.31+) | Открыт (убедитесь, что отключен) |
| **10248** | HTTP | Healthz (health check) | Только loopback |

**Важно:** Порт 10255 (read-only) является критической уязвимостью. Он позволяет читать данные о подах, секретах и конфигурациях без аутентификации. В production必須 отключен через `--read-only-port=0`.

### Цепочка обработки запроса к Kubelet API

```
Клиент (kubectl exec / curl)
        │
        ▼
   Kubelet API (:10250 HTTPS)
        │
        ├── 1. TLS Handshake (проверка клиенского сертификата)
        │
        ├── 2. Аутентификация (Authentication)
        │   ├── X.509 Client Certificate (CN = system:node:<node-name>, O = system:nodes)
        │   ├── Webhook Token (TokenReview)
        │   └── Anonymous (если включен — ОПАСНО)
        │
        ├── 3. Авторизация (Authorization)
        │   ├── Node Authorizer (проверка принадлежности ресурсов узлу)
        │   ├── RBAC Webhook (NodeRestriction admission controller)
        │   └── AlwaysAllow (режим по умолчанию — ОПАСНО)
        │
        └── 4. Выполнение запроса
            ├── exec (запуск команд в контейнере)
            ├── logs (получение логов)
            ├── port-forward (проброс портов)
            ├── run (запуск временного пода в host namespace)
            └── attach (подключение к консоли)
```

### Архитектура безопасности Kubelet

```
┌─────────────────────────────────────────────────────┐
│                  API Server                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │   Node       │  │ NodeRestriction│  │  RBAC      │ │
│  │  Authorizer  │  │ (admission)   │  │  ClusterRole│ │
│  └──────┬──────┘  └──────┬───────┘  └─────┬──────┘ │
│         └────────────────┼────────────────┘         │
└──────────────────────────┼──────────────────────────┘
                           │ X.509 Certificate
                           ▼
┌─────────────────────────────────────────────────────┐
│                   Kubelet                            │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐ │
│  │ TLS Server   │  │  AuthN/AuthZ │  │   CRI     │ │
│  │ (port 10250) │  │  (X.509 +    │  │(containerd│ │
│  │              │  │   NodeAuthZ) │  │  /CRI-O)  │ │
│  └──────────────┘  └──────────────┘  └───────────┘ │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │          KubeletConfiguration                │   │
│  │  authentication:                             │   │
│  │    x509: clientCAFile: /var/lib/kubelet/...  │   │
│  │    webhook: enabled: true                    │   │
│  │    anonymous: enabled: false                 │   │
│  │  authorization:                              │   │
│  │    mode: Webhook                             │   │
│  │  rotateCertificates: true                    │   │
│  │  serverTLSBootstrap: true                    │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### Аутентификация Kubelet

**X.509 Client Certificate (рекомендуется):**

- **CN (Common Name):** `system:node:<node-name>` — имя узла
- **O (Organization):** `system:nodes` — группа узлов
- **Подписан:** CA кластера (`/etc/kubernetes/pki/ca.crt`)
- **Хранение:** `/var/lib/kubelet/pki/kubelet-client-current.pem`

**Проверка сертификата:**

```bash
# Просмотр сертификата kubelet
openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -noout -subject -issuer -dates
# → subject=O = system:nodes, CN = system:node:node01.example.com
# → issuer=CN = kubernetes
# → notBefore=Sep  1 00:00:00 2026 GMT
# → notAfter=Sep  1 00:00:00 2027 GMT

# Проверка盐城 (SAN)
openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -noout -text | grep -A1 "Subject Alternative Name"
# → X509v3 Subject Alternative Name:
# →     DNS:node01.example.com
```

**Аутентификация через Webhook (альтернатива):**

```yaml
# kubelet-config.yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
authentication:
  x509:
    clientCAFile: /etc/kubernetes/pki/ca.crt
  webhook:
    enabled: true
    cacheTTL: 2m0s
  anonymous:
    enabled: false  # ОБЯЗАТЕЛЬНО отключить
```

### Авторизация Kubelet

**Node Authorizer (встроенный модуль):**

Разрешает kubelet'у доступ к ресурсам, принадлежащим его узлу:

| Ресурс | Действия | Условие |
|:---|:---|:---|
| pods | get, list, watch, update, patch, delete | Pod привязан к узлу |
| pods/status | update, patch | Pod привязан к узлу |
| secrets | get, list, watch | Secret используется подами на узле |
| configmaps | get, list, watch | ConfigMap используется подами на узле |
| endpoints | get, list, watch | Endpoint связан с сервисом для подов на узле |
| services | get, list, watch | Service связан с подами на узле |
| nodes | get, list, watch, update, patch | Имя узла совпадает |
| persistentvolumeclaims | get, list, watch | PVC привязан к подам на узле |

**Важно:** Node Authorizer проверяет только "view" операции. Для "create/delete" операций над ресурсами других узлов kubelet использует NodeRestriction admission controller.

**NodeRestriction Admission Controller:**

```yaml
# Ограничения NodeRestriction
- kubelet может обновлять только status своего узла
- kubelet может создавать/удалять только привязанные к его узлу Pod
- kubelet может читать Secret/ConfigMap только используемые его подами
- kubelet НЕ может создавать ClusterRole/ClusterRoleBinding
- kubelet НЕ может изменять ClusterRole/ClusterRoleBinding
- kubelet НЕ может использовать impersonation
```

**Настройка NodeRestriction:**

```bash
# В kubeadm конфигурации API-сервера
apiVersion: kubeadm.k8s.io/v1beta3
kind: ClusterConfiguration
apiServer:
  extraArgs:
    enable-admission-plugins: "NodeRestriction"
```

### TLS Bootstrapping — автоматическое получение сертификатов

**Процесс:**

```
1. Kubelet стартует с --bootstrap-kubeconfig=/etc/kubernetes/bootstrap-kubelet.conf
        │
        ▼
2. Kubelet отправляет CSR (Certificate Signing Request) в API-сервер
   ├── CN: system:node:<node-name>
   ├── O: system:nodes
   └── Подпись bootstrap token'ом
        │
        ▼
3. CSR Approved (Bootstrap Token authenticates as system:bootstrappers:<bootstrap-token-name>)
        │
        ▼
4. Kubelet получает клиентский сертификат
   ├── Сохраняется в /var/lib/kubelet/pki/kubelet-client-current.pem
   └── Используется для последующих запросов
        │
        ▼
5. Kubelet запрашивает серверный сертификат (если serverTLSBootstrap: true)
   ├── CSR для порта 10250
   ├── Подпись клиентским сертификатом
   └── Требует ручного или автоматического одобрения (CSR Approver)
        │
        ▼
6. Kubelet использует ~/.kube/config (автоматически обновленный)
```

**Конфигурация TLS Bootstrapping:**

```yaml
# /var/lib/kubelet/config.yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
rotateCertificates: true  # Автоматическая ротация клиентских сертификатов
serverTLSBootstrap: true  # Автоматическое получение серверного сертификата
authentication:
  x509:
    clientCAFile: /etc/kubernetes/pki/ca.crt
  webhook:
    enabled: true
  anonymous:
    enabled: false
authorization:
  mode: Webhook  # Использование Node Authorizer через webhook
```

**Проверка статуса ротации:**

```bash
# Проверка CSR
kubectl get csr | grep node
# → NAME                           AGE   SIGNERNAME                     REQUESTOR                    STATUS
# → node-csr-abc123                5m    kubernetes.io/kube-apiserver-client-kubelet   system:bootstrappers:my-token   Approved,Issued

# Проверка сертификата на узле
openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -noout -dates
# → notBefore=Sep  1 00:00:00 2026 GMT
# → notAfter=Sep  1 00:00:00 2027 GMT

# Проверка серверного сертификата
openssl x509 -in /var/lib/kubelet/pki/kubelet-server-current.pem -noout -subject -dates
# → subject=O = system:nodes, CN = system:node:node01.example.com
# → notBefore=Sep  1 00:00:00 2026 GMT
# → notAfter=Sep  1 00:00:00 2027 GMT
```

### Автоматическая ротация сертификатов

**Механизм ротации:**

```yaml
# kubelet-config.yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
rotateCertificates: true  # Включает автоматическую ротацию клиентских сертификатов
```

**Цикл ротации:**

1. kubelet обнаруживает, что сертификат истекает через < 30 дней
2. kubelet генерирует новый ключ и CSR
3. CSR отправляется в API-сервер
4. CSR Approver автоматически одобряет (если настроен CSR Approver)
5. Новый сертификат сохраняется в `/var/kubelet/pki/kubelet-client-current.pem`
6. kubelet перезапускает HTTPS-сервер с новым сертификатом

**CSR Approver (рекомендуется для production):**

```bash
# Установка kubelet-serving-cert-approver
# Автоматически одобряет CSR для kubelet, если IP/DNS в CSR совпадают с реальным узлом
helm install kubelet-serving-cert-approver \
  --namespace kube-system \
  --set image.repository=ghcr.io/alex1989hu/kubelet-serving-cert-approver
```

### Безопасная конфигурация Kubelet

**Полный hardened KubeletConfiguration:**

```yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
# Аутентификация
authentication:
  x509:
    clientCAFile: /etc/kubernetes/pki/ca.crt
  webhook:
    enabled: true
    cacheTTL: 2m0s
  anonymous:
    enabled: false  # ОБЯЗАТЕЛЬНО

# Авторизация
authorization:
  mode: Webhook  # НЕ "AlwaysAllow"

# Сертификаты
rotateCertificates: true
serverTLSBootstrap: true

# Порты
readOnlyPort: 0  # ОТКЛЮЧИТЬ read-only порт (10255)
port: 10250

# Контейнерный runtime
containerRuntimeEndpoint: unix:///var/run/containerd/containerd.sock

# Ограничения ресурсов
evictionHard:
  memory.available: "200Mi"
  nodefs.available: "10%"
  imagefs.available: "15%"
evictionMinimumReclaim:
  memory.available: "0"
  nodefs.available: "5%"
  imagefs.available: "10%"

# Логирование
containerLogMaxSize: "50Mi"
containerLogMaxFiles: 5

# Sysctls (безопасные)
allowedUnsafeSysctls: []  # НЕ добавлять небезопасные sysctls
```

### CIS Benchmark проверки для Kubelet

kube-bench проверяет следующие параметры безопасности kubelet:

| Параметр | Рекомендация | CIS ID |
|:---|:---|:---|
| `--anonymous-auth=false` | Отключить анонимный доступ | 4.2.1 |
| `--authorization-mode=Webhook` | Включить webhook авторизацию | 4.2.2 |
| `--client-ca-file` | Указать CA для клиентской аутентификации | 4.2.3 |
| `--read-only-port=0` | Отключить read-only порт | 4.2.4 |
| `--streaming-connection-idle-timeout` | Таймаут неактивных streaming соединений | 4.2.5 |
| `--protect-kernel-defaults=true` | Защита kernel default значений | 4.2.6 |
| `--make-iptables-util-chains=true` | Автоматическое управление iptables | 4.2.7 |
| `--hostname-override` | Не использовать (для предотвращения spoofing) | 4.2.8 |
| `--event-qps=0` | Отключить rate limiting событий (0 = unlimited) | 4.2.9 |
| `--tls-cert-file` | Серверный сертификат | 4.2.10 |
| `--tls-private-key-file` | Серверный приватный ключ | 4.2.11 |
| `--rotate-certificates=true` | Автоматическая ротация сертификатов | 4.2.12 |

**Запуск проверки:**

```bash
# Проверка node (включая kubelet)
kube-bench run --targets node

# Проверка конкретных контролов
kube-bench run --targets node --check 4.2

# Экспорт результатов в JSON
kube-bench run --targets node --json --outputfile /tmp/kube-bench-results.json
```

---

## Практические сценарии

### Сценарий 1: Диагностика ошибок аутентификации Kubelet

```bash
# 1. Проверка сертификата kubelet
openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -noout -subject -issuer -dates
# → Если сертификат истек — проблема с ротацией

# 2. Проверка CSR
kubectl get csr | grep node01
# → Если CSR в статусе Pending — CSR Approver не настроен

# 3. Проверка логов kubelet
journalctl -u kubelet --since "10 minutes ago" | grep -i "error\|unauthorized\|certificate"
# → "Unable to connect to the server: x509: certificate has expired"
# → "failed to authenticate: user \"system:anonymous\" not found"

# 4. Проверка конфигурации kubelet
cat /var/lib/kubelet/config.yaml | grep -A5 "authentication"
# → Проверка: anonymous.enabled, x509.clientCAFile, webhook.enabled

# 5. Проверка доступа к API-серверу
kubectl get nodes --kubeconfig=/var/lib/kubelet/kubeconfig
# → Если ошибка — проблема с клиентским сертификатом
```

### Сценарий 2: Решение проблемы "Node NotReady"

```bash
# 1. Проверка статуса узла
kubectl describe node node01 | grep -A5 "Conditions"
# → Type: Ready, Status: False

# 2. Проверка логов kubelet на узле
ssh node01
journalctl -u kubelet --since "5 minutes ago" | tail -50
# → "Failed to connect to apiserver"
# → "x509: certificate signed by unknown authority"

# 3. Проверка сертификатов
ls -la /var/lib/kubelet/pki/
# → kubelet.crt, kubelet.key, kubelet-client-current.pem, kubelet-server-current.pem

# 4. Проверка CA
openssl verify -CAfile /etc/kubernetes/pki/ca.crt /var/lib/kubelet/pki/kubelet-client-current.pem
# → 如果输出 "OK" — сертификат валиден

# 5. Ручная ротация сертификатов (если автоматическая не работает)
rm /var/lib/kubelet/pki/kubelet-client-current.pem
systemctl restart kubelet
# → kubelet запросит новый сертификат через TLS Bootstrapping
```

### Сценарий 3: Проверка прав NodeRestriction

```bash
# 1. Попытка kubelet получить Secret из другого неймспейса
kubectl get secret my-secret -n other-namespace --as=system:node:node01
# → Error: forbidden: User "system:node:node01" cannot get secrets in namespace "other-namespace"

# 2. Попытка kubelet обновить status чужого узла
kubectl patch node node02 -p '{"status":{"conditions":[{"type":"Ready","status":"True"}]}}' --subresource=status --as=system:node:node01
# → Error: nodes.node02 is forbidden: User "system:node:node01" cannot patch resource "nodes" in API group "" at the cluster scope

# 3. Проверка RBAC привязаний для system:nodes
kubectl get clusterrolebinding system:nodes -o yaml
# → subjects:
# → - kind: Group
# →   name: system:nodes
# →   apiGroup: rbac.authorization.k8s.io
# → roleRef:
# →   kind: ClusterRole
# →   name: system:node
```

### Сценарий 4: Настройка Server TLS Bootstrap

```bash
# 1. Включение serverTLSBootstrap в kubelet-config.yaml
cat >> /var/lib/kubelet/config.yaml <<EOF
serverTLSBootstrap: true
EOF

# 2. Перезапуск kubelet
systemctl restart kubelet

# 3. Проверка создания CSR
kubectl get csr | grep node01
# → NAME                           AGE   SIGNERNAME                     REQUESTOR                    STATUS
# → node-server-csr-abc123         30s   kubernetes.io/kube-apiserver-client-kubelet   system:node:node01   Pending

# 4. Одобрение CSR (ручное или автоматическое)
kubectl certificate approve node-server-csr-abc123

# 5. Проверка нового сертификата
openssl x509 -in /var/lib/kubelet/pki/kubelet-server-current.pem -noout -subject -dates
# → subject=O = system:nodes, CN = system:node:node01.example.com
# → notAfter=Sep  1 00:00:00 2027 GMT

# 6. Установка kubelet-serving-cert-approver для автоматического одобрения
helm install kubelet-serving-cert-approver \
  --namespace kube-system \
  --create-namespace \
  --set image.repository=ghcr.io/alex1989hu/kubelet-serving-cert-approver
```

---

## Best Practices

1. **Отключите анонимный доступ:** `authentication.anonymous.enabled: false` — ОБЯЗАТЕЛЬНО для production.
2. **Используйте Webhook авторизацию:** `authorization.mode: Webhook` вместо `AlwaysAllow`.
3. **Отключите read-only порт:** `readOnlyPort: 0` — порт 10255 устарел и небезопасен.
4. **Включите ротацию сертификатов:** `rotateCertificates: true` и `serverTLSBootstrap: true`.
5. **Установите NodeRestriction:** Ограничивает kubelet возможностью работать только со своими ресурсами.
6. **Регулярно проверяйте через kube-bench:** CIS Benchmark автоматизирует проверку конфигурации.
7. **Мониторьте сертификаты:** Настройте алерты на истечение сертификатов kubelet (Prometheus метрика `kubelet_certificate_manager_server_ttl_seconds`).
8. **Не используйте bootstrap токены дольше 24 часов:** Ограничьте время жизни bootstrap token.
9. **Сетевая изоляция:** Ограничьте доступ к порту 10250 только через NetworkPolicy или файрвол.
10. **Регулярно обновляйте kubelet:** Следите за CVE и обновляйте Kubernetes до актуальных версий.

---

## Дополнительная информация

### Связанные документы

- [Pod Security Context — безопасность подов](./pod_security_context.md)
- [Admission Controllers — контроллеры допуска](../Concepts/admission_controllers.md)
- [TLS и mTLS в Kubernetes](./tls_and_mtls_in_kubernetes.md)
- [Certificate Management — управление сертификатами](../Operations/certificate_management.md)
- [kube-bench — CIS Benchmark](./kube-bench.md)
- [RBAC — управление доступом](./rbac/rbac_overview.md)
- [kubelet — концепции](../Concepts/kubelet.md)
- [Troubleshooting: Kubelet Issues](../Troubleshooting/Common_Errors/NodeUnavailability/kubelet_issues.md)

### Мониторинг Kubelet

| Метрика | Назначение | Алерт |
|:---|:---|:---|
| `kubelet_certificate_manager_server_ttl_seconds` | Время жизни серверного сертификата | `< 7 * 86400` (менее 7 дней) |
| `kubelet_certificate_manager_client_ttl_seconds` | Время жизни клиентского сертификата | `< 7 * 86400` |
| `kubelet_runtime_operations_errors_total` | Ошибки CRI операций | Рост > baseline |
| `kubelet_pLEG_reconciliation_duration_seconds` | Длительность reconciliation loop | P99 > 1s |
