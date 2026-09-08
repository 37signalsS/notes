# Установка cert-manager

## Определения

**Установка cert-manager** — процесс развёртывания контроллера и сопутствующих CRD в кластере Kubernetes для автоматизации управления TLS-сертификатами. Официальная документация: [cert-manager.io/docs/installation](https://cert-manager.io/docs/installation/).

**Предварительные требования (Prerequisites)** — минимальный набор компонентов, версий и состояния кластера, необходимых для успешной установки cert-manager без конфликтов.

**Namespace-стратегия** — подход к размещению ресурсов cert-manager и связанных объектов в кластере для обеспечения изоляции, безопасности и удобства администрирования.

**Связанные темы:**

- **[Определения и концепции](./definitions.md)** — архитектура, CRD и жизненный цикл ACME.
- **[Администрирование: Операции](./Administration/operations.md)** — мониторинг, резервное копирование и стратегии обновления.
- **[Диагностика (Troubleshooting)](./Administration/troubleshooting.md)** — решение проблем с установкой и выпуском.
- **[Приватный CA: Сценарии](./Private_CA/scenarios.md)** — настройка внутренних иерархий и trust-manager.

---

## Основные концепции

### Методы развёртывания

| Метод | Преимущества | Недостатки | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Helm** | Управление версиями, шаблонизация (values), поддержка атомарных откатов. | Требует Helm-клиент в инфраструктуре. | **Стандарт для Production** |
| **kubectl apply** | Максимальная простота, отсутствие внешних зависимостей. | Сложность обновления и кастомизации параметров. | Быстрые тесты, простые CI-пайплайны, air-gapped среды. |
| **Operator Hub** | Автоматизированное управление жизненным циклом в OpenShift. | Зависимость от Operator Lifecycle Manager (OLM). | Среды Red Hat OpenShift. |

### Предварительные требования (версии 2026 года)

| Требование | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| **Kubernetes** | 1.25+ | Рекомендуется 1.30+ для полной поддержки Gateway API. |
| **kubectl** | 1.25+ | Должен соответствовать версии кластера. |
| **Helm** | 3.12+ | Требуется для поддержки OCI-репозиториев и новых схем валидации. |
| **cmctl** | 1.21+ | CLI-утилита для проверки и диагностики (заменяет плагин kubectl). |
| **Gateway API** | v1.1.0+ | Должен быть установлен **строго до** cert-manager. |

### Компоненты системы

При стандартной установке развёртываются три основных пода:
1. **cert-manager-controller**: Основная логика управления ресурсами (Issuer, Certificate).
2. **cert-manager-webhook**: Валидация ресурсов при создании/изменении и поддержка мутаций.
3. **cert-manager-cainjector**: Настройка доверия для системных вебхуков и агрегированных API.

### Проверка готовности кластера

Перед установкой cert-manager выполните pre-flight проверки. Отсутствие любого из компонентов приведёт к ошибкам установки или блокировке API.

```bash
#!/bin/bash
set -euo pipefail

echo "=== Проверка предварительных требований cert-manager ==="

# 1. Проверка kubectl и контекста
echo "[1/5] Проверка kubectl и контекста..."
kubectl version --client --short
kubectl cluster-info
CURRENT_CONTEXT=$(kubectl config current-context)
echo "Текущий контекст: ${CURRENT_CONTEXT}"

# 2. Проверка версии Kubernetes
echo "[2/5] Проверка версии Kubernetes..."
K8S_VERSION=$(kubectl version -o jsonpath='{.serverVersion.major}.{.serverVersion.minor}')
echo "Версия сервера: ${K8S_VERSION}"

# 3. Проверка доступных ресурсов
echo "[3/5] Проверка ресурсов нод..."
kubectl top nodes 2>/dev/null || echo "Metrics Server не установлен, пропуск проверки ресурсов"

# 4. Проверка существующих CRD cert-manager
echo "[4/5] Проверка существующих CRD..."
if kubectl get crd | grep -q cert-manager; then
  echo "ВНИМАНИЕ: CRD cert-manager уже существуют в кластере!"
  kubectl get crd | grep cert-manager
  read -p "Продолжить установку? (y/N) " -n 1 -r
  echo
  if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
  fi
else
  echo "CRD cert-manager не найдены — можно продолжать."
fi

# 5. Проверка Gateway API (опционально)
echo "[5/5] Проверка Gateway API..."
if kubectl get crd gateways.gateway.networking.k8s.io &>/dev/null; then
  echo "Gateway API CRD обнаружены."
else
  echo "Gateway API CRD не найдены. Если планируется использование Gateway API, установите их ДО cert-manager."
fi

echo "=== Pre-flight проверка завершена ==="
```

### Namespace-стратегия

Правильный выбор namespace снижает риск конфликтов и упрощает администрирование.

```bash
# 1. Создание выделенного namespace для cert-manager
kubectl create namespace cert-manager --dry-run=client -o yaml | kubectl apply -f -

# 2. Явное ограничение ресурсов (рекомендуется для Production)
kubectl apply -f - <<EOF
apiVersion: v1
kind: ResourceQuota
metadata:
  name: cert-manager-quota
  namespace: cert-manager
spec:
  hard:
    requests.cpu: "2"
    requests.memory: 4Gi
    limits.cpu: "4"
    limits.memory: 8Gi
    pods: "20"
EOF

# 3. Создание service account (опционально, для кастомной RBAC)
kubectl create serviceaccount cert-manager -n cert-manager --dry-run=client -o yaml | kubectl apply -f -
```

**Рекомендации:**
- **Изоляция:** Используйте выделенный namespace `cert-manager` для системных компонентов. Не размещайте их в `default` или `kube-system`.
- **RBAC:** Ограничьте доступ к namespace `cert-manager` только администраторам PKI. Секреты с CA-ключами должны быть доступны минимуму сервисных аккаунтов.
- **Мультитенантность:** Для командных Issuer используйте namespace-scoped `Issuer` в namespace команды, а `ClusterIssuer` размещайте в `cert-manager` или `security`.

---

## Практические сценарии

### Сценарий 1: Установка через Helm (Рекомендуемый)

**1. Добавление репозитория:**

```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update
```

**2. Установка Gateway API (опционально):**

Если планируется использование Gateway API, CRD должны быть в кластере до запуска основного контроллера cert-manager.

```bash
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.1.0/standard-install.yaml
```

**3. Установка контроллера:**

Для версии `v1.21.0` (актуальная стабильная на август 2026):

```bash
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.21.0 \
  --set installCRDs=true \
  --set global.leaderElection.namespace=cert-manager
```

**Альтернатива через OCI (рекомендуется для изолированных сред):**

```bash
helm install cert-manager oci://quay.io/jetstack/charts/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.21.0 \
  --set crds.enabled=true
```

---

### Сценарий 1.5: Установка через kubectl apply (YAML-манифесты)

Подходит для сред без Helm, минималистичных CI-пайплайнов или быстрого тестирования.

**1. Применение манифестов:**

```bash
# Установка CRD и всех компонентов через единый манифест
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.21.0/cert-manager.yaml

# Или: установка только CRD (для ручного управления)
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.21.0/cert-manager.crds.yaml
```

**2. Проверка установки:**

```bash
# Проверка CRD
kubectl get crd | grep cert-manager

# Проверка подов
kubectl get pods -n cert-manager
```

**Особенности метода:**
- При `helm uninstall` CRD не удаляются (управляются отдельно).
- Для обновления требуется скачать новый манифест и применить его.
- Кастомизация параметров (replicaCount, ресурсы) выполняется через patches или отдельные манифесты.

---

### Сценарий 2: Установка в Production с ручным управлением CRD

В критических средах рекомендуется управлять CRD отдельно от Helm-чарта, чтобы избежать их случайного удаления при `helm uninstall`.

**1. Установка CRD:**

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.21.0/cert-manager.crds.yaml
```

**2. Установка чарта с отключенным управлением CRD:**

```bash
helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --version v1.21.0 \
  --set installCRDs=false
```

---

### Сценарий 3: Дополнительные компоненты и расширения

#### Включение поддержки Gateway API

Если CRD были установлены (см. Сценарий 1, шаг 2), включите поддержку в контроллере:

```bash
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --reuse-values \
  --set "extraArgs={--enable-gateway-api=true}"
```

#### Установка trust-manager (Дистрибуция CA)

Для автоматического распространения корневых сертификатов во все Namespace:

```bash
helm install trust-manager jetstack/trust-manager \
  --namespace cert-manager \
  --version v0.7.0 \
  --set app.trust.namespace=cert-manager
```

#### Настройка Garbage Collection (Owner References)

Для автоматического удаления Secret при удалении Certificate:

```bash
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --reuse-values \
  --set "extraArgs={--enable-certificate-owner-ref=true}"
```

---

### Сценарий 4: Установка cert-manager-csi-driver

Позволяет монтировать сертификаты напрямую в поды без использования Kubernetes Secrets.

**1. Установка драйвера через Helm:**

```bash
helm upgrade --install cert-manager-csi-driver jetstack/cert-manager-csi-driver \
  --namespace cert-manager \
  --set "app.certManager.namespace=cert-manager" \
  --set "app.driver.name=csi.cert-manager.io"
```

**2. Пример использования в Pod:**

```yaml
volumes:
  - name: tls
    csi:
      driver: csi.cert-manager.io
      readOnly: true
      volumeAttributes:
        csi.cert-manager.io/issuer-name: letsencrypt-prod
        csi.cert-manager.io/dns-names: app.example.com
```

---

### Сценарий 5: Конфигурация высокой доступности (HA)

Для обеспечения отказоустойчивости в Production рекомендуется запускать компоненты в нескольких репликах.

```bash
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --set replicaCount=3 \
  --set webhook.replicaCount=3 \
  --set cainjector.replicaCount=2 \
  --set global.leaderElection.namespace=cert-manager
```

*Примечание: `replicaCount` настраивает количество подов для основного контроллера, а `webhook.replicaCount` — для вебхука.*

---

### Подготовка air-gapped среды

В изолированных кластерах cert-manager не может загружать образы или обращаться к ACME-серверам. Подготовка делится на три этапа.

**1. Зеркалирование образов:**

```bash
# Список требуемых образов (v1.21.0)
IMAGES=(
  "quay.io/jetstack/cert-manager-controller:v1.21.0"
  "quay.io/jetstack/cert-manager-webhook:v1.21.0"
  "quay.io/jetstack/cert-manager-cainjector:v1.21.0"
  "quay.io/jetstack/trust-manager:v0.7.0"
  "quay.io/jetstack/cert-manager-csi-driver:v0.5.0"
)

# Пример: перенос во внутренний registry через skopeo
for img in "${IMAGES[@]}"; do
  skopeo copy docker://"${img}" docker://internal-registry.io/"${img##*/}"
done
```

**2. Установка через OCI с внутренним registry:**

```bash
helm install cert-manager oci://internal-registry.io/jetstack/charts/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.21.0 \
  --set crds.enabled=true \
  --set image.repository=internal-registry.io/jetstack/cert-manager-controller \
  --set webhook.image.repository=internal-registry.io/jetstack/cert-manager-webhook \
  --set cainjector.image.repository=internal-registry.io/jetstack/cert-manager-cainjector
```

**3. Предварительное создание секретов:**

```bash
# Предварительно загрузите корневые CA в secrets
kubectl create secret generic internal-root-ca \
  --namespace=cert-manager \
  --from-file=ca.crt=./internal-root-ca.pem

# Создайте ClusterIssuer ДО установки контроллера
kubectl apply -f internal-clusterissuer.yaml
```

**См. также:** [Приватный CA: Сценарии](./Private_CA/scenarios.md#сценарий-9-работа-в-изолированной-среде-air-gapped)

---

### Сценарий 6: Проверка и верификация

**1. Проверка статуса подов:**

```bash
kubectl get pods -n cert-manager
# → Должно быть 3+ пода в статусе Running
```

**2. Проверка через cmctl (Рекомендуется):**

```bash
# Проверка готовности API
cmctl check api

# Проверка статуса установки
cmctl status certificate cert-example-tls -n default
```

**3. Тестовый самоподписанный выпуск:**

```yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: test-selfsigned
  namespace: default
spec:
  selfSigned: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: test-cert
  namespace: default
spec:
  dnsNames:
    - example.com
  secretName: test-cert-tls
  issuerRef:
    name: test-selfsigned
```

**4. Расширенная проверка компонентов:**

```bash
# Проверка CRD и их версий API
kubectl get crd | grep cert-manager
kubectl get crd certificates.cert-manager.io -o jsonpath='{.spec.versions[*].name}'

# Проверка webhook-конфигураций
kubectl get validatingwebhookconfigurations | grep cert-manager
kubectl get mutatingwebhookconfigurations | grep cert-manager

# Проверка ServiceAccount и RBAC
kubectl get sa -n cert-manager
kubectl get clusterrole | grep cert-manager
kubectl get clusterrolebinding | grep cert-manager
```

**5. Установка и проверка cmctl:**

```bash
# macOS (Homebrew)
brew install cert-manager/tools/cmctl

# Или скачивание бинарника
curl -L https://github.com/cert-manager/cert-manager/releases/download/v1.21.0/cmctl-darwin-amd64.tar.gz -o cmctl.tar.gz
tar xvzf cmctl.tar.gz
sudo mv cmctl /usr/local/bin

# Проверка установки
cmctl version
cmctl check api --wait=2m
```

---

### Типичные проблемы при установке

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| `ImagePullBackOff` / `ErrImagePull` | Образ недоступен в registry | Проверьте доступность registry, в air-gapped средах используйте внутренний registry. |
| `CrashLoopBackOff` (webhook) | Недостаток памяти или конфликт портов | Увеличьте `webhook.resources.limits.memory`, проверьте, что порт 9443 свободен. |
| `Failed calling webhook` | CABundle устарел или вебхук недоступен | Выполните `kubectl rollout restart deployment cert-manager-webhook -n cert-manager`. |
| `cert-manager-webhook` не готов | Ошибка загрузки TLS-сертификата | Проверьте `cainjector` логи: `kubectl logs -n cert-manager -l app.kubernetes.io/component=cainjector`. |
| CRD Conflict | Установка поверх существующих CRD | Удалите старые CRD: `kubectl delete crd certificates.cert-manager.io` и повторите установку. |
| `Forbidden` при создании ресурсов | Недостаточно прав RBAC | Проверьте `ClusterRole` и `ClusterRoleBinding` для сервисного аккаунта cert-manager. |

---

### Сценарий 7: Удаление системы

> **Предупреждение:** Удаление CRD приведет к безвозвратному удалению всех ресурсов Certificate, Issuer и ClusterIssuer.

**1. Удаление через Helm:**

```bash
helm uninstall cert-manager -n cert-manager
```

**2. Ручное удаление CRD (если устанавливались отдельно):**

```bash
kubectl delete -f https://github.com/cert-manager/cert-manager/releases/download/v1.21.0/cert-manager.crds.yaml
```

---

## Дополнительная информация

### Параметры конфигурации Helm

| Параметр | Назначение | Значение для Production | По умолчанию |
| :--- | :--- | :--- | :--- |
| `installCRDs` | Автоматическая установка CRD. | `false` (управляйте CRD отдельно) | `false` |
| `replicaCount` | Количество реплик основного контроллера. | `3` | `1` |
| `webhook.replicaCount` | Количество реплик вебхука. | `3` | `1` |
| `cainjector.replicaCount` | Количество реплик cainjector. | `2` | `1` |
| `webhook.timeoutSeconds` | Таймаут вызова вебхука. | `10` | `10` |
| `prometheus.enabled` | Экспорт метрик для Prometheus. | `true` | `true` |
| `extraArgs` | Дополнительные флаги запуска контроллера. | `--enable-certificate-owner-ref=true` | `{}` |
| `global.leaderElection.namespace` | Namespace для leader election. | `cert-manager` | `cert-manager` |
| `global.networkPolicy.enabled` | Включить NetworkPolicy для контроллера. | `true` (v1.20+) | `false` |

**Пример values.yaml для Production:**

```yaml
# values.yaml
replicaCount: 3
webhook:
  replicaCount: 3
  timeoutSeconds: 10
  resources:
    requests:
      memory: "128Mi"
      cpu: "50m"
    limits:
      memory: "512Mi"
      cpu: "250m"
cainjector:
  replicaCount: 2
  resources:
    requests:
      memory: "64Mi"
      cpu: "25m"
    limits:
      memory: "256Mi"
      cpu: "100m"
controller:
  replicaCount: 3
  resources:
    requests:
      memory: "256Mi"
      cpu: "100m"
    limits:
      memory: "1Gi"
      cpu: "500m"
extraArgs:
  - --enable-certificate-owner-ref=true
  - --enable-gateway-api=true
```

### Лучшие практики

1. **Управляйте CRD отдельно** в Production. Используйте `installCRDs=false` и применяйте CRD через отдельный манифест или GitOps.
2. **Используйте OCI-репозитории** в изолированных средах. Helm с OCI не требует дополнительных индексных файлов.
3. **Настраивайте ресурсные квоты** для namespace `cert-manager`, чтобы предотвратить утечку памяти в другие namespace.
4. **Включайте `ownerReference`** через `--enable-certificate-owner-ref=true` для автоматической очистки секретов.
5. **Устанавливайте Gateway API до cert-manager**, если планируется его использование. Порядок имеет значение.
6. **Используйте cmctl** для диагностики после установки. Утилита заменила плагин kubectl и является стандартом 2026 года.
7. **Ротация CA-ключей:** Храните резервные копии Secrets с приватными ключами промежуточных CA в защищенном хранилище (Vault, AWS Secrets Manager) вне кластера.

### Смотрите также

- **[Администрирование: Операции](./Administration/operations.md)** — обновление до v1.22+ и стратегии ротации.
- **[Администрирование: Index](./Administration/index.md)** — HA, RBAC, NetworkPolicy и Garbage Collection.
- **[Приватный CA: Сценарии](./Private_CA/scenarios.md)** — использование trust-manager Bundle.
- **[Troubleshooting](./Administration/troubleshooting.md)** — диагностика проблем с вебхуком и API.
