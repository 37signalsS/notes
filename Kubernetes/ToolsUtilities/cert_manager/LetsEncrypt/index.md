# Let's Encrypt: Публичные сертификаты через ACME

## Definitions

**Let's Encrypt** — бесплатный, автоматизированный и открытый центр сертификации (CA), использующий протокол ACME (RFC 8555) для выдачи TLS-сертификатов.

**ACME (Automatic Certificate Management Environment)** — протокол для автоматизированного получения и продления сертификатов через проверку владения доменом.

**cert-manager** — Kubernetes-контроллер, автоматизирующий запрос и продление сертификатов Let's Encrypt через CRD `Issuer`, `Certificate`, `Order`, `Challenge`.

---

## Basic Concepts

### Ограничения Let's Encrypt

| Лимит | Значение | Период |
| :--- | :--- | :--- |
| Сертификатов на домен | 50 | 7 дней |
| Запросов на регистрацию | 10 | 3 часа |
| Wildcard-сертификатов | 50 | 7 дней |
| Срок действия | 90 дней | — |

### ACME Solvers (проверки владения)

| Метод | Принцип | Wildcard | Требования |
| :--- | :--- | :--- | :--- |
| **HTTP-01** | Файл по `http://<domain>/.well-known/acme-challenge/` | ❌ Нет | Публичный Ingress |
| **DNS-01** | TXT-запись `_acme-challenge.<domain>` | ✅ Да | Доступ к DNS API |
| **TLS-ALPN-01** | TLS-соединение на порт 443 | ❌ Нет | Прямой доступ к 443 |

### Окружения Let's Encrypt

| Окружение | URL | Назначение |
| :--- | :--- | :--- |
| **Production** | `https://acme-v02.api.letsencrypt.org/directory` | Боевые сертификаты |
| **Staging** | `https://acme-staging-v02.api.letsencrypt.org/directory` | Тестирование (лимиты выше) |

> **Важно:** Staging использует отдельные тестовые CA, которые не доверяются браузерами. Используйте для отладки конфигурации.

### Поток запроса сертификата

```
Certificate → Order → Challenge(s) → CertificateRequest → Secret
```

**Подробное описание CRD:** [cert_manager definitions](../definitions.md)

---

## Practical Scenarios

| Сценарий | Документ | Описание |
| :--- | :--- | :--- |
| **ClusterIssuer с HTTP-01** | [letsencrypt_scenarios](./letsencrypt_scenarios.md) | Публичный сертификат для Ingress |
| **DNS-01 (Cloudflare)** | [letsencrypt_scenarios](./letsencrypt_scenarios.md) | Wildcard-сертификат через Cloudflare API |
| **DNS-01 (Yandex Cloud)** | [letsencrypt_scenarios](./letsencrypt_scenarios.md) | Проверка через Yandex Cloud DNS webhook |
| **Staging для тестирования** | [letsencrypt_scenarios](./letsencrypt_scenarios.md) | Отладка без лимитов production |
| **Несколько Issuer** | [letsencrypt_scenarios](./letsencrypt_scenarios.md) | Разделение по доменам/окружениям |

**Диагностика и частые ошибки:** [letsencrypt_advanced](./letsencrypt_advanced.md)

---

## Additional Information

### Best Practices

1. **Всегда используйте staging** для первичной настройки
2. **Настройте уведомления** на email о продлении
3. **Мониторьте статус** Certificate через Prometheus/Grafana
4. **Избегайте лимитов** — кэшируйте заказы при разработке

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| ACME протокол | **10** | RFC 8555, документация Let's Encrypt |
| HTTP-01 solver | **10** | Стандартный паттерн cert-manager |
| DNS-01 solver | **10** | Подтверждено для wildcard |
| Staging окружение | **10** | Официальное тестовое окружение LE |

**Связанные документы:** [cert_manager CRD](../definitions.md), [administration](../Administration/index.md), [private_ca](../Private_CA/index.md), [gateway_api](../gateway_api/practical_scenarios.md), [ingress](../ingress/scenarios.md).
