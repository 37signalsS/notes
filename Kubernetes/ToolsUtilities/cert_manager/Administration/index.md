# Администрирование cert-manager в Kubernetes

## Определения

**Администрирование cert-manager** — процесс настройки системных политик, обеспечения отказоустойчивости (HA), управления доступом (RBAC) и контроля жизненного цикла ресурсов для обеспечения надежной работы инфраструктуры открытых ключей (PKI) в кластере.

**Garbage Collection (Сборка мусора)** — механизм автоматической очистки связанных ресурсов (например, Kubernetes Secret) при удалении родительского объекта `Certificate`.

**Policy Enforcement (Обеспечение политик)** — использование внешних контроллеров (Kyverno, OPA) или внутренних настроек cert-manager для принудительного соблюдения стандартов безопасности (алгоритмы ключей, сроки действия).

---

## Основные концепции

### Управление жизненным циклом и ресурсами

#### Автоматическая очистка секретов (Garbage Collection)

По умолчанию cert-manager не удаляет `Secret` при удалении ресурса `Certificate`. Это предотвращает случайную потерю рабочих сертификатов, но приводит к накоплению неиспользуемых данных в etcd.

*   **Рекомендация:** Включайте флаг `--enable-certificate-owner-ref=true` через Helm. Это добавляет `ownerReference` к секрету, связывая его жизненный цикл с `Certificate`.
*   **Особенность:** При использовании GitOps (ArgoCD) убедитесь, что механизмы синхронизации не конфликтуют с автоматическим удалением секретов.

#### Лимиты истории запросов (revisionHistoryLimit)

Начиная с **v1.18+**, параметр `revisionHistoryLimit` по умолчанию равен **1** (ранее ресурсы `CertificateRequest` могли накапливаться бесконечно).
*   **Администрирование:** В высоконагруженных кластерах убедитесь, что это значение не завышено, чтобы минимизировать нагрузку на API-сервер и etcd.

#### Политика ротации ключей (rotationPolicy)

Определяет поведение контроллера при продлении сертификата:
*   `Never` (старый стандарт): Приватный ключ остается прежним.
*   `Always` (рекомендуется): При каждом продлении генерируется новый приватный ключ. Это соответствует требованиям **Perfect Forward Secrecy (PFS)**.

### Высокая доступность и производительность (HA)

Для обеспечения непрерывности работы (High Availability) cert-manager должен быть развернут в нескольких репликах. Дополнительно к репликам критически важны **PodDisruptionBudget** (защита от плановых обслуживаний узлов) и явные лимиты памяти.

| Компонент | HA-механизм | Рекомендация |
| :--- | :--- | :--- |
| **Controller** | Leader Election | 2+ реплики. Только одна активна (лидер), остальные в режиме ожидания. |
| **Webhook** | Load Balancing | 3 реплики. Критично для доступности API (создание ресурсов). |
| **CA Injector** | Leader Election | 2 реплики. Отвечает за инжекцию CA в CRD и Webhooks. |

**Ресурсы (Resources):** При большом количестве сертификатов (>500) увеличьте лимиты памяти для контроллера, так как он держит кэш ресурсов в памяти. Для webhook критична минимальная задержка (latency-sensitive), поэтому выделяйте ему отдельные requests/limits.

#### PodDisruptionBudget (PDB)

PDB защищает cert-manager от одновременного выселения всех реплик при `kubectl drain` или обновлении узлов кластера.

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: cert-manager-webhook-pdb
  namespace: cert-manager
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: cert-manager
      app.kubernetes.io/component: webhook
```

*   **Особенность:** PDB блокирует только добровольные прерывания (eviction). При аварийном падении узла PDB не применяется.
*   **Конфликт с Cluster Autoscaler:** Если `minAvailable` слишком жесткий (100%), Cluster Autoscaler не сможет завершить масштабирование узла. Используйте `maxUnavailable: 1` для webhook в высоконагруженных кластерах.

### Безопасность и управление доступом (RBAC)

#### Разделение ответственности

1.  **Инфраструктурный уровень:** Только администраторы кластера имеют права на создание `ClusterIssuer` и настройку DNS-01 секретов в namespace `cert-manager`.
2.  **Прикладной уровень:** Разработчики имеют права на создание `Certificate` и `Issuer` (namespace-scoped), но не могут изменять системные настройки контроллера.

#### Сетевая изоляция (v1.20+)

Начиная с версии **v1.20**, Helm-чарт поддерживает нативные `NetworkPolicy`.
*   **Egress:** Ограничьте доступ контроллера только к API-серверу Kubernetes и эндпоинтам центров сертификации (Let's Encrypt, Vault).
*   **Ingress:** Разрешите входящий трафик к Webhook только из `kube-system` (API-сервер).

---

### Конфигурация Webhook

Webhook cert-manager валидирует ресурсы при создании и обновлении. Неправильная конфигурация может привести к блокировке всего кластера.

*   **failurePolicy:** Рекомендуется значение `Fail` (по умолчанию в новых версиях). При `Ignore` невалидные сертификаты могут попасть в кластер.
*   **timeoutSeconds:** По умолчанию webhook ожидает ответ 10 секунд. При большой нагрузке увеличьте до `30`, но не более — иначе API-сервер будет держать соединения.
*   **Порт метрик:** Webhook экспортирует метрики на порту `9402` (Prometheus формат). Подробнее о настройке алертов: **[Cert-manager: Операции](./operations.md)**.

### Шифрование секретов и защита приватных ключей

Приватные ключи CA и сертификаты хранятся в Kubernetes Secrets. Без дополнительных мер они защищены только RBAC и etcd-шифрованием (при наличии EncryptionConfiguration).

*   **EncryptionConfiguration:** Обязательно включите шифрование `Secrets` на уровне etcd для Production-кластеров.
*   **CSI-драйвер cert-manager (v1.14+):** Генерирует ключи в памяти узла и хранит их в CSI-volume. Приватный ключ никогда не попадает в etcd. Это критично для высокосекретных сред.
*   **RBAC:** Ограничьте доступ к namespace `cert-manager` только администраторами PKI. Секреты с CA-ключами должны быть доступны минимуму сервисных аккаунтов.

### Мониторинг и аудит

Для proactive администрирования необходимо отслеживать не только метрики, но и события Kubernetes.

*   **События (Events):** cert-manager генерирует события `Reason: Readiness` и `Reason: Renewal` при изменении состояния сертификатов. Анализ событий позволяет выявлять проблемы до истечения срока.
*   **Аудит API-сервера:** Включите audit log для ресурсов `cert-manager.io/v1`. Это позволяет отследить, кто создал или изменил Issuer.
*   **Prometheus:** Метрики экспортируются на порту `9402`. Базовый PrometheusRule приведен в **[Cert-manager: Операции](./operations.md)**.

---

## Практические сценарии

### Настройка эталонного ClusterIssuer (стандарты 2026)

При администрировании важно задать глобальные политики через Issuer.

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: security-alerts@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-account-key
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
```

### Принудительное соблюдение стандартов через Kyverno

Пример политики для запрета создания сертификатов с небезопасным алгоритмом RSA 2048:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: enforce-ecdsa-p256
spec:
  validationFailureAction: Enforce
  rules:
  - name: check-ecdsa
    match:
      any:
      - resources:
          kinds:
          - cert-manager.io/v1/Certificate
    validate:
      message: "Все сертификаты должны использовать алгоритм ECDSA P-256."
      pattern:
        spec:
          privateKey:
            algorithm: ECDSA
            size: 256
```

### Масштабирование Webhook для отказоустойчивости

Webhook является критическим узлом: если он недоступен, создание любых ресурсов в кластере может быть заблокировано.

```bash
# Установка через Helm с фокусом на HA и безопасность
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --set installCRDs=true \
  --set replicaCount=3 \
  --set webhook.replicaCount=3 \
  --set cainjector.replicaCount=2 \
  --set "extraArgs={--enable-certificate-owner-ref=true}" \
  --set global.networkPolicy.enabled=true
```

### Защита от плановых обслуживаний (PodDisruptionBudget)

PDB предотвращает одновременное выселение всех реплик cert-manager при обновлении узлов или drain. Без PDB webhook может стать недоступен, блокируя создание любых ресурсов в кластере.

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: cert-manager-webhook-pdb
  namespace: cert-manager
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: cert-manager
      app.kubernetes.io/component: webhook
```

*   **Для air-graded сред:** Если используется `maxUnavailable`, убедитесь, что значение не превышает количество реплик webhook.
*   **Конфликт с Cluster Autoscaler:** PDB с `minAvailable: 100%` блокирует масштабирование узлов. Для кластеров с CA используйте `maxUnavailable: 1`.

### Управление ресурсами компонентов

При больших нагрузках (>1000 сертификатов) cert-manager требует явных лимитов памяти, особенно контроллер и webhook.

```yaml
# Пример ресурсов для контроллера через values.yaml (Helm)
controller:
  resources:
    requests:
      memory: "256Mi"
      cpu: "100m"
    limits:
      memory: "1Gi"
      cpu: "500m"

webhook:
  resources:
    requests:
      memory: "128Mi"
      cpu: "50m"
    limits:
      memory: "512Mi"
      cpu: "250m"
```

*   **QoS:** Для webhook установите `requests == limits` для гарантированного QoS `Guaranteed`. Это защищает webhook от OOM Kill при пиковых нагрузках.
*   **Диагностика нехватки памяти:** Если контроллер перезапужается с `OOMKilled`, увеличивайте лимиты постепенно и мониторьте `container_memory_working_set_bytes`.

### Аудит событий cert-manager

Анализ событий Kubernetes позволяет выявлять проблемы до истечения срока действия сертификатов.

```bash
# Мониторинг событий Readiness и Renewal в реальном времени
kubectl get events -n production --field-selector reason=Readiness,reason=Renewal --watch

# Поиск всех событий cert-manager за последний час
kubectl get events -A --field-selector involvedObject.apiVersion=cert-manager.io/v1 --sort-by='.lastTimestamp'

# Аудит: кто создал или изменил Issuer
kubectl get clusterissuer -o json | jq '.items[] | {name: .metadata.name, managedFields: .metadata.managedFields}'
```

### Восстановление после сбоя (Disaster Recovery)

Потеря CA-секретов (приватных ключей) делает невозможным выпуск новых сертификатов. Подробный алгоритм восстановления и проверка бэкапов описаны в **[Cert-manager: Операции](./operations.md)**.

### Работа в air-gapped средах

В изолированных кластерах cert-manager не может обращаться к публичным ACME-серверам. Используйте внутренние Issuer (Vault, self-signed, CA) и trust-manager для распространения CA-бандлов. Сценарии развертывания: **[Приватный CA: Сценарии](../Private_CA/scenarios.md#сценарий-9-работа-в-изолированной-среде-air-gapped)**.

---

## Безопасность и хранение секретов

### Проблема: приватные ключи в etcd

По умолчанию cert-manager хранит приватные ключи CA и сертификатов в Kubernetes Secrets, которые записываются в etcd в открытом виде (или с шифрованием через EncryptionConfiguration). Компрометация etcd приводит к утечке всех приватных ключей.

### Решение 1: Sealed Secrets

**Sealed Secrets** — контроллер, шифрующий Kubernetes Secrets с помощью RSA-OAEP так, что их безопасно хранить в Git.

```yaml
# Оригинальный Secret (НЕ хранится в Git)
apiVersion: v1
kind: Secret
metadata:
  name: letsencrypt-prod-account-key
  namespace: cert-manager
type: Opaque
data:
  account-key: <base64-encoded-private-key>
```

```yaml
# SealedSecret (БЕЗОПАСНО хранится в Git)
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: letsencrypt-prod-account-key
  namespace: cert-manager
spec:
  encryptedData:
    account-key: AgBy3i4OJSWK+PiTySYZZA9rO...
  template:
    metadata:
      name: letsencrypt-prod-account-key
      namespace: cert-manager
```

**Установка:**
```bash
# Установка Sealed Secrets через Helm
helm install sealed-secrets bitnami-labs/sealed-secrets \
  --namespace kube-system \
  --set secretNameAnnotations."cert-manager\.io/cluster-issuer"=letsencrypt-prod
```

**Интеграция с cert-manager:** Sealed Secrets controller может использовать cert-manager для выпуска собственного TLS-сертификата для webhook.

### Решение 2: External Secrets Operator

**External Secrets Operator (ESO)** — контроллер, синхронизирующий секреты из внешних хранилищ (AWS Secrets Manager, HashiCorp Vault, GCP Secret Manager) в Kubernetes Secrets.

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: letsencrypt-prod-account-key
  namespace: cert-manager
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: letsencrypt-prod-account-key
    creationPolicy: Owner
  data:
  - secretKey: account-key
    remoteRef:
      key: secret/cert-manager/letsencrypt-prod
      property: account-key
```

**Преимущества:**
- Приватные ключи никогда не хранятся в etcd
- Автоматическая ротация внешних секретов
- Централизованное управление доступом

### Решение 3: OPA/Gatekeeper политики

**OPA (Open Policy Agent)** — движок политик для принудительства стандартов безопасности. Gatekeeper — интеграция OPA с Kubernetes admission controller.

#### Политика: Запрет RSA 2048

```yaml
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: certmanagersecurity
spec:
  crd:
    spec:
      names:
        kind: CertManagerSecurity
      validation:
        openAPIV3Schema:
          type: object
          properties:
            algorithms:
              type: array
              items:
                type: string
  targets:
    - target: admission.k8s.gatekeeper.sh
      rego: |
        package certmanagersecurity

        violation[{"msg": msg}] {
          input.review.kind.kind == "Certificate"
          alg := input.review.object.spec.privateKey.algorithm
          not alg in input.parameters.algorithms
          msg := sprintf("Алгоритм %v запрещен. Разрешены: %v", [alg, input.parameters.algorithms])
        }
```

```yaml
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: CertManagerSecurity
metadata:
  name: enforce-modern-algorithms
spec:
  match:
    kinds:
    - apiGroups: ["cert-manager.io"]
      kinds: ["Certificate"]
  parameters:
    algorithms: ["ECDSA", "Ed25519"]
```

#### Политика: Ограничение срока действия

```yaml
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: certmanagerduration
spec:
  crd:
    spec:
      names:
        kind: CertManagerDuration
      validation:
        openAPIV3Schema:
          type: object
          properties:
            maxDurationDays:
              type: integer
  targets:
    - target: admission.k8s.gatekeeper.sh
      rego: |
        package certmanagerduration

        violation[{"msg": msg}] {
          input.review.kind.kind == "Certificate"
          dur := input.review.object.spec.duration
          days := parse_duration_to_days(dur)
          days > input.parameters.maxDurationDays
          msg := sprintf("Срок действия %v дней превышает максимум %v дней", [days, input.parameters.maxDurationDays])
        }

        parse_duration_to_days(dur) = days {
          endswith(dur, "h")
          hours := to_number(trim_suffix(dur, "h"))
          days := hours / 24
        }
```

---

## Дополнительная информация

### Управление доверием (trust-manager)

Для централизованного распространения корневых сертификатов (CA Bundle) по всем namespace используйте аддон **trust-manager**.
*   **Администрирование:** Создайте ресурс `Bundle` один раз, и trust-manager автоматически обновит ConfigMap во всех пространствах имен при ротации CA.
*   **См. подробнее:** [Сценарии приватного CA](../Private_CA/scenarios.md).

### Переход на ARI (v1.21+)

В новых версиях администрирование упрощается за счет **ACME Renewal Information (ARI)**. Контроллер сам определяет оптимальное время продления, основываясь на данных от CA.
*   **Совет:** При переходе на v1.21+ постепенно удаляйте поле `renewBefore` из пользовательских ресурсов `Certificate`, чтобы полностью переключиться на логику ARI.

### Ограничения и известные проблемы

*   **etcd-риски:** cert-manager не хранит историю Secret'ов. При случайном удалении Secret восстановление возможно только из внешнего бэкапа или повторным запросом в CA.
*   **ReferenceGrant (Gateway API):** Если `Secret` находится в другом namespace, требуется явный `ReferenceGrant`. Без него Gateway не увидит сертификат.
*   **Rate Limits Let's Encrypt:** При массовой регенерации сертификатов используйте Staging-окружение. Production Rate Limit — 50 дубликатов домена в неделю.
*   **Версия 1.21+:** Удалены права на создание ServiceAccount токенов из стандартного чарта. Для интеграции с AWS IRSA или GCP Workload Identity требуется ручная настройка RBAC.

### Best practices для Production

1.  **Используйте ClusterIssuer для общих CA:** Централизуйте управление учетными данными и снижайте риск утечки ключей из-за множества Issuer'ов в разных namespace.
2.  **Предпочитайте ECDSA/Ed25519:** Алгоритм `ECDSA-P256` обеспечивает высокую производительность и эквивалентную безопасность по сравнению с RSA 2048. Ed25519 еще компактнее и быстрее.
3.  **Настраивайте `revisionHistoryLimit`:** В высоконагруженных кластерах явно задавайте `revisionHistoryLimit: 5` для `CertificateRequest`, чтобы контролировать количество объектов в etcd.
4.  **Включайте `ownerReference`:** Флаг `--enable-certificate-owner-ref=true` автоматически удаляет Secret при удалении Certificate, предотвращая "мусор" в etcd.
5.  **Используйте Staging для тестов:** Все изменения политик Issuer и ротацию CA тестируйте на Let's Encrypt Staging.
6.  **Настройте алерты:** Минимум — алерт на истечение сертификатов (<7 дней) и недоступность webhook.
7.  **Бэкап CA-секретов:** Храните бэкапы приватных ключей CA в зашифрованном виде вне кластера. Подробнее: **[Cert-manager: Операции](./operations.md)**.
8.  **Сетевая изоляция:** Используйте `NetworkPolicy` для ограничения egress контроллера только необходимыми эндпоинтами.
9.  **CSI-драйвер для высокосекретных сред:** Генерация ключей в памяти узла исключает хват приватных ключей в etcd.
10. **Аудит:** Включите audit log для API-сервера с фокусом на ресурсы `cert-manager.io/v1`.
11. **Мульти-тенантность:** Используйте Issuer per Tenant и namespace-scoped RBAC (подробнее: **[Мульти-тенантность](./multi_tenancy.md)**).
12. **Внутренний mTLS:** Для сервисов используйте короткие TTL (≤72ч) и CSI Driver (подробнее: **[Внутренний mTLS](./internal_mtls.md)**).

### Смотрите также

- **[Cert-manager: Операции](./operations.md)** — мониторинг, резервное копирование и обновление.
- **[Cert-manager: Диагностика](./troubleshooting.md)** — глубокий анализ ошибок и troubleshooting.
- **[Обновление и миграция cert-manager](./upgrades_and_migration.md)** — апгрейд версий, breaking changes, rollback.
- **[Масштабирование и производительность](./scaling_and_performance.md)** — tuning при 1000+ сертификатах, HPA, PDB.
- **[RBAC-примеры](./rbac_examples.md)** — готовые Role/ClusterRole для типичных ролей (dev, platform, CI/CD).
- **[Ephemeral/Preview-среды](./ephemeral_environments.md)** — автоматизация TLS для динамических preview деплоев.
- **[Cert-manager: GitOps интеграция](./gitops_integration.md)** — настройка ArgoCD/Flux с cert-manager.
- **[Cert-manager: Тестирование в CI/CD](./cicd_testing.md)** — валидация манифестов перед деплоем.
- **[Cert-manager: Production Playbooks](./production_playbooks.md)** — пошаговые инструкции по инцидентам.
- **[Cert-manager: Отзыв сертификатов](./certificate_revocation.md)** — CRL, OCSP, короткие TTL.
- **[Cert-manager: Мульти-тенантность](./multi_tenancy.md)** — изоляция tenant'ов, RBAC, NetworkPolicy.
- **[Cert-manager: DNS-провайдеры](./dns_providers.md)** — Cloudflare, Route53, Google Cloud DNS.
- **[Cert-manager: Внутренний mTLS](./internal_mtls.md)** — mTLS для баз, gRPC, Redis.
- **[Cert-manager: Безопасность и TLS](../../../Security/tls_and_mtls_in_kubernetes.md)** — общие принципы защиты трафика.
