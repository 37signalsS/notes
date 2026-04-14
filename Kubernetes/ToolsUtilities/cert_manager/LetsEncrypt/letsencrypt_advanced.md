# Let's Encrypt: Диагностика и troubleshooting

## Definitions

**ACME-ошибки Let's Encrypt** — ошибки, возвращаемые сервером Let's Encrypt при прохождении проверок владения доменом (HTTP-01, DNS-01, TLS-ALPN-01).

> **Общая диагностика cert-manager:** [Administration troubleshooting](../Administration/troubleshooting.md)

---

## Basic Concepts

### ACME-коды ошибок Let's Encrypt

| Код | ACME Error Type | Причина |
| :--- | :--- | :--- |
| `400` | `malformed` | Некорректный ACME-запрос |
| `403` | `unauthorized` | Проверка не пройдена, неверный ключ |
| `429` | `rateLimited` | Превышен лимит запросов |
| `500` | `serverInternal` | Внутренняя ошибка LE |

### Лимиты Let's Encrypt (повторно)

| Лимит | Значение | Период | Сброс |
| :--- | :--- | :--- | :--- |
| Certificates per Domain | 50 | 7 дней | Скользящее окно |
| Certificates per Registered Domain | 50 | 7 дней | По базе suffix |
| Failed Validation | 5 | 1 час | По IP + домен |
| New Orders per Account | 300 | 3 часа | По аккаунту |

**Подробные лимиты:** [letsencrypt_concepts](./letsencrypt_concepts.md)

---

## Practical Scenarios

### Диагностика ACME-Challenge

```bash
# Статус конкретного Challenge
kubectl describe challenge -l cert-manager.io/certificate-name=<cert-name>

# Детали ACME-запроса из логов
kubectl logs -n cert-manager -l app=cert-manager --tail=200 | grep -iE "acme|challenge|error"

# Проверка HTTP-01 извне (если доступен)
curl -v http://<domain>/.well-known/acme-challenge/<token>

# Проверка DNS-01 TXT-записи
dig TXT _acme-challenge.<domain> +short
```

### Rate limit exceeded (429)

**Симптом:** `acme: error: 429 :: urn:ietf:params:acme:error:rateLimited`

**Решение:**

1. Переключиться на staging-сервер для отладки:

   ```yaml
   spec:
     acme:
       server: https://acme-staging-v02.api.letsencrypt.org/directory
   ```

2. Дождаться сброса лимита (1 час для Failed Validation, 7 дней для Certificates per Domain)
3. Проверить конфигурацию на staging перед повторным запросом в production

### HTTP-01 не проходит

**Симптом:** `Connection timed out` или `404 Not Found` от LE сервера.

**Диагностика:**

| Проверка | Команда |
| :--- | :--- |
| Ingress существует | `kubectl get ingress -A` |
| Solver Pod запущен | `kubectl get pods -n cert-manager -l app=cert-manager-acmesolver` |
| Порт 80 доступен извне | `curl http://<domain>/.well-known/acme-challenge/test` |
| Firewall/Security Group | Проверить правило входящего трафика на порт 80 |

### DNS-01 не проходит

**Симптом:** `DNS problem: NXDOMAIN looking up TXT` или `DNS problem: SERVFAIL`.

**Диагностика:**

| Проверка | Команда |
| :--- | :--- |
| TXT-запись создана | `dig TXT _acme-challenge.<domain> +short` |
| DNS API credentials верны | Проверить Secret: `kubectl get secret <dns-credentials> -o yaml` |
| DNS propagation | Подождать 1–5 минут, повторить `dig` |
| Webhook для провайдера | `kubectl logs -n cert-manager -l app=webhook` |

### Staging vs Production: типичные проблемы

| Проблема | Staging | Production |
| :--- | :--- | :--- |
| Сертификат не доверяется браузерами | ✅ Ожидается (тестовый CA) | ❌ Не должно происходить |
| Лимиты выше | ✅ 50000/неделю | ❌ 50/неделю |
| Задержки обработки | ✅ Возможны | Обычно быстрее |

> **Важно:** После успешной отладки на staging создайте отдельный production `ClusterIssuer` и `Certificate`. Не переиспользуйте staging-ресурсы.

---

## Additional Information

### Best Practices для Let's Encrypt

1. **Staging-first** — всегда тестируйте на staging перед production
2. **Раздельные Issuer** — отдельные `ClusterIssuer` для staging и production
3. **Мониторинг** — отслеживание `Certificate Ready` через Prometheus/Grafana
4. **Заблаговременное продление** — `renewBefore: 360h` (15 дней) для 90-дневных сертификатов
5. **Кэширование при разработке** — использовать один Certificate для нескольких доменов вместо множественных запросов
6. **Email для уведомлений** — указать `email` в ClusterIssuer для получения уведомлений об истечении

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| ACME error codes | **10** | RFC 8555, документация Let's Encrypt |
| Rate limits | **10** | [letsencrypt.org/docs/rate-limits](https://letsencrypt.org/docs/rate-limits) |
| Diagnostic commands | **9** | Стандартные kubectl + cert-manager CRD |
| Staging behavior | **10** | Подтверждено официальной документацией LE |

**Связанные документы:** [углублённые концепции](./letsencrypt_concepts.md), [практические сценарии](./letsencrypt_scenarios.md), [cert_manager CRD](../definitions.md), [Administration troubleshooting](../Administration/troubleshooting.md).
