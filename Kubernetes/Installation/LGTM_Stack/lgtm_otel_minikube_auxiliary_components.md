# Развертывание вспомогательных компонентов LGTM на Minikube

> **Навигация по руководству:**
>
> - **[Предварительные требования и подготовка окружения](./lgtm_otel_minikube_prerequisites_environment.md)**
> - **[Развертывание вспомогательных компонентов](./lgtm_otel_minikube_auxiliary_components.md)** (текущий)
> - **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)**
> - **[Развертывание OpenTelemetry](./lgtm_otel_minikube_opentelemetry_deployment.md)**
> - **[Тестирование и верификация](./lgtm_otel_minikube_test_app_verification.md)**

---

## Определения

**Cert-manager** — нативный Kubernetes-контроллер для автоматизации управления TLS-сертификатами. В данном стеке обеспечивает выпуск сертификатов для Ingress. Подробнее: **[Cert-manager: Определения](../../ToolsUtilities/cert_manager/definitions.md)**.

**Docker Registry** — сервис хранения и распространения образов. Используется для хранения локально собранных образов приложений и компонентов. Подробнее: **[Docker Registries](../../../Docker/docker_registries.md)**.

**ClusterIssuer** — ресурс cert-manager, представляющий центр сертификации (CA), доступный на уровне всего кластера.

**Самоподписанный сертификат (Self-signed)** — сертификат, выпущенный внутренним CA кластера. Применяется для шифрования трафика в тестовых окружениях без использования публичных доверенных центров.

---

## Основные концепции

### Архитектура вспомогательных компонентов

```text
┌─────────────────────────────────────────────────────────────┐
│                     Minikube Cluster                        │
│                                                             │
│  ┌─────────────────┐         ┌─────────────────────────┐   │
│  │  Cert-manager   │         │   Docker Registry       │   │
│  │                 │         │   (twuni chart)         │   │
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

### Жизненный цикл выпуска сертификатов

1. Развертывание оператора **cert-manager**.
2. Настройка **ClusterIssuer** (создание локального CA).
3. Определение ресурсов **Certificate** для сервисов стека.
4. Генерация TLS-секретов и их автоматическое обновление.
5. Подключение секретов в конфигурацию **Ingress** для терминирования TLS.

### Распределение ресурсов

| Компонент | CPU (request/limit) | Memory (request/limit) |
| :--- | :--- | :--- |
| **Cert-manager** | 10m / 100m | 32Mi / 128Mi |
| **Docker Registry** | 100m / 500m | 128Mi / 512Mi |

---

## Практические сценарии

### Сценарий 1: Установка Cert-manager и настройка внутреннего CA

**Цель:** Развернуть инфраструктуру управления сертификатами и подготовить доверенный источник для кластера.

#### Шаг 1: Установка cert-manager

Используется актуальная версия (на июль 2026 г. — v1.20.2). Подробности в SSoT: **[Установка cert-manager](../../ToolsUtilities/cert_manager/installation.md)**.

```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update

helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set installCRDs=true \
  --version v1.20.2
```

#### Шаг 2: Создание ClusterIssuer

```yaml
# Создание ClusterIssuer (self-signed)
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: minikube-ca
spec:
  selfSigned: {}
EOF

# Создание корневого CA-сертификата
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: minikube-ca-root
  namespace: cert-manager
spec:
  isCA: true
  commonName: "minikube-ca"
  secretName: minikube-ca-secret
  issuerRef:
    name: minikube-ca
    kind: ClusterIssuer
    group: cert-manager.io
EOF

# Создание ClusterIssuer на базе созданного CA
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: minikube-ca-issuer
spec:
  ca:
    secretName: minikube-ca-secret
EOF
```

---

### Сценарий 2: Развертывание локального Docker Registry

**Цель:** Обеспечить хранилище для артефактов внутри кластера с поддержкой TLS.

#### Шаг 1: Настройка Helm-репозитория

В 2025 году репозиторий twuni был перенесен.

```bash
helm repo add twuni https://twuni.github.io/docker-registry.helm
helm repo update
```

#### Шаг 2: Установка реестра

```bash
helm upgrade --install docker-registry twuni/docker-registry \
  --namespace docker-registry \
  --create-namespace \
  --set service.type=NodePort \
  --set service.nodePort=30000 \
  --set ingress.enabled=true \
  --set ingress.hosts[0]=registry.test \
  --set ingress.tls[0].secretName=registry-tls \
  --set ingress.annotations."cert-manager.io/cluster-issuer"=minikube-ca-issuer
```

#### Шаг 3: Настройка окружения

```bash
# Добавление записи в локальный hosts
echo "$(minikube ip) registry.test" | sudo tee -a /etc/hosts

# Настройка доверия к реестру в Minikube
minikube ssh "sudo tee /etc/docker/daemon.json <<< '{\"insecure-registries\": [\"registry.test:30000\"]}'"
minikube ssh "sudo systemctl restart docker"
```

#### Шаг 4: Настройка аутентификации в Kubernetes

```bash
kubectl create secret docker-registry regcred \
  --docker-server=registry.test:30000 \
  --docker-username=admin \
  --docker-password=admin \
  --namespace default

# Автоматическое использование секрета для всех подов
kubectl patch serviceaccount default -p '{"imagePullSecrets": [{"name": "regcred"}]}'
```

---

## Дополнительная информация

### Устранение неисправностей

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Pod завис в Pending** | Дефицит ресурсов ноды | Проверить лимиты Minikube через `minikube status` |
| **Certificate не готов (False)** | Ошибка в Issuer или ресурсе | Изучить статус: `kubectl describe certificate -n <namespace>` |
| **Registry возвращает 502/503** | Ingress не видит сервис | Проверить готовность пода в `docker-registry` namespace |
| **Docker push fail (x509)** | Недоверенный сертификат | Проверить `insecure-registries` в конфиге докера или импортировать CA |

### Диагностические команды

```bash
# Проверка работы контроллера
kubectl logs -n cert-manager -l app=cert-manager --tail=50

# Статус всех сертификатов в кластере
kubectl get certificate -A
```

### Связанные материалы

- **[Cert-manager: Администрирование](../../ToolsUtilities/cert_manager/Administration/index.md)**
- **[Minikube: Практические сценарии](../../Installation/minikube/minikube_practical_scenarios.md)**
- **[Реестры Docker: Обзор](../../../Docker/docker_registries.md)**

### Безопасность и масштабирование

> **Внимание:** Данная конфигурация предназначена исключительно для разработки и тестирования.

| Параметр | Текущий (Dev) | Production (рекомендация) |
| :--- | :--- | :--- |
| **Тип сертификатов** | Self-signed | Let's Encrypt или Enterprise PKI |
| **Хранилище реестра** | Local PV (emptyDir) | S3-совместимое хранилище (MinIO, AWS S3) |
| **Аутентификация** | Basic (упрощенная) | OIDC / Интеграция с LDAP |
| **Изоляция** | Отсутствует | Ограничение доступа через NetworkPolicies |

---

**Навигация по руководству:**

- **[Предварительные требования](./lgtm_otel_minikube_prerequisites_environment.md)** (назад)
- **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)** (вперед)
