# OpenTelemetry: Безопасность Collector в Kubernetes

## Определения

**Безопасность OpenTelemetry Collector в Kubernetes** — это набор практик и настроек, обеспечивающих защиту Collector от несанкционированного доступа, утечки данных и отказа в обслуживании. Включает RBAC, NetworkPolicies, Secrets, TLS и аудит.

В 2026 году безопасность является критическим компонентом production-развёртывания OTel.

## Теоретический блок

### Уровни безопасности

| Уровень | Описание | Компоненты |
| :--- | :--- | :--- |
| **Базовый** | Минимальные права для работы Collector | ServiceAccount, ClusterRole |
| **Средний** | Сетевая изоляция и шифрование | NetworkPolicy, TLS |
| **Высокий** | Полный аудит и контроль доступа | OIDC, Audit Logging, PodSecurity |

### Ключевые компоненты

1. **ServiceAccount** — отдельная учётная запись для Collector.
2. **ClusterRole/ClusterRoleBinding** — права доступа к ресурсам Kubernetes.
3. **NetworkPolicy** — ограничение сетевого доступа.
4. **Secrets** — хранение сертификатов и ключей.
5. **PodSecurity** — ограничения на уровне подов.

## Практические сценарии

### Сценарий 1: Настройка RBAC

**ServiceAccount:**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: otel-collector
  namespace: opentelemetry
```

**ClusterRole с минимальными правами:**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: otel-collector
rules:
  - apiGroups: [""]
    resources: ["pods", "nodes", "namespaces", "endpoints"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["networking.k8s.io"]
    resources: ["ingresses"]
    verbs: ["get", "list", "watch"]
```

**ClusterRoleBinding:**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: otel-collector
subjects:
  - kind: ServiceAccount
    name: otel-collector
    namespace: opentelemetry
roleRef:
  kind: ClusterRole
  name: otel-collector
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 2: NetworkPolicy

**Ограничение входящего трафика:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: otel-collector
  namespace: opentelemetry
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: opentelemetry-collector
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector: {}
      ports:
        - protocol: TCP
          port: 4317
        - protocol: TCP
          port: 4318
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              name: tempo
      ports:
        - protocol: TCP
          port: 4317
    - to:
        - namespaceSelector:
            matchLabels:
              name: loki
      ports:
        - protocol: TCP
          port: 3100
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
```

### Сценарий 3: TLS для Collector

**Создание сертификатов:**

```bash
# Генерация CA
openssl req -x509 -newkey rsa:4096 -keyout ca.key -out ca.crt -days 365 -nodes \
  -subj "/CN=OTel CA"

# Сертификат Collector
openssl req -newkey rsa:4096 -keyout server.key -out server.csr -nodes \
  -subj "/CN=otel-collector.opentelemetry.svc"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days 365
```

**Сохранение в Kubernetes Secrets:**

```bash
kubectl create secret tls otel-collector-tls \
  --cert=server.crt \
  --key=server.key \
  -n opentelemetry

kubectl create secret generic otel-ca \
  --from-file=ca.crt \
  -n opentelemetry
```

**Конфигурация Collector с TLS:**

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        tls:
          cert_file: /etc/otel/certs/tls.crt
          key_file: /etc/otel/certs/tls.key
          client_ca_file: /etc/otel/certs/ca.crt
```

### Сценарий 4: PodSecurity

**Ограничения на уровне подов:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: otel-collector
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    fsGroup: 1000
  containers:
    - name: collector
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop:
            - ALL
      resources:
        limits:
          cpu: "1"
          memory: "1Gi"
        requests:
          cpu: "500m"
          memory: "512Mi"
```

## Дополнительная информация

### Типичные проблемы и решение

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Collector не может читать поды** | Отсутствует ClusterRole | Проверить `kubectl auth can-i list pods` |
| **NetworkPolicy блокирует трафик** | Неверные правила | Проверить `kubectl describe networkpolicy` |
| **TLS handshake failure** | Неверные сертификаты | Проверить `openssl x509 -in server.crt -noout -dates` |
| **PodSecurity блокирует запуск** | Нарушение ограничений | Проверить `kubectl describe pod` |

### Best Practices

1. **Используйте минимальные права** — не выдавайте лишних привилегий.
2. **Шифруйте данные** — используйте TLS для всех соединений.
3. **Изоляция по сети** — настройте NetworkPolicy для ограничения доступа.
4. **Мониторьте безопасность** — настройте алерты на подозрительную активность.
5. **Регулярно обновляйте** — обновляйте образы и зависимости.

### Ссылки

- [Kubernetes RBAC](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
- [Kubernetes NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
- [Kubernetes Secrets](https://kubernetes.io/docs/concepts/configuration/secret/)
- [OTel Collector Security](https://opentelemetry.io/docs/collector/security/)
