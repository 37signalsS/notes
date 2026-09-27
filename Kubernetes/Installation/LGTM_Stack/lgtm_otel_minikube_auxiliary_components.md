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
| **Cert-manager** (controller + webhook + cainjector) | 10m / 100m | 32Mi / 128Mi |
| **Docker Registry** (single-binary) | 100m / 500m | 128Mi / 512Mi |
| **Ingress Controller (nginx-minikube)** | 10m / 0 (host) | 20Mi / 0 (host) |

> **Примечание:** В Minikube Ingress-контроллер запускается как аддон и потребляет ресурсы из **host-level**, поэтому request/limit для него не задаются в обычных PVC-подах. Подробнее о ресурсах cert-manager: **[cert-manager: операции](../../ToolsUtilities/cert_manager/Administration/operations.md)**.

---

## Практические сценарии

### Сценарий 1: Установка Cert-manager и настройка внутреннего CA

**Цель:** Развернуть инфраструктуру управления сертификатами и подготовить доверенный источник для кластера.

#### Шаг 1: Установка cert-manager

Используется актуальная версия (на август 2026 г. — v1.21.1, входит в серию `>=1.21.x`). Подробности в SSoT: **[Установка cert-manager](../../ToolsUtilities/cert_manager/installation.md)**.

```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update

helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --set crds.enabled=true \
  --version v1.21.1
```

> **Пояснение параметров:**
> - `crds.enabled=true` — управляет CRD через Helm (в версиях chart v1.14+ параметр `installCRDs` устарел и заменен на `crds.enabled`). Подробнее в [установка через Helm](../../ToolsUtilities/cert_manager/installation.md#сценарий-1-установка-через-helm-рекомендуемый).
> - `helm upgrade --install` (сокращение `upgrade --install`) — идемпотентная команда, создаёт релиз при первом запуске и обновляет при повторном. Это безопаснее `helm install`, так как не требует удаления существующего релиза перед повторным запуском.
> - `--namespace cert-manager --create-namespace` — выделенное пространство имён для компонентов cert-manager (controller, webhook, cainjector).

**Валидация установки:**

```bash
# Проверка, что все 3 компонента cert-manager в статусе Running
kubectl get pods -n cert-manager
# → Expected: cert-manager-*, cert-manager-cainjector-*, cert-manager-webhook-* в статусе Running (1/1 или 2/2)

# Проверка готовности CRDs
kubectl get crd | grep cert-manager.io
# → Expected: certificates.cert-manager.io, certificaterequests.cert-manager.io, challenges.acme.cert-manager.io, ...

# Проверка через cmctl (если установлена)
cmctl check api
# → Expected: API is ready
```

> **Примечание:** Если `cmctl` недоступна, установить её можно по инструкции в SSoT: **[cert-manager: Администрирование](../../ToolsUtilities/cert_manager/Administration/operations.md)**.

#### Шаг 2: Создание ClusterIssuer

> **Концепция двухэтапного CA (Bootstrap-паттерн):** Сначала создаётся временный `selfSigned` Issuer для выпуска корневого сертификата CA, затем на его основе формируется постоянный CA Issuer. Этот паттерн устраняет проблему "курицы и яйца" (для `ca`-issuer нужен Secret, который ещё не создан). Подробнее в SSoT: **[Сценарии приватного CA](../../ToolsUtilities/cert_manager/Private_CA/scenarios.md#сценарий-4-начальное-создание-внутреннего-ca-bootstrap)**.

```yaml
# Создание временного self-signed ClusterIssuer для выпуска корневого CA
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: minikube-ca
spec:
  selfSigned: {}
EOF

# Создание корневого CA-сертификата (Root CA)
# Подробности параметров: [Certificate: структура ресурса](../../ToolsUtilities/cert_manager/definitions.md#структура-ресурса-certificate)
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
  duration: 43800h       # 5 лет (стандарт для Root CA)
  renewBefore: 720h      # 30 дней до истечения
  privateKey:
    algorithm: ECDSA
    size: 256
    rotationPolicy: Never  # Root CA ротируется вручную
  issuerRef:
    name: minikube-ca
    kind: ClusterIssuer
    group: cert-manager.io
EOF

# Создание постоянного ClusterIssuer на базе выпущенного CA
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

**Валидация выпуска сертификатов:**

```bash
# Проверка, что корневой сертификат создан и готов
kubectl get certificate minikube-ca-root -n cert-manager
# → Expected: READY=True

# Проверка наличия Secret с CA
kubectl get secret minikube-ca-secret -n cert-manager -o jsonpath='{.data.ca\.crt}' | base64 -d | openssl x509 -text -noout | head -10
# → Expected: выводит информацию о сертификате CA (Version, Serial, Signature Algorithm, Issuer, Validity, Subject)

# Проверка ClusterIssuer
kubectl get clusterissuer minikube-ca-issuer
# → Expected: STATUS=Ready, CONDITIONS с True
```

---

### Сценарий 1.5: Подготовка DNS-записей для Ingress

**Цель:** Добавить все необходимые DNS-записи в `/etc/hosts` на хост-машине, чтобы Ingress-контроллер Minikube мог маршрутизировать трафик к сервисам стека LGTM и локальному реестру.

```bash
# Получение IP Minikube (один раз)
MINIKUBE_IP=$(minikube ip)
echo "Minikube IP: $MINIKUBE_IP"

# Добавление всех DNS-записей для Ingress
for host in grafana.test loki.test tempo.test registry.test; do
  grep -q "$host" /etc/hosts || echo "$MINIKUBE_IP $host" | sudo tee -a /etc/hosts
done

# Проверка
cat /etc/hosts | grep -E "grafana\.test|registry\.test|loki\.test|tempo\.test"
# → Expected: 4 строки с IP Minikube и именами хостов
```

> **Примечание:** Ingress-контроллер (nginx) в Minikube уже запущен как аддон (`--addons=ingress` в `minikube start`). DNS-записи нужны только на хост-машине для доступа к сервисам через Ingress. Подробнее: **[Minikube: Практические сценарии](../../Installation/minikube/minikube_practical_scenarios.md)**.

**Цель:** Обеспечить хранилище для артефактов внутри кластера с поддержкой TLS и персистентности.

> **Архитектурная записка:** В Minikube с `--driver=docker` узел работает как отдельный контейнер, и его внутренний Docker daemon используется `kubelet` для загрузки образов подов. Параметр `--insecure-registry="10.0.0.0/24"` (заданный в `minikube start` во [Сценарии 4 подготовки окружения](./lgtm_otel_minikube_prerequisites_environment.md)) уже разрешает не-TLS доступ для IP-адресов в этом CIDR. Кроме того, DNS-запись `registry.test` уже добавлена в [Сценарии 1.5](#сценарий-15-подготовка-dns-записей-для-ingress).

#### Шаг 1: Настройка Helm-репозитория

Репозиторий `twuni` является официальным Helm-чартом для Docker Registry (CNCF Distribution).

```bash
helm repo add twuni https://twuni.github.io/docker-registry.helm
helm repo update
```

#### Шаг 2: Установка реестра

Для обеспечения сохранности образов рекомендуется использовать `persistence`. В Minikube это создаст `HostPath PVC` через `standard` StorageClass (провижионер `k8s.io/minikube-hostpath`).

```bash
helm upgrade --install docker-registry twuni/docker-registry \
  --namespace docker-registry \
  --create-namespace \
  --set service.type=NodePort \
  --set service.nodePort=30000 \
  --set ingress.enabled=true \
  --set ingress.hosts[0]=registry.test \
  --set ingress.tls[0].secretName=registry-tls \
  --set ingress.annotations."cert-manager.io/cluster-issuer"=minikube-ca-issuer \
  --set persistence.enabled=true \
  --set persistence.size=10Gi \
  --set persistence.storageClass=standard
```

> **Пояснение параметров:**
> - `service.type=NodePort` + `service.nodePort=30000` — реестр доступен извне на порту `30000` (в диапазоне NodePort 30000–32767).
> - `ingress.annotations."cert-manager.io/cluster-issuer"=minikube-ca-issuer` — автоматически выпускает TLS-сертификат для `registry.test` через настроенный ClusterIssuer.
> - `persistence.storageClass=standard` — явное указание StorageClass (иначе может использоваться `manual` или другой дефолтный).

#### Шаг 3: Настройка окружения для работы с реестром

```bash
# Настройка доверяемого Docker daemon внутри Minikube
# Необходимо, чтобы kubelet и minikube image могли работать с реестром
# без проверки TLS (самоподписанный сертификат)
minikube ssh "echo '{\"insecure-registries\": [\"registry.test:30000\"]}' | sudo tee /etc/docker/daemon.json"
minikube ssh "sudo systemctl restart docker"
# → Ожидается: перезапуск завершен без ошибок

# Проверка, что daemon принял конфигурацию
minikube ssh "cat /etc/docker/daemon.json"
# → Expected: {"insecure-registries": ["registry.test:30000"]}

# Проверка доступности реестра изнутри Minikube (через NodePort на localhost)
minikube ssh -- curl -s http://127.0.0.1:30000/v2/_catalog
# → Expected: {"repositories":[]}

# Проверка доступности реестра из хоста (через NodePort на IP Minikube)
curl -s http://$(minikube ip):30000/v2/_catalog
# → Expected: {"repositories":[]}
```

> **Альтернатива для сборки образов:** Вместо `docker push` с настройкой insecure-реестра можно использовать `minikube image`, который загружает образ прямо в Docker daemon Minikube без публикации в реестр:
> ```bash
> minikube image build -t my-app:v1 ./app/
> ```
> Этот метод не требует настройки `insecure-registries` и подходит для быстрой разработки. Однако для CI/CD и воспроизводимых сборок предпочтительнее использовать Registry.

#### Шаг 4: Настройка аутентификации в Kubernetes

Подробнее о типах секретов и best practices: **[Secret: создание](../../Base/secrets/creating_secrets.md)** и **[Secret: использование](../../Base/secrets/using_secrets.md)**.

```bash
# Создание ImagePullSecret для доступа к локальному реестру
# Используется тип docker-registry (kubernetes.io/dockerconfigjson)
kubectl create secret docker-registry regcred \
  --docker-server=registry.test:30000 \
  --docker-username=admin \
  --docker-password=admin \
  --docker-email=admin@example.com \
  --namespace default \
  --dry-run=client -o yaml | kubectl apply -f -

# Автоматическое добавление секрета в ServiceAccount default
# Подробнее: [imagePullSecrets](../../Base/secrets/using_secrets.md#использование-imagepullsecrets)
kubectl patch serviceaccount default -p '{"imagePullSecrets": [{"name": "regcred"}]}'
```

> **Важно:** Если вы используете `--namespace <other-ns>` для подов, повторите создание `regcred` и `patch serviceaccount` в каждом namespace.

---

## Дополнительная информация

### Устранение неисправностей

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Pod завис в Pending** | Дефицит ресурсов ноды Minikube | Проверить лимиты: `minikube status`, `kubectl describe node`. Увеличить `--memory`/`--cpus` при необходимости |
| **Certificate не готов (False)** | Ошибка в ClusterIssuer или CA-секрет | Изучить события: `kubectl describe certificate minikube-ca-root -n cert-manager`. Проверить Secret: `kubectl describe clusterissuer minikube-ca-issuer` |
| **Cert-manager не назначает сертификат Ingress** | Аннотация cluster-issuer не найдена или Issuer не Ready | Проверить аннотацию: `kubectl describe ingress <name>`. Убедиться, что `minikube-ca-issuer` в статусе Ready |
| **Registry возвращает 502/503** | Ingress не видит сервис или readinessProbe не проходит | Проверить readinessProbe: `kubectl describe pod -n docker-registry`. Проверить сервис: `kubectl get svc -n docker-registry` |
| **Docker push fail (x509: certificate signed by unknown authority)** | Docker daemon не доверяет самоподписанному сертификату | Добавить CA в `/etc/docker/certs.d/registry.test:30000/ca.crt` на хосте, либо использовать `insecure-registries` (см. Шаг 3) |
| **ImagePullBackOff** | Секрет `regcred` не найден в namespace пода | Убедиться, что секрет создан в том же namespace. Проверить: `kubectl get secret regcred -n <namespace>` |
| **minikube ssh: systemctl restart docker зависает** | Docker daemon в Minikube зависш | Подождите 30 сек. Если не помогает: `minikube ssh -- sudo systemctl restart docker --no-block` |
| **Ingress возвращает 404** | TLS-секрет не создан или сертификат в состоянии Pending | Проверить: `kubectl get certificate,secret -A \| grep registry`. Дождитесь READY=True у Certificate |

### Диагностические команды

```bash
# Проверка статуса ресурсов cert-manager
# Примечание: для self-signed и CA-issuer не создаются ресурсы Order/Challenge
# (они существуют только для ACME). Используйте:
kubectl get clusterissuer,certificate,certificaterequest -A

# Детальная проверка сертификата CA
kubectl describe certificate minikube-ca-root -n cert-manager
kubectl describe clusterissuer minikube-ca-issuer

# Логи контроллера при ошибках выпуска
kubectl logs -n cert-manager -l app=cert-manager --tail=50

# Проверка выдачи сертификата для registry
kubectl get certificate -n docker-registry
kubectl get secret registry-tls -n docker-registry -o yaml

# Проверка монтирования томов и состояния пода реестра
kubectl describe pod -n docker-registry -l app=docker-registry

# Проверка PVC реестра
kubectl get pvc -n docker-registry

# Проверка доступности реестра изнутри кластера (из namespace default)
kubectl run -it --rm debug-pod --image=curlimages/curl --restart=Never -- \
  curl -s http://docker-registry.docker-registry:5000/v2/_catalog
```

### Связанные материалы

- **[Cert-manager: Определения и концепции](../../ToolsUtilities/cert_manager/definitions.md)** — архитектура, CRD, жизненный цикл ACME
- **[Cert-manager: Установка](../../ToolsUtilities/cert_manager/installation.md)** — методы развертывания (Helm, kubectl, OCI)
- **[Cert-manager: Сценарии приватного CA](../../ToolsUtilities/cert_manager/Private_CA/scenarios.md)** — двухуровневая иерархия, Bootstrap, trust-manager
- **[Cert-manager: Администрирование](../../ToolsUtilities/cert_manager/Administration/index.md)** — мониторинг, backup, ротация сертификатов
- **[Minikube: Практические сценарии](../minikube/minikube_practical_scenarios.md)**
- **[Реестры Docker: Обзор](../../../Docker/docker_registries.md)**
- **[Secret: создание](../../Base/secrets/creating_secrets.md)** — типы секретов, `docker-registry`

### Безопасность и масштабирование

> **Внимание:** Данная конфигурация предназначена исключительно для разработки и тестирования.

| Параметр | Текущий (Dev) | Production (рекомендация) |
| :--- | :--- | :--- |
| **Тип сертификатов** | CA на базе Self-signed | Let's Encrypt (ACME HTTP-01/DNS-01) или корпоративный CA (HashiCorp Vault PKI) |
| **Хранилище реестра** | Local PV (hostPath) | MinIO (S3-совместимый on-premise) или Rook/Ceph (распределённое хранилище) |
| **Аутентификация** | Basic (статическая, plaintext) | OIDC (Keycloak, Dex) / интеграция с корпоративным LDAP/Active Directory |
| **Изоляция** | Отсутствует (общий namespace) | NetworkPolicies, выделенные NodePools, выделенные namespace per-сервис |
| **Управление секретами** | Kubernetes Secrets (base64) | HashiCorp Vault (K8sSecretsStore CSI) или Sealed Secrets |

> **Примечание:** Для on-premise production-окружений рекомендуется использовать MinIO вместо облачных S3-совместимых хранилищ. MinIO можно развернуть напрямую в Kubernetes через официальный Helm-чарт и интегрировать с cert-manager для TLS.

---

### Очистка вспомогательных компонентов

Для удаления только вспомогательных компонентов (cert-manager и Docker Registry), не затрагивая стек LGTM:

```bash
# 1. Удаление Docker Registry и связанных ресурсов
helm uninstall docker-registry -n docker-registry
kubectl delete namespace docker-registry

# 2. Удаление ImagePullSecret и снятие patch ServiceAccount
kubectl delete secret regcred -n default --ignore-not-found
kubectl patch serviceaccount default -p '{"imagePullSecrets": []}'

# 3. Удаление записей из /etc/hosts (если добавлялись в Сценарии 1.5)
sudo sed -i '' '/registry\.test/d' /etc/hosts
sudo sed -i '' '/grafana\.test/d' /etc/hosts
sudo sed -i '' '/loki\.test/d' /etc/hosts
sudo sed -i '' '/tempo\.test/d' /etc/hosts

# 4. Удаление cert-manager (опционально — если остальной стек тоже удаляется)
# Подробнее: [cert-manager: удаление](../../ToolsUtilities/cert_manager/installation.md#сценарий-7-удаление-системы)
helm uninstall cert-manager -n cert-manager
kubectl delete namespace cert-manager
kubectl delete crd -l app.kubernetes.io/part-of=cert-manager
```

> **Важно:** Шаг 4 удаляет все CRD cert-manager, включая ресурсы `Certificate`, `ClusterIssuer` и `CertificateRequest`. Если стек LGTM ещё используется и нуждается в TLS-сертификатах, не выполняйте шаг 4.

---

**Навигация по руководству:**

- **[Предварительные требования](./lgtm_otel_minikube_prerequisites_environment.md)** (назад)
- **[Развертывание стека LGTM](./lgtm_otel_minikube_lgtm_stack_deployment.md)** (вперед)
- **[Обзор стека](./lgtm_otel_minikube_overview.md)** (содержание)
