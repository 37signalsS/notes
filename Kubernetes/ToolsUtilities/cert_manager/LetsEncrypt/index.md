# Let's Encrypt: Публичные сертификаты через ACME

## Определения

**Let's Encrypt** — бесплатный, автоматизированный и открытый центр сертификации (CA), использующий протокол ACME (RFC 8555) для выдачи TLS-сертификатов.

**ACME (Automatic Certificate Management Environment)** — протокол для автоматизированного получения и продления сертификатов через проверку владения доменом.

**ARI (ACME Renewal Information)** — расширение протокола ACME, позволяющее CA рекомендовать клиенту (cert-manager) оптимальное окно для продления. Это критически важно для предотвращения лимитов и обработки массовых отзывов.

**cert-manager** — Kubernetes-контроллер, автоматизирующий жизненный цикл сертификатов через CRD `Issuer`, `Certificate`, `Order`, `Challenge`.

---

## Основные концепции

### Ограничения Let's Encrypt (Rate Limits)

| Лимит | Значение | Период | Особенности |
| :--- | :--- | :--- | :--- |
| **Certificates per Domain** | 50 | 7 дней | На зарегистрированный домен (registered domain) |
| **Duplicate Certificates** | 5 | 7 дней | Один и тот же набор имен. **ARI позволяет обойти этот лимит.** |
| **Failed Validations** | 5 | 1 час | На аккаунт + имя хоста |
| **New Orders** | 300 | 3 часа | На аккаунт |
| **Срок действия** | 90 дней | — | Планируется переход на **45 дней** в 2025–2026 гг. |

### ACME ARI (Renewal Information)

Поддержка ARI появилась в cert-manager v1.15 (стабильно) и v1.21+ (расширенно).
- **Преимущество:** cert-manager больше не использует жесткое значение `renewBefore`, а опрашивает Let's Encrypt.
- **Отказоустойчивость:** Если Let's Encrypt обнаружит уязвимость в ключе, он через ARI даст команду всем клиентам немедленно обновить сертификаты.

### ACME Solvers (проверки владения)

| Метод | Принцип | Wildcard | Требования |
| :--- | :--- | :--- | :--- |
| **HTTP-01** | Файл по `http://<domain>/.well-known/acme-challenge/` | ❌ Нет | Публичный порт 80, Ingress |
| **DNS-01** | TXT-запись `_acme-challenge.<domain>` | ✅ Да | Доступ к API DNS-провайдера |
| **TLS-ALPN-01** | TLS-соединение на порт 443 | ❌ Нет | Прямой доступ к 443, без прокси |

### Окружения Let's Encrypt

| Окружение | URL | Назначение |
| :--- | :--- | :--- |
| **Production** | `https://acme-v02.api.letsencrypt.org/directory` | Боевые сертификаты (строгие лимиты) |
| **Staging** | `https://acme-staging-v02.api.letsencrypt.org/directory` | Тестирование (лимиты в сотни раз выше) |

> **Важно:** Сертификаты Staging не доверяются браузерами. Используйте их для отладки конфигурации `ClusterIssuer` и DNS-01.

---

## Практические сценарии

| Сценарий | Документ | Описание |
| :--- | :--- | :--- |
| **ClusterIssuer с HTTP-01** | [letsencrypt_scenarios](./letsencrypt_scenarios.md) | Публичный сертификат для Ingress |
| **DNS-01 (Cloudflare)** | [letsencrypt_scenarios](./letsencrypt_scenarios.md) | Wildcard-сертификат через Cloudflare API |
| **DNS-01 (Yandex Cloud)** | [letsencrypt_scenarios](./letsencrypt_scenarios.md) | Проверка через Yandex Cloud DNS webhook |
| **Staging для тестирования** | [letsencrypt_scenarios](./letsencrypt_scenarios.md) | Отладка без риска блокировок |

**Диагностика и решение проблем:** [letsencrypt_advanced](./letsencrypt_advanced.md)

---

## Дополнительная информация

### Best Practices (2025)

1. **Используйте cert-manager v1.15+**: Это необходимо для поддержки ARI и готовности к переходу на 45-дневные сертификаты.
2. **Мониторинг вместо Email**: Let's Encrypt прекращает рассылку уведомлений по почте. Настройте алерты Prometheus на метрику `cert_manager_certificate_expiration_timestamp_seconds`.
3. **Высокая доступность (HA)**: Для продакшена запускайте `cert-manager-webhook` в **3 репликах**. Сбой вебхука блокирует создание любых ресурсов в кластере.
4. **Staging-first**: Любая смена DNS-провайдера или конфигурации Issuer должна сначала проверяться в Staging.
5. **Безопасность**: Используйте `Secret` с минимальными правами для DNS-01 (например, Cloudflare API Token вместо Global Key).

### Смотрите также

- **[Cert-manager: Определения](../definitions.md)** — базовая структура CRD
- **[Cert-manager: Администрирование](../Administration/index.md)** — эксплуатация и HA
- **[Ingress: Сценарии интеграции](../ingress/scenarios.md)** — примеры использования в Ingress
- **[Углублённые концепции ACME](./letsencrypt_concepts.md)** — подробности ARI, CT-логи и типы аккаунтов

---

### Достоверность информации

| Предмет | Оценка | Источник |
| :--- | :--- | :--- |
| Лимиты Let's Encrypt | **10** | Официальная документация LE (2024–2025) |
| Протокол ARI | **9** | RFC 9773, документация cert-manager |
| ACME Solvers | **10** | RFC 8555 |
| Рекомендации HA | **9** | Практика эксплуатации крупных кластеров |
