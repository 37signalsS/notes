# Тестирование и перенос трафика при миграции на Gateway API

**Надёжность:** 10 (SSoT + Практический опыт эксплуатации v1.5/1.6)

## Определения

**Валидация конфигурации** — процесс проверки корректности ресурсов Gateway API (GatewayClass, Gateway, Routes) на соответствие спецификации и готовность контроллера к обработке трафика.

**Поэтапный перенос (Canary Migration)** — стратегия переключения трафика с устаревшего Ingress-контроллера на новую инфраструктуру Gateway API малыми порциями (например, 1%, 5%, 10%) для минимизации рисков.

**Status Conditions** — встроенный в Gateway API механизм обратной связи, позволяющий отслеживать состояние ресурсов (Accepted, Programmed, ResolvedRefs) через поле `status` в манифестах.

## Базовые концепции

### Стратегия верификации в 2026 году

Миграция считается успешной только после прохождения пяти уровней контроля:

1. **Синтаксический уровень:** Отсутствие ошибок в YAML и соответствие версии API (v1 для Standard Channel).
2. **Логический уровень:** Проверка статусов ресурсов (Conditions) — подтверждение того, что контроллер "понял" и "принял" настройки.
3. **Безопасность кросс-ссылок:** Проверка корректности `ReferenceGrant` для доступа к секретам или сервисам в других пространствах имён.
4. **Сетевой уровень:** Синтетические тесты (curl, openssl) через новый внешний IP-адрес.
5. **Операционный уровень:** Наличие метрик в Prometheus и логов доступа.

### Роль Status Conditions

Gateway API является самодокументированным. Если трафик не доходит до приложения, первым делом проверяются статусы:
- **Accepted:** Конфигурация синтаксически верна.
- **Programmed:** (Gateway) Балансировщик успешно настроен в облаке или on-premise.
- **ResolvedRefs:** (Route) Все зависимости (Service, Secret, ReferenceGrant) найдены и валидны.

## Практические сценарии

### Шаг 1: Диагностика статусов

Перед началом тестирования трафика убедитесь, что все ресурсы находятся в состоянии `True`.

```bash
# 1. Проверка шлюза
kubectl describe gateway main-gateway -n infra-ns

# Ищите в выводе:
# - Accepted: True
# - Programmed: True
# - IP-адрес в секции .status.addresses

# 2. Проверка маршрута и кросс-ссылок
kubectl describe httproute app-route -n app-ns

# Ищите:
# - Accepted: True
# - ResolvedRefs: True (Если False — проверьте наличие ReferenceGrant)
```

### Шаг 2: Синтетическое тестирование (Smoke Test)

Тестирование шлюза без изменения DNS-записей.

1. **Запрос через внешний IP шлюза:**
   ```bash
   # Получение IP-адреса шлюза
   GW_IP=$(kubectl get gateway main-gateway -n infra-ns -o jsonpath='{.status.addresses[0].value}')
   
   # Тест HTTP
   curl -v -H "Host: app.example.com" http://$GW_IP/api/health
   
   # Тест TLS (Проверка сертификата)
   openssl s_client -connect $GW_IP:443 -servername app.example.com
   ```

2. **Проверка Multi-tenancy (ListenerSet):**
   Если используются `ListenerSet`, убедитесь, что они успешно "приклеились" к основному шлюзу (`Programmed: True`).

### Шаг 3: Поэтапный перенос трафика (DNS/LB)

Переключение выполняется на уровне внешнего DNS (Route53, Cloudflare) или глобального балансировщика.

| Этап | Доля трафика | Метрики для мониторинга |
| :--- | :--- | :--- |
| **Smoke** | 1% | `gatewayapi_http_requests_total{code=~"5.."}` (Рост 5xx ошибок) |
| **Canary** | 10% | `gatewayapi_http_request_duration_seconds` (Задержки / Latency) |
| **Scaling** | 50% | Нагрузка на Control Plane контроллера (CPU/RAM) |
| **Full** | 100% | Сверка логов Ingress и Gateway API |

### Шаг 4: Операционный мониторинг (Prometheus)

Примеры запросов для валидации работы в 2026 году:

```promql
# Проверка конфликтов слушателей (должно быть 0)
sum(gatewayapi_gateway_listener_status{condition="Conflicted", status="True"})

# Сравнение успеха запросов (2xx/3xx) между Ingress и Gateway
sum(rate(gatewayapi_http_requests_total{code=~"[23].."}[5m])) / sum(rate(gatewayapi_http_requests_total[5m]))
```

## Дополнительная информация

### Типичные ошибки миграции

- **Отсутствие ReferenceGrant:** HTTPRoute в `namespace-A` не может ссылаться на Service в `namespace-B` без явного разрешения. В статусе будет `ResolvedRefs: False`.
- **Конфликт Hostnames:** Два HTTPRoute с одинаковым `hostname`, привязанные к одному Gateway, вызовут ошибку `Conflicted: True`.
- **Версия CRD:** Использование `v1alpha2` ресурсов в кластере с контроллером, ожидающим `v1`.

**См. также:**
- [Общий процесс миграции](./migration.md) — стратегия и инструменты (ingress2gateway).
- [Миграция TLS](./migration_tls_and_routing.md) — перенос сертификатов.
- [Определения Gateway API](./definitions.md) — подробнее о ролевой модели.

**Родительская тема:** [Gateway API](./definitions.md)
