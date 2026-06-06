# Cert-manager: Интеграция с Ingress

## Определения

**Ingress-интеграция cert-manager** — механизм автоматического создания и обновления TLS-сертификатов для Ingress-ресурсов через добавление специальных аннотаций. Cert-manager обнаруживает аннотации, создаёт ресурс `Certificate`, проходит ACME-проверку и сохраняет сертификат в `Secret`, который используется Ingress для терминации TLS.

**Преимущества:**

- Минимальная конфигурация (только аннотации в Ingress)
- Автоматическое получение и продление сертификатов
- Совместимость с любым Ingress-контроллером (nginx, Traefik, HAProxy)
- Поддержка HTTP-01 и DNS-01 проверок

> **См. также:** [Cert-manager: Определения и основные понятия](../definitions.md) — CRD, типы Issuer, структура ресурсов.

---

## Основные концепции

### Поток работы

```
Ingress с аннотацией cert-manager
       ↓
cert-manager обнаруживает аннотацию
       ↓
Автоматически создаётся ресурс Certificate
       ↓
Выполняется ACME-проверка (HTTP-01 или DNS-01)
       ↓
Сертификат сохраняется в указанный Secret
       ↓
Ingress использует Secret для TLS-терминации
```

### Аннотации cert-manager для Ingress

Полный список аннотаций и их значений доступен в [Cert-manager: Определения](../definitions.md#интеграция-с-ingress).

**Ключевые аннотации:**

| Аннотация | Описание | Пример |
| :--- | :--- | :--- |
| `cert-manager.io/issuer` | Issuer в том же namespace | `my-issuer` |
| `cert-manager.io/cluster-issuer` | ClusterIssuer (общекластерный) | `letsencrypt-prod` |
| `cert-manager.io/issue-temporary-certificate` | Временный сертификат до ACME | `true` |
| `cert-manager.io/acme-challenge-type` | Принудительный solver | `http01`, `dns01` |
| `cert-manager.io/common-name` | Переопределение CN | `example.com` |
| `cert-manager.io/duration` | Срок действия сертификата | `2160h` (90 дней) |
| `cert-manager.io/renew-before` | Время до начала продления | `360h` (15 дней) |
| `cert-manager.io/private-key-size` | Размер ключа | `4096` |
| `cert-manager.io/private-key-algorithm` | Алгоритм ключа | `RSA`, `ECDSA` |

### Устаревшие аннотации

| Устаревшая | Современная замена |
| :--- | :--- |
| `kubernetes.io/tls-acme: "true"` | `cert-manager.io/cluster-issuer` |
| `certmanager.k8s.io/issuer` | `cert-manager.io/issuer` |

> **Важно:** Используйте только аннотации с префиксом `cert-manager.io`. Устаревшие префиксы `certmanager.k8s.io` и `kubernetes.io/tls-acme` не поддерживаются в актуальных версиях.

### Базовый пример Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myapp-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - myapp.example.com
    secretName: myapp-tls
  rules:
  - host: myapp.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: myapp-service
            port:
              number: 80
```

---

## Практические сценарии

Подробные примеры использования доступны в отдельном документе:

- **[Сценарии интеграции](./scenarios.md)** — HTTP-01, wildcard-домены, временные сертификаты, прямой Certificate

**Типовые сценарии (кратко):**

| Сценарий | Описание | Аннотации |
| :--- | :--- | :--- |
| Базовый HTTP-01 | Автоматический сертификат для одного домена | `cert-manager.io/cluster-issuer` |
| Несколько доменов (SAN) | Один сертификат для нескольких хостов | `+ cert-manager.io/common-name` |
| Временный сертификат | Избежание ошибок TLS во время ACME | `+ cert-manager.io/issue-temporary-certificate: "true"` |
| Wildcard через DNS-01 | Сертификат `*.example.com` | `+ cert-manager.io/acme-challenge-type: "dns01"` |
| Прямой Certificate | Полный контроль без аннотаций | Не требуются (Certificate создаётся вручную) |

---

## Дополнительная информация

### Диагностика

```bash
# Статус сертификата
kubectl get certificate -n <namespace>

# Детали Certificate (ошибки, события)
kubectl describe certificate <name> -n <namespace>

# Связанные Order и Challenge (ACME)
kubectl get order -n <namespace>
kubectl get challenge -n <namespace>

# Логи cert-manager
kubectl logs -n cert-manager -l app=cert-manager --tail=100
```

### Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Waiting for HTTP-01 challenge` | Ingress недоступен извне | Проверить LoadBalancer, firewall, DNS |
| `Secret not found` | Certificate ещё не создан | Подождать 1–2 минуты, проверить логи cert-manager |
| `Issuer not found` | Неправильный namespace или имя Issuer | Проверить аннотацию и наличие ClusterIssuer/Issuer |
| `Rate limit exceeded` | Лимит Let's Encrypt исчерпан | Использовать staging-сервер, подождать |

### Связанные документы

- **[Cert-manager: Определения](../definitions.md)** — CRD, Issuer, ACME Solvers
- **[Let's Encrypt](../LetsEncrypt/index.md)** — публичные сертификаты через ACME
- **[Private CA](../Private_CA/index.md)** — собственные центры сертификации
- **[Administration](../Administration/index.md)** — управление и диагностика cert-manager
- **[Сценарии интеграции](./scenarios.md)** — детальные примеры манифестов
- **[Ingress: Обзор](../../../Networking/Ingress/overview.md)** — общие концепции Ingress и TLS
