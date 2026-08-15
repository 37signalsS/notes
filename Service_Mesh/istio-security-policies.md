# Политики безопасности Istio

## Определения

**Безопасность Istio** — комплекс механизмов для реализации модели **Zero Trust** в микросервисных архитектурах. Она базируется на трех фундаментальных принципах:
1.  **Идентичность (Identity):** Каждая рабочая нагрузка (Workload) имеет уникальный криптографический идентификатор на основе стандарта [SPIFFE](https://spiffe.io/).
2.  **Аутентификация (Authentication):** Проверка подлинности отправителя (mTLS) и конечного пользователя (JWT/OIDC).
3.  **Авторизация (Authorization):** Управление доступом на основе политик (L4–L7), определяющих, «кто», «куда» и «как» может обращаться.

В 2026 году (версии 1.32+) основным интерфейсом управления безопасностью стал **Gateway API** (GAMMA), а механизмы mTLS инкапсулированы в протокол **HBONE** для поддержки Ambient Mesh.

---

## Идентичность и SPIFFE

Istio использует идентификаторы **SPIFFE ID** для представления сервисов. Формат: `spiffe://<trust-domain>/ns/<namespace>/sa/<service-account>`.

- **Trust Domain:** Логическая группа доверия (по умолчанию `cluster.local`).
- **SVID (SPIFFE Verifiable Identity Document):** X.509 сертификат, выпускаемый Istiod (или внешним CA, например Vault/SPIRE), содержащий SPIFFE ID в поле SAN (Subject Alternative Name).
- **Ротация:** Сертификаты короткоживущие (обычно 24 часа) и ротируются автоматически без участия приложения.

---

## Аутентификация (Authentication)

### 1. Peer Authentication (mTLS)

Ресурс `PeerAuthentication` определяет, как прокси принимают входящие соединения. В 2026 году mTLS между узлами в Ambient Mesh выполняется компонентом **Ztunnel**.

**Режимы работы (`mode`):**
- **`STRICT` (Стандарт 2026):** Разрешен ТОЛЬКО mTLS-трафик. Любые запросы в открытом тексте блокируются.
- **`PERMISSIVE`:** Принимает mTLS и Plain Text. Используется исключительно для временной миграции (не рекомендуется для продакшена).
- **`DISABLE`:** mTLS отключен.

**Пример: Глобальный Strict mTLS (istio-system)**

```yaml
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: istio-system
spec:
  mtls:
    mode: STRICT
```

### 2. Request Authentication (JWT)

Проверяет токены конечных пользователей (JWT) от внешних провайдеров (Auth0, Keycloak, Okta).

```yaml
apiVersion: security.istio.io/v1beta1
kind: RequestAuthentication
metadata:
  name: jwt-auth
  namespace: prod
spec:
  selector:
    matchLabels:
      app: api-server
  jwtRules:
  - issuer: "https://keycloak.example.com/auth/realms/master"
    jwksUri: "https://keycloak.example.com/auth/realms/master/protocol/openid-connect/certs"
```

---

## Авторизация (Authorization)

Политики авторизации (`AuthorizationPolicy`) реализуют принцип наименьших привилегий.

### Иерархия и приоритеты
1.  **DENY:** Если запрос подпадает под правило `DENY`, он блокируется немедленно.
2.  **ALLOW:** Если есть правила `ALLOW`, запрос разрешается только при совпадении с одним из них.
3.  **Default-Deny:** Если определена хотя бы одна политика `ALLOW`, весь остальной трафик к ворклоаду запрещен.

### Безопасность в Ambient Mesh
- **L4 Политики (IP, Principals):** Исполняются на уровне **Ztunnel** (максимальная производительность).
- **L7 Политики (Path, Methods, Headers):** Исполняются на уровне **Waypoint Proxy**. Для их работы необходимо развернуть Waypoint для неймспейса или сервиса.

**Пример: Default-Deny (Блокировать всё по умолчанию)**

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: allow-nothing
  namespace: prod
spec:
  {} # Пустая политика ALLOW запрещает всё, что не разрешено явно
```

**Пример: Доступ по SPIFFE ID (L4)**

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: allow-billing-to-inventory
  namespace: prod
spec:
  selector:
    matchLabels:
      app: inventory
  action: ALLOW
  rules:
  - from:
    - source:
        principals: ["spiffe://cluster.local/ns/prod/sa/billing-sa"]
```

**Пример: Проверка JWT Claims (L7)**

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: require-admin-role
  namespace: prod
spec:
  action: ALLOW
  rules:
  - when:
    - key: request.auth.claims[role]
      values: ["admin"]
```

---

## Практические сценарии

### Сценарий 1: Защита Gateway API
С 2026 года для mTLS между шлюзом (Gateway) и бэкендом используется `BackendTLSPolicy`.

### Сценарий 2: Мультикластерная федерация
При использовании нескольких кластеров сертификаты должны иметь общие корни доверия. Istio поддерживает федерацию через `MeshConfig` или внешние системы управления идентификацией (SPIRE Federation).

### Сценарий 3: Изоляция системных компонентов
Защита `istiod` и других компонентов `istio-system` с помощью жестких политик `AuthorizationPolicy`, разрешающих доступ только из доверенных систем мониторинга (Prometheus, Kiali).

---

## Диагностика и отладка

- **`istioctl analyze`**: Автоматический поиск конфликтов в политиках.
- **`istioctl proxy-config secret <pod-name>`**: Просмотр текущих mTLS сертификатов и их срока действия.
- **`istioctl proxy-status`**: Проверка синхронизации политик с прокси-серверами.
- **Логи Ztunnel/Waypoint:** Анализ отказов по кодам `403 Forbidden` (AuthZ) или `Connection Reset` (AuthN).

---

## Дополнительная информация

- [**Архитектура Istio и режим Ambient**](./istio_architecture.md) — детали работы Ztunnel и Waypoint.
- [**Наблюдаемость в Istio**](./istio_observability_and_tools.md) — визуализация mTLS и отказов в Kiali.
- [**Zero Trust с HashiCorp Vault**](../Vault/zero_trust.md) — интеграция SPIFFE с Vault.
- [**SPIFFE.io**](https://spiffe.io/) — официальная спецификация идентификации.

Документация: [Istio Security Overview](https://istio.io/latest/docs/concepts/security/).
