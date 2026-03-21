# Cert-manager: Определения и основные понятия

## Определения

**Cert-manager** — нативный для Kubernetes контроллер для автоматизации управления TLS-сертификатами. Автоматизирует получение, продление и отзыв сертификатов, минимизируя ручное вмешательство.

**Ключевые возможности:**

| Возможность | Описание |
| :--- | :--- |
| **Автоматизация получения** | Интеграция с Let's Encrypt, HashiCorp Vault, Venafi, приватными CA, self-signed |
| **Автопродление** | Мониторинг срока действия, автоматическое продление до истечения |
| **Ingress-интеграция** | Автоматическое создание сертификатов для Ingress-ресурсов через аннотации |
| **Gateway API** | Поддержка Gateway API (требуется флаг `--enable-gateway-api`) |
| **Жизненный цикл** | Управление созданием, продлением, отзывом сертификатов |

---

## Основные концепции (CRD)

Cert-manager расширяет Kubernetes API через Custom Resource Definitions:

### Источники сертификатов (Issuers)

| Ресурс | Область действия | Описание |
| :--- | :--- | :--- |
| **`Issuer`** | Namespace | Представляет CA в рамках одного namespace |
| **`ClusterIssuer`** | Кластер | Общекластерный ресурс, доступен из любого namespace |

**Типы Issuer:**

| Тип | Описание | Сценарий |
| :--- | :--- | :--- |
| `acme` | ACME-протокол (Let's Encrypt) | Публичные сертификаты |
| `ca` | Существующий CA в Secret | Внутренние PKI |
| `selfSigned` | Самоподписанные сертификаты | Тестирование, корневые CA |
| `vault` | HashiCorp Vault | Интеграция с Vault PKI |
| `venafi` | Venafi Cloud/TPE | Корпоративные PKI |

### Ресурсы сертификатов

| Ресурс | Описание |
| :--- | :--- |
| **`Certificate`** | Запрос сертификата у Issuer/ClusterIssuer. Cert-manager создаёт/обновляет Secret с сертификатом |
| **`CertificateRequest`** | Внутренний ресурс, представляет CSR к Issuer. Не рекомендуется для прямого использования |
| **`Order`** | ACME-заказ (только для ACME-Issuer). Содержит информацию о заказе сертификата |
| **`Challenge`** | ACME-проверка (HTTP-01, DNS-01, TLS-ALPN-01). Создаётся для каждого домена в Order |

### Поток ACME-запроса (Let's Encrypt)

```
Certificate → Order → Challenge(s) → CertificateRequest → Secret
```

1. Пользователь создаёт `Certificate`
2. Cert-manager создаёт `Order` для ACME-сервера
3. Для каждого домена создаётся `Challenge` (проверка владения)
4. После прохождения проверок создаётся `CertificateRequest`
5. При успехе сертификат сохраняется в `Secret`

---

## Структура ресурса Certificate

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: example-com
  namespace: default
spec:
  # Целевой Secret
  secretName: example-com-tls
  
  # Срок действия и продление
  duration: 2160h        # 90 дней (по умолчанию)
  renewBefore: 360h      # 15 дней до истечения (по умолчанию)
  
  # Доменные имена
  dnsNames:
    - example.com
    - www.example.com
  ipAddresses:
    - 192.168.1.1
  
  # Ссылка на Issuer
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
    group: cert-manager.io
  
  # Дополнительные параметры
  isCA: false                    # true для CA-сертификатов
  commonName: example.com        # CN (опционально)
  privateKey:
    algorithm: RSA               # RSA, ECDSA
    size: 2048                   # 2048, 4096 (RSA); 256, 384 (ECDSA)
    encoding: PKCS8              # PKCS8, PKCS1 (важно для Java)
  usages:
    - digital signature
    - key encipherment
```

**Важно:** Для Java-приложений (OpenSearch, Elasticsearch) указывайте `encoding: PKCS8`.

---

## ACME Solvers (проверки владения)

| Метод | Принцип | Требования | Сценарий |
| :--- | :--- | :--- | :--- |
| **HTTP-01** | Размещение файла по `http://<domain>/.well-known/acme-challenge/` | Ingress с публичным доступом |Wildcard-сертификаты **не поддерживаются** |
| **DNS-01** | Создание TXT-записи `_acme-challenge.<domain>` | Доступ к DNS API провайдера | Wildcard-сертификаты, нет публичного HTTP |
| **TLS-ALPN-01** | TLS-соединение на порт 443 с специальным сертификатом | Прямой доступ к порту 443 | Редко используется |

### Пример HTTP-01 solver

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
      name: letsencrypt-prod-key
    solvers:
    - http01:
        ingress:
          ingressClassName: nginx
          podTemplate:
            spec:
              nodeSelector:
                ingress-ready: "true"
```

### Пример DNS-01 solver (Cloudflare)

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
      name: letsencrypt-prod-key
    solvers:
    - dns01:
        cloudflare:
          email: admin@example.com
          apiKeySecretRef:
            name: cloudflare-api-key
            key: api-key
```

---

## Интеграция с Ingress

### Аннотации cert-manager

| Аннотация | Описание |
| :--- | :--- |
| `cert-manager.io/issuer` | Использовать Issuer из того же namespace |
| `cert-manager.io/cluster-issuer` | Использовать ClusterIssuer |
| `cert-manager.io/issue-temporary-certificate` | `true` — выдать временный сертификат до подтверждения ACME |
| `cert-manager.io/acme-challenge-type` | Принудительный выбор solver (`http01`, `dns01`) |

### Пример Ingress с аннотацией

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - example.com
    secretName: example-com-tls
  rules:
  - host: example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: my-service
            port:
              number: 80
```

> **Устаревшая аннотация:** `kubernetes.io/tls-acme: "true"` — не используйте, заменено на `cert-manager.io/cluster-issuer`.

---

## Интеграция с Gateway API

> **Требование:** Установить CRD Gateway API **до** cert-manager.

### Включение поддержки Gateway API

```bash
helm install cert-manager jetstack/cert-manager \
  --set "extraArgs={--enable-gateway-api=true}" \
  -n cert-manager --create-namespace
```

### Пример Gateway с TLS

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: example-gateway
spec:
  gatewayClassName: traefik
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: example-tls-secret
        namespace: default
```

**Особенности:**

- Поле `hostname` в Gateway может конфликтовать с автогенерацией Certificate
- Рекомендуется создавать Certificate вручную перед Gateway
- Поддерживаются несколько HTTPS-слушателей на одном шлюзе

**См.** [Gateway API: Интеграция](./gateway_api/practical_scenarios.md)

---

## Дополнительные сведения

### Версии и совместимость

| Компонент | Минимальная версия K8s | Примечание |
| :--- | :--- | :--- |
| cert-manager 1.13+ | 1.22 | Текущая стабильная ветка |
| cert-manager 1.14+ | 1.23 | Gateway API v1 |
| Gateway API CRD | 1.21+ | Устанавливаются отдельно |

**Проверка версий:**

```bash
kubectl get deployments -n cert-manager -o wide
helm list -n cert-manager
```

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| CRD и API | **10** | Официальная документация cert-manager.io |
| ACME solvers | **10** | RFC 8555, документация Let's Encrypt |
| Gateway API | **9** | Интеграция подтверждена в релизах 1.13+ |
| PKCS8 encoding | **10** | Требуется для Java (OpenSearch, Elasticsearch) |
