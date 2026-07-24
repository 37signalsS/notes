# Cert-manager: Интеграция с Ingress

## Определения

**Ingress-интеграция cert-manager** — механизм автоматического создания и обновления TLS-сертификатов для Ingress-ресурсов. Реализуется компонентом **ingress-shim**, который отслеживает создание и изменение объектов Ingress и, при наличии специальных аннотаций, автоматически создает ресурсы `Certificate`.

**Преимущества:**

- Минимальная конфигурация (только аннотации в Ingress)
- Полная автоматизация жизненного цикла сертификата (от заказа до продления)
- Совместимость с любым Ingress-контроллером (nginx, Traefik, HAProxy, AWS ALB, GCE)
- Поддержка различных методов ACME-проверки (HTTP-01, DNS-01)

> **См. также:** [Cert-manager: Определения и основные понятия](../definitions.md) — CRD, типы Issuer, структура ресурсов.

---

## Основные концепции

### ingress-shim

**ingress-shim** — это встроенный контроллер в составе cert-manager, отвечающий за интеграцию с Ingress. Он работает по следующему алгоритму:
1. Сканирует аннотации в Ingress.
2. Если найдены аннотации выбора Issuer (например, `cert-manager.io/cluster-issuer`), создает объект `Certificate`.
3. Объект `Certificate` настраивается так, чтобы его `secretName` совпадал с `tls[].secretName` из Ingress, а домены — с `tls[].hosts`.
4. В дальнейшем cert-manager обрабатывает `Certificate` стандартным образом.

### Использование Issuer по умолчанию

Если при установке cert-manager были настроены флаги `--default-issuer-name` и `--default-issuer-kind`, можно инициировать выпуск сертификата простой аннотацией:
`kubernetes.io/tls-acme: "true"` — заставляет cert-manager использовать Issuer по умолчанию.

### Поток работы

```
Ingress с аннотацией cert-manager
       ↓
ingress-shim обнаруживает аннотацию
       ↓
Автоматически создаётся ресурс Certificate
       ↓
Выполняется ACME-проверка (HTTP-01 или DNS-01)
       ↓
Сертификат сохраняется в указанный Secret
       ↓
Ingress-контроллер подхватывает Secret для TLS
```

---

## Аннотации cert-manager для Ingress

### Основные (Выбор Issuer)

| Аннотация | Описание | Пример |
| :--- | :--- | :--- |
| `cert-manager.io/issuer` | Issuer в том же namespace | `my-issuer` |
| `cert-manager.io/cluster-issuer` | ClusterIssuer (общекластерный) | `letsencrypt-prod` |
| `kubernetes.io/tls-acme: "true"` | Использовать Issuer по умолчанию | `"true"` |

### Настройка параметров сертификата

| Аннотация | Описание | Значение |
| :--- | :--- | :--- |
| `cert-manager.io/common-name` | Установка Common Name (CN) | `example.com` |
| `cert-manager.io/duration` | Срок действия | `1080h` (45 дней) |
| `cert-manager.io/renew-before` | За сколько до конца продлевать | `168h` (7 дней) |
| `cert-manager.io/usages` | Использование ключа (через запятую) | `server auth, client auth` |
| `cert-manager.io/certificate-name` | Явное имя ресурса Certificate | `my-app-cert` |
| `cert-manager.io/issue-temporary-certificate` | Временный сертификат до ACME | `"true"` |

### Параметры приватного ключа (Стандарты 2026)

| Аннотация | Описание | Пример |
| :--- | :--- | :--- |
| `cert-manager.io/private-key-algorithm` | Алгоритм | `RSA`, `ECDSA`, `Ed25519` |
| `cert-manager.io/private-key-size` | Размер | `2048`, `4096`, `256`, `384` |
| `cert-manager.io/private-key-rotation-policy` | Политика ротации ключа | `Always` (рекомендуется) |

### Специфичные для ACME (HTTP-01)

| Аннотация | Описание | Когда использовать |
| :--- | :--- | :--- |
| `acme.cert-manager.io/http01-edit-in-place` | Не создавать временный Ingress | AWS ALB, GCE Ingress |
| `acme.cert-manager.io/http01-ingress-class` | Класс Ingress для проверки | Если отличается от основного |

---

## Базовый пример Ingress (2026)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myapp-ingress
  annotations:
    # Выбор Issuer
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    # Безопасность: ротация ключа при каждом обновлении сертификата
    cert-manager.io/private-key-rotation-policy: "Always"
    # Для AWS ALB / GCE (необязательно для NGINX)
    # acme.cert-manager.io/http01-edit-in-place: "true"
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

- **[Сценарии интеграции](./scenarios.md)** — HTTP-01, wildcard-домены, временные сертификаты, прямой Certificate.

---

## Дополнительная информация

### Диагностика через cmctl

Для диагностики рекомендуется использовать официальную утилиту **cmctl** (преемник плагина kubectl cert-manager).

```bash
# Проверка статуса сертификата
cmctl status certificate myapp-tls -n <namespace>

# Проверка готовности Issuer
cmctl check api

# Просмотр логов контроллера через kubectl
kubectl logs -n cert-manager -l app=cert-manager --tail=100
```

### Диагностика через kubectl

```bash
# Список всех ресурсов выпуска
kubectl get certificate,certificaterequest,order,challenge -n <namespace>

# Ошибки в конкретном заказе (Order)
kubectl describe order <order-name> -n <namespace>
```

### Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Waiting for HTTP-01 challenge` | Ingress недоступен извне или 80 порт закрыт | Проверить LoadBalancer, Firewall, DNS |
| `Issuer not found` | Неверное имя или namespace | Проверить ClusterIssuer vs Issuer |
| `Rate limit exceeded` | Слишком много запросов к Let's Encrypt | Использовать Let's Encrypt Staging для тестов |

### Связанные документы

- **[Cert-manager: Определения](../definitions.md)** — CRD, Issuer, ACME Solvers
- **[Gateway API: TLS](../gateway_api/definitions_and_concepts.md)** — современная замена Ingress-интеграции
- **[Let's Encrypt](../LetsEncrypt/index.md)** — работа с публичными CA
- **[Administration](../Administration/index.md)** — администрирование и тюнинг cert-manager
- **[Ingress: Обзор](../../../Networking/Ingress/overview.md)** — общие концепции Ingress
