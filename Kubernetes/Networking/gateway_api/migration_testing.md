# Тестирование и перенос трафика при миграции на Gateway API

## Определения

**Валидация конфигурации** — процесс проверки корректности ресурсов Gateway API (GatewayClass, Gateway, Routes) на соответствие спецификации и готовность контроллера к обработке трафика.

**Поэтапный перенос (Canary Migration)** — стратегия переключения трафика с устаревшего Ingress-контроллера на новую инфраструктуру Gateway API малыми порциями (например, 1%, 5%, 10%) для минимизации рисков.

**Blue-Green Deployment** — стратегия развертывания с двумя идентичными средами (blue — текущая, green — новая), где переключение трафика выполняется атомарно на уровне DNS или балансировщика.

**Status Conditions** — встроенный в Gateway API механизм обратной связи, позволяющий отслеживать состояние ресурсов (Accepted, Programmed, ResolvedRefs) через поле `status` в манифестах.

**Synthetic Testing** — метод проверки работоспособности инфраструктуры с помощью искусственно сгенерированных запросов (curl, openssl) без изменения production-трафика.

## Предварительные требования

Перед началом тестирования и переноса трафика убедитесь, что выполнены следующие условия:

| Компонент | Требование | Проверка |
|:---|:---|:---|
| Kubernetes | Версия 1.25+ | `kubectl version --short` |
| Gateway API CRD | v1.0+ (Standard Channel) | `kubectl get crd gateways.gateway.networking.k8s.io` |
| Контроллер Gateway API | Установлен и работает | `kubectl get pods -n <controller-namespace>` |
| Prometheus | Для сбора метрик (опционально) | `kubectl get servicemonitor -A` |
| DNS-управление | Доступ к управлению DNS-записями | Возможность создавать/изменять A/CNAME записи |

**Проверка готовности контроллера:**
```bash
# Проверка статуса GatewayClass
kubectl get gatewayclass -o yaml
# → status.conditions[].type=Accepted должно быть True

# Проверка логов контроллера (пример для Envoy Gateway)
kubectl logs -n envoy-gateway-system -l control-plane=envoy-gateway-controller --tail=50
# → Должно быть "started" без ошибок
```

## Базовые концепции

### Стратегия верификации

Миграция считается успешной только после прохождения пяти уровней контроля:

1. **Синтаксический уровень:** Отсутствие ошибок в YAML и соответствие версии API (v1 для Standard Channel).
2. **Логический уровень:** Проверка статусов ресурсов (Conditions) — подтверждение того, что контроллер "понял" и "принял" настройки.
3. **Безопасность кросс-ссылок:** Проверка корректности `ReferenceGrant` для доступа к секретам или сервисам в других пространствах имён.
4. **Сетевой уровень:** Синтетические тесты (curl, openssl) через новый внешний IP-адрес.
5. **Операционный уровень:** Наличие метрик в Prometheus и логов доступа.

### Роль Status Conditions

Gateway API является самодокументированным. Если трафик не доходит до приложения, первым делом проверяются статусы:
- **Accepted:** Конфигурация синтаксически верна.
- **Programmed:** (Gateway) Балансировщик успешно настроен в инфраструктуре (on-premise или ЦОД).
- **ResolvedRefs:** (Route) Все зависимости (Service, Secret, ReferenceGrant) найдены и валидны.

### Стратегии переноса трафика

| Стратегия | Описание | Преимущества | Недостатки |
|:---|:---|:---|:---|
| **Canary** | Постепенное увеличение доли трафика (1% → 5% → 10% → 50% → 100%) | Минимальный риск, возможность отката | Длительный процесс |
| **Blue-Green** | Атомарное переключение между двумя идентичными средами | Быстрый откат, простота | Требует двойных ресурсов |
| **Shadow** | Дублирование трафика на новую систему без влияния на пользователей | Безопасное тестирование | Сложность реализации |

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

# 3. Массовая проверка всех ресурсов
kubectl get gateway,httproute -A -o jsonpath='{range .items[*]}{.kind}{"/"}{.metadata.name}{"\t"}{.metadata.namespace}{"\t"}{.status.conditions[0].type}{"\t"}{.status.conditions[0].status}{"\n"}{end}'
```

**Ожидаемый результат:**
```bash
# → Gateway/main-gateway    infra-ns    Accepted    True
# → HTTPRoute/app-route      app-ns      Accepted    True
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

3. **Проверка содержимого ответа:**
   ```bash
   # Сравнение ответов от Ingress и Gateway API
   curl -s -o /dev/null -w "%{http_code}" -H "Host: app.example.com" http://$INGRESS_IP/api/health
   curl -s -o /dev/null -w "%{http_code}" -H "Host: app.example.com" http://$GW_IP/api/health
   
   # Оба кода должны совпадать (например, 200)
   ```

### Шаг 3: Поэтапный перенос трафика (Canary)

Переключение выполняется на уровне внешнего DNS или глобального балансировщика.

| Этап | Доля трафика | Метрики для мониторинга | Действия при проблемах |
|:---|:---|:---|:---|
| **Smoke** | 1% | `gatewayapi_http_requests_total{code=~"5.."}` (Рост 5xx ошибок) | Немедленный откат на предыдущий этап |
| **Canary** | 10% | `gatewayapi_http_request_duration_seconds` (Задержки / Latency) | Анализ логов, сравнение с Ingress |
| **Scaling** | 50% | Нагрузка на Control Plane контроллера (CPU/RAM) | Масштабирование контроллера |
| **Full** | 100% | Сверка логов Ingress и Gateway API | Деактивация Ingress через 24-48 часов |

**Пример настройки Canary через DNS:**
```bash
# Предположим, текущая запись:
# app.example.com.  CNAME  ingress-old.example.com.

# Создание weighted записей:
# app.example.com.  CNAME  gw-new.example.com.  (weight: 10)
# app.example.com.  CNAME  ingress-old.example.com.  (weight: 90)
```

### Шаг 3a: Blue-Green Deployment

Альтернативная стратегия с атомарным переключением:

```bash
# 1. Развертывание "зеленой" среды (Gateway API)
kubectl apply -f gateway-api-manifests/

# 2. Проверка "зеленой" среды
GW_IP=$(kubectl get gateway green-gateway -n infra-ns -o jsonpath='{.status.addresses[0].value}')
curl -v -H "Host: app.example.com" http://$GW_IP/api/health

# 3. Переключение DNS на "зеленую" среду
# app.example.com.  CNAME  green-gateway.example.com.

# 4. Мониторинг 24-48 часов
# При проблемах — мгновенный откат:
# app.example.com.  CNAME  blue-ingress.example.com.
```

### Шаг 4: Операционный мониторинг (Prometheus)

Примеры запросов для валидации работы:

```promql
# Проверка конфликтов слушателей (должно быть 0)
sum(gatewayapi_gateway_listener_status{condition="Conflicted", status="True"})

# Сравнение успеха запросов (2xx/3xx) между Ingress и Gateway
sum(rate(gatewayapi_http_requests_total{code=~"[23].."}[5m])) / sum(rate(gatewayapi_http_requests_total[5m]))

# Мониторинг задержений (P95)
histogram_quantile(0.95, sum(rate(gatewayapi_http_request_duration_seconds_bucket[5m])) by (le))

# Количество ошибок контроллера
sum(rate(gatewayapi_controller_reconcile_errors_total[5m]))
```

**Алерты для мониторинга:**
```yaml
- alert: GatewayAPIHighErrorRate
  expr: sum(rate(gatewayapi_http_requests_total{code=~"5.."}[5m])) / sum(rate(gatewayapi_http_requests_total[5m])) > 0.05
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Gateway API возвращает более 5% ошибок 5xx"

- alert: GatewayAPIHighLatency
  expr: histogram_quantile(0.95, sum(rate(gatewayapi_http_request_duration_seconds_bucket[5m])) by (le)) > 1
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "P95 задержка Gateway API превышает 1 секунду"
```

### Шаг 5: Валидация переноса трафика

```bash
# 1. Сравнение количества запросов
# Получение метрик из логов Ingress и Gateway API
kubectl logs -n ingress-ns -l app=ingress-controller --since=1h | grep -c "GET /api"
kubectl logs -n infra-ns -l app=envoy --since=1h | grep -c "GET /api"

# 2. Проверка отсутствия ошибок в логах контроллера
kubectl logs -n infra-ns -l app=gateway-controller --since=1h | grep -i error
# → Должно быть пусто или только известные некритичные ошибки

# 3. Финальная проверка статусов
kubectl get gateway,httproute -A | grep -v "True"
# → Должно быть пусто (все ресурсы в состоянии True)
```

## Troubleshooting

### Типичные ошибки и решения

| Симптом | Причина | Решение |
|:---|:---|:---|
| `ResolvedRefs: False` | Отсутствие ReferenceGrant для кросс-неймспейс ссылок | Создать ReferenceGrant в target namespace |
| `Programmed: False` | Контроллер не может настроить балансировщик | Проверить логи контроллера, права доступа |
| `Conflicted: True` | Два HTTPRoute с одинаковым hostname на одном Gateway | Исправить hostnames или разделить на разные Gateway |
| 5xx ошибки после переноса | Неверная конфигурация бэкенда или фильтров | Проверить логи Envoy/прокси, валидность Service |
| Увеличение задержек | Проблемы с сетью или перегрузка контроллера | Масштабировать контроллер, проверить сетевые политики |
| TLS-ошибки | Неверный сертификат или отсутствие ReferenceGrant для Secret | Проверить статус Certificate, наличие ReferenceGrant |

### Диагностика проблем

```bash
# Проверка всех условий ресурсов
kubectl get gateway,httproute -A -o jsonpath='{range .items[*]}{.kind}{"/"}{.metadata.name}{"\t"}{.status.conditions[0].type}{"\t"}{.status.conditions[0].status}{"\n"}{end}'

# Просмотр событий с ошибками
kubectl get events -A --field-selector reason=ResolvedRefsFailed
kubectl get events -A --field-selector reason=BackendNotFound
kubectl get events -A --field-selector reason=ProgrammedFailed

# Проверка логов контроллера
kubectl logs -n <controller-namespace> -l control-plane=controller --tail=100 | grep -i error

# Проверка конфигурации Envoy (для Envoy Gateway)
kubectl exec -n <controller-namespace> deploy/envoy-gateway -- envoy-config-dump | jq '.configs[] | select(.["@type"] == "type.googleapis.com/envoy.config.route.v3.RouteConfiguration")'
```

### Откат изменений

```bash
# Откат DNS на старый Ingress
# app.example.com.  CNAME  ingress-old.example.com.

# Или через kubectl (если использовался автоматический инструмент)
kubectl annotate ingress app-ingress -n app-ns "external-dns.alpha.kubernetes.io/target=ingress-old.example.com"

# Проверка отката
dig app.example.com +short
# → Должен указывать на старый Ingress
```

## Best Practices

### Подготовка к миграции

1. **Документируйте текущую конфигурацию:**
   ```bash
   kubectl get ingress -A -o yaml > ingress-backup.yaml
   kubectl get ingressclass -A -o yaml > ingressclass-backup.yaml
   ```

2. **Создайте план отката:**
   - Зафиксируйте текущие DNS-записи
   - Подготовьте скрипт для быстрого отката
   - Определите ответственных за откат

3. **Настройте мониторинг заранее:**
   - Убедитесь, что Prometheus собирает метрики Gateway API
   - Настройте алерты до начала переноса

### Процесс переноса

1. **Начинайте с малого:**
   - Переносите один сервис за раз
   - Начинайте с наименее критичных сервисов
   - Увеличивайте долю трафика постепенно

2. **Мониторинг на каждом этапе:**
   - Сравнивайте метрики до и после переключения
   - Анализируйте логи на наличие ошибок
   - Проверяйте задержки (P50, P95, P99)

3. **Коммуникация:**
   - Уведомляйте команду о начале переноса
   - Определите канал для экстренной связи
   - Зафиксируйте временные окна для каждого этапа

### После миграции

1. **Наблюдение 24-48 часов:**
   - Держите старый Ingress активным для возможности быстрого отката
   - Мониторьте метрики в течение суток

2. **Очистка:**
   ```bash
   # После успешного переноса и стабилизации
   kubectl delete ingress app-ingress -n app-ns
   kubectl delete ingressclass nginx  # Если больше не используется
   ```

3. **Документирование:**
   - Зафиксируйте финальную конфигурацию
   - Обновите runbooks и инструкции
   - Проведите post-mortem анализ

## Дополнительная информация

### Нюансы использования

- **Время распространения DNS:** Учитывайте TTL DNS-записей. Рекомендуется снизить TTL до 60-300 секунд за 24 часа до миграции.
- **Сессионная привязка:** Приложения с сессиями могут требовать дополнительной настройки (sticky sessions).
- **Кэширование:** Убедитесь, что клиенты и промежуточные прокси не кэшируют старые DNS-записи.

**См. также:**

- [Общий процесс миграции](./migration.md) — стратегия и инструменты (ingress2gateway).
- [Миграция TLS](./migration_tls_and_routing.md) — перенос сертификатов.
- [Определения Gateway API](./definitions.md) — подробнее о ролевой модели.

**Родительская тема:** [Gateway API](./definitions.md)