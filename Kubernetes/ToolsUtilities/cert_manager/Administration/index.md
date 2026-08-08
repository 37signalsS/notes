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

Для обеспечения непрерывности работы (High Availability) cert-manager должен быть развернут в нескольких репликах.

| Компонент | HA-механизм | Рекомендация |
| :--- | :--- | :--- |
| **Controller** | Leader Election | 2+ реплики. Только одна активна (лидер), остальные в режиме ожидания. |
| **Webhook** | Load Balancing | 3 реплики. Критично для доступности API (создание ресурсов). |
| **CA Injector** | Leader Election | 2 реплики. Отвечает за инжекцию CA в CRD и Webhooks. |

**Ресурсы (Resources):** При большом количестве сертификатов (>500) увеличьте лимиты памяти для контроллера, так как он держит кэш ресурсов в памяти.

### Безопасность и управление доступом (RBAC)

#### Разделение ответственности

1.  **Инфраструктурный уровень:** Только администраторы кластера имеют права на создание `ClusterIssuer` и настройку DNS-01 секретов в namespace `cert-manager`.
2.  **Прикладной уровень:** Разработчики имеют права на создание `Certificate` и `Issuer` (namespace-scoped), но не могут изменять системные настройки контроллера.

#### Сетевая изоляция (v1.20+)

Начиная с версии **v1.20**, Helm-чарт поддерживает нативные `NetworkPolicy`.
*   **Egress:** Ограничьте доступ контроллера только к API-серверу Kubernetes и эндпоинтам центров сертификации (Let's Encrypt, Vault).
*   **Ingress:** Разрешите входящий трафик к Webhook только из `kube-system` (API-сервер).

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

---

## Дополнительная информация

### Управление доверием (trust-manager)

Для централизованного распространения корневых сертификатов (CA Bundle) по всем namespace используйте аддон **trust-manager**.
*   **Администрирование:** Создайте ресурс `Bundle` один раз, и trust-manager автоматически обновит ConfigMap во всех пространствах имен при ротации CA.
*   **См. подробнее:** [Сценарии приватного CA](../Private_CA/scenarios.md).

### Переход на ARI (v1.21+)

В новых версиях администрирование упрощается за счет **ACME Renewal Information (ARI)**. Контроллер сам определяет оптимальное время продления, основываясь на данных от CA.
*   **Совет:** При переходе на v1.21+ постепенно удаляйте поле `renewBefore` из пользовательских ресурсов `Certificate`, чтобы полностью переключиться на логику ARI.

### Смотрите также

- **[Cert-manager: Операции](./operations.md)** — мониторинг, резервное копирование и обновление.
- **[Cert-manager: Диагностика](./troubleshooting.md)** — глубокий анализ ошибок и troubleshooting.
- **[Cert-manager: Безопасность и TLS](../../../Security/tls_and_mtls_in_kubernetes.md)** — общие принципы защиты трафика.
