# Let's Encrypt: Практические сценарии

## Определения

**ClusterIssuer** — общекластерный ресурс cert-manager, представляющий учетную запись ACME на сервере сертификации. В отличие от `Issuer`, он не привязан к конкретному пространству имен и может использоваться для выпуска сертификатов в любом namespace.

**Certificate** — абстракция Kubernetes, описывающая желаемое состояние TLS-сертификата. Контроллер cert-manager использует этот ресурс для генерации запроса (CSR), прохождения проверок (Challenges) и сохранения итогового сертификата в Secret.

**API Token (Cloudflare)** — современный и безопасный метод аутентификации в API Cloudflare с использованием принципа наименьших привилегий (вместо использования Global API Key).

> **Базовые концепции:** [index.md](./index.md) | **Спецификация CRD:** [definitions.md](../../definitions.md)

---

## Основные концепции

### Структура ClusterIssuer

Ресурс `ClusterIssuer` определяет, как именно контроллер будет взаимодействовать с Let's Encrypt.

```yaml
ClusterIssuer
├── acme.server          # URL сервера (production или staging)
├── acme.email           # Email для технических уведомлений
├── acme.privateKeySecretRef  # Секрет с ключом аккаунта ACME
└── acme.solvers         # Список методов проверки (HTTP-01, DNS-01)
```

### Параметры Certificate и ARI

С появлением протокола ARI (ACME Renewal Information) в cert-manager 1.15+, жесткое указание времени продления становится менее критичным, так как контроллер может следовать рекомендациям центра сертификации.

| Поле | Значение (45 дней, 2026+) | Значение (90 дней, стандарт) |
| :--- | :--- | :--- |
| `duration` | `1080h` | `2160h` |
| `renewBefore` | `168h` (7 дней) | `360h` (15 дней) |

### Сравнение Solvers для сценариев

| Сценарий | Метод (Solver) | Wildcard | Требования |
| :--- | :--- | :--- | :--- |
| Публичный веб-сайт | HTTP-01 | Нет | Доступ к порту 80/TCP из интернета |
| Wildcard-сертификаты | DNS-01 | Да | Доступ к API DNS-провайдера |
| Внутренние ресурсы | DNS-01 | Да | Публичная DNS-зона (даже для серых IP) |

---

## Практические сценарии

### Сценарий 1: Базовый HTTP-01 для Ingress

Самый распространенный сценарий для публичных сервисов.

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-account-key
    solvers:
    - http01:
        ingress:
          ingressClassName: nginx
```

**Ресурс сертификата:**

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: site-com-tls
  namespace: prod
spec:
  secretName: site-com-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
    - site.com
    - www.site.com
```

### Сценарий 2: DNS-01 (Cloudflare) с использованием API Token

Безопасный метод выпуска Wildcard-сертификатов.

**1. Создание секрета с API токеном:**

```bash
kubectl create secret generic cloudflare-api-token \
  --from-literal=api-token=YOUR_CLOUDFLARE_API_TOKEN \
  -n cert-manager
```

**2. Настройка ClusterIssuer:**

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-dns-prod
spec:
  acme:
    email: admin@example.com
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-dns-account-key
    solvers:
    - dns01:
        cloudflare:
          apiTokenSecretRef:
            name: cloudflare-api-token
            key: api-token
```

### Сценарий 3: Интеграция с Gateway API

Использование современных стандартов Kubernetes для автоматизации TLS.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: my-app-route
  namespace: apps
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  parentRefs:
  - name: my-gateway
  hostnames:
  - "app.example.com"
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /
    backendRefs:
    - name: my-service
      port: 80
```

### Сценарий 4: DNS-01 (Yandex Cloud DNS)

Использование внешнего вебхука для интеграции с облаком Яндекс.

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-yandex
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-yandex-key
    solvers:
    - dns01:
        webhook:
          groupName: acme.cert-manager.io
          solverName: yandex-cloud-dns
          config:
            zoneID: "your-zone-id"
            credentialsSecretRef:
              name: yandex-cloud-credentials
              key: service-account-key
```

### Сценарий 5: Тестирование через Staging

Обязательный этап перед запуском в продакшен для проверки конфигурации solvers.

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-staging-key
    solvers:
    - http01:
        ingress:
          ingressClassName: nginx
```

---

## Дополнительная информация

### Рекомендации по эксплуатации

1. **Staging-first**: Всегда проверяйте новые конфигурации DNS-01 на staging-сервере, чтобы избежать блокировок (Rate Limits) со стороны основного API Let's Encrypt.
2. **Безопасность ключей**: Регулярно делайте бэкап Secret-ов, указанных в `privateKeySecretRef`, так как их потеря означает потерю доступа к аккаунту ACME.
3. **Мониторинг**: Используйте метрику `cert_manager_certificate_ready_status` для отслеживания проблем с выпуском сертификатов в системе мониторинга.

### Смотрите также

- **[Углублённые концепции ACME](./letsencrypt_concepts.md)** — подробности ARI, CT-логи и типы аккаунтов
- **[Cert-manager: Диагностика](./letsencrypt_advanced.md)** — решение проблем с прохождением проверок
- **[Cert-manager: Определения](../../definitions.md)** — детальное описание параметров ресурсов

---

### Достоверность информации

| Предмет | Оценка | Источник |
| :--- | :--- | :--- |
| Параметры ARI (1.15+) | **10** | Официальная документация cert-manager.io |
| Планы Let's Encrypt на 2026 | **9** | ISRG / Let's Encrypt official blog |
| Интеграция с Gateway API | **10** | Kubernetes Gateway API SIG / cert-manager docs |
| Cloudflare API Tokens | **10** | Cloudflare API Documentation |
