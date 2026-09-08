# Let's Encrypt: Публичные сертификаты через ACME в Kubernetes

## Определения

**Let's Encrypt** — бесплатный, автоматизированный и открытый центр сертификации (CA), использующий протокол ACME (RFC 8555) для выдачи TLS-сертификатов. В 2026 году Let's Encrypt является основным источником публичных сертификатов для Kubernetes-кластеров, обеспечивая полную автоматизацию жизненного цикла без ручного вмешательства.

**ACME (Automatic Certificate Management Environment)** — протокол (RFC 8555) для автоматизированного получения, продления и отзыва сертификатов через проверку владения доменом. Клиент (cert-manager) взаимодействует с ACME API через операции: регистрация аккаунта, создание заказа (Order), прохождение проверки (Challenge) и получение сертификата.

**ARI (ACME Renewal Information)** — расширение протокола ACME (RFC 9773), позволяющее центру сертификации рекомендовать клиенту (cert-manager) оптимальное временное окно для продления сертификата. Вместо статичного `renewBefore` cert-manager опрашивает эндпоинт `/acme/renewal-info`. ARI критически важно для предотвращения перегрузки API, соблюдения лимитов и оперативной обработки массовых отзывов сертификатов.

**Certificate Transparency (CT)** — открытый стандарт мониторинга цифровых сертификатов, требующий публикации пре-сертификатов в публичных логах. С 15 июня 2026 года пре-сертификаты должны быть залогированы до выдачи финального сертификата (Pre-issuance CT). Без SCT (Signed Certificate Timestamp) браузеры Chrome/Safari блокируют доступ. CT-логи позволяют обнаружить несанкционированный выпуск сертификатов.

**CAA (Certificate Authority Authorization)** — DNS-запись, указывающая, каким центрам сертификации разрешено выпускать сертификаты для данного домена. Если для домена настроены CAA, Let's Encrypt проверяет их перед выдачей. Отсутствие CAA-записи разрешает выпуск любым CA.

**OCSP (Online Certificate Status Protocol)** — протокол проверки отзыва сертификатов в реальном времени. Клиент запрашивает у OCSP-резолвера статус конкретного сертификата (valid/revoked). Let's Encrypt предоставляет OCSP-сервис, но cert-manager не использует OCSP stapling по умолчанию.

**cert-manager** — нативный для Kubernetes контроллер, автоматизирующий жизненный цикл сертификатов через ресурсы `Issuer`, `Certificate`, `Order` и `Challenge`. Интегрируется с Let's Encrypt через ACME-протокол, обеспечивая автоматическое получение и продление.

**ECDSA (Elliptic Curve Digital Signature Algorithm)** — современный алгоритм цифровой подписи на основе эллиптических кривых. В контексте Let's Encrypt: сертификаты на ECDSA (P-256/P-384) меньше по размеру и быстрее обрабатываются, чем RSA, при аналогичном уровне безопасности. Let's Encrypt использует иерархию E5-E9 для ECDSA и R10-R14 для RSA.

**preferredChain** — параметр ресурса `Certificate`, позволяющий выбрать конкретную цепочку доверия из предложенных CA. Используется для совместимости с легаси-клиентами или для перехода на новую иерархию (например, `ISRG Root X1` → `ISRG Root X2`).

---

## Основные концепции

### Жизненный цикл ACME-заказа

Понимание внутреннего конвейера cert-manager критично для диагностики:

```
Certificate
    │
    ├──► CertificateRequest (CSR)
    │         │
    │         ▼
    │    Order (ACME API)
    │         │
    │         ├──► Challenge: HTTP-01 (портирование токена)
    │         └──► Challenge: DNS-01 (TXT-запись)
    │
    └──► Secret (tls.crt + tls.key)
```

| Этап | Что происходит | Кто инициирует | Типичная задержка |
| :--- | :--- | :--- | :--- |
| `Certificate` создан | cert-manager видит ресурс | Пользователь | — |
| `CertificateRequest` создан | Генерируется CSR | cert-manager | 1–5 сек |
| `Order` создан | Запрос в ACME API | cert-manager | 5–30 сек |
| `Challenge` создан | Создаётся задача проверки | cert-manager | 1–5 сек |
| Проверка пройдена | Подтверждение владения доменом | Let's Encrypt | 10–60 сек (HTTP-01), 30–120 сек (DNS-01) |
| `Secret` обновлён | Сертификат записан в Secret | cert-manager | 1–2 сек |

### Ограничения Let's Encrypt (Rate Limits)

Соблюдение лимитов обязательно для обеспечения стабильности сервиса. Превышение лимитов в Production может привести к блокировке выдачи на срок до 7 дней.

| Лимит | Значение | Период | Особенности |
| :--- | :--- | :--- | :--- |
| **Certificates per Domain** | 50 | 7 дней | На основной зарегистрированный домен (например, `example.com`) |
| **Duplicate Certificates** | 5 | 7 дней | Для идентичного набора имен (SAN). ARI помогает оптимизировать этот процесс. |
| **Failed Validations** | 5 | 1 час | На аккаунт и имя хоста. Критично при отладке. |
| **New Orders** | 300 | 3 часа | Общий лимит на аккаунт |
| **Срок действия** | 90 дней | — | Планируется переход на **45 дней** (ARI является основным механизмом для этой частоты) |

> **Стратегия защиты от rate limits:** Используйте Staging-first подход (см. ниже), разделяйте Issuer для каждого домена/команды и мониторьте количество активных Order через метрики Prometheus.

### ACME ARI (Информация о продлении)

Поддержка ARI стала стабильной в cert-manager v1.15. В версиях v1.21+ функционал расширен для лучшей совместимости с различными CA.

- **Динамика:** cert-manager больше не полагается на статичное значение `renewBefore` (например, за 30 дней), а опрашивает эндпоинт `/acme/renewal-info`.
- **Отказоустойчивость:** Если Let's Encrypt обнаружит проблему в цепочке доверия, он через ARI даст команду всем клиентам немедленно обновить сертификаты.
- **Настройка:** При использовании ARI рекомендуется удалять поле `renewBefore` из ресурса `Certificate`, чтобы передать управление контроллеру.
- **Массовая ротация:** При обнаружении уязвимости ARI позволяет CA инициировать продление всех сертификатов без ручного вмешательства.

### ACME Solvers (Методы проверки владения)

| Метод | Принцип | Wildcard | Требования | Задержка |
| :--- | :--- | :--- | :--- | :--- |
| **HTTP-01** | Токен по адресу `http://<domain>/.well-known/acme-challenge/` | ❌ Нет | Публичный порт 80, Ingress или LoadBalancer | 10–60 сек |
| **DNS-01** | TXT-запись `_acme-challenge.<domain>` | ✅ Да | Доступ к API DNS-провайдера | 30–120 сек |
| **TLS-ALPN-01** | TLS-соединение на порт 443 с использованием специального протокола | ❌ Нет | Прямой доступ к 443 порту, отсутствие прокси-серверов (L7) перед подом | 10–30 сек |

### Поддержка DNS-01 провайдеров

Для интеграции с DNS-01 cert-manager использует плагины провайдеров. Ключевые провайдеры:

| Провайдер | Механизм | Примечания |
| :--- | :--- | :--- |
| **Cloudflare** | API Token (рекомендуется) или Global API Key | Используйте API Tokens с минимальными правами на зону |
| **AWS Route53** | IAM Role / Access Key | Для EKS-кластеров рекомендуется IRSA (IAM Roles for Service Accounts) |
| **Yandex Cloud DNS** | Service Account Key | Секрет в формате JSON |
| **RFC 2136** | Динамические DNS-обновления | Для Self-Hosted DNS (BIND, PowerDNS) |
| **Webhook** | Внешние плагины | Для отсутствующих провайдеров (Infoblox, Netlify, DNSMadeEasy) |

> **Безопасность:** Минимизируйте права API-токенов. Для Cloudflare используйте API Token с правами только на `Zone:DNS:Edit` для конкретной зоны, а не Global API Key.

### Окружения Let's Encrypt

| Окружение | URL API (Directory) | Назначение |
| :--- | :--- | :--- |
| **Production** | `https://acme-v02.api.letsencrypt.org/directory` | Боевые сертификаты, доверенные браузерами. Строгие лимиты. |
| **Staging** | `https://acme-staging-v02.api.letsencrypt.org/directory` | Тестирование конфигурации. Лимиты в сотни раз выше, сертификаты не доверены. |

> **Профессиональный подход:** Всегда проверяйте новую конфигурацию (особенно DNS-01) через Staging, чтобы не исчерпать лимиты продакшена при ошибках настройки.

### Выбор алгоритма ключа (RSA vs ECDSA vs Ed25519)

| Алгоритм | Размер ключа | Безопасность | Производительность | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **RSA-2048** | 2048 бит | Базовый | Низкая | Минимальный стандарт, заменять при возможности |
| **RSA-4096** | 4096 бит | Высокая | Средняя | Для Legacy-систем, требующих RSA |
| **ECDSA P-256** | 256 бит | Высокая | Высокая | **Рекомендуется** для новых инсталляций |
| **ECDSA P-384** | 384 бит | Очень высокая | Средняя | Для систем с повышенными требованиями к безопасности |
| **Ed25519** | 256 бит | Очень высокая | Очень высокая | Поддерживается cert-manager 1.14+, 아직 не всеми CA |

**В 2026 году ECDSA P-256 является предпочтительным выбором** для большинства сценариев. Let's Encrypt выпускает ECDSA-сертификаты через иерархию E5-E9, кросс-подписанную ISRG Root X1 для обратной совместимости.

### Стратегии Wildcard и Multi-Domain

**Wildcard-сертификаты (`*.example.com`):**
- Обязательно используют DNS-01 проверку (требование ACME).
- Покрывают один уровень поддоменов (например, `app.example.com`, но не `sub.app.example.com`).
- Рекомендуются для сервисов с динамическими поддоменами (например, preview deployments).

**Multi-Domain (SAN) сертификаты:**
- Один сертификат может содержать до 100 SAN (Subject Alternative Names).
- Все SAN должны проходить проверку владения.
- Подходят для случаев, когда несколько сервисов используют один Ingress/Gateway.

**Рекомендация по стратегии:**

| Сценарий | Подход | Причина |
| :--- | :--- | :--- |
| Один сервис, один домен | Single-domain сертификат | Простота, минимальные лимиты |
| Несколько сервисов на одном Ingress | SAN-сертификат | Экономия лимитов, меньше Order |
| Preview-деплоймы, динамические поддомены | Wildcard + DNS-01 | Автоматическое покрытие новых поддоменов |
| Высокая безопасность, изоляция | Отдельные сертификаты | Минимизация surface area компрометации |

---

## Практические сценарии

### Staging-first подход (Методология)

Стандартная процедура тестирования новой конфигурации cert-manager:

**Этап 1: Создание Staging Issuer**
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
      name: letsencrypt-staging-account-key
    solvers:
    - http01:
        ingress:
          ingressClassName: nginx
```

**Этап 2: Тестирование выпуска**
```bash
# Примените staging issuer и тестовый Certificate
kubectl apply -f staging-issuer.yaml
kubectl apply -f test-certificate.yaml

# Мониторьте статус
cmctl status certificate test-cert -n default
kubectl describe challenge -n default
```

**Этап 3: Верификация (Staging-сертификаты не доверены браузерам)**
```bash
# Проверка через openssl (самоподписанный CA staging)
kubectl get secret test-cert-secret -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -text | grep -E "Issuer|Subject|Not Before|Not After"
```

**Этап 4: Переключение на Production**
```bash
# Обновите issuerRef в Certificate
kubectl patch certificate test-cert -n default --type=merge -p '{"spec":{"issuerRef":{"name":"letsencrypt-prod"}}}'

# Или удалите staging-сертификат и создайте новый с production issuer
```

### Мониторинг и алертинг для Let's Encrypt

Настройка Prometheus-метрик для контроля состояния сертификатов Let's Encrypt:

**Ключевые метрики cert-manager:**

| Метрика | Описание | Критический порог |
| :--- | :--- | :--- |
| `certmanager_certificate_expiration_timestamp_seconds` | Время истечения сертификата | `< 7 дней` для сервисов |
| `certmanager_certificate_ready_status` | Статус готовности (condition=True: 1, False: 0) | `< 1` |
| `certmanager_http_acme_client_request_count` | Количество запросов к ACME API | Аномальный рост |
| `controller_runtime_reconcile_errors_total` | Ошибки реконсиляции контроллера | `> 0` в течение 5 минут |
| `certmanager_webhook_request_duration_seconds` | Задержка webhook | `> 1 сек` |
| `certmanager_order_ready_status` | Статус ACME-заказов | Множественные `False` |

**Пример PrometheusRule для Let's Encrypt:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: letsencrypt-alerts
  namespace: cert-manager
spec:
  groups:
  - name: letsencrypt.rules
    rules:
    - alert: LetEncryptCertificateExpiringSoon
      expr: |
        certmanager_certificate_expiration_timestamp_seconds - time() < 14 * 24 * 3600
      for: 1h
      labels:
        severity: warning
      annotations:
        summary: "Сертификат {{ $labels.name }} в {{ $labels.namespace }} истекает менее чем через 14 дней"

    - alert: LetEncryptCertificateExpired
      expr: certmanager_certificate_expiration_timestamp_seconds < time()
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Сертификат {{ $labels.name }} в {{ $labels.namespace }} просрочен"

    - alert: LetEncryptOrderFailed
      expr: certmanager_order_ready_status{result="False"} > 0
      for: 15m
      labels:
        severity: warning
      annotations:
        summary: "ACME-заказ для {{ $labels.name }} не завершён в течение 15 минут"

    - alert: LetEncryptControllerDown
      expr: up{job="cert-manager"} == 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Контроллер cert-manager недоступен — сертификаты не продлеваются"
```

**Мониторинг CT-логов (2026):**
```bash
# Проверка наличия SCT в сертификате
kubectl get secret <secret-name> -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -text | grep -A 5 "CT Precertificate SCTs"

# Проверка через online-инструменты
# crt.sh — поиск сертификатов по домену в CT-логах
curl -s "https://crt.sh/?q=example.com&output=json" | jq '.[] | {name: .name_value, issuer: .issuer_name, not_after: .not_after}'
```

---

## Дополнительная информация

### Лучшие практики (2026)

1. **Версия контроллера**: Используйте cert-manager v1.15+. Это обязательное требование для поддержки ARI и корректной работы с 45-дневными сертификатами.
2. **Staging-first**: Всегда проверяйте конфигурацию через Staging перед применением в Production. Ошибки DNS-01 в Staging не тратят лимиты Production.
3. **Отказ от Email-уведомлений**: Let's Encrypt постепенно сокращает использование email для алертов. Настройте мониторинг Prometheus на базе метрики `certmanager_certificate_expiration_timestamp_seconds`.
4. **Высокая доступность (HA)**: Запускайте `cert-manager-webhook` как минимум в 2–3 репликах. Его недоступность блокирует создание и обновление любых ресурсов в кластере Kubernetes.
5. **Минимизация прав DNS API**: При использовании DNS-01 создавайте API-токены с правами только на редактирование конкретных зон (например, Cloudflare API Tokens вместо Global API Key).
6. **ECDSA по умолчанию**: Переходите на ECDSA P-256 для новых инсталляций. Они обеспечивают аналогичный уровень безопасности при меньшем размере ключа и меньшей нагрузке на CPU.
7. **Разделение Issuer**: Используйте отдельные ClusterIssuer для каждого домена/команды для изоляции rate limits.
8. **ARI без renewBefore**: При использовании ARI удаляйте `renewBefore` из Certificate, чтобы передать управление окном продления контроллеру.
9. **Мониторинг CT**: Проверяйте наличие SCT в выпущенных сертификатах для подтверждения соответствия требованиям 2026 года.

### Смотрите также

- **[Углублённые концепции ACME](./letsencrypt_concepts.md)** — ACME Account, CT-логи, JWS и архитектура заказа
- **[Практические сценарии Let's Encrypt](./letsencrypt_scenarios.md)** — полные YAML-манифесты для HTTP-01 и DNS-01
- **[Диагностика и Troubleshooting](./letsencrypt_advanced.md)** — решение проблем с ACME-заказами и ошибками
- **[Cert-manager: Определения](../definitions.md)** — базовая структура ресурсов (Certificate, Issuer)
- **[Cert-manager: Администрирование](../Administration/index.md)** — эксплуатация, HA и обновление контроллера
- **[Ingress: Интеграция](../ingress/overview.md)** — автоматизация через аннотации Ingress
- **[Gateway API и TLS](../gateway_api/definitions_and_concepts.md)** — настройка сертификатов для Gateway API
