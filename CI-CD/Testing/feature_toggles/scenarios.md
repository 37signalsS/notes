# Сценарии использования Feature Toggles

## Определения

**Сценарии использования Feature Toggles** — это типовые архитектурные и бизнес-паттерны, реализуемые через механизмы динамического управления функциональностью в рантайме. Использование сценариев позволяет полностью разделить технический деплой (Deployment) и бизнес-релиз (Release), обеспечивая гибкость и безопасность доставки ПО.

**Blast Radius (Радиус поражения)** — объем негативного влияния на пользователей или систему в случае сбоя новой функциональности. Feature Toggles являются основным инструментом контроля этого показателя, позволяя ограничить воздействие узким сегментом трафика.

---

## Предварительные требования

Перед внедрением сценариев Feature Toggles необходима базовая инфраструктура.

### Инструментарий для каждого типа сценария

| Тип сценария | Минимальная инфраструктура | Рекомендуемый стек |
| :--- | :--- | :--- |
| **Canary / Dark Launch** | FFaaS-платформа + SDK + мониторинг | Unleash/Flipt + OpenFeature SDK + Prometheus + Grafana |
| **Kill Switch / Circuit Breaker** | FFaaS-платформа + Alertmanager | Unleash + Alertmanager webhook → Unleash API |
| **A/B Тестирование** | FFaaS + аналитика + трассировка | Unleash + OTel Collector + Grafana Tempo |
| **Dual Write / Shadow Read** | Клиентские библиотеки + логирование | OpenFeature SDK + structured logging + Prometheus |
| **Permission Toggles** | FFaaS + IAM-интеграция | Unleash + OIDC-провайдер для сегментации |

### Требования к команде

- **Владелец (Owner)** для каждого флага — конкретный инженер или команда, ответственная за удаление после завершения эксперимента.
- **Процесс очистки (Cleanup)**: TTL (Time to Live) обязателен для релизных и экспериментальных флагов. Операционные флаги (Kill Switch) — бессрочные.
- **Согласование переключений**: Для критических флагов в Production — процесс four-eyes principle (четыре глаза).
- **Соглашение об именовании**: Единый формат, например `[domain].[feature].[action].[identifier]`.

---

## Основные концепции

### Критерии выбора сценария

Выбор подхода зависит от бизнес-цели, допустимого уровня риска и требуемой скорости реакции системы. В 2026 году к классическим критериям добавились требования по стоимости (FinOps) и безопасности (SecOps).

| Цель | Сценарий | Тип флага | Динамичность | Владелец |
| :--- | :--- | :--- | :--- | :--- |
| **Постепенный запуск** | Canary Deployment | Релизный / Экспериментальный | Высокая | Dev / QA |
| **Снижение рисков** | Kill Switch / Circuit Breaker | Операционный | Критическая | SRE / DevOps |
| **Ограниченный доступ** | Бета-тестирование / Dark Launch | Флаг разрешений | Средняя | Product / Marketing |
| **Проверка гипотез** | A/B Тестирование | Экспериментальный | Высокая | Product / Data |
| **Миграция систем** | Shadow Read / Dual Write | Операционный | Высокая | Backend / DBA |
| **Оптимизация затрат** | Cost Optimization / FinOps | Операционный | Средняя | FinOps / SRE |
| **Безопасность** | Security Patch / Compliance | Операционный | Критическая | SecOps / Legal |

### Фундаментальные принципы реализации

1.  **Контекстное управление (Context-awareness):** Решение о включении флага принимается на основе атрибутов входящего запроса (ID пользователя, геопозиция, тип устройства, версия приложения, статус подписки, ID организации).
2.  **Детерминизм и «Липкость» (Stickiness):** Для одного и того же контекста (например, `user_id`) флаг должен возвращать консистентное значение на протяжении всей сессии или эксперимента, чтобы избежать "мерцания" интерфейса или логики.
3.  **Безопасные фолбеки (Safe Fallbacks):** Наличие захардкоженных значений по умолчанию на случай недоступности системы управления флагами (FFaaS) или сетевых сбоев. Принцип Fail-safe: система должна продолжать работать в стабильном, предсказуемом состоянии.
4.  **Глубокая наблюдаемость (Advanced Observability):** Каждое переключение должно сопровождаться телеметрией. В 2026 году обязательна инъекция состояния флагов в спаны **OpenTelemetry** и логи запросов для анализа влияния на производительность, ошибки и бизнес-метрики.

### Выбор между Static и Dynamic флагами

| Критерий | Static (флаги в Git) | Dynamic (платформа флагов) |
| :--- | :--- | :--- |
| Скорость изменения | Скорость мержа PR (минуты) | Мгновенно (API/UI) |
| Аудит | Полный, в Git-истории | Только если платформа экспортирует события |
| Drift | Невозможен — Git единственный источник | Возможен: правка в UI ≠ Git |
| Инфраструктура | Ноль дополнительной | Платформа + ее HA + бэкапы |
| Типичные сценарии | Kill Switch (реабилитация через revert) | A/B тесты, процентная раскатка |

**Практический гибрид:** Kill Switch и настройки по умолчанию — в Git (static); эксперименты и раскатки — в платформе (dynamic) с обязательным экспортом событий в аудит.

---

## Практические сценарии

### Сценарий 1: Канареечный релиз (Canary Deployment)

Постепенное включение новой функции для процента пользователей с целью мониторинга стабильности. В отличие от сетевого Canary (на уровне Nginx/Envoy/Istio), флаги позволяют сегментировать пользователей по любым атрибутам приложения.

**Контекст:** Новая система рекомендаций развёрнута, но ее влияние на бизнес-метрики неизвестно.

#### Реализация (Python/SDK)

```python
user_context = {
    "user_id": user.id,
    "region": "EU",
    "is_beta": user.is_beta,
    "version": "2.4.0"
}

if ff_client.is_enabled("new-payment-checkout", context=user_context):
    return render_modern_checkout()
return render_legacy_checkout()
```

#### Конфигурация Unleash (процентная раскатка)

```bash
# Процентная раскатка через Unleash API
curl -s -X PUT "$UNLEASH_URL/api/admin/projects/default/features/new-payment-checkout/environments/production/variants" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "variants": [
      {"name": "new", "weight": 10},
      {"name": "old", "weight": 90}
    ],
    " stickiness": "default",
    "group": "new-payment-checkout"
  }'
```

#### Автоматизация: Prometheus Alertmanager → Unleash

Если метрики ухудшились — автоматическое отключение флага:

```yaml
# alertmanager.yml — webhook в Unleash при росте 5xx
route:
  receiver: unleash-webhook
  match:
    alertname: HighErrorRateCheckout

receivers:
  - name: unleash-webhook
    webhook_configs:
      - url: 'http://unleash-webhook.internal:8080/api/admin/projects/default/features/new-payment-checkout/environments/production/off'
        send_resolved: true
```

```python
# Flask-эндпоинт для Alertmanager (если нет прямого webhook)
@app.route('/webhook/alertmanager', methods=['POST'])
def handle_alertmanager():
    data = request.json
    if data.get('status') == 'firing' and data.get('labels', {}).get('alertname') == 'HighErrorRateCheckout':
        unleash_client.disable_feature('new-payment-checkout')
        logger.warning("Auto-disabled new-payment-checkout due to high error rate")
    return '', 200
```

*Подробнее о метриках автогейтов см. в документе **[Canary мониторинг и гейтинг](../Deployment_Strategies/canary_monitoring_and_gating.md)**.*

---

### Сценарий 2: Аварийный выключатель (Kill Switch)

Мгновенное отключение ресурсоемкой или сбойной функции при деградации инфраструктуры.

**Контекст:** При росте нагрузки на БД выше 90% или всплеске 5xx ошибок в сервисе рекомендаций, SRE через панель управления (Unleash, Flagsmith или LaunchDarkly) отключает флаг, чтобы спасти основной функционал покупки.

#### Реализация в коде

```python
@app.route('/product/<id>')
def product_page(id):
    product = db.get_product(id)
    recommendations = []
    
    # Kill Switch: если флаг выключен или FFaaS недоступна — рекомендаций нет
    # Fail-safe: значение по умолчанию False (рекомендации отключены)
    if ff_client.is_enabled("enable-ai-recommendations"):
        try:
            with tracer.start_as_current_span("fetch_recommendations") as span:
                span.set_attribute("feature_flag.ai_recs", True)
                recommendations = ai_service.get_related(id)
        except Exception as e:
            logging.error(f"AI Service failure: {e}")
            recommendations = []
    
    return render_template('product.html', product=product, recs=recommendations)
```

#### Автоматический Kill Switch через Alertmanager

```yaml
# Пример Prometheus-правила для автоматического отключения
groups:
  - name: feature-flag-automation
    rules:
      - alert: KillSwitchTriggerCheckoutRecommendations
        expr: |
          (
            rate(http_requests_total{service="checkout", status=~"5.."}[5m])
            / rate(http_requests_total{service="checkout"}[5m])
          ) > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Auto-disabling checkout recommendations due to error rate"
          runbook_url: "https://wiki.internal/runbooks/kill-switch-checkout-recs"
```

#### Ручное отключение

```bash
# Dynamic (Unleash): мгновенное отключение через API
curl -s -X POST "$UNLEASH_URL/api/admin/projects/billing/features/new-checkout/environments/production/off" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN"
# → {"enabled": false}
```

*Правило эксплуатации:* Любое runtime-переключение фиксируется в инцидент-тикете, а follow-up PR приводит статическое состояние (Git) в соответствие — иначе следующий рефакторинг наткнется на рассинхрон «UI против Git».*

---

### Сценарий 3: Разрыв цепи (Circuit Breaker) на уровне приложения

Ручное или автоматическое отключение интеграции с внешним нестабильным API.

**Контекст:** Внешний сервис проверки кредитного рейтинга начал отвечать с задержкой 10 сек. Чтобы не блокировать поток заказов и не исчерпать пул воркеров приложения, интеграция временно отключается через флаг.

#### Реализация в коде

```python
import time
from circuitbreaker import circuit

# Circuit Breaker: автоматическое отключение при превышении порога ошибок
@circuit(failure_threshold=5, recovery_timeout=60)
def call_credit_check(user_id: str) -> dict:
    """Вызов внешнего API кредитного рейтинга."""
    response = external_credit_api.check(user_id, timeout=3)
    return response.json()

@app.route('/order/<user_id>')
def create_order(user_id: str):
    # Флаг-оркестратор: если флаг выключен — пропуск проверки
    if not ff_client.is_enabled("enable-credit-check"):
        return process_order_without_check(user_id)
    
    try:
        credit_result = call_credit_check(user_id)
        if credit_result['approved']:
            return process_order(user_id)
        return render_template('order_denied.html')
    except Exception:
        # Fallback: запись в Outbox для последующей обработки
        outbox.add_pending_check(user_id)
        return render_template('order_pending_review.html')
```

#### Конфигурация Outbox для отказоустойчивости

```python
# Outbox: запросы, которые не удалось обработать, сохраняются для retry
class PendingCheckOutbox:
    def __init__(self, redis_client):
        self.redis = redis_client
    
    def add_pending_check(self, user_id: str):
        self.redis.lpush("pending_credit_checks", json.dumps({
            "user_id": user_id,
            "timestamp": time.time(),
            "retry_count": 0
        }))
    
    def process_pending(self):
        """Фоновый воркер обрабатывает накопленные запросы."""
        while True:
            item = self.redis.rpop("pending_credit_checks")
            if item:
                data = json.loads(item)
                try:
                    result = call_credit_check(data['user_id'])
                    finalize_order(data['user_id'], result)
                except Exception:
                    data['retry_count'] += 1
                    if data['retry_count'] < 3:
                        self.redis.lpush("pending_credit_checks", json.dumps(data))
            time.sleep(10)
```

**Фолбек:** Запись запроса в очередь (Outbox) для последующей обработки или пропуск проверки с пометкой «требует ручного подтверждения». Это позволяет системе сохранять работоспособность при отказе зависимостей.

---

### Сценарий 4: Бета-тестирование и сегментация (Entitlements)

Предоставление доступа к функциям на основе ролей, вхождения в список (Allow-list) или специфических атрибутов подписки.

```python
# Доступ только для сотрудников компании и участников программы раннего доступа
context = {
    "user_id": user.id,
    "email": user.email,
    "is_staff": user.is_staff,
    "org_id": user.org_id
}

if user.is_staff or ff_client.is_enabled("next-gen-editor", context=context):
    enable_experimental_features()
```

---

### Сценарий 5: Миграция данных (Shadow Read / Dual Write)

Безопасный переход с одной БД/API на другую без простоя с использованием принципа **[Expand-Contract](../../Databases/Concepts/migrations/expand_contract.md)**.

#### Пошаговая реализация

1.  **Dual Write:** Приложение пишет данные в старую (основная) и новую (теневая) системы. Ошибки в теневой системе логируются, но не блокируют основной процесс.

```python
# Dual Write: запись в обе системы
def save_user_profile(user_id: str, data: dict):
    # Основная запись (старая система) — всегда работает
    old_db.users.update({"_id": user_id}, {"$set": data})
    
    # Теневая запись (новая система) — ошибки не блокируют
    if ff_client.is_enabled("dual-write-new-db"):
        try:
            new_db.profiles.upsert({"user_id": user_id}, data)
        except Exception as e:
            # Логируем, но не падаем
            logger.warning(f"Dual write failed for {user_id}: {e}")
```

2.  **Shadow Read:** Читаем из старой и новой систем одновременно. Сравниваем результаты в фоновом режиме, логируем расхождения. Флаг позволяет включать этот режим для 1% трафика.

```python
# Shadow Read: сравнение результатов из двух систем
def get_user_profile(user_id: str) -> dict:
    old_result = old_db.users.find_one({"_id": user_id})
    
    if ff_client.is_enabled("shadow-read-new-db", {"user_id": user_id}):
        try:
            new_result = new_db.profiles.find_one({"user_id": user_id})
            if old_result != new_result:
                logger.info(f"Shadow read mismatch for {user_id}: "
                           f"old={old_result}, new={new_result}")
        except Exception as e:
            logger.warning(f"Shadow read failed: {e}")
    
    return old_result  # Всегда возвращаем из старой системы
```

3.  **Primary Switch:** Переключаем флаг, делая новую систему основной для чтения. Старая остается для подстраховки (Fallthrough) и продолжает получать записи (Dual Write).
4.  **Contract:** После подтверждения стабильности (отсутствие расхождений в течение недели) отключаем старую систему.

---

### Сценарий 6: Оптимизация стоимости (FinOps / Cost Control)

Динамическое отключение функций, требующих дорогих вычислений или внешних платных вызовов, в зависимости от бюджета или нагрузки.

#### Реализация через Quota-флаги

```python
# Ограничение использования дорогих ресурсов на основе бюджета организации
context = {"org_id": org.id, "quota_remaining": org.monthly_api_calls_left}

if ff_client.is_enabled("enable-premium-analytics", context=context):
    result = expensive_analytics_api.query(query)
else:
    # Бесплатный план: упрощенная аналитика или кэшированные данные
    result = cached_analytics.get(query_hash)

# Контроль LLM-моделей: переключение между дорогими и дешевыми
if org.plan == "enterprise":
    model = "gpt-4-turbo"  # Дорогая модель для премиум-клиентов
elif ff_client.is_enabled("llm-downgrade-to-cheaper", {"org_id": org.id}):
    model = "llama-3-local"  # Локальная модель, без внешних API-вызовов
else:
    model = "gpt-3.5-turbo"  # Стандартная модель
```

#### Автоматическое переключение при достижении лимита

```python
# Мониторинг квоты и автоматическое переключение
@app.before_request
def check_quota():
    org = get_current_org()
    if org.monthly_api_calls_used >= org.monthly_api_calls_limit * 0.9:
        # 90% квоты использовано — включаем downgrade
        ff_client.set_feature("llm-downgrade-to-cheaper", {"org_id": org.id}, True)
```

*Пример:* В период пиковых нагрузок отключается функция детальной аналитики поведения пользователей в реальном времени, если стоимость вычислений превышает заданный лимит.

---

### Сценарий 7: Темный запуск (Dark Launching)

Развертывание кода и подача на него реального трафика «в тени» без изменения UI. Цель — прогрев кэшей, проверка производительности бэкенда и наполнение БД новыми данными.

#### Реализация в коде

```python
def get_search_results(query: str):
    legacy_results = legacy_engine.search(query)
    
    # Теневой запуск через флаг
    if ff_client.is_enabled("shadow-search-v2"):
        try:
            # Вычисляем, но не используем в ответе
            shadow_results = v2_engine.search(query)
            # Логируем расхождения для анализа
            compare_and_log(legacy_results, shadow_results)
        except Exception as e:
            logging.error(f"Shadow search failed: {e}")
            
    return legacy_results
```

**Метод:** Активация флага, который инициирует асинхронный вызов новой логики. Результат отбрасывается, но система мониторинга собирает метрики потребления ресурсов (CPU, Memory, IO).

---

### Сценарий 8: Безопасность и комплаенс (Security Toggles)

Мгновенная реакция на обнаруженные уязвимости или изменение законодательных требований.

*   **Emergency Patch:** При обнаружении критической уязвимости в новом модуле авторизации, он отключается глобально через Kill Switch до выпуска исправления.

```bash
# Мгновенное отключение уязвимого модуля
curl -s -X POST "$UNLEASH_URL/api/admin/projects/default/features/vulnerable-auth-module/environments/production/off" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN"
# Отправка алерта в SecOps
curl -s -X POST "https://alertmanager.internal/api/v1/alerts" \
  -d '[{"labels":{"alertname":"SecurityToggleActivated","module":"auth","severity":"critical"}}]'
```

*   **Regional Compliance:** Динамическое включение/выключение функций (например, биометрического входа или определенных методов сбора данных) в зависимости от региона пользователя для соответствия GDPR, CCPA или локальным законам.

```python
# Определение доступных функций на основе региона
context = {"user_id": user.id, "country": user.country_code}

features = {
    "biometric_login": ff_client.is_enabled("biometric-login-enabled", context),
    "cookie_consent_banner": ff_client.is_enabled("gdpr-cookie-consent", context),
    "data_export_api": ff_client.is_enabled("ccpa-data-export", context),
}
return render_template('settings.html', features=features)
```

---

### Сценарий 9: Инфраструктурная миграция (Storage Switch)

Переключение между хранилищами данных или CDN на уровне приложения без изменения DNS или балансировщиков.

**Контекст:** Переход с одного файлового хранилища на другое (например, с NFS на Ceph/S3-совместимое, или междуONUS-хранилищами) без downtime.

#### Реализация в коде

```python
# Определение провайдера хранилища через флаг
storage_provider = ff_client.get_string_value(
    "storage-provider", 
    default="ceph-legacy",
    context={"org_id": org.id, "file_type": file_type}
)

STORAGE_BACKENDS = {
    "ceph-legacy": CephStorage(host="ceph-old.internal"),
    "ceph-new": CephStorage(host="ceph-new.internal"),
    "minio": MinioStorage(endpoint="minio.internal:9000"),
}

storage = STORAGE_BACKENDS[storage_provider]
storage.upload(file_key, file_data)
```

#### Конфигурация переключения

```yaml
# Unleash: конфигурация флага с процентным распределением
flags:
  storage-provider:
    variants:
      - name: ceph-legacy
        weight: 80
      - name: ceph-new
        weight: 20
    defaultVariant: ceph-legacy
    targeting:
      rules:
        - context:
            org_id:
              in: ["org-beta-testers"]
          variant: ceph-new
```

*Это позволяет проводить миграцию данных между хранилищами, постепенно переключая трафик по организациям, типам контента или регионам.*

---

## Техническая наблюдаемость (OpenTelemetry)

В 2026 году проверка флага считается критическим событием. Состояние всех активных флагов должно быть доступно в трассировке.

### Инъекция состояния флагов в спаны

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

def process_request(user):
    with tracer.start_as_current_span("main_logic") as span:
        variant = ff_client.get_variant("checkout-ui-version", user.id)
        
        # Инъекция состояния флага в атрибуты спана для последующего анализа в Jaeger/Grafana
        span.set_attribute("app.feature_flag.key", "checkout-ui-version")
        span.set_attribute("app.feature_flag.variant", variant)
        
        if variant == "v3":
            return run_checkout_v3()
        return run_checkout_v2()
```

### Дашборды для мониторинга флагов

| Метрика | PromQL-запрос | Назначение |
| :--- | :--- | :--- |
| % пользователей с активным флагом | `sum by (flag) (feature_flag_evaluations_total{value="true"}) / sum by (flag) (feature_flag_evaluations_total)` | Визуализация экспозиции |
| Ошибки при оценке флага | `rate(feature_flag_evaluation_errors_total[5m]) > 0` | Детекция проблем с FFaaS |
| Latency оценки флага | `histogram_quantile(0.99, rate(feature_flag_evaluation_duration_seconds_bucket[5m]))` | Производительность SDK |
| Сравнение метрик по группам | `rate(http_requests_total{feature_flag="new-checkout"}[5m])` vs base | Влияние флага на бизнес |

---

## Валидация и тестирование

### Что проверять перед запуском

| Проверка | Метод | Ожидаемый результат |
| :--- | :--- | :--- |
| Флаг создан и доступен | API-запрос к платформе | Флаг возвращается в списке активных |
| Значение по умолчанию | SDK с пустым контекстом | Возвращает `False` (для новых фич) или `defaultVariant` |
| Таргетинг по проценту | Генерация 1000 запросов с разными `user_id` | ~10% получают `True` при настройке `10%` |
| «Липкость» (Stickiness) | Два запроса с одним `user_id` | Оба возвращают одинаковое значение |
| Fail-safe при недоступности FFaaS | Остановка сервера флагов, запрос к приложению | Приложение работает в safestate (все новые фичи выключены) |
| Инъекция в OpenTelemetry | Запрос → проверка спана в Jaeger/Tempo | Атрибут `feature_flag.*` присутствует в спане |
| Kill Switch срабатывает | Имитация алерта (curl к webhook) | Флаг отключается за < 30 секунд |

### Автоматизация тестирования

| Уровень теста | Подход | Практика |
| :--- | :--- | :--- |
| **Unit-тесты** | Toggle-aware testing | Параметризация для запуска тестов в обоих состояниях (`On/Off`) |
| **Интеграционные** | Shadow Testing | Новая логика в фоне, результаты сравниваются, но не возвращаются |
| **E2E / QA** | Matrix Testing | Стандартный набор (все флаги Off) + целевой (все флаги раскатки On) |
| **Смок-тесты** | Default State Validation | Проверка старта приложения при недоступности FFaaS |
| **SRE-валидация** | Chaos Engineering | Имитация отказа FFaaS → приложение должно работать с fallback-значениями |

---

## Типичные проблемы и решение

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Флаг не переключается через UI | SDK кеширует старое значение | Убедиться, что SDK настроен на polling/sse (сINCT intervals); проверить `maxAge` в конфигурации провайдера |
| Приложение падает при недоступности FFaaS | Отсутствие fail-safe значений по умолчанию | Каждая проверка флага обязана содержать fallback-значение: `get_boolean_value("flag", False)` |
| Флаги живут годами, код оброс ветвлениями | Нет процесса удаления | Expiration-даты, cleanup-PR обязательным пунктом Definition of Done, лимит активных флагов на сервис |
| Тесты взрываются от числа комбинаций | Все флаги тестируются во всех сочетаниях | CI гоняет дефолтную конфигурацию; комбинации — точечные e2e только для активных раскаток |
| Оценка флага добавляет latency | Ход в удаленную платформу на каждый вызов | Локальный flagd/sidecar, кеширование провайдера; платформа — источник истины, не hot path |
| Прод ведет себя не как staging | Разные значения флагов в средах | Декларативное управление через GitOps; diff флагов между средами — часть ревью PR |
| Утечка экспериментального функционала | Флаг доступен всем пользователям без сегментации | Настроить targeting rules: флаг доступен только определенным сегментам (staff, beta, определенный регион) |
| Неконсистентность данных при Dual Write | Флаг переключил запись до завершения Backfill | Расширенный паттерн Expand-Contract: флаг управляет только логикой чтения/записи, но не структурой таблиц |
| Включили флаг — а миграции БД нет | Функциональность завязана на схему | Expand-contract: схема совместима с обоими путями кода; контракт-фаза удаляется после стабилизации |
| Secret попал в конфиг флага | Флаговый конфиг используют как конфиг приложения | Запретить политикой (conftest/Kyverno); секреты — только через ESO/SOPS |

---

## Ограничения и особые случаи

### Когда Feature Toggles НЕ подходят

- **Простые CRUD-приложения** без альтернативных веток логики — Overhead от инфраструктуры флагов не окупается.
- **Критические пути с нулевой容忍 к latency** — каждая проверка флага добавляет вычисления (хотя и `O(1)` при локальном вычислении). В high-frequency trading или real-time bidding этот overhead может быть неприемлем.
- **Замена системы авторизации** — флаги не предназначены для обеспечения безопасности. Злоумышленник может подменить контекст на клиенте.

### Ограничения по архитектуре

- **Комбинаторный взрыв:** 10 независимых бинарных флагов дают 1024 состояния системы. Необходимо ограничивать количество одновременно активных релизных флагов на сервис (типично: 5-10).
- **Глобальные побочные эффекты:** Если два флага влияют на один глобальный ресурс (переменную окружения, запись в БД) в несовместимых режимах — возникает коллизия. Требуется группировка флагов по доменам и конфликт-тестирование.
- **Миграции БД:** Флаги не должны управлять структурой таблиц. Попытка изменять схему БД внутри логических условий флага приводит к разрыву между состоянием кода и схемы.

### Edge Cases в Production

- **Одновременное включение нескольких экспериментов:** Если два A/B-теста затрагивают один и тот же UI-компонент, результаты могут быть искажены. Необходимо выявлять пересечения и запускать их последовательно или исключать пересекающуюся аудиторию.
- **Кэширование на CDN/Браузере:** Если флаг определяет видимость элемента UI, а страница кэшируется CDN или браузером, пользователь может видеть устаревшее состояние. Решение: не кэшировать страницы с активными флагами или добавлять `Cache-Control: no-cache` для путей с флагами.
- **Offline-режим (Mobile):** При отсутствии сети SDK не может получить обновленное значение флага. Используйте bootstrap-файл (последнее известное состояние) или hardcoded fallback.

---

## Governance: Управление жизненным циклом флагов

### Flag Lifecycle Automation

```
Создание флага → Установка TTL → Мониторинг → Cleanup → Удаление
       │               │              │            │          │
    PR с кодом     поле в UI      алерт       auto-PR    merge в main
    + флаг         expiration   (30 дней    (удаление   + удаление
    в реестре       в FFaaS     без изменений)  if/else)   из реестра
```

### Процессы Governance

- **Flag Aging:** Автоматические алерты в Slack/Jira для владельцев флагов, которые не меняли состояние более 30 дней.
- **Auto-Cleanup:** Боты (аналог Uber Piranha) анализируют код и создают Pull Request на удаление флага, если он включен на 100% во всех окружениях и тесты проходят успешно.
- **Metric-Driven Toggling:** Автоматическое переключение экспериментальных флагов (Multi-armed bandit) в пользу наиболее конверсионного варианта без участия человека.
- **Flag Auditing:** Ежемесячный аудит всех флагов со статусом "Permanent" (постоянные флаги разрешений или Kill Switch).
- **Лимиты:** Не более N активных release-флагов на сервис (типично 5-10). Cleanup-PR обязателен после стабилизации.

---

## Дополнительная информация

### См. также
- **[Обзор Feature Toggles](./overview.md)** — концептуальное введение и парадигма Deploy vs Release.
- **[Типы Feature Toggles](./types.md)** — детальная классификация флагов по времени жизни.
- **[Архитектура систем](./architecture.md)** — проксирование, реле и хранилища флагов.
- **[Реализация в коде](./implementation.md)** — использование паттерна Wrapper и OpenFeature SDK.
- **[Лучшие практики](./best_practices.md)** — гигиена кода и стратегии тестирования.
- **[Антипаттерны](./antipatterns.md)** — как избежать «спагетти-логики» и утечки секретов.
- **[Expand-Contract в БД](../../Databases/Concepts/migrations/expand_contract.md)** — детальное описание паттерна для сценария 5.
- **[Feature Flags в GitOps](../../../GitOps/Concepts/feature_flags_gitops.md)** — разделение deploy и release, комбинация с canary.
- **[Canary мониторинг и гейтинг](../Deployment_Strategies/canary_monitoring_and_gating.md)** — метрики и автоматизация гейтинга.

### Внешние ресурсы
- [Feature Toggles (Martin Fowler)](https://martinfowler.com/articles/feature-toggles.html) — фундаментальное описание моделей.
- [OpenFeature Standard](https://openfeature.dev/) — открытый стандарт для интеграции Feature Flags.
- [Circuit Breaker Pattern (Microsoft)](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker) — паттерн отказоустойчивости.
- [Shadow Deployment Patterns](https://www.split.io/glossary/shadow-deployment/) — подробнее о теневых запусках.
