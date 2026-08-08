# Let's Encrypt: Диагностика и решение проблем

## Определения

**ACME-ошибки Let's Encrypt** — коды и сообщения об ошибках (RFC 8555), возвращаемые API-сервером Let's Encrypt при взаимодействии с контроллером cert-manager.

**Иерархия ресурсов (Resource Archaeology)** — метод последовательного анализа состояния цепочки объектов Kubernetes (Certificate → CertificateRequest → Order → Challenge), позволяющий точно локализовать сбой.

**cmctl** (Cert-manager Control) — специализированная CLI-утилита (ранее `kubectl cert-manager`) для проверки состояния контроллера, ресурсов и диагностики API.

**CAA (Certificate Authority Authorization)** — запись в DNS, указывающая, каким центрам сертификации разрешено выпускать сертификаты для данного домена.

---

## Основные концепции

### Иерархия диагностики (The "Archaeology" Flow)

Если объект `Certificate` не переходит в статус `Ready: True`, необходимо спускаться вниз по цепочке ресурсов. Ошибка всегда транслируется снизу вверх.

1.  **Certificate**: Содержит ссылки на текущий запрос.
2.  **CertificateRequest**: Описывает процесс формирования CSR.
3.  **Order**: Отражает состояние заказа в ACME API (pending, invalid, valid).
4.  **Challenge**: Конечная точка диагностики. Содержит причину сбоя проверки владения доменом.

### Инструментарий cmctl (2025–2026)

Для быстрой диагностики рекомендуется использовать утилиту `cmctl`:

```bash
# Проверка доступности вебхука и API
cmctl check api

# Детальный статус сертификата и всей цепочки ресурсов
cmctl status certificate <name> -n <namespace>

# Инспекция секрета (проверка срока, SAN, эмитента)
cmctl inspect secret <secret-name> -n <namespace>
```

### Типовые ACME-коды ошибок

| Код | Тип ошибки | Причина | Решение |
| :--- | :--- | :--- | :--- |
| `400` | `malformed` | Просроченный челлендж | Удалите `Challenge` для пересоздания |
| `403` | `unauthorized` | Ошибка авторизации | Проверьте DNS-записи или HTTP-доступ |
| `429` | `rateLimited` | Превышены лимиты | Используйте **Staging** окружение |
| `500` | `serverInternal` | Сбой на стороне CA | Ожидание (обычно до 1 часа) |

---

## Практические сценарии

### Глубокая диагностика через kubectl

Если `cmctl` недоступен, используйте стандартные команды:

```bash
# 1. Поиск проблемных ресурсов
kubectl get certificate,certificaterequest,order,challenge -A | grep -v "True"

# 2. Осмотр Challenge (самый информативный уровень)
kubectl describe challenge <name>

# 3. Чтение логов контроллера по домену
kubectl logs -n cert-manager -l app.kubernetes.io/instance=cert-manager | grep "example.com"
```

### Проблемы HTTP-01 проверки

**Симптом:** `Waiting for HTTP-01 challenge propagation: failed to perform self check`.

| Причина | Диагностика и решение |
| :--- | :--- |
| **Network Policies** | Убедитесь, что Ingress-контроллер может достучаться до пода-солвера (`cm-acme-http-solver`) по порту 8089. |
| **Split-horizon DNS** | Контроллер должен разрешать внешнее имя домена в IP своего Ingress. Настройте `recursive-nameservers` в аргументах контроллера. |
| **NAT Loopback** | Кластер за NAT не может достучаться до своего внешнего IP. Используйте **DNS-01** или настройте локальный проброс. |
| **Force HTTPS** | Редирект с 80 на 443 может мешать проверке. Исключите путь `/.well-known/acme-challenge/*` из редиректов. |

### Проблемы DNS-01 и CAA

**Симптом:** `CAA prevents issuance` или `DNS problem: networking error looking up CAA`.

1.  **Проверка CAA**: Если в DNS есть записи CAA, они должны явно разрешать Let's Encrypt:
    ```text
    example.com. IN CAA 0 issue "letsencrypt.org"
    ```
2.  **DNS Propagation**: Используйте флаг `--dns01-recursive-nameservers` (например, `8.8.8.8:53`), чтобы cert-manager проверял записи в обход внутреннего DNS кластера.
3.  **Permissions**: Секрет с API-токеном (Cloudflare/Yandex) должен находиться в том же namespace, что и `Issuer` (для `ClusterIssuer` — в namespace cert-manager).

### Диагностика ARI (ACME Renewal Information)

cert-manager 1.15+ использует ARI для динамического определения окна продления.

*   **Проверка**: Если сертификат обновляется задолго до `renewBefore`, это работа ARI.
*   **Диагностика**: `kubectl logs ... | grep "ARI"` покажет `suggestedWindow`. Это штатное поведение при обнаружении уязвимостей или техработах на стороне CA.

---

## Дополнительная информация

### Рекомендации по безопасности и стабильности

1.  **Gateway API**: В версиях 1.15+ поддержка Gateway API стабильна. Если сертификат не создается для `HTTPRoute`, проверьте наличие аннотации `cert-manager.io/issuer` на самом ресурсе `Gateway`.
2.  **Cleanup**: Если `Order` или `Challenge` зависли в статусе `invalid`, удалите их вручную. cert-manager автоматически инициирует новую попытку.
3.  **Staging-first**: Для любых тестов всегда используйте `server: https://acme-staging-v02.api.letsencrypt.org/directory`.
4.  **Resource Limits**: Недостаток памяти у пода `cert-manager` может приводить к перезагрузкам во время обработки больших списков `Challenge`.

### Смотрите также

- **[Углублённые концепции ACME](./letsencrypt_concepts.md)** — подробности ARI, CT-логи и типы аккаунтов.
- **[Практические сценарии Let's Encrypt](./letsencrypt_scenarios.md)** — полные YAML-примеры конфигураций.
- **[Cert-manager: Troubleshooting](../Administration/troubleshooting.md)** — общая диагностика контроллера (CPU, Memory, Webhook).

---
