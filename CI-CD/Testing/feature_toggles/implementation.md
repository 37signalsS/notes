# Реализация Feature Toggles в коде

## Определения

**Реализация Feature Toggles** — это процесс интеграции механизмов динамического управления логикой непосредственно в программный код приложения. Это позволяет выполнять различные ветки алгоритмов в зависимости от состояния внешних или внутренних флагов без пересборки артефактов.

**OpenFeature** — открытый стандарт (CNCF Graduated) для управления флагами функций, предоставляющий унифицированный API (Vendor-neutral) для работы с любыми поставщиками (Unleash, LaunchDarkly, Flipt) или собственными реализациями.

---

## Основные концепции

### Архитектурные паттерны внедрения

Для предотвращения превращения кода в «спагетти» из условий `if/else`, в 2026 году рекомендуется использовать следующие паттерны:

1.  **Паттерн «Стратегия» (Strategy Pattern)**:
    - Логика разных веток инкапсулируется в отдельные классы-реализации одного интерфейса.
    - Выбор конкретной стратегии происходит на этапе инициализации или внедрения зависимостей (DI).
    - **Плюс:** Высокая тестируемость и изоляция кода.
2.  **Паттерн «Декоратор» (Decorator Pattern)**:
    - Новая функциональность «оборачивает» существующую.
    - Флаг определяет, будет ли вызван декоратор или оригинальный метод.
3.  **Унифицированная «Обертка» (Wrapper/Facade)**:
    - Создание внутреннего сервиса-абстракции над FF-SDK.
    - Позволяет сменить вендора флагов (например, уйти с SaaS решения на self-hosted Unleash) за один день, изменив только провайдера в обертке.

### Интеграция с наблюдаемостью (Observability)

В современных SRE-практиках проверка флага в коде обязана сопровождаться телеметрией:
- **Span Injection**: Состояние всех проверенных флагов за время запроса должно попадать в атрибуты спана **OpenTelemetry**.
- **Exposure Events**: Генерация события в момент, когда пользователь физически столкнулся с логикой флага (не просто при вычислении, а при фактическом выполнении ветки).

---

## Практические сценарии

### Сценарий 1: Промышленная реализация (Python + OpenFeature)

Использование стандарта OpenFeature позволяет отвязать бизнес-логику от конкретного SDK вендора.

```python
from openfeature import api
from openfeature.contrib.provider.unleash import UnleashProvider
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

# 1. Глобальная настройка провайдера (обычно в main.py / app.py)
api.set_provider(UnleashProvider(
    url="https://ff-api.internal/api",
    app_name="checkout-service"
))

# 2. Бизнес-логика
def process_checkout(user_id: str, cart_total: float):
    client = api.get_client()
    context = {"user_id": user_id, "cart_total": cart_total}
    
    with tracer.start_as_current_span("checkout_process") as span:
        # Проверка флага
        is_modern_v3 = client.get_boolean_value("checkout-v3-enabled", False, context)
        
        # Обязательная фиксация в телеметрии
        span.set_attribute("feature_flag.checkout_v3", is_modern_v3)
        
        if is_modern_v3:
            return run_modern_workflow(user_id)
        return run_legacy_workflow(user_id)
```

### Сценарий 2: Теневая проверка (Shadow Evaluation)

Используется для проверки производительности или стабильности новой логики без риска для пользователя. Результат новой функции вычисляется, но не возвращается.

```python
def get_search_results(query: str):
    legacy_results = legacy_engine.search(query)
    
    # Теневой запуск через флаг
    if client.get_boolean_value("shadow-search-v2", False):
        try:
            # Вычисляем, но не используем в ответе
            shadow_results = v2_engine.search(query)
            # Логируем расхождения для анализа
            compare_and_log(legacy_results, shadow_results)
        except Exception as e:
            # Ошибка в новой логике не аффектит пользователя
            logging.error(f"Shadow search failed: {e}")
            
    return legacy_results
```

### Сценарий 3: Реализация через паттерн «Стратегия» (Dependency Injection)

Подход для чистого кода в крупных проектах.

```python
from abc import ABC, abstractmethod

class PricingStrategy(ABC):
    @abstractmethod
    def calculate(self, base_price: float) -> float:
        pass

class DefaultPricing(PricingStrategy):
    def calculate(self, base_price: float) -> float:
        return base_price

class HolidayDiscountPricing(PricingStrategy):
    def calculate(self, base_price: float) -> float:
        return base_price * 0.8  # 20% скидка

# Фабрика на основе флагов
def get_pricing_service(ff_client, user_id: str) -> PricingStrategy:
    if ff_client.get_boolean_value("holiday-sale", False, {"user_id": user_id}):
        return HolidayDiscountPricing()
    return DefaultPricing()
```

---

## Тестирование реализации

### Юнит-тестирование (Pytest)

Для тестирования кода с флагами необходимо проверять **обе ветки** логики. Использование параметризации — лучший способ избежать дублирования.

```python
import pytest
from unittest.mock import MagicMock

@pytest.mark.parametrize("toggle_state, expected_result", [
    (True, "Premium UI"),
    (False, "Standard UI")
])
def test_ui_rendering(toggle_state, expected_result):
    mock_ff = MagicMock()
    mock_ff.get_boolean_value.return_value = toggle_state
    
    result = render_dashboard(mock_ff, "user_1")
    assert result == expected_result
```

---

## Дополнительная информация

### См. также
- **[Архитектура систем](./architecture.md)** — описание Relay, Proxy и Edge-вычислений.
- **[Лучшие практики](./best_practices.md)** — именование, жизненный цикл и TTL флагов.
- **[Сценарии использования](./scenarios.md)** — от Canary до Kill Switches.
- **[Антипаттерны](./antipatterns.md)** — как избежать «спагетти-логики» и утечки секретов.

### Внешние ресурсы
- [OpenFeature Standard Specification](https://openfeature.dev/docs/reference/intro) — детальное описание стандарта.
- [Python OpenFeature SDK](https://github.com/open-feature/python-sdk) — репозиторий официального SDK.
- [Martin Fowler: Feature Toggles](https://martinfowler.com/articles/feature-toggles.html) — архитектурные основы.
