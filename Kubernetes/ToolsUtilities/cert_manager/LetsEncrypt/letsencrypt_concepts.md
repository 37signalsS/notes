# Let's Encrypt: Основные концепции

## 1. Определения

**Let's Encrypt** — бесплатный, автоматизированный и открытый центр сертификации, использующий протокол ACME для выдачи TLS-сертификатов.

**ACME (Automatic Certificate Management Environment)** — протокол (RFC 8555) для автоматизированного получения и продления сертификатов.

## 2. Ограничения Let's Encrypt

| Лимит | Значение | Период |
| :--- | :--- | :--- |
| Сертификатов на домен | 50 | 7 дней |
| Запросов на регистрацию | 10 | 3 часа |
| Wildcard-сертификатов | 50 | 7 дней |
| Срок действия | 90 дней | — |

## 3. ACME Solvers (проверки владения)

| Метод | Принцип | Wildcard | Требования |
| :--- | :--- | :--- | :--- |
| **HTTP-01** | Файл по `http://<domain>/.well-known/acme-challenge/` | ❌ Нет | Публичный Ingress |
| **DNS-01** | TXT-запись `_acme-challenge.<domain>` | ✅ Да | Доступ к DNS API |
| **TLS-ALPN-01** | TLS-соединение на порт 443 | ❌ Нет | Прямой доступ к 443 |

## 4. Окружения Let's Encrypt

| Окружение | URL | Назначение |
| :--- | :--- | :--- |
| **Production** | `https://acme-v02.api.letsencrypt.org/directory` | Боевые сертификаты |
| **Staging** | `https://acme-staging-v02.api.letsencrypt.org/directory` | Тестирование (лимиты выше) |

> **Важно:** Staging использует отдельные тестовые CA, которые не доверяются браузерами. Используйте для отладки конфигурации.

## Связанные документы

- **[Практические сценарии](./letsencrypt_scenarios.md)** — ClusterIssuer, HTTP-01, DNS-01, wildcard
- **[Дополнительные темы](./letsencrypt_advanced.md)** — диагностика, ошибки, best practices
- **[cert_manager](../cert_manager_overview.md)** — обзор cert-manager
- **[private_ca](../private_ca.md)** — частные CA для внутренних доменов
