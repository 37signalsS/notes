# Обзор Feature Toggles

## Определения

**Feature Toggle (Feature Flag, фиче-флаг)** — механизм управления функциональностью, позволяющий изменять поведение системы во время выполнения (runtime) без изменения исходного кода и повторного развертывания. Флаг инкапсулирует проверку `if/else`, которая принимает решение о включении или отключении конкретной ветки логики.

**Progressive Delivery (Прогрессивная поставка)** — эволюция CI/CD, использующая Feature Toggles для постепенного выпуска функционала, контроля blast radius и автоматизации на основе метрик. Ключевое отличие от классического deploy: код доставляется continuously, а открытие функционала пользователям управляется отдельно.

**Blast Radius (Радиус поражения)** — объем негативного влияния на пользователей или систему при сбое новой функциональности. Feature Toggles являются первичным инструментом ограничения этого радиуса.

**Trunk-Based Development (TBD)** — модель разработки, при которой все инженеры ежедневно сливают изменения в единую основную ветку (`main`/`trunk`). Feature Toggles позволяют скрывать незавершенный код от пользователей, сохраняя основную ветку в стабильном состоянии.

**Deployment vs Release:**
- **Deployment** — технический процесс размещения кода в среде (staging/production).
- **Release** — бизнес-решение о предоставлении доступа к функционалу конечным пользователям.

Feature Toggles полностью разделяют эти два процесса.

---

## Основные концепции

### Проблема: Merge Hell и долгоживущие ветки

Традиционный подход с feature branches для каждой новой функции приводит к накоплению конфликтов, задержке интеграции и риску регрессии. Код не попадает в `main` до полной готовности, нарушая принципы Continuous Integration.

### Решение: Trunk-Based Development

Разработчики ежедневно интегрируют код в `main` под флагом. Незавершенная функциональность скрыта от пользователей, но присутствует в бинарном файле и проходит CI/CD.

```python
if feature_flags.is_enabled("modern_checkout_flow"):
    process_modern_payment()
else:
    process_legacy_payment()
```

**Преимущества:**
- **Continuous Integration:** Ошибки несовместимости обнаруживаются мгновенно.
- **Kill Switch:** Мгновенный откат без redeploy через панель управления.
- **Shift-Right Testing:** Тестирование на реальных данных (Canary, Dark Launch) с минимальным риском.

### SRE-контекст: Наблюдаемость и автоматизация

В 2026 году Feature Toggles неразрывно связаны с SRE-практиками:

1.  **Automatic Rollback:** При превышении порога 5xx или деградации latency Prometheus + Alertmanager вызывает API платформы флагов для отключения проблемной функции.
2.  **Runbook Integration:** Каждый runtime-переключатель фиксируется в инцидент-тикете с привязкой к runbook. Follow-up PR приводит статическое состояние (Git) в соответствие с runtime.
3.  **Telemetry:** Состояние флагов инжектируется в спаны OpenTelemetry, что позволяет при анализе трейсов видеть, какая ветка кода сработала для конкретного запроса.
4.  **Four-Eyes Principle:** Критические операционные флаги (Kill Switch, Security Toggles) требуют аппрува от второго инженера или SRE через Change Request workflow.

### GitOps и декларативное управление

В парадигме GitOps конфигурация флагов хранится в Git (ConfigMaps, Vault, YAML/JSON), обеспечивая аудит и версионность. Runtime-изменения через UI фиксируются как drift и приводятся в соответствие через declarative manifests. Декларативный подход исключает расхождения между staging и production.

### Компромиссы и цена использования

- **Технический долг:** Каждый флаг — временный `if/else`. Без дисциплины удаления (Cleanup) кодовая база деградирует за месяцы.
- **Сложность тестирования:** Матрица состояний растет экспоненциально. Требуется toggle-aware testing и ограничение количества активных релизных флагов на сервис (типично 5–10).
- **Fail-safe:** При недоступности платформы флагов система должна деградировать в безопасное состояние. Для Release/Experiment/Permission это `default=False`; для Ops (Kill Switch) — `default=True`.
- **Безопасность:** Флаги не заменяют IAM/RBAC. Неправильно настроенные targeting rules ведут к утечке экспериментального функционала.

---

## Практические сценарии

### Сценарий 1: Trunk-Based Development и Release Toggle

Разработчик создает новую функциональность. Код готов на 30%, но его нужно вливать в `main` ежедневно. Флаг `FEATURE_CRYPTO_PAYMENT=false` скрывает незавершенный код. CI/CD проходит успешно, риск merge hell минимален. TTL установлен на 14 дней; по истечении срока автоматический алерт напоминает команде об удалении или раскатке.

### Сценарий 2: Прогрессивная раскатка (Canary)

Новая система рекомендаций открывается для 1% → 5% → 25% → 100% пользователей. В отличие от сетевого Canary (Ingress/Envoy), флаги сегментируют по `user_id`, региону, версии клиента. При росте 5xx Alertmanager автоматически отключает флаг через webhook. Детали конфигурации и автоматизации см. в [Сценарии использования](./scenarios.md).

### Сценарий 3: Аварийный выключатель (Kill Switch)

При деградации latency в сервисе рекомендаций SRE включает флаг через CLI или UI. Флаг создается с `type: ops` и `default=True` — при отказе FFaaS рекомендации остаются активными. Владелец создает инцидент-тикет, прикрепляет runbook. После стабилизации флаг остается включенным до завершения root-cause analysis.

### Сценарий 4: Темный запуск (Dark Launching)

Новая логика развернута, но мы не знаем, выдержит ли она нагрузку. Флаг включает теневой режим для 1% трафика: результат вычисляется, но не показывается пользователю, логируется только latency. Цель — проверка производительности на реальных данных без риска для UX.

---

## Предварительная настройка (Quick Start)

### Шаг 1: Развертывание FFaaS

Для self-hosted варианта (без cloud-зависимостей) рекомендуется **Unleash** или **Flipt**.

```bash
# Unleash через Docker Compose
git clone https://github.com/Unleash/unleash-docker.git
cd unleash-docker
docker compose up -d
# → Доступ: http://localhost:4242 (admin/unleash4all)
```

### Шаг 2: Создание первого флага

```bash
curl -s -X POST "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "new-checkout-flow", "type": "release"}'
# → {"name":"new-checkout-flow","type":"release",...}
```

### Шаг 3: Интеграция SDK в приложение (Python + OpenFeature)

```python
from openfeature import api
from openfeature.contrib.provider.unleash import UnleashProvider
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

api.set_provider(UnleashProvider(
    url="https://ff-api.internal/api",
    app_name="checkout-service"
))

def process_checkout(user_id: str, cart_total: float):
    client = api.get_client()
    context = {"user_id": user_id, "cart_total": cart_total}

    with tracer.start_as_current_span("checkout_process") as span:
        is_modern_v3 = client.get_boolean_value("checkout-v3-enabled", False, context)
        span.set_attribute("feature_flag.checkout_v3", is_modern_v3)

        if is_modern_v3:
            return run_modern_workflow(user_id)
        return run_legacy_workflow(user_id)
```

### Шаг 4: Проверка работоспособности

```bash
curl -s "$UNLEASH_URL/api/client/features" \
  -H "Authorization: $UNLEASH_FRONTEND_TOKEN" | \
  jq '.features[] | select(.name=="new-checkout-flow")'
# → {"name":"new-checkout-flow","enabled":true,...}
```

---

## Операции и команды

### Управление флагами

```bash
# Включение/отключение флага
curl -s -X POST "$UNLEASH_URL/api/admin/projects/default/features/new-checkout-flow/environments/production/off" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN"
# → {"enabled": false}

# Список ops-флагов, включенных в production
curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
  jq '[.features[] | select(.type == "ops" and .stages[]?.enabled == true) | .name]'
# → ["killswitch-recs", "enable-third-party-coupons"]
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

---

## Типичные ошибки и диагностика

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Флаг не переключается в UI | SDK кеширует значение | `tcpdump -i any port 8013` — проверить SSE/polling | Переключиться на SSE; проверить `maxAge` |
| Приложение падает при отказе FFaaS | Отсутствие fallback | Остановить платформу → проверить приложение | Каждый `get_boolean_value` требует `default` аргумент |
| Флаги живут месяцами | Нет TTL и cleanup процесса | `rg "is_enabled" src/` — найти старые флаги | Cleanup-PR в Definition of Done; алерт на возраст >14 дней |
| Прод отличается от staging | Дрифт сред | `diff` через API staging и production | Декларативное управление через Git; diff в CI/CD |
| Неконсистентность данных | Флаг переключил запись до backfill | Сравнить записи в старой и новой БД | Expand-Contract: флаг управляет только чтением/записью, не структурой |
| Утечка экспериментального кода | Отсутствие targeting rules | `curl .../features/flag-name` — проверить constraints | Настроить сегментацию: `is_staff`, `beta_group`, регион |

---

## Best Practices

Детальные best practices, включая naming conventions, TTL, Four-Eyes Principle, cleanup, CI/CD интеграцию и SRE/DevOps контекст, описаны в **[Лучшие практики](./best_practices.md)**.

### Ключевые принципы выбора типа

- **Release Toggle:** Только для скрытия незавершенного кода при TBD. TTL 7–14 дней.
- **Experiment Toggle:** Только при наличии четкой метрики успеха (conversion, latency, error rate) и выделенного Data Scientist. TTL = длительность эксперимента + 7 дней.
- **Ops Toggle (Kill Switch):** Для всех критических зависимостей. `default=True`. Владелец — SRE/DevOps.
- **Permission Toggle:** Для управления доступом к beta-фичам. Владелец — Product/Support.

### Fail-safe значения

```python
# Release/Experiment/Permission: default=False
release_flag = client.get_boolean_value("new-checkout", False, context)

# Ops (Kill Switch): default=True
ops_kill_switch = client.get_boolean_value("killswitch-recs", True, context)
```

---

## Дополнительная информация

### См. также

- **[Лучшие практики](./best_practices.md)** — naming conventions, TTL, Four-Eyes Principle, cleanup, CI/CD интеграция.
- **[Типы Feature Toggles](./types.md)** — классификация по назначению и сроку жизни.
- **[Архитектура систем](./architecture.md)** — FFaaS, SDK, flagd, Bootstrap File.

### Внешние ресурсы

- [Feature Toggles (Martin Fowler)](https://martinfowler.com/articles/feature-toggles.html) — фундаментальное описание моделей.
- [OpenFeature Specification](https://openfeature.dev/specification/) — стандарт управления флагами.
- [Trunk Based Development](https://trunkbaseddevelopment.com/feature-flags/) — роль флагов в CI/CD.
