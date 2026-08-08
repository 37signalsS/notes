# Установка cert-manager

## Определения

**Установка cert-manager** — процесс развёртывания контроллера и сопутствующих CRD в кластере Kubernetes для автоматизации управления TLS-сертификатами. Официальная документация: [cert-manager.io/docs/installation](https://cert-manager.io/docs/installation/).

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
| **kubectl apply** | Максимальная простота, отсутствие внешних зависимостей. | Сложность обновления и кастомизации параметров. | Быстрые тесты, простые CI-пайплайны. |
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

| Параметр | Назначение | По умолчанию |
| :--- | :--- | :--- |
| `installCRDs` | Автоматическая установка CRD. | `false` |
| `replicaCount` | Количество реплик основного контроллера. | `1` |
| `webhook.replicaCount` | Количество реплик вебхука. | `1` |
| `webhook.timeoutSeconds` | Таймаут вызова вебхука. | `10` |
| `prometheus.enabled` | Экспорт метрик для Prometheus. | `true` |
| `extraArgs` | Дополнительные флаги запуска контроллера. | `{}` |

### Смотрите также

- **[Администрирование: Операции](./Administration/operations.md)** — обновление до v1.22+ и стратегии ротации.
- **[Приватный CA: Сценарии](./Private_CA/scenarios.md)** — использование trust-manager Bundle.
- **[Troubleshooting](./Administration/troubleshooting.md)** — диагностика проблем с вебхуком и API.
