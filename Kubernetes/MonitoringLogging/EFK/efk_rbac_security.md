# RBAC и безопасность EFK в Kubernetes

## Определения

**RBAC (Role-Based Access Control)** — механизм управления доступом в Kubernetes, основанные на ролях. Определяет, кто (Subject) может выполнять какие действия (Verbs) над какими ресурсами (Resources) в каком пространстве имен (Namespace).

**ServiceAccount** — учетная запись, предоставляемая подам для аутентификации в API-сервере Kubernetes. Каждый под может иметь свою ServiceAccount.

**Role** — набор прав (permissions) в пределах одного namespace. Определяет доступ к ресурсам (pods, services, configmaps и т.д.).

**ClusterRole** — набор прав, применимых ко всему кластеру или конкретным namespace. Используется для доступа к кластерным ресурсам (nodes, persistent volumes) или для управления ресурсами в нескольких namespace.

**RoleBinding** — связывает Role с Subject (User, Group, ServiceAccount) в конкретном namespace.

**ClusterRoleBinding** — связывает ClusterRole с Subject во всем кластере.

**Secret** — объект Kubernetes для хранения конфиденциальных данных (пароли, токены, сертификаты). Данные кодируются в base64.

**TLS (Transport Layer Security)** — протокол для обеспечения безопасности передачи данных между клиентом и сервером. Используется для шифрования трафика в Elasticsearch.

**X-Pack Security** — модуль безопасности Elasticsearch, включающий аутентификацию, авторизацию, шифрование и аудит.

## Теоретический блок

### Модель безопасности EFK

```
┌─────────────────────────────────────────────────────────────┐
│                    Безопасность EFK                          │
├─────────────────────────────────────────────────────────────┤
│  1. Аутентификация (кто вы?)                                │
│     └─ ServiceAccount, Basic Auth, API Keys, TLS            │
│                                                             │
│  2. Авторизация (что вам можно?)                            │
│     └─ RBAC Roles, X-Pack Security Roles                    │
│                                                             │
│  3. Шифрование (что скрыть?)                                │
│     └─ TLS для трафика, Шифрование на диске                 │
│                                                             │
│  4. Аудит (что вы делали?)                                   │
│     └─ Audit Logging, Security Events                       │
└─────────────────────────────────────────────────────────────┘
```

### Принцип最小特权 (Least Privilege)

Каждый компонент EFK должен иметь только те права, которые необходимы для его работы:

- **Fluent Bit**: доступ к чтению логов с узлов, отправка в Elasticsearch
- **Elasticsearch**: доступ к storage, сетевые порты, управление индексами
- **Kibana**: доступ к Elasticsearch API для визуализации
- **Мониторинг**: доступ к метрикам компонентов

### Типы аутентификации в Elasticsearch 8.x

| Тип | Описание | Использование |
| :--- | :--- | :--- |
| **Basic Auth** | Логин/пароль | Простые сценарии, ручное управление |
| **API Keys** | Статические ключи | Автоматизация, CI/CD |
| **Service Account Tokens** | Динамические токены | Kubernetes native, рекомендуется |
| **TLS Client Certs** | Сертификаты клиента | Высокая безопасность, mTLS |
| **SAML/OIDC** | Внешние провайдеры | Enterprise, SSO интеграция |

## Практический блок

### 1. Создание ServiceAccount для компонентов EFK

```yaml
# 01-service-accounts.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: elasticsearch
  namespace: logging
  labels:
    app: elasticsearch
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: fluent-bit
  namespace: logging
  labels:
    app: fluent-bit
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: kibana
  namespace: logging
  labels:
    app: kibana
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: elasticsearch-exporter
  namespace: monitoring
  labels:
    app: elasticsearch-exporter
```

### 2. RBAC для Fluent Bit

Fluent Bit должен читать логи с узлов и отправлять их в Elasticsearch.

```yaml
# 02-fluent-bit-rbac.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: fluent-bit
  labels:
    app: fluent-bit
rules:
# Чтение метаданных подов
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
# Чтение метаданных нод
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list", "watch"]
# Чтение метаданных namespace
- apiGroups: [""]
  resources: ["namespaces"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: fluent-bit
  labels:
    app: fluent-bit
subjects:
- kind: ServiceAccount
  name: fluent-bit
  namespace: logging
roleRef:
  kind: ClusterRole
  name: fluent-bit
  apiGroup: rbac.authorization.k8s.io
```

### 3. RBAC для Elasticsearch Exporter

```yaml
# 03-elasticsearch-exporter-rbac.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: elasticsearch-exporter
  labels:
    app: elasticsearch-exporter
rules:
# Чтение информации о подах
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list"]
# Чтение информации о сервисах
- apiGroups: [""]
  resources: ["services"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: elasticsearch-exporter
  labels:
    app: elasticsearch-exporter
subjects:
- kind: ServiceAccount
  name: elasticsearch-exporter
  namespace: monitoring
roleRef:
  kind: ClusterRole
  name: elasticsearch-exporter
  apiGroup: rbac.authorization.k8s.io
```

### 4. Создание Secret для учетных данных Elasticsearch

```bash
# Создание Secret с паролем для пользователя elastic
kubectl create secret generic elasticsearch-credentials \
  --namespace logging \
  --from-literal=password=$(openssl rand -base64 32) \
  --dry-run=client -o yaml | kubectl apply -f -

# Просмотр созданного Secret
kubectl get secret elasticsearch-credentials -n logging -o jsonpath='{.data.password}' | base64 -d
```

### 5. Настройка TLS в Elasticsearch

```yaml
# 04-elasticsearch-tls-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: elasticsearch-config
  namespace: logging
data:
  elasticsearch.yml: |
    cluster.name: elasticsearch-cluster
    network.host: 0.0.0.0
    
    # Включение безопасности
    xpack.security.enabled: true
    xpack.security.transport.ssl.enabled: true
    xpack.security.transport.ssl.verification_mode: certificate
    xpack.security.transport.ssl.keystore.path: certs/transport.p12
    xpack.security.transport.ssl.truststore.path: certs/transport.p12
    
    # Включение HTTP TLS
    xpack.security.http.ssl.enabled: true
    xpack.security.http.ssl.keystore.path: certs/http.p12
```

### 6. Настройка Fluent Bit для работы с Elasticsearch и TLS

```yaml
# 05-fluent-bit-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: fluent-bit-config
  namespace: logging
data:
  fluent-bit.conf: |
    [SERVICE]
        Flush         5
        Log_Level     info
        Daemon        off
        Parsers_File  parsers.conf
        HTTP_Server   On
        HTTP_Listen   0.0.0.0
        HTTP_Port     2020
        Metrics_On    On
        storage.path  /var/fluent-bit/state/
    
    [INPUT]
        Name              tail
        Tag               kube.*
        Path              /var/log/containers/*.log
        Parser            docker
        DB                /var/fluent-bit/state/flb_kube.db
        Mem_Buf_Limit     50MB
        Skip_Long_Lines   On
        Refresh_Interval  10
    
    [FILTER]
        Name                kubernetes
        Match               kube.*
        Kube_URL            https://kubernetes.default.svc:443
        Kube_CA_File        /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
        Kube_Token_File     /var/run/secrets/kubernetes.io/serviceaccount/token
        Kube_Tag_Prefix     kube.var.log.containers.
        Merge_Log           On
        Merge_Log_Key       log_processed
        K8S-Logging.Parser  On
        K8S-Logging.Exclude Off
    
    [OUTPUT]
        Name            es
        Match           *
        Host            ${FLUENT_ELASTICSEARCH_HOST}
        Port            ${FLUENT_ELASTICSEARCH_PORT}
        Logstash_Format On
        Logstash_Prefix fluent-bit
        Logstash_DateFormat %Y.%m.%d
        TLS             On
        TLS.verify      Off
        HTTP_User       ${FLUENT_ELASTICSEARCH_USER}
        HTTP_Passwd     ${FLUENT_ELASTICSEARCH_PASSWORD}
        Retry_Limit     False
        Replace_Dots    On
        Suppress_Type_Name On
        Trace_Error     On
        Workers         2
```

### 7. Настройка RBAC для Prometheus мониторинга

```yaml
# 06-monitoring-rbac.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: prometheus-elasticsearch
  labels:
    app: prometheus
rules:
# Доступ к ServiceMonitor
- apiGroups: ["monitoring.coreos.com"]
  resources: ["servicemonitors", "podmonitors", "prometheusrules"]
  verbs: ["get", "list", "watch"]
# Дост_METRICС сервисам
- apiGroups: [""]
  resources: ["services", "endpoints", "pods"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: prometheus-elasticsearch
  labels:
    app: prometheus
subjects:
- kind: ServiceAccount
  name: prometheus-kube-prometheus-prometheus
  namespace: monitoring
roleRef:
  kind: ClusterRole
  name: prometheus-elasticsearch
  apiGroup: rbac.authorization.k8s.io
```

### 8. Настройка NetworkPolicy для EFK

```yaml
# 07-network-policies.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: elasticsearch-netpol
  namespace: logging
spec:
  podSelector:
    matchLabels:
      app: elasticsearch
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Доступ от Fluent Bit
  - from:
    - podSelector:
        matchLabels:
          app: fluent-bit
    ports:
    - protocol: TCP
      port: 9200
  # Доступ от Kibana
  - from:
    - podSelector:
        matchLabels:
          app: kibana
    ports:
    - protocol: TCP
      port: 9200
  # Доступ от мониторинга
  - from:
    - podSelector:
        matchLabels:
          app: elasticsearch-exporter
    ports:
    - protocol: TCP
      port: 9200
  egress:
  # Доступ к DNS
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  # Доступ к API-серверу Kubernetes
  - to:
    - ipBlock:
        cidr: 10.0.0.0/8
    ports:
    - protocol: TCP
      port: 6443
  # Внутренний кластерный трафик
  - to:
    - podSelector:
        matchLabels:
          app: elasticsearch
    ports:
    - protocol: TCP
      port: 9300
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: fluent-bit-netpol
  namespace: logging
spec:
  podSelector:
    matchLabels:
      app: fluent-bit
  policyTypes:
  - Egress
  egress:
  # Доступ к Elasticsearch
  - to:
    - podSelector:
        matchLabels:
          app: elasticsearch
    ports:
    - protocol: TCP
      port: 9200
  # Доступ к API-серверу Kubernetes
  - to:
    - ipBlock:
        cidr: 10.0.0.0/8
    ports:
    - protocol: TCP
      port: 6443
  # Доступ к DNS
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
  # Доступ к метрикам
  - to:
    - podSelector:
        matchLabels:
          app: prometheus
    ports:
    - protocol: TCP
      port: 2020
```

## Дополнительная информация

### Проверка безопасности

```bash
# Проверка ServiceAccount
kubectl get serviceaccount -n logging

# Проверка Role и RoleBinding
kubectl get role,rolebinding -n logging

# Проверка ClusterRole и ClusterRoleBinding
kubectl get clusterrole,clusterrolebinding | grep -E "elasticsearch|fluent-bit|kibana"

# Проверка Secret
kubectl get secret -n logging

# Проверка NetworkPolicy
kubectl get networkpolicy -n logging

# Проверка прав ServiceAccount
kubectl auth can-i get pods --as=system:serviceaccount:logging:fluent-bit
kubectl auth can-i create events --as=system:serviceaccount:logging:fluent-bit
```

### Частые проблемы

1. **Fluent Bit не может читать логи с других нод**: Убедитесь, что ClusterRole имеет права на чтение pods и nodes.
2. **Elasticsearch Exporter не может собирать метрики**: Проверьте, что ServiceAccount имеет права доступа к pods и services.
3. **Prometheus не скрейпит метрики**: Убедитесь, что ServiceMonitor имеет правильные labels.
4. **NetworkPolicy блокирует трафик**: Проверьте, что правила NetworkPolicy не блокируют необходимый трафик.
5. **TLS handshake failure**: Убедитесь, что сертификаты корректно установлены и доверяются.

### Рекомендации по безопасности

1. Используйте отдельные ServiceAccount для каждого компонента.
2. Применяйте принцип минимальных привилегий.
3. Включайте TLS для всех соединений.
4. Регулярно ротируйте пароли и сертификаты.
5. Используйте NetworkPolicy для ограничения сетевого доступа.
6. Включайте аудит для отслеживания действий.
7. Используйте secrets management (Vault, Sealed Secrets) для хранения конфиденциальных данных.

### Полезные ссылки

- [Kubernetes RBAC Documentation](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
- [Elasticsearch Security](https://www.elastic.co/guide/en/elasticsearch/reference/current/security.html)
- [ECK Security](https://www.elastic.co/guide/en/cloud-on-k8s/current/k8s-elastic-stack-saas-auth.html)
- [Fluent Bit Kubernetes Security](https://docs.fluentbit.io/manual/pipeline/kubernetes)
- [Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/)