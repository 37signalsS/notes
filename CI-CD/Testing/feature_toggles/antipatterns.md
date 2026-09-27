# Антипаттерны Feature Toggles

## Определения

**Антипаттерн Feature Toggle** — распространенный, но неэффективный, опасный или трудноподдерживаемый способ использования механизмов динамического управления функциональностью. Антипаттерны приводят к накоплению технического долга, усложнению кодовой базы («спагетти-логика»), деградации производительности и возникновению критических инцидентов в Production, которые трудно диагностировать из-за вариативности состояний системы.

**Зомби-флаг (Zombie Flag)** — «мертвый» или забытый флаг, код которого остается в системе после завершения его жизненного цикла, создавая риск случайного включения устаревшей и непротестированной логики.

**Коллизия флагов (Toggle Collision)** — ситуация, когда два или более независимых флага влияют на один и тот же ресурс (переменная окружения, запись в БД, HTTP-ответ) в несовместимых режимах, приводя к непредсказуемому поведению системы.

**Combinatorial Explosion** — экспоненциальный рост количества возможных состояний системы при увеличении количества независимых бинарных флагов, что делает полное тестирование невозможным.

**Silent Failure** — сбой работы FFaaS или SDK, который не приводит к явной ошибке в приложении, но заставляет систему деградировать в опасное состояние из-за неверно выбранных значений по умолчанию.

---

## Основные концепции

### Категории антипаттернов

Классификация по типу последствий и зоне ответственности:

| Категория | Описание | Основной риск | Владелец |
| :--- | :--- | :--- | :--- |
| **Кодовые** | Нарушение чистоты кода и абстракций. | Рост сложности поддержки, ошибки при рефакторинге. | Разработка |
| **Эксплуатационные** | Ошибки мониторинга и управления рантаймом. | Непредсказуемое поведение при отказе FFaaS, «мертвые» флаги. | SRE / DevOps |
| **Архитектурные** | Ошибки проектирования системных взаимодействий. | Нарушение безопасности, деградация БД, коллизии логики. | Архитектура / Backend |
| **Процессные** | Отсутствие владения и регламентов удаления. | Бесконечный рост технического долга, drift сред. | Tech Lead / SRE Lead |

### ПринципFail-safe и почему его нарушение — антипаттерн

Каждый вызов `get_boolean_value()` или `get_string_value()` должен содержать явный `default` аргумент. Отсутствие fallback-значения превращает флаг в точку отказа: при недоступности FFaaS приложение либо падает с исключением, либо деградирует в опасное состояние.

Правило простое:
- **Release / Experiment / Permission:** `default=False` (новая фича выключена при сбое).
- **Ops (Kill Switch):** `default=True` (защита активна при сбое).

Нарушение этого правила — один из самых частых антипаттернов в Production, ведущий к инцидентам, когда FFaaS перегружена или недоступна.

### Метрики для обнаружения антипаттернов

Для систематического выявления проблем с флагами используются следующие показатели:

| Метрика | Формула / Метод | Пороговое значение |
| :--- | :--- | :--- |
| **Flag Count** | `count(flags WHERE state='enabled')` на сервис | >10 release-флагов на сервис |
| **Flag Age** | `now() - created_at` для каждого флага | >30 дней без изменения состояния |
| **Evaluation Latency** | `p99(feature_flag_evaluation_duration_seconds)` | >10ms на одну оценку |
| **Dead Flag Ratio** | `flags_stuck_at_100% / total_flags` | >20% флагов в одном состоянии >90 дней |
| **Collision Potential** | Количество флагов, влияющих на один ресурс | >2 флага на один ресурс |
| **Polling Rate** | `rate(http_requests_total{job="unleash-api"}[1m])` | >100 запросов/мин на сервис |

### SRE-контекст: Антипаттерны как инциденты

В современной эксплуатации каждый антипаттерн должен иметь:
1. **Индикатор в мониторинге** (Prometheus rule).
2. **Алерт с severity** (warning/critical).
3. **Runbook** с пошаговым восстановлением.
4. **Follow-up** (cleanup-PR, рефакторинг, документирование).

Это превращает антипаттерны из абстрактных плохих практик в управляемые операционные риски.

---

## Практические сценарии

### 1. Избыточная сложность и вложенность (Combinatorial Explosion)

**Проблема:** Создание условий, зависящих от комбинации нескольких независимых флагов, или использование глубокой вложенности (`if inside if`). Это приводит к экспоненциальному росту состояний системы, которые невозможно полностью протестировать.

**Почему это антипаттерн:** 10 независимых бинарных флагов дают 1024 состояния системы. Полное тестирование всех комбинаций невозможно, что приводит к необнаруженным ошибкам в Production.

**Пример (Bad Practice):**
```python
if ff.is_enabled('new-ui') and not ff.is_enabled('legacy-backend'):
    if ff.is_enabled('experiment-alpha'):
        render_complex_view()
```

**Пример конфигурации (Bad Practice):**
```yaml
# Unleash: зависимые флаги без guard-условий
flags:
  new-ui:
    enabled: true
  legacy-backend:
    enabled: true  # Конфликтует с new-ui, но нет зависимостей
  experiment-alpha:
    enabled: true  # Зависит от new-ui, но не настроен
```

**Решение:**
- Стремитесь к плоской структуре флагов.
- Используйте **Dependency Toggling**: настраивайте зависимости на уровне FFaaS-платформы (в Unleash флаг B активен только если флаг A включен).
- Выносите сложную логику принятия решений в стратегии (Strategy Pattern).

**Правильная архитектура:**
```python
def render_view(ff_client, user_context):
    strategies = {
        "new-ui": render_modern_view,
        "legacy-ui": render_legacy_view,
    }
    strategy_name = ff_client.get_string_value(
        "ui-strategy", 
        default="legacy-ui",
        context=user_context
    )
    return strategies[strategy_name](user_context)
```

**SRE-валидация:** Количество одновременно активных release-флагов на сервис не должно превышать 5–10.
```bash
curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
  jq '[.features[] | select(.stages[]?.name == "production" and .enabled == true)] | length'
# → Ожидаемое значение: ≤10
```

---

### 2. Утечка бизнес-логики (Logic Leakage)

**Проблема:** Проверка флага разбросана по всему коду приложения вместо того, чтобы быть инкапсулированной в абстракцию. В коде появляются десятки `if/else` с проверкой одного и того же флага.

**Почему это антипаттерн:** При изменении логики флага (или его удалении) необходимо найти и изменить десятки файлов, что приводит к ошибкам и неполным удалениям.

**Пример (Bad Practice):**
```python
def render_header():
    if ff.is_enabled('new-nav'): return new_nav_html()
    return legacy_nav_html()

def render_sidebar():
    if ff.is_enabled('new-nav'): return new_sidebar_html()
    return legacy_sidebar_html()

def render_footer():
    if ff.is_enabled('new-nav'): return new_footer_html()
    return legacy_footer_html()
# ... и ещё 7 мест с проверкой того же флага
```

**Решение:** Используйте паттерн Strategy или Dependency Injection. Код не должен спрашивать «Включена ли фича X?», он должен вызывать метод интерфейса, реализация которого определяется состоянием флага.

```python
class NavigationRenderer(ABC):
    @abstractmethod
    def render_header(self) -> str: pass
    @abstractmethod
    def render_sidebar(self) -> str: pass
    @abstractmethod
    def render_footer(self) -> str: pass

class ModernNavigation(NavigationRenderer): ...
class LegacyNavigation(NavigationRenderer): ...

def get_navigation(ff_client, user_context) -> NavigationRenderer:
    if ff_client.get_boolean_value("new-nav", False, context=user_context):
        return ModernNavigation()
    return LegacyNavigation()
```

**Валидация:** Флаг должен проверяться не более чем в 2–3 местах кода:
```bash
rg "is_enabled\(['\"]new-nav['\"]\)" --type py | wc -l
# → Ожидаемое значение: ≤3
```

---

### 3. «Зомби-флаги» и отсутствие владения

**Проблема:** Флаги без назначенного владельца (Owner) и даты удаления. Код превращается в кладбище условий, которые никто не решается удалить.

**Почему это антипаттерн:** Зомби-флаги создают иллюзию «на случай, если понадобится», но на практике их устаревшая логика тестируется и поддерживается, увеличивая стоимость изменений.

**Пример (Bad Practice):**
```python
if ff.is_enabled('old-recommendation-engine'):
    return old_recommender.get_recommendations(user_id)
return new_recommender.get_recommendations(user_id)
```

**Решение:**
- Каждому флагу — **Owner** (команда или конкретный инженер).
- **TTL (Time to Live):** Автоматические алерты, если флаг не менял состояние более 30 дней.
- **Cleanup-спринты:** Регулярное удаление кода завершенных релизов. Подробный процесс, включая Prometheus правила, Piranha и CI/CD интеграцию, — в [Лучшие практики](./best_practices.md).

---

### 4. Флаги как замена авторизации (Security Auth Anti-pattern)

**Проблема:** Использование Feature Toggles для ограничения доступа к функционалу на основе прав пользователей (RBAC) без интеграции с IAM-системой.

**Риск:** Флаги функций не предназначены для обеспечения безопасности. Злоумышленник может подменить контекст на клиенте и получить доступ к скрытой функции.

**Пример (Bad Practice):**
```python
# Опасно: флаг проверяется ТОЛЬКО на клиенте
def get_admin_panel(user_id, is_admin):
    if ff.is_enabled('admin-panel', context={"is_admin": is_admin}):
        return render_admin_panel()
    return render_user_panel()
```

**Решение:** Флаги управляют *наличием* функции, а IAM/RBAC — *правом* на её использование. Авторизация объектов и действий остается в зоне ответственности IAM.

```python
def get_admin_panel(user_id):
    if not iam_client.verify_permission(user_id, "admin:access"):
        raise ForbiddenError("Access denied")
    if not ff_client.is_enabled('admin-panel'):
        return render_user_panel()
    return render_admin_panel()
```

**Валидация:**
```bash
rg "is_enabled\(['\"]admin" --type py -A5 | grep -v "iam_client\|rbac\|verify_permission"
# → Не должно быть результатов
```

---

### 5. Бесшумный отказ и опасные фолбеки (Silent Failure)

**Проблема:** Использование `false` как значения по умолчанию для критически важных операционных флагов (например, Kill Switch) без учета их семантики.

**Пример:** Если FFaaS недоступна, флаг `enable-firewall` возвращает `false`, отключая защиту.

**Пример (Bad Practice):**
```python
def check_request(request):
    if ff.is_enabled("enable-waf-protection"):
        validate_request(request)
    return process(request)  # Без валидации!
```

**Решение:** Для Kill Switch значение по умолчанию должно соответствовать самому безопасному состоянию системы.

```python
protection_enabled = ff_client.get_boolean_value(
    "enable-waf-protection", 
    default=True  # ← Защита активна при сбое FFaaS
)
```

**Валидация fail-safe значений:** См. [Лучшие практики](./best_practices.md) — раздел "Safe Defaults".

---

### 6. Коллизии флагов (Toggle Collision)

**Проблема:** Два независимых флага влияют на один и тот же глобальный ресурс в несовместимых режимах.

**Пример (Bad Practice):**
```python
def process_payment(amount):
    if ff.is_enabled("apply-discount"):
        amount = amount * 0.9
    if ff.is_enabled("apply-surchage"):
        amount = amount * 1.05
    # Оба флага активны: amount = amount * 0.9 * 1.05 = amount * 0.945
    return charge(amount)
```

**Решение:**
- Группировка флагов по доменам.
- Конфликт-тестирование: проверка работы системы при всех комбинациях активных флагов в данном домене.
- Централизованный контроль через абстракцию (PricingFlags и т.п.).

**Реализация контроля коллизий:**
```python
class PricingFlags:
    def get_price_modifier(self, user_context) -> float:
        modifiers = []
        if self.ff.get_boolean_value("discount-10-percent", False, user_context):
            modifiers.append(("discount", 0.9))
        if self.ff.get_boolean_value("surcharge-5-percent", False, user_context):
            modifiers.append(("surcharge", 1.05))
        if len(modifiers) > 1:
            logger.warning(f"Price collision detected: {modifiers}. Using first only.")
            modifiers = [modifiers[0]]
        return modifiers[0][1] if modifiers else 1.0
```

**Валидация:**
```bash
curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
  jq '[.features[] | select(.stages[]?.name == "production" and .enabled == true) | .name] | 
    map(select(test("discount|surcharge|pricing"))) | 
    if length > 1 then "COLLISION RISK: \(length) pricing flags active" else "OK" end'
```

---

### 7. Неконсистентность окружений (Environment Drift)

**Проблема:** Ручное управление флагами приводит к тому, что в `Dev`, `Staging` и `Prod` включены разные наборы экспериментальных флагов, что делает невозможным воспроизведение багов.

**Решение:**
- Декларативное управление через GitOps.
- Синхронизация состояний флагов между окружениями для отладки конкретных инцидентов.
- Ежедневный diff флагов между staging и production как часть CI/CD. См. [Лучшие практики](./best_practices.md) — раздел "Окружение-паритет".

---

### 8. Управление схемой БД через флаги

**Проблема:** Попытка изменять структуру БД (миграции) внутри логических условий флага.

**Риск:** Разрыв между состоянием кода и схемы БД, невозможность отката.

**Пример (Bad Practice):**
```python
def migrate_data():
    if ff.is_enabled("new-schema"):
        db.execute("ALTER TABLE users ADD COLUMN preferences_v2 JSONB")
        db.execute("UPDATE users SET preferences_v2 = preferences::jsonb")
```

**Решение:** Применяйте паттерн **Expand-Contract**. Флаг управляет только логикой *чтения/записи* данных, но не самой структурой таблиц.

```python
def get_user_preferences(user_id):
    if ff_client.is_enabled("use-new-preferences-schema"):
        return db.query("SELECT preferences_v2 FROM users WHERE id = %s", user_id)
    return db.query("SELECT preferences FROM users WHERE id = %s", user_id)
```

**Валидация:**
```bash
rg "ALTER|CREATE TABLE|DROP COLUMN|ADD COLUMN" --type py -B5 -A5 | grep -i "is_enabled\|get_boolean"
# → Не должно быть результатов
```

---

### 9. Избыточная частота опроса (Polling Overload)

**Проблема:** SDK настроен на слишком частый опрос FFaaS сервера, создавая избыточную нагрузку на сеть и платформу флагов. При 500 инстансах приложения каждый опрос генерирует десятки тысяч HTTP-запросов в минуту.

**Пример (Bad Practice):**
```python
api.set_provider(UnleashProvider(
    url="https://ff-api.internal/api",
    app_name="checkout-service",
    polling_interval=1,  # ← 1 секунда = 500 * 60 = 30,000 запросов/мин
))
```

**Решение:** Используйте SSE (Server-Sent Events) или gRPC streaming вместо polling. Если polling необходим — увеличьте интервал до 30–60 секунд и используйте локальный кеш.

```python
api.set_provider(UnleashProvider(
    url="https://ff-api.internal/api",
    app_name="checkout-service",
    enable_sse=True,
    polling_interval=60,
    enable_local_cache=True,
    cache_ttl=300
))
```

**Валидация:**
```bash
sum(rate(http_requests_total{job="unleash-api"}[1m]))
# → Ожидаемое: <100 запросов/мин
```

---

### 10. Отсутствие мониторинга влияния флагов (Monitoring Gap)

**Проблема:** Флаги включаются без настройки наблюдаемости. Нет возможности определить, влияет ли флаг на ошибки, латентность или бизнес-метрики.

**Почему это антипаттерн:** Без мониторинга невозможно определить, безопасен ли флаг, и принять решение о его удалении или раскатке.

**Пример (Bad Practice):**
```python
def render_checkout(user):
    if ff.is_enabled("new-checkout-flow"):
        return render_new_checkout(user)
    return render_legacy_checkout(user)
# Нет телеметрии, нет дашборда, нет алертов
```

**Решение:** Каждое включение флага должно сопровождаться настройкой дашборда и алертов. Используйте OpenTelemetry для инъекции состояния флагов в спаны.

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

def render_checkout(user):
    with tracer.start_as_current_span("checkout_render") as span:
        is_new_flow = ff_client.get_boolean_value(
            "new-checkout-flow", False, 
            context={"user_id": user.id}
        )
        span.set_attribute("feature_flag.new_checkout_flow", is_new_flow)
        if is_new_flow:
            result = render_new_checkout(user)
            span.set_attribute("checkout.variant", "new")
        else:
            result = render_legacy_checkout(user)
            span.set_attribute("checkout.variant", "legacy")
        return result
```

**Валидация:**
```bash
curl -s "http://localhost:3200/api/traces?query=feature_flag.new_checkout_flow&limit=1" | \
  jq '.traces[0].spans[] | select(.attributes | map(select(.key == "feature_flag.new_checkout_flow")) | length > 0) | .traceID'
# → Должен вернуть traceID
```

---

## Операции и команды

### Обнаружение антипаттернов

```bash
# Подсчет активных флагов на сервис
curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
  jq '[.features[] | select(.stages[]?.name == "production" and .enabled == true)] | length'
# → Ожидаемое значение: ≤10

# Поиск проверок одного флага в коде (Logic Leakage)
rg "is_enabled\(['\"]flag-name['\"]\)" --type py | wc -l
# → Ожидаемое значение: ≤3

# Проверка fail-safe значений для Kill Switch
curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
  -H "Authorization: $UNLEASH_ADMIN_TOKEN" | \
  jq '[.features[] | select(.type == "ops") | {
    name: .name,
    defaultVariant: .variants[0].name,
    enabled: .stages[]?.enabled
  }]'
# → defaultVariant должен быть "enabled"

# Проверка DDL-команд в контексте флагов
rg "ALTER|CREATE TABLE|DROP COLUMN|ADD COLUMN" --type py -B5 -A5 | grep -i "is_enabled\|get_boolean"
# → Не должно быть результатов

# Проверка консистентности staging vs production
diff <(curl -s "$UNLEASH_URL/api/admin/projects/default/features" \
        -H "Authorization: $UNLEASH_ADMIN_TOKEN" | jq -r '.features[].name | sort') \
     <(curl -s "$UNLEASH_STAGING_URL/api/admin/projects/default/features" \
        -H "Authorization: $UNLEASH_STAGING_TOKEN" | jq -r '.features[].name | sort')
# → (пусто) если среды синхронизированы
```

### Операции и команды

Подробные операции и команды для управления флагами, включая аудит, approval workflow, CI/CD интеграцию, cleanup и мониторинг, описаны в **[Лучшие практики](./best_practices.md)**.

---

## Типичные ошибки и диагностика

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Флаг не переключается через UI | SDK кеширует старое значение | `curl $UNLEASH_URL/api/client/features` → проверить актуальность; `tcpdump -i any port 8013` → проверить SSE/polling | Убедиться, что SDK настроен на SSE с корректным `maxAge` |
| Приложение падает при недоступности FFaaS | Отсутствие fail-safe значений по умолчанию | Остановить FFaaS → попробовать запросить приложение; `grep "is_enabled" src/` → найти проверки без default | Каждая проверка флага обязана содержать fallback-значение |
| Флаги живут месяцами, код оброс ветвлениями | Нет TTL и процесса cleanup | `rg "is_enabled" src/ | wc -l` → подсчет проверок; проверить возраст флагов через API | Cleanup-PR в Definition of Done; алерт на возраст >14 дней |
| Прод ведет себя не как staging | Разные значения флагов в средах | `diff <(prod-flags) <(staging-flags)` → найти расхождения | Декларативное управление через Git; diff флагов — часть ревью PR |
| Оценка флага добавляет latency | Ход в удаленную платформу на каждый вызов | `curl -w "@curl-format.txt" -o /dev/null -s $UNLEASH_URL/api/client/features` → замерить latency | Локальный flagd/sidecar, кеширование; платформа — источник истины, не hot path |
| Утечка экспериментального функционала | Отсутствие targeting rules | `curl $UNLEASH_URL/api/admin/projects/default/features/flag-name` → проверить constraints | Настроить сегментацию: `is_staff`, `beta_group`, регион |
| Неконсистентность данных при Dual Write | Флаг переключил запись до завершения Backfill | Сравнить записи в старой и новой БД | Expand-Contract: флаг управляет только чтением/записью, не структурой |
| Включили флаг — а миграции БД нет | Функциональность завязана на схему | `psql -c "\d users"` → проверить наличие колонки | Expand-Contract: схема совместима с обоими путями кода |
| Secret попал в конфиг флага | Флаговый конфиг используют как конфиг приложения | `rg "password\|secret\|token" $UNLEASH_URL/api/admin/projects/default/features/flag-name` | Запретить политикой; секреты — только через ESO/SOPS |
| Тесты взрываются от числа комбинаций | Все флаги тестируются во всех сочетаниях | `time pytest tests/` → проверить время; посмотреть CI-логи | CI гоняет дефолтную конфигурацию; комбинации — точечные e2e |
| Коллизия: два флага меняют одну цену | Отсутствие группировки по доменам | Проверить логику модификации цены | Централизованный PricingFlags с явным приоритетом |
| Dark Launch растет CPU | Shadow-ветка блокирует воркеры | `top`/`htop` в момент dark launch | Выполнять shadow-вызовы асинхронно; добавить timeout |

---

## Best Practices

Детальные best practices, включая naming conventions, TTL, Four-Eyes Principle, cleanup, CI/CD интеграцию и SRE/DevOps контекст, описаны в **[Лучшие практики](./best_practices.md)**.

---

## Дополнительная информация

### Интеграция с Observability для обнаружения антипаттернов

Комбинация Prometheus + OpenTelemetry позволяет автоматически выявлять антипаттерны:

| Антипаттерн | Индикатор в мониторинге | Алерт |
| :--- | :--- | :--- |
| **Зомби-флаги** | `flag_last_change_timestamp` >30 дней | `ZombieFlagDetected` |
| **Коллизии флагов** | 2+ флага влияют на один ресурс | `FlagCollisionDetected` |
| **Polling Overload** | `rate(http_requests_total{job="unleash-api"}[1m])` >100 | `FFaaSOverloaded` |
| **Silent Failure** | `feature_flag_evaluations_total{value="false"}` для Kill Switch | `KillSwitchDefaultRisk` |
| **Monitoring Gap** | Отсутствие `feature_flag.*` атрибутов в спанах | `FlagTelemetryMissing` |

### Ограничения и особые случаи (Edge Cases)

#### Когда Feature Toggles НЕ подходят

- **Простые CRUD-приложения** без альтернативных веток логики — overhead от инфраструктуры флагов не окупается.
- **Критические пути с нулевой толерантностью к latency** — каждая проверка флага добавляет вычисления (хотя и `O(1)` при локальном вычислении). В high-frequency trading или real-time bidding этот overhead может быть неприемлем.
- **Замена системы авторизации** — флаги не предназначены для обеспечения безопасности. Злоумышленник может подменить контекст на клиенте.

#### Ограничения по архитектуре

- **Комбинаторный взрыв:** 10 независимых бинарных флагов дают 1024 состояния системы. Необходимо ограничивать количество одновременно активных релизных флагов на сервис (типично: 5–10).
- **Глобальные побочные эффекты:** Если два флага влияют на один глобальный ресурс (переменную окружения, запись в БД) в несовместимых режимах — возникает коллизия. Требуется группировка флагов по доменам и конфликт-тестирование.
- **Миграции БД:** Флаги не должны управлять структурой таблиц. Попытка изменять схему БД внутри логических условий флага приводит к разрыву между состоянием кода и схемы.

#### Edge Cases в Production

- **Одновременное включение нескольких экспериментов:** Если два A/B-теста затрагивают один и тот же UI-компонент, результаты могут быть искажены. Необходимо выявлять пересечения и запускать их последовательно или исключать пересекающуюся аудиторию.
- **Кэширование на CDN/Браузере:** Если флаг определяет видимость элемента UI, а страница кэшируется CDN или браузером, пользователь может видеть устаревшее состояние. Решение: не кэшировать страницы с активными флагами или добавлять `Cache-Control: no-cache` для путей с флагами.
- **Offline-режим (Mobile):** При отсутствии сети SDK не может получить обновленное значение флага. Используйте bootstrap-файл (последнее известное состояние) или hardcoded fallback.

### См. также

- **[Лучшие практики](./best_practices.md)** — naming conventions, TTL, Four-Eyes Principle, cleanup, CI/CD интеграция, SRE/DevOps контекст.
- **[Обзор Feature Toggles](./overview.md)** — концептуальная база, Deploy vs Release, SRE-контекст.
- **[Сценарии использования](./scenarios.md)** — правильные паттерны для подражания.

### Внешние ресурсы

- [Feature Toggles (Martin Fowler)](https://martinfowler.com/articles/feature-toggles.html) — фундаментальное описание моделей.
- [OpenFeature Specification](https://openfeature.dev/specification/) — стандарт управления флагами.
- [Trunk Based Development](https://trunkbaseddevelopment.com/feature-flags/) — роль флагов в CI/CD.
