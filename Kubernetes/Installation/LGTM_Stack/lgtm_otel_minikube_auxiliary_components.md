# Развертывание вспомогательных компонентов LGTM на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)** ← текущий
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

## Определения

**Cert-manager** — нативный для Kubernetes контроллер для автоматизации управления TLS-сертификатами. В данном руководстве используется для выпуска самоподписанных сертификатов для Ingress-ресурсов (Grafana, Loki, Tempo). Полная документация: **[Cert-manager](../../ToolsUtilities/cert_manager/definitions.md)**.

**Docker Registry** — сервис для хранения и распространения Docker-образов. В данном руководстве разворачивается локальный registry внутри кластера Minikube для публикации тестовых образов. Подробнее: **[Docker Registries](../../../Docker/docker_registries.md)**.

**ClusterIssuer** — общекластерный ресурс cert-manager, представляющий центр сертификации (CA). Доступен из любого namespace. См. **[CRD cert-manager](../../ToolsUtilities/cert_manager/definitions.md#Основные-концепции-CRD)**.

**Самоподписанный сертификат** — сертификат, подписанный собственным CA кластера, а не публичным центром сертификации (Let's Encrypt). Используется только для локальных/тестовых окружений.

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
│  │  grafana.test → Grafana (TLS: grafana-tls)         │   │
│  │  loki.test    → Loki    (TLS: loki-tls)            │   │
│  │  tempo.test   → Tempo   (TLS: tempo-tls)            │   │
│  │  registry.test → Registry (TLS: registry-tls)      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Поток выпуска сертификатов

1. **Cert-manager** устанавливается в кластер
2. Создаётся **ClusterIssuer** с self-signed CA
3. Для каждого сервиса (Grafana, Loki, Tempo, Registry) создаётся **Certificate**
4. Cert-manager генерирует TLS-сертификат и сохраняет в **Secret**
5. **Ingress** использует Secret для HTTPS-терминации

### Требования к ресурсам

| Компонент | CPU (request/limit) | Memory (request/limit) |
| :--- | :--- | :--- |
| **Cert-manager** | 10m / 100m | 32Mi / 128Mi |
| **Docker Registry** | 100m / 500m | 128Mi / 512Mi |

---

## Практические сценарии

### Сценарий 1: Установка Cert-manager и настройка CA

**Цель:** Развернуть cert-manager и создать самоподписанный CA для внутренних сервисов.

#### Шаг 1: Установка cert-manager

Установите cert-manager через Helm (рекомендуемый способ). Полная инструкция: **[Установка cert-manager](../../ToolsUtilities/cert_manager/installation.md)**.

```bash
# Добавление репозитория Jetstack
helm repo add jetstack https://charts.jetstack.io
helm repo update

# Установка cert-manager с CRD
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set installCRDs=true \
  --version v1.15.0

# Проверка установки
kubectl get deployments -n cert-manager
kubectl get pods -n cert-manager
```

**Ожидаемый результат:**

```
NAME                      READY   UP-TO-DATE   AVAILABLE   AGE
cert-manager              1/1     1            1           2m
cert-manager-cainjector   1/1     1            1           2m
cert-manager-webhook      1/1     1            1           2m
```

#### Шаг 2: Создание ClusterIssuer для самоподписанных сертификатов

Создайте корневой CA и Certificate для выпуска внутренних сертификатов:

```bash
# Создание ClusterIssuer с self-signed CA
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

**Проверка:**

```bash
kubectl get clusterissuer minikube-ca
kubectl get certificate -n cert-manager minikube-ca-secret
```

**Ожидаемый статус:** `Ready=True`

---

### Сценарий 2: Развёртывание локального Docker Registry

**Цель:** Развернуть Docker Registry внутри кластера с TLS и доступом для pull/push образов.

#### Шаг 1: Установка Docker Registry через Helm

```bash
# Создание namespace
kubectl create namespace docker-registry

# Установка Docker Registry
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

# Настройка Docker Daemon для работы с insecure registry
minikube ssh "sudo tee /etc/docker/daemon.json <<< '{\"insecure-registries\": [\"registry.test:30000\"]}'"
minikube ssh "sudo systemctl restart docker"

# Перезапуск Minikube для применения настроек
minikube stop && minikube start
```

#### Шаг 3: Создание секрета для доступа к Registry

```bash
# Создание Docker registry secret
kubectl create secret docker-registry regcred \
  --docker-server=registry.test:30000 \
  --docker-username=admin \
  --docker-password=admin \
  --namespace default

# Привязка secret к service account
kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "regcred"}]}'
```

#### Шаг 4: Верификация

```bash
# Проверка статуса Pod
kubectl get pods -n docker-registry

# Проверка Ingress
kubectl get ingress -n docker-registry

# Тестирование push/pull
docker tag alpine:latest registry.test:30000/alpine:test
docker push registry.test:30000/alpine:test
```

---

## Дополнительная информация

### Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Cert-manager Pod не запускается** | Недостаточно ресурсов | `kubectl describe pod -n cert-manager`, увеличить лимиты Minikube |
| **Certificate в статусе Pending** | ClusterIssuer не найден | Проверить `kubectl get clusterissuer`, имя в `issuerRef` |
| **Registry недоступен по HTTPS** | TLS Secret не создан | Проверить `kubectl get secret registry-tls -n docker-registry` |
| **ImagePullBackOff** | Secret `regcred` не привязан | Проверить `kubectl get serviceaccount default -o yaml` |
| **dial tcp: lookup registry.test** | Запись в `/etc/hosts` отсутствует | Добавить запись: `echo "$(minikube ip) registry.test" \| sudo tee -a /etc/hosts` |

### Диагностика

```bash
# Логи cert-manager
kubectl logs -n cert-manager -l app=cert-manager --tail=100

# Проверка Certificate
kubectl get certificate -A
kubectl describe certificate <name> -n <namespace>

# Проверка Registry
kubectl get ingress docker-registry -n docker-registry
kubectl get secret registry-tls -n docker-registry

# Тестирование TLS
curl -kv https://registry.test:30000/v2/
```

### Ссылки на SSoT

- **Cert-manager:**
  - **[Определения и концепции](../../ToolsUtilities/cert_manager/definitions.md)**
  - **[Установка](../../ToolsUtilities/cert_manager/installation.md)**
  - **[Cluster CA](../../ToolsUtilities/cert_manager/cluster_ca.md)**
  - **[Troubleshooting](../../ToolsUtilities/cert_manager/Administration/troubleshooting.md)**
- **Docker Registry:**
  - **[Docker Registries overview](../../../Docker/docker_registries.md)**
  - **[Minikube Registry](../../Installation/minikube/minikube_practical_scenarios.md)** — раздел "Использование локального Registry"
- **Ingress:**
  - **[Ingress Overview](../../Networking/Ingress/overview.md)**

### Безопасность

> **Внимание:** Данная конфигурация предназначена **только для локальных/тестовых окружений**.

| Аспект | Текущая конфигурация | Production-рекомендация |
| :--- | :--- | :--- |
| **TLS** | Самоподписанные сертификаты | Публичные сертификаты (Let's Encrypt) или корпоративный CA |
| **Аутентификация Registry** | Базовая (admin/admin) | OAuth2, робот-аккаунты (Harbor) |
| **Сетевая изоляция** | Отсутствует | NetworkPolicies, отдельные namespace |
| **Хранение секретов** | Kubernetes Secrets | HashiCorp Vault, External Secrets Operator |

### Альтернативы

| Компонент | Текущий вариант | Production-альтернатива |
| :--- | :--- | :--- |
| **Registry** | twuni/docker-registry (Helm) | Harbor, GitLab Registry, GHCR |
| **CA** | Self-signed | Let's Encrypt, корпоративный PKI |
| **Ingress** | Minikube Ingress (nginx) | Nginx Ingress Controller, Traefik, Gateway API |

---

**Навигация по руководству:**

- **[← Предварительные требования](./lgtm_otel_minikube_prerequisites_environment.md)**
- **[Развертывание стека LGTM →](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
