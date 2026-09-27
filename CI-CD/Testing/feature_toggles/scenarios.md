# Сценарии использования Feature Toggles

## Определения

**Feature Toggle (Feature Flag, фиче-флаг)** — механизм управления функциональностью, позволяющий изменять поведение системы во время выполнения (runtime) без изменения исходного кода и повторного развертывания. Флаг инкапсулирует проверку `if/else`, которая принимает решение о включении или отключении конкретной ветки логики.

**Канареечный релиз (Canary Deployment)** — стратегия прогрессивной поставки, при которой новая функциональность открывается для постепенно увеличивающегося сегмента пользователей (1% → 5% → 25% → 100%) с контролем метрик на каждом этапе. В отличие от сетевого Canary (Ingress/Envoy), флаги сегментируют по атрибутам приложения (`user_id`, регион, версия клиента).

**Аварийный выключатель (Kill Switch)** — операционный флаг с приоритетом безопасности, предназначенный для мгновенного отключения критической или деградировавшей функциональности. Значение по умолчанию — `True` (фича активна), чтобы при отказе FFaaS система продолжала работать в штатном режиме.

**Разрыв цепи (Circuit Breaker)** — паттерн отказоустойчивости, комбинируемый с флагом для управления временным отключением нестабильной внешней зависимости (API, БД, сервис) с возможностью последующего восстановления.

**Теневой запуск (Dark Launching)** — техника проверки производительности, при которой новая логика выполняется параллельно с рабочей, но результат отбрасывается. Цель — прогрев кешей, нагрузочное тестирование и сбор метрик без изменения пользовательского опыта.

**Shadow Read / Dual Write** — паттерн безопасной миграции данных, при котором приложение одновременно пишет в старую и новую системы (Dual Write) или сравнивает результаты чтения (Shadow Read) без влияния на основной поток.

**Stickiness (Липкость)** — свойство системы возвращать одно и то же значение флага для одного и того же контекста (`user_id`, `session_id`) на протяжении всего эксперимента или сессии, исключая «мерцание» интерфейса.

**Fail-safe** — режим деградации, при котором система продолжает работать в безопасном состоянии при недоступности FFaaS, сетевых сбоях или невалидном контексте.

---

## Основные концепции

### Критерии выбора сценария

Выбор подхода зависит от бизнес-цели, допустимого риска и требуемой скорости реакции. Для SRE/DevOps критичны динамичность контроля и возможность автоматизации.

| Цель | Сценарий | Тип флага | Динамичность | Владелец |
| :--- | :--- | :--- | :--- | :--- |
| **Постепенный запуск** | Canary Deployment | Release / Experiment | Высокая | Dev / QA |
| **Снижение рисков** | Kill Switch / Circuit Breaker | Ops | Критическая | SRE / DevOps |
| **Ограниченный доступ** | Beta Testing / Entitlements | Permission | Средняя | Product / Marketing |
| **Проверка гипотез** | A/B Testing | Experiment | Высокая | Product / Data |
| **Миграция систем** | Shadow Read / Dual Write | Ops / Release | Высокая | Backend / DBA |
| **Безопасность** | Emergency Patch | Ops | Критическая | SecOps / SRE |
| **Инфраструктура** | Storage Switch | Ops / Release | Средняя | SRE / DevOps |

### Контекстное управление и таргетинг

Решение о включении флага принимается на основе атрибутов запроса. В 2026 году стандартом является декларативный targeting внутри FFaaS-платформы (Unleash, Flipt) или через локальный демон flagd.

```python
context = {
    "user_id": user.id,
    "region": user.region,
    "is_staff": user.is_staff,
    "app_version": request.headers.get("X-App-Version"),
    "org_id": user.org_id
}

if ff_client.is_enabled("modern-checkout", context=context):
    return run_modern_workflow()
return run_legacy_workflow()
```

Для высоконагруженных сервисов вычисление происходит локально (OpenFeature SDK + flagd sidecar), что дает `O(1)` производительность без сетевого вызова во внешнюю систему на каждый запрос.

### Детерминизм и липкость (Stickiness)

Для одного и того же контекста флаг должен возвращать консистентное значение на протяжении всей сессии или эксперимента. Нарушение этого принципа приводит к «мерцанию» UI и невалидным результатам A/B-тестов.

```python
# Правильно: stickiness по user_id
variant = ff_client.get_variant("checkout-ui-v3", user_id=user.id)
# Один user_id → один variant на всю сессию
```

В Unleash stickiness настраивается на уровне флага (`stickiness: default/customField`), в Flipt — через сегменты с условиями.

### Fail-safe значения и деградация

При недоступности FFaaS система должна деградировать в безопасное состояние. Правило простое: новые фичи выключены, защита активна.

```python
# Release / Experiment / Permission: default=False
release_flag = client.get_boolean_value("new-checkout", False, context)
experiment_flag = client.get_boolean_value("exp-search-v2", False, context)
permission_flag = client.get_boolean_value("beta-editor", False, context)

# Ops (Kill Switch): default=True
ops_kill_switch = client.get_boolean_value("killswitch-recs", True, context)
```

Дополнительная защита — bootstrap-файл с последними известными состояниями, смонтированный в приложение через ConfigMap/Volume.

### Наблюдаемость: OpenTelemetry и метрики

Каждая проверка флага — критическое событие. Состояние флага инжектируется в спаны OpenTelemetry, что позволяет при анализе трейсов видеть, какая ветка кода сработала для конкретного запроса.

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

def process_request(user):
    with tracer.start_as_current_span("main_logic") as span:
        variant = ff_client.get_variant("checkout-ui-version", user.id)
        span.set_attribute("app.feature_flag.key", "checkout-ui-version")
        span.set_attribute("app.feature_flag.variant", variant)
        span.set_attribute("app.feature_flag.enabled", variant != "off")

        if variant == "v3":
            return run_checkout_v3()
        return run_checkout_v2()
```

### Static vs Dynamic флаги

| Критерий | Static (Git) | Dynamic (FFaaS) |
| :--- | :--- | :--- |
| Скорость изменения | Скорость мержа PR | Мгновенно (API/UI) |
| Аудит | Git history | Audit Log + экспорт в SIEM |
| Drift | Невозможен | Возможен: правка в UI ≠ Git |
| Инфраструктура | Ноль дополнительной | FFaaS + HA + бэкапы |
| Типичные сценарии | Kill Switch, default values | Canary, A/B, процентная раскатка |

Практический гибрид: Kill Switch и настройки по умолчанию — в Git (static); эксперименты и раскатки — в платформе (dynamic) с обязательным экспортом событий в Loki/SIEM.

---

## Практические сценарии

### Сценарий 1: Канареечный релиз (Canary Deployment)

Постепенное включение новой функции для процента пользователей с целью мониторинга стабильности. В отличие от сетевого Canary, флаги сегментируют по атрибутам приложения.

**Контекст:** Новая система рекомендаций развернута, но ее влияние на бизнес-метрики неизвестно. Необходимо открыть функционал для 1% → 5% → 25% → 100% с автоматическим откатом при росте 5xx.

#### Реализация в коде

```python
user_context = {
    "user_id": user.id,
    "region": user.region,
    "is_beta": user.is_beta,
    "version": request.headers.get("X-App-Version", "2.4.0")
}

if ff_client.is_enabled("new-recommendations-v2", context=user_context):
    return render_recommendations_v2()
return render_recommendations_v1()
```

#### Конфигурация процентной раскатки

```bash
# Unleash: gradual rollout через variants
curl -s -X PUT "$UNLEASH_URL/api/admin/projects/default/features/new-recommendations-v2/environments/production/variants" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "variants": [
      {"name": "new", "weight": 10},
      {"name": "old", "weight": 90}
    ],
    "stickiness": "user_id",
    "defaultVariant": "old"
  }'
# → {"variants":[{"name":"new","weight":10},...],"stickiness":"user_id"}
```

#### Автоматический откат через Alertmanager

```yaml
# alertmanager.yml — webhook в Unleash при росте 5xx
route:
  receiver: unleash-webhook
  match:
    alertname: HighErrorRateRecommendations

receivers:
  - name: unleash-webhook
    webhook_configs:
      - url: 'http://unleash-webhook.internal:8080/api/admin/projects/default/features/new-recommendations-v2/environments/production/off'
        send_resolved: true
```

```python
# Flask-эндпоинт для Alertmanager (если нет прямого webhook)
@app.route('/webhook/alertmanager', methods=['POST'])
def handle_alertmanager():
    data = request.json
    if data.get('status') == 'firing' and data.get('labels', {}).get('alertname') == 'HighErrorRateRecommendations':
        unleash_client.disable_feature('new-recommendations-v2')
        logger.warning("Auto-disabled new-recommendations-v2 due to high error rate")
    return '', 200
```

#### Валидация раскатки

```bash
# Проверка распределения трафика (1000 запросов → ~10% new)
for i in $(seq 1 1000); do
  curl -s -H "X-User-ID: user-$i" http://checkout.internal/api/recommendations
done | jq -r '.variant' | sort | uniq -c
# → 90 old / 10 new
```

---

### Сценарий 2: Аварийный выключатель (Kill Switch)

Мгновенное отключение ресурсоемкой или сбойной функции при деградации инфраструктуры. Флаг создается с `type: ops` и `default=True` — при отказе FFaaS функция остается активной.

**Контекст:** При росте latency в сервисе рекомендаций выше 500ms или всплеске 5xx, SRE включает флаг через CLI или UI. Владелец создает инцидент-тикет, прикрепляет runbook. После стабилизации флаг остается включенным до завершения root-cause analysis.

#### Реализация в коде

```python
@app.route('/product/<id>')
def product_page(id):
    product = db.get_product(id)
    recommendations = []

    # Kill Switch: default=True → рекомендации активны при отказе FFaaS
    if ff_client.is_enabled("enable-recommendations", default=True):
        try:
            with tracer.start_as_current_span("fetch_recommendations") as span:
                span.set_attribute("feature_flag.recommendations", True)
                recommendations = recommendation_service.get_related(id)
        except Exception as e:
            logger.error(f"Recommendation service failure: {e}")
            recommendations = []

    return render_template('product.html', product=product, recs=recommendations)
```

#### Ручное отключение

```bash
# Включение/отключение флага
curl -s -X POST "$UNLEASH_URL/api/admin/projects/default/features/enable-recommendations/environments/production/off" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN"
# → {"enabled": false}

# Список ops-флагов, включенных в production
curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
  jq '[.features[] | select(.type == "ops" and .stages[]?.enabled == true) | .name]'
# → ["killswitch-recs", "enable-third-party-coupons"]
```

#### Автоматический Kill Switch через Prometheus

```yaml
groups:
  - name: feature-flag-automation
    rules:
      - alert: KillSwitchTriggerRecommendations
        expr: |
          (
            rate(http_requests_total{service="recommendations", status=~"5.."}[5m])
            / rate(http_requests_total{service="recommendations"}[5m])
          ) > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Auto-disabling recommendations due to error rate"
          runbook_url: "https://wiki.internal/runbooks/kill-switch-recs"
```

---

### Сценарий 3: Разрыв цепи (Circuit Breaker) с Outbox

Ручное или автоматическое отключение интеграции с внешним нестабильным API с гарантированной доставкой через Outbox.

**Контекст:** Внешний сервис проверки кредитного рейтинга начал отвечать с задержкой 10 секунд. Чтобы не блокировать поток заказов и не исчерпать пул воркеров, интеграция временно отключается через флаг. Запросы записываются в Outbox (Redis) для последующей обработки.

#### Реализация в коде

```python
import time
from circuitbreaker import circuit

@circuit(failure_threshold=5, recovery_timeout=60)
def call_credit_check(user_id: str) -> dict:
    response = external_credit_api.check(user_id, timeout=3)
    return response.json()

@app.route('/order/<user_id>')
def create_order(user_id: str):
    if not ff_client.is_enabled("enable-credit-check"):
        return process_order_without_check(user_id)

    try:
        credit_result = call_credit_check(user_id)
        if credit_result['approved']:
            return process_order(user_id)
        return render_template('order_denied.html')
    except Exception:
        outbox.add_pending_check(user_id)
        return render_template('order_pending_review.html')
```

#### Outbox на Redis

```python
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

**Фолбэк:** При отказе кредитного сервиса заказ проходит в статусе «требует ручного подтверждения». Фоновая задача разбирает очередь после восстановления зависимости.

---

### Сценарий 4: Бета-тестирование и сегментация (Entitlements)

Предоставление доступа к функциям на основе ролей, Allow-list или атрибутов подписки.

#### Реализация в коде

```python
context = {
    "user_id": user.id,
    "email": user.email,
    "is_staff": user.is_staff,
    "org_id": user.org_id
}

if user.is_staff or ff_client.is_enabled("next-gen-editor", context=context):
    enable_experimental_features()
```

#### Проверка targeting rules

```bash
# Проверка constraints для флага
curl -s "$UNLEASH_URL/api/admin/projects/default/features/next-gen-editor" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
  jq '.environments.production.variants[].constraints'
# → [{"contextName":"is_staff","operator":"IN","values":["true"]},...]
```

**Важно:** Флаги не заменяют IAM/RBAC. Targeting rules управляют доступом к функции, но авторизация объектов и действий остается в зоне ответственности IAM.

---

### Сценарий 5: Миграция данных (Shadow Read / Dual Write)

Безопасный переход с одной БД/API на другую без простоя с использованием принципа Expand-Contract.

#### Пошаговая реализация

1. **Dual Write:** Приложение пишет данные в старую (основная) и новую (теневая) системы. Ошибки в теневой системе логируются, но не блокируют основной процесс.

```python
def save_user_profile(user_id: str, data: dict):
    old_db.users.update({"_id": user_id}, {"$set": data})

    if ff_client.is_enabled("dual-write-new-db"):
        try:
            new_db.profiles.upsert({"user_id": user_id}, data)
        except Exception as e:
            logger.warning(f"Dual write failed for {user_id}: {e}")
```

2. **Shadow Read:** Читаем из старой и новой систем одновременно. Сравниваем результаты в фоновом режиме, логируем расхождения. Флаг позволяет включать этот режим для 1% трафика.

```python
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

    return old_result
```

3. **Primary Switch:** Переключаем флаг, делая новую систему основной для чтения. Старая остается для подстраховки (Fallthrough) и продолжает получать записи (Dual Write).

4. **Contract:** После подтверждения стабильности (отсутствие расхождений в течение недели) отключаем старую систему.

---

### Сценарий 6: Темный запуск (Dark Launching)

Развертывание кода и подача на него реального трафика «в тени» без изменения UI. Цель — прогрев кешей, проверка производительности бэкенда и наполнение БД новыми данными.

#### Реализация в коде

```python
def get_search_results(query: str):
    legacy_results = legacy_engine.search(query)

    if ff_client.is_enabled("shadow-search-v2"):
        try:
            shadow_results = v2_engine.search(query)
            compare_and_log(legacy_results, shadow_results)
        except Exception as e:
            logger.error(f"Shadow search failed: {e}")

    return legacy_results
```

**SRE-контекст:** Темный запуск включается на 1% трафика в ночное время. Метрики потребления ресурсов (CPU, Memory, IO) собираются в Prometheus. Если shadow-ветка превышает лимит latency, SRE снижает процент через API без деплоя.

```bash
# Снижение процента dark launch с 1% до 0.1%
curl -s -X PUT "$UNLEASH_URL/api/admin/projects/default/features/shadow-search-v2/environments/production/variants" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"variants":[{"name":"new","weight":1},{"name":"old","weight":99}]}'
# → {"variants":[{"name":"new","weight":1},...]}
```

---

### Сценарий 7: Миграция хранилищ (Storage Switch)

Переключение между хранилищами данных или бэкендами на уровне приложения без изменения DNS или балансировщиков.

**Контекст:** Переход с одного файлового хранилища на другое (например, Ceph Legacy → Ceph New, MinIO) без downtime. Трафик переключается постепенно по организациям или типам файлов.

#### Реализация в коде

```python
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

**SRE-контекст:** При ошибках загрузки в новое хранилище автоматически включается алерт. SRE через CLI откатывает variant на `ceph-legacy` для пострадавшей организации, не затрагивая остальных пользователей.

```bash
# Жесткий откат для конкретной организации
curl -s -X POST "$UNLEASH_URL/api/admin/projects/default/features/storage-provider/environments/production/off" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN"
# → {"enabled": false} — все возвращаются на ceph-legacy
```

---

### Сценарий 8: Аварийное отключение функциональности (Emergency Patch)

Мгновенная реакция на обнаруженную уязвимость или критический дефект в новом модуле.

**Контекст:** При обнаружении критической уязвимости в модуле авторизации, он отключается глобально через Kill Switch до выпуска исправления. Владелец создает инцидент-тикет с severity `critical`, прикрепляет runbook.

```bash
# Мгновенное отключение уязвимого модуля
curl -s -X POST "$UNLEASH_URL/api/admin/projects/default/features/vulnerable-auth-module/environments/production/off" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN"
# → {"enabled": false}

# Отправка алерта в SecOps
curl -s -X POST "https://alertmanager.internal/api/v1/alerts" \
  -d '[{"labels":{"alertname":"SecurityToggleActivated","module":"auth","severity":"critical"}}]'
```

**Follow-up:** После стабилизации флаг остается выключенным до завершения root-cause analysis и выпуска патча. Follow-up PR приводит статическое состояние (Git) в соответствие с runtime.

---

## Операции и команды

### Управление флагами

```bash
# Включение/отключение флага
curl -s -X POST "$UNLEASH_URL/api/admin/projects/default/features/new-checkout-flow/environments/production/off" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN"
# → {"enabled": false}

# Процентная раскатка: 10% → 50%
curl -s -X PUT "$UNLEASH_URL/api/admin/projects/default/features/new-recommendations-v2/environments/production/variants" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"variants":[{"name":"new","weight":50},{"name":"old","weight":50}]}'
# → {"variants":[{"name":"new","weight":50},...]}
```

### Аудит и гигиена

```bash
# Release-флаги без изменений >14 дней (кандидаты на cleanup)
curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
  jq '[.features[] | select(.type == "release" and .staleData.potentiallyStale == true) | .name]'
# → ["old-flag-1", "old-flag-2"]

# Проверка консистентности staging vs production
diff <(curl -s "$UNLEASH_STAGING_URL/api/admin/projects/default/features" \
        -H "Authorization: $STAGING_TOKEN" | jq -r '.features[].name | sort') \
     <(curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
        -H "Authorization: $PROD_TOKEN" | jq -r '.features[].name | sort')
# → (пусто) если среды синхронизированы
```

### Fail-safe аудит

```bash
# Проверка значений по умолчанию для Kill Switch
curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
  jq '[.features[] | select(.type == "ops") | 
    {name, defaultVariant: .variants[0].name, enabled: .stages[]?.enabled}]'
# → [{"name":"killswitch-recs","defaultVariant":"enabled","enabled":false}]
```

### Approval workflow

```bash
# Включение four-eyes для ops и permission флагов
curl -s -X PUT "$UNLEASH_URL/api/admin/projects/default/settings" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "open",
    "changeRequestEnvironmentConfigs": [
      {
        "environment": "production",
        "requiredApprovals": 2,
        "requiresApproval": true
      }
    ]
  }'
# → Настройки применены
```

---

## Типичные ошибки и диагностика

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Флаг не переключается в UI | SDK кеширует значение | `tcpdump -i any port 8013` — проверить SSE/polling | Переключиться на SSE; проверить `maxAge` |
| Приложение падает при отказе FFaaS | Отсутствие fallback | Остановить платформу → проверить приложение | Каждый `get_boolean_value` требует `default` аргумент |
| Canary: «мерцание» UI | Отсутствие stickiness | Два запроса с одним `user_id` → разные значения | Настроить `stickiness: user_id` в FFaaS |
| Shadow Read: нет расхождений в логах | Флаг выключен или контекст не совпадает | `curl .../features/shadow-read-new-db` — проверить enabled | Включить флаг; проверить формат `user_id` |
| Dark Launch: растет CPU | Shadow-ветка блокирует воркеры | `top`/`htop` в момент dark launch | Выполнять shadow-вызовы асинхронно; добавить timeout |
| Флаги живут месяцами | Нет TTL и cleanup процесса | `rg "is_enabled" src/` — найти старые флаги | Cleanup-PR в Definition of Done; алерт на возраст >14 дней |
| Прод отличается от staging | Дрифт сред | `diff` через API staging и production | Декларативное управление через Git; diff в CI/CD |
| Утечка экспериментального кода | Отсутствие targeting rules | `curl .../features/flag-name` — проверить constraints | Настроить сегментацию: `is_staff`, `beta_group`, регион |
| Storage Switch: потеря данных | Переключили primary до backfill | Сравнить записи в старой и новой БД | Expand-Contract: флаг управляет только чтением/записью, не структурой |
| Kill Switch не срабатывает | Неверное значение по умолчанию | Проверить `defaultVariant` в FFaaS | Для Ops флагов default всегда `True` |

---

## Best Practices

Детальные best practices, включая naming conventions, TTL, Four-Eyes Principle, cleanup, CI/CD интеграцию, валидационные чек-листы и SRE/DevOps контекст, описаны в **[Лучшие практики](./best_practices.md)**.

---

## Дополнительная информация

### См. также

- **[Лучшие практики](./best_practices.md)** — naming conventions, TTL, cleanup, Four-Eyes Principle, CI/CD интеграция.
- **[Обзор Feature Toggles](./overview.md)** — концептуальное введение, Deploy vs Release, SRE-контекст.
- **[Архитектура систем](./architecture.md)** — FFaaS, SDK, flagd, Bootstrap File.

### Внешние ресурсы

- [Feature Toggles (Martin Fowler)](https://martinfowler.com/articles/feature-toggles.html) — фундаментальное описание моделей.
- [OpenFeature Specification](https://openfeature.dev/specification/) — стандарт управления флагами.
- [Trunk Based Development](https://trunkbaseddevelopment.com/feature-flags/) — роль флагов в CI/CD.
