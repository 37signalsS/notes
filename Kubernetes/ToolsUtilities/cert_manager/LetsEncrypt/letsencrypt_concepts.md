# Let's Encrypt: Углублённые концепции ACME

## Definitions

**Let's Encrypt** — бесплатный, автоматизированный и открытый центр сертификации (CA), использующий протокол ACME (RFC 8555) для выдачи TLS-сертификатов.

**ACME Account** — учётная запись в ACME-сервере с ключевой парой, используемой для подписи всех запросов. Хранится в Secret `letsencrypt-<env>-key`.

**Certificate Transparency (CT)** — публичный лог всех выпущенных сертификатов. Let's Encrypt обязан записывать каждый сертификат в CT-логи.

**ARI (ACME Renewal Information)** — расширение ACME (draft-ietf-acme-ari), предоставляющее информацию об оптимальном времени продления.

> **Базовые концепции (лимиты, solvers, окружения):** [index.md](../index.md)

---

## Basic Concepts

### ACME Account и ключи

Каждый `ClusterIssuer` создаёт ACME Account — учётную запись на сервере Let's Encrypt.

| Параметр | Описание |
| :--- | :--- |
| **Account Key** | ECDSA или RSA ключ для подписи ACME-запросов |
| **Account URL** | Уникальный идентификатор аккаунта на ACME-сервере |
| **Email** | Привязан к аккаунту, используется для уведомлений об истечении |
| **Terms of Service** | Согласие с условиями Let's Encrypt (автоматически принимается cert-manager) |

**Важно:** Потеря `privateKeySecretRef` означает потерю аккаунта. Все ранее выданные сертификаты придётся запрашивать заново с новым аккаунтом.

```yaml
spec:
  acme:
    privateKeySecretRef:
      name: letsencrypt-prod-key  # Хранить в backup!
    email: admin@example.com
```

### Certificate Transparency (CT)

Все сертификаты Let's Encrypt записываются в публичные CT-логи:

| Лог | Оператор | URL |
| :--- | :--- | :--- |
| Google Argon 2026 | Google | `ct.googleapis.com/logs/argon2026/` |
| Cloudflare Nimbus 2026 | Cloudflare | `nimbus2026.ct.cloudflare.com/` |
| Let's Encrypt Oak 2026 | ISRG | `oak2026.letsencrypt.org/` |

**Последствия:**

- Любой выпущенный сертификат виден публично
- Невозможно скрыть домены из сертификата
- Можно проверить историю выдачи: `https://crt.sh/?q=<domain>`

### Изменения 2026: сокращение срока действия

| Период | Срок действия | `renewBefore` рекомендация |
| :--- | :--- | :--- |
| До 2026 | 90 дней | 360h (15 дней) |
| Переходный период | 64 дня | 240h (10 дней) |
| Конец 2026+ | **45 дней** | 168h (7 дней) |

> **Важно:** Для поддержки ARI (ACME Renewal Information) используйте cert-manager **1.15+**. Продление будет автоматическим без изменения конфигурации.

### Сравнение ACME-CA

| CA | Срок | Wildcard | Лимиты | Особенности |
| :--- | :--- | :--- | :--- | :--- |
| **Let's Encrypt** | 90 → 45 дней | ✅ DNS-01 | 50/домен/7д | Самый популярный, 400M+ сертификатов |
| **ZeroSSL** | 90 дней | ✅ DNS-01 | 3/домен/7д (free) | ACME-совместимый, платные тарифы |
| **Buypass Go SSL** | 180 дней | ❌ | 5/домен/7д | Дольший срок, только DV |
| **Google Trust Services** | 90 дней | ❌ | N/A | Публичный CA, без ACME |

---

## Practical Scenarios

### Просмотр ACME Account

```bash
# Secret с ключом аккаунта
kubectl get secret letsencrypt-prod-key -n cert-manager -o yaml

# Расшифровка URL аккаунта (из данных секрета)
kubectl get secret letsencrypt-prod-key -n cert-manager \
  -o jsonpath='{.data.url}' | base64 -d
# Результат: https://acme-v02.api.letsencrypt.org/acme/acct/123456789
```

### Проверка Certificate Transparency

```bash
# Получить сертификат из Secret
kubectl get secret example-com-tls -o jsonpath='{.data.tls\.crt}' | base64 -d > cert.pem

# Извлечь Subject Alternative Names
openssl x509 -in cert.pem -noout -text | grep -A1 "Subject Alternative Name"

# Проверить в CT-логах (онлайн)
# https://crt.sh/?q=example.com
```

### Миграция при потере ACME Account Key

**Сценарий:** Secret `letsencrypt-prod-key` удалён или повреждён.

1. Создать новый ClusterIssuer с новым ключом:

   ```yaml
   spec:
     acme:
       privateKeySecretRef:
         name: letsencrypt-prod-key-new  # Новый Secret
   ```

2. Обновить все Certificate на новый `issuerRef`:

   ```yaml
   issuerRef:
     name: letsencrypt-prod-new
     kind: ClusterIssuer
   ```

3. Удалить старый Issuer после продления всех сертификатов

### Подготовка к 45-дневным сертификатам

**Что проверить:**

| Проверка | Статус |
| :--- | :--- |
| cert-manager ≥ 1.15 | `kubectl get deployments -n cert-manager -o wide` |
| ARI поддержка | Подтверждена в release notes cert-manager |
| `renewBefore` ≥ 168h | Обновить в Certificate spec |
| Мониторинг продления | Prometheus-алерты на `Certificate Ready` |

---

## Дополнительная информация

### ACME-протокол: ключевые эндпоинты

| Эндпоинт | Назначение |
| :--- | :--- |
| `/acme/new-nonce` | Получить одноразовый токен для запроса |
| `/acme/new-account` | Создать или найти аккаунт |
| `/acme/new-order` | Создать заказ на сертификат |
| `/acme/authz/{id}` | Статус авторизации домена |
| `/acme/chall/{id}` | Детали challenge (проверки) |
| `/acme/finalize/{id}` | Получить сертификат после прохождения проверок |
| `/acme/renewal-info` | ARI: рекомендуемое время продления |

**Полная спецификация:** [RFC 8555](https://datatracker.ietf.org/doc/html/rfc8555)

### Смотрите также

- **[Let's Encrypt: Обзор](./index.md)** — лимиты, solvers и окружения
- **[Практические сценарии Let's Encrypt](./letsencrypt_scenarios.md)** — HTTP-01, DNS-01, Staging
- **[Cert-manager: Troubleshooting](./letsencrypt_advanced.md)** — диагностика ошибок ACME
its-45-day-certs) |
| ARI поддержка | **9** | Draft IETF, cert-manager 1.15+ |
| Сравнение CA | **8** | Документация CA, может меняться |

**Связанные документы:** [базовые сведения](../index.md), [практические сценарии](./letsencrypt_scenarios.md), [cert_manager CRD](../definitions.md), [диагностика](./letsencrypt_advanced.md).
nced.md).
