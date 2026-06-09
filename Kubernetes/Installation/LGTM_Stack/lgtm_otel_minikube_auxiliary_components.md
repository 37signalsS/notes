# Развертывание вспомогательных компонентов LGTM на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)** ← текущий
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

## Определения

**Cert-manager** — контроллер Kubernetes для автоматизации управления TLS-сертификатами. Подробнее: **[Cert-manager: Определения](../../ToolsUtilities/cert_manager/definitions.md)**.

**Docker Registry** — сервис хранения и распространения образов. В данном руководстве разворачивается локально. Подробнее: **[Docker Registries](../../../Docker/docker_registries.md)**.

**ClusterIssuer** — ресурс cert-manager, представляющий центр сертификации (CA) на уровне кластера.

**Самоподписанный сертификат** — сертификат, подписанный собственным CA кластера. Используется для тестирования.

---

## Основные концепции

### Архитектура вспомогательных компонентов

```
┌─────────────────────────────────────────────────────────────┐
│                     Minikube Cluster                        │
│                                                             │
│  ┌─────────────────┐         ┌─────────────────────────┐   │
│  │  Cert-manager   │         │   Docker Registry       │   │
│  │                 │         │   (twuni/chart)         │   │
│  │  - CA Issuer    │         │   Port: 30000           │   │
│  │  - Certificate  │         │   Host: registry.test   │   │
│  │  - TLS Secret   │         │   TLS: self-signed      │   │
│  └────────┬────────┘         └────────────┬────────────┘   │
│           │                               │                 │
│           ▼                               ▼                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Ingress Controller (nginx)             │   │
│  │                                                     │   │
│  │  grafana.test -> Grafana (TLS: grafana-tls)         │   │
│  │  loki.test    -> Loki    (TLS: loki-tls)            │   │
│  │  tempo.test   -> Tempo   (TLS: tempo-tls)            │   │
│  │  registry.test -> Registry (TLS: registry-tls)      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Поток выпуска сертификатов

1. Установка **cert-manager**.
2. Создание **ClusterIssuer** (self-signed CA).
3. Создание ресурса **Certificate** для каждого сервиса.
4. Выпуск TLS-сертификата и сохранение в **Secret**.
5. Использование Secret в **Ingress** для HTTPS.

### Требования к ресурсам

| Компонент | CPU (request/limit) | Memory (request/limit) |
| :--- | :--- | :--- |
| **Cert-manager** | 10m / 100m | 32Mi / 128Mi |
| **Docker Registry** | 100m / 500m | 128Mi / 512Mi |

---

## Практические сценарии

### Сценарий 1: Установка Cert-manager и настройка CA

**Цель:** Развернуть cert-manager и создать самоподписанный CA.

#### Шаг 1: Установка cert-manager

Подробная инструкция: **[Установка cert-manager](../../ToolsUtilities/cert_manager/installation.md)**.

```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update

helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set installCRDs=true \
  --version v1.15.0
```

#### Шаг 2: Создание ClusterIssuer

```bash
# Создание ClusterIssuer
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: minikube-ca
spec:
  ca:
    secretName: minikube-ca-secret
EOF

# Создание корневого CA-сертификата
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: minikube-ca-secret
  namespace: cert-manager
spec:
  isCA: true
  duration: 8760h
  secretName: minikube-ca-secret
  privateKey:
    algorithm: RSA
    size: 2048
  commonName: "minikube-ca"
  issuerRef:
    name: minikube-ca
    kind: ClusterIssuer
    group: cert-manager.io
EOF
```

---

### Сценарий 2: Развёртывание локального Docker Registry

**Цель:** Развернуть реестр с TLS внутри кластера.

#### Шаг 1: Установка Docker Registry

```bash
helm upgrade --install docker-registry twuni/docker-registry \
  --namespace docker-registry \
  --create-namespace \
  --set service.type=NodePort \
  --set service.nodePort=30000 \
  --set ingress.enabled=true \
  --set ingress.host=registry.test \
  --set ingress.tls.enabled=true \
  --set ingress.tls.secretName=registry-tls \
  --set ingress.tls.issuerName=minikube-ca \
  --set ingress.tls.issuerKind=ClusterIssuer
```

#### Шаг 2: Настройка DNS и Docker Daemon

```bash
# Добавление записи в /etc/hosts
echo "$(minikube ip) registry.test" | sudo tee -a /etc/hosts

# Настройка insecure registry в Minikube
minikube ssh "sudo tee /etc/docker/daemon.json <<< '{\"insecure-registries\": [\"registry.test:30000\"]}'"
minikube ssh "sudo systemctl restart docker"
```

#### Шаг 3: Настройка доступа (ImagePullSecrets)

```bash
kubectl create secret docker-registry regcred \
  --docker-server=registry.test:30000 \
  --docker-username=admin \
  --docker-password=admin \
  --namespace default

kubectl patch serviceaccount default -p '{"imagePullSecrets": [{"name": "regcred"}]}'
```

---

## Дополнительная информация

### Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Pod в Pending** | Недостаточно ресурсов | Увеличить лимиты Minikube |
| **Certificate в Pending** | Ошибка в ClusterIssuer | Проверить `kubectl describe certificate` |
| **Registry недоступен** | Ошибка TLS Secret | Проверить наличие секрета `registry-tls` |

### Диагностика

```bash
# Логи
kubectl logs -n cert-manager -l app=cert-manager --tail=100

# Статус сертификатов
kubectl get certificate -A
```

### Связанные темы

- **[Cert-manager: Администрирование](../../ToolsUtilities/cert_manager/Administration/index.md)**
- **[Minikube: Практические сценарии](../../Installation/minikube/minikube_practical_scenarios.md)**
- **[Docker Registry: Обзор](../../../Docker/docker_registries.md)**

### Безопасность

> **Внимание:** Конфигурация только для тестовых окружений.

| Аспект | Текущая конфигурация | Production |
| :--- | :--- | :--- |
| **TLS** | Самоподписанные | Let's Encrypt / Корпоративный CA |
| **Аутентификация** | Basic (admin/admin) | OIDC / Harbor |
| **Изоляция** | Отсутствует | NetworkPolicies |

---

**Навигация по руководству:**

- **[← Предварительные требования](./lgtm_otel_minikube_prerequisites_environment.md)**
- **[Развертывание стека LGTM →](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
