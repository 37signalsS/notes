# Интеграция cert-manager с Gateway API: Продвинутые темы и диагностика

## Определения

**Конфликт Hostname** — ситуация, при которой логика `gateway-shim` не может однозначно определить список доменов для выпуска сертификата из-за противоречий между полем `hostname` в слушателе Gateway и явными настройками в ресурсе `Certificate` или аннотациями.

**TLS Passthrough (Сквозной TLS)** — режим работы шлюза, при котором TLS-трафик передаётся бэкенду без расшифровки. Используется ресурс `TLSRoute`. В этом режиме шлюз не управляет сертификатами, и cert-manager на уровне инфраструктуры шлюза не задействуется.

**gateway-shim** — компонент cert-manager, отвечающий за автоматическую генерацию ресурсов `Certificate` на основе структуры и аннотаций `Gateway` и `ListenerSet`.

**Dedicated Challenge Gateway (Выделенный шлюз для проверок)** — архитектурный паттерн, изолирующий трафик ACME-проверок (HTTP-01) на отдельном шлюзе, что предотвращает конфликты с продуктовыми маршрутами и повышает безопасность.

---

## Основные концепции

### Разрешение конфликтов Hostname

При использовании автоматизации (gateway-shim) cert-manager извлекает список доменов из поля `spec.listeners[].hostname`. 

**Нюансы и рекомендации:**
1.  **Приоритет явных ресурсов:** Если вы создаете ресурс `Certificate` вручную, cert-manager игнорирует попытки автоматического выпуска для тех же доменов через аннотации Gateway. Это рекомендуемый подход для Production-сред.
2.  **Пустые Hostname (Wildcard):** Если в слушателе поле `hostname` не заполнено, Gateway API трактует это как «принимать любой трафик». В этом случае автоматический выпуск через аннотации невозможен — домены должны быть указаны явно в `Certificate`.
3.  **Дублирование в HTTPRoute:** Аннотации на уровне `HTTPRoute` имеют приоритет над аннотациями `Gateway` для конкретного маршрута.

### Механика HTTP-01 ParentRef Fallback (v1.21+)

В 2026 году стандартом для Self-Service TLS является использование `ListenerSet`, который часто работает только на порту 443. Однако проверка HTTP-01 требует порта 80.

**Решение:** Аннотация `acme.cert-manager.io/http01-parentreffallback: "true"`.
- Позволяет `ListenerSet` использовать слушатель порта 80 родительского `Gateway` для размещения временного `HTTPRoute` с ACME-токеном.
- Это исключает необходимость открывать порт 80 в каждом `ListenerSet`.

### Безопасность: ReferenceGrant в мультитеннантных средах

Gateway API запрещает кросс-неймспейс ссылки по умолчанию. Для работы TLS в распределенной среде:
1.  **Namespace `apps`**: Содержит `Certificate` и итоговый `Secret`.
2.  **Namespace `infra`**: Содержит `Gateway`.
3.  **ReferenceGrant**: Должен быть создан в namespace `apps`, разрешая группе `gateway.networking.k8s.io` (ресурс `Gateway`) доступ к объектам `Secret`.

---

## Практические сценарии

### Глубокая диагностика цепочки ресурсов

Если TLS-терминация не работает, используйте метод последовательного анализа (Resource Archaeology):

```bash
# 1. Проверка условий в ресурсе Gateway (уровни ResolvedRefs и Ready)
kubectl describe gateway <name> -n <namespace>

# 2. Проверка статуса в ListenerSet (если используется)
kubectl describe listenerset <name> -n <namespace>

# 3. Анализ CertificateRequest (трансляция ошибок от Issuer)
kubectl get certificaterequest -n <namespace>
kubectl describe certificaterequest <name>

# 4. Отслеживание временных маршрутов ACME
kubectl get httproute -A | grep "acme-http-01"
```

### Настройка выделенного шлюза для проверок (Dedicated Challenge Gateway)

Для крупных кластеров рекомендуется выносить все ACME-проверки на отдельный технический шлюз. Это настраивается в `ClusterIssuer`:

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    solvers:
    - http01:
        gatewayHTTPRoute:
          parentRefs:
          - name: acme-challenge-gateway
            namespace: cert-manager
            kind: Gateway
```

### Отладка в реальном времени через cmctl

Утилита `cmctl` (v1.20+) предоставляет нативный способ диагностики Gateway API:

```bash
# Проверка готовности инфраструктуры Gateway API для cert-manager
cmctl check api

# Статус сертификата с учетом привязки к Gateway
cmctl status certificate <name>
```

---

## Дополнительная информация

### Частые ошибки и методы их устранения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Gateway API not enabled` | Отсутствует флаг в контроллере | Добавить `--enable-gateway-api=true` в аргументы запуска cert-manager. |
| `Forbidden Secret reference` | Отсутствует `ReferenceGrant` | Создать `ReferenceGrant` в namespace, где лежит TLS-секрет. |
| `Hostname conflict` | Неоднозначность доменов | Указать `hostname` в слушателе явно или использовать ручной ресурс `Certificate`. |
| `ResolvedRefs: False` | Ошибка контроллера шлюза | Проверить, поддерживает ли ваш Gateway Controller версию Gateway API v1.1+. |
| `Challenge pending` | Недоступность 80 порта | Проверить наличие слушателя HTTP на родителе и аннотацию `http01-parentreffallback`. |

### Специфика версий (состояние на 2026 год)

*   **cert-manager v1.21+**: Стабильная поддержка `ListenerSet` и интеграция с протоколом ARI. Теперь ошибки выпуска сертификата транслируются непосредственно в `status.conditions` шлюза с детальным описанием причины (например, `RateLimitExceeded`).
*   **Gateway API v1.1+**: Является стандартом. Использование старых Ingress-контроллеров для новых сервисов не рекомендуется (статус EOL для многих реализаций).

### Смотрите также

- **[Практические сценарии интеграции](./practical_scenarios.md)** — полные YAML-примеры.
- **[Определения и концепции](./definitions_and_concepts.md)** — теоретическая база и ролевая модель.
- **[Cert-manager: Диагностика Let's Encrypt](../LetsEncrypt/letsencrypt_advanced.md)** — решение общих проблем с ACME.
