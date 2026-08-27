# Реализация Feature Toggles в коде

## Определения

**Реализация Feature Toggles** — это процесс интеграции механизмов динамического управления логикой непосредственно в программный код приложения. Это позволяет выполнять различные ветки алгоритмов в зависимости от состояния внешних или внутренних флагов без пересборки артефактов.

**OpenFeature** — открытый стандарт (CNCF Graduated) для управления флагами функций, предоставляющий унифицированный API (Vendor-neutral) для работы с любыми поставщиками (Unleash, LaunchDarkly, Flipt) или собственными реализациями.

---

## Предварительные требования

### Инструментарий

| Компонент | Назначение | Минимальная версия |
| :--- | :--- | :--- |
| **FFaaS платформа** | Хранение и управление флагами (Unleash, Flipt, Flagsmith) | Unleash v5+ / Flipt v1.35+ |
| **OpenFeature SDK** | Унифицированный API для проверки флагов в коде | v0.4+ (Python/Go/Java/Node) |
| **flagd** | Локальный демон оценки флагов (OpenFeature) | v0.8+ |
| **OpenTelemetry SDK** | Инъекция телеметрии по флагам в спаны | v1.24+ |
| **Prometheus** | Сбор метрик по использованию флагов | v2.50+ |

### Локальное окружение для проверки паттернов

```bash
# Развертывание FFaaS + flagd для проверки реализаций
git clone https://github.com/Unleash/unleash-docker.git
cd unleash-docker
docker compose up -d
# → Unleash: http://localhost:4242 (admin/unleash4all)

# Проверка доступности API
curl -s http://localhost:4242/api/admin/user | jq '.user.permissions'
# → ["admin"]

# Установка OpenFeature SDK (Python)
pip install openfeature-sdk openfeature-provider-unleash opentelemetry-api

# Установка OpenFeature SDK (Go)
go get github.com/open-feature/go-sdk
go get github.com/open-feature/go-sdk-contrib/providers/unleash

# Установка OpenFeature SDK (Node.js)
npm install @openfeature/js-sdk @openfeature/unleash-provider
```

### Базовые знания

Перед изучением рекомендуется ознакомиться с:
- Архитектурой систем Feature Toggles ([Архитектура](./architecture.md))
- Лучшими практиками ([Best Practices](./best_practices.md))
- Типами флагов ([Типы](./types.md))

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

## Практические реализации

### Паттерн «Стратегия» (Strategy Pattern) — полная реализация

#### Python + Dependency Injection

```python
from abc import ABC, abstractmethod
from openfeature import api

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

class LoyaltyDiscountPricing(PricingStrategy):
    def calculate(self, base_price: float) -> float:
        return base_price * 0.85  # 15% скидка для лояльных

# Фабрика на основе флагов
def get_pricing_service(ff_client, user_id: str, is_loyal: bool = False) -> PricingStrategy:
    context = {"user_id": user_id, "is_loyal": str(is_loyal)}
    
    if ff_client.get_boolean_value("pricing.holiday-sale.active", False, context):
        return HolidayDiscountPricing()
    if ff_client.get_boolean_value("pricing.loyalty-discount.active", False, context):
        return LoyaltyDiscountPricing()
    return DefaultPricing()

# Использование
def process_order(user_id: str, base_price: float, is_loyal: bool = False):
    client = api.get_client()
    strategy = get_pricing_service(client, user_id, is_loyal)
    final_price = strategy.calculate(base_price)
    return {"user_id": user_id, "base_price": base_price, "final_price": final_price}
```

#### Go + Context

```go
package pricing

import (
    "context"
    "github.com/open-feature/go-sdk/openfeature"
)

type PricingStrategy interface {
    Calculate(basePrice float64) float64
}

type DefaultPricing struct{}
func (d DefaultPricing) Calculate(basePrice float64) float64 { return basePrice }

type HolidayDiscountPricing struct{}
func (h HolidayDiscountPricing) Calculate(basePrice float64) float64 { return basePrice * 0.8 }

func GetPricingService(ctx context.Context, userID string) PricingStrategy {
    client := openfeature.GetClient(ctx)
    evalCtx := openfeature.NewEvaluationContext(userID)
    
    isActive, err := client.BooleanValue(ctx, "pricing.holiday-sale.active", false, evalCtx)
    if err != nil || !isActive {
        return DefaultPricing{}
    }
    return HolidayDiscountPricing{}
}
```

#### Node.js + TypeScript

```typescript
import { OpenFeature, Provider } from "@openfeature/js-sdk";

interface PricingStrategy {
  calculate(basePrice: number): number;
}

class DefaultPricing implements PricingStrategy {
  calculate(basePrice: number): number { return basePrice; }
}

class HolidayDiscountPricing implements PricingStrategy {
  calculate(basePrice: number): number { return basePrice * 0.8; }
}

async function getPricingService(userId: string): Promise<PricingStrategy> {
  const client = OpenFeature.getClient();
  const context = { targetingKey: userId };
  
  const isActive = await client.getBooleanValue("pricing.holiday-sale.active", false, context);
  return isActive ? new HolidayDiscountPricing() : new DefaultPricing();
}
```

### Паттерн «Декоратор» (Decorator Pattern)

Декоратор позволяет добавлять логику «вокруг» существующего метода без изменения его кода. Флаг управляет тем, будет ли декоратор активирован.

```python
from functools import wraps
from openfeature import api
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

class AuditDecorator:
    """Декоратор для аудита критических операций — активируется через флаг."""
    
    def __init__(self, func):
        self.func = func
    
    def __call__(self, *args, **kwargs):
        client = api.get_client()
        context = kwargs.get("context", {})
        
        # Проверка флага: включать ли аудит
        audit_enabled = client.get_boolean_value(
            "security.audit.enabled", True, context
        )
        
        if audit_enabled:
            # Логирование до выполнения
            logger.info(f"AUDIT: Pre-execution of {self.func.__name__}")
            with tracer.start_as_current_span(f"audit.{self.func.__name__}") as span:
                span.set_attribute("audit.operation", self.func.__name__)
                result = self.func(*args, **kwargs)
                span.set_attribute("audit.result", "success")
                return result
        else:
            # Без аудита — быстрый путь
            return self.func(*args, **kwargs)

# Использование декоратора
@AuditDecorator
def transfer_funds(from_account: str, to_account: str, amount: float, context: dict = None):
    # Критическая операция — всегда выполняется
    # Аудит включается/выключается динамически через флаг
    return {"status": "ok", "transferred": amount}
```

### Унифицированная «Обертка» (Wrapper/Facade)

Критически важный паттерн для смены вендора без изменения бизнес-логики.

#### Python: полная реализация Wrapper

```python
from openfeature import api
from openfeature.contrib.provider.unleash import UnleashProvider
from openfeature.contrib.provider.flipt import FliptProvider
from opentelemetry import trace
import logging

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

class FeatureFlagService:
    """Обертка над OpenFeature API — единая точка входа для всех проверок флагов.
    
    Позволяет сменить вендора (Unleash → Flipt → LaunchDarkly) за один день,
    изменив только конфигурацию провайдера.
    """
    
    def __init__(self, provider_name: str = "unleash", **kwargs):
        self._init_provider(provider_name, **kwargs)
    
    def _init_provider(self, name: str, **kwargs):
        providers = {
            "unleash": lambda: UnleashProvider(
                url=kwargs.get("url", "http://localhost:4242"),
                app_name=kwargs.get("app_name", "default"),
                api_key=kwargs.get("api_key"),
            ),
            "flipt": lambda: FliptProvider(
                url=kwargs.get("url", "http://localhost:9080"),
            ),
        }
        
        if name not in providers:
            raise ValueError(f"Unknown provider: {name}. Available: {list(providers.keys())}")
        
        provider = providers[name]()
        api.set_provider(provider)
        logger.info(f"Feature flag provider initialized: {name}")
    
    def is_enabled(self, flag_name: str, default: bool = False, context: dict = None) -> bool:
        """Проверка boolean-флага с fallback-значением и OTel-трассировкой."""
        client = api.get_client()
        ctx = context or {}
        
        with tracer.start_as_current_span(f"feature_flag.{flag_name}") as span:
            try:
                result = client.get_boolean_value(flag_name, default, ctx)
                span.set_attribute(f"feature_flag.{flag_name}", result)
                return result
            except Exception as e:
                logger.warning(f"Flag evaluation failed for '{flag_name}': {e}")
                span.set_attribute("feature_flag.error", str(e))
                return default  # Fail-safe
    
    def get_string(self, flag_name: str, default: str = "", context: dict = None) -> str:
        """Получение строкового варианта флага."""
        client = api.get_client()
        ctx = context or {}
        
        with tracer.start_as_current_span(f"feature_flag.{flag_name}") as span:
            try:
                result = client.get_string_value(flag_name, default, ctx)
                span.set_attribute(f"feature_flag.{flag_name}", result)
                return result
            except Exception as e:
                logger.warning(f"Flag evaluation failed for '{flag_name}': {e}")
                return default
    
    def get_number(self, flag_name: str, default: float = 0.0, context: dict = None) -> float:
        """Получение числового значения флага."""
        client = api.get_client()
        ctx = context or {}
        
        try:
            return client.get_number_value(flag_name, default, ctx)
        except Exception as e:
            logger.warning(f"Flag evaluation failed for '{flag_name}': {e}")
            return default

# Инициализация в main.py
ff_service = FeatureFlagService(
    provider_name="unleash",
    url="http://unleash.internal:4242",
    app_name="checkout-service",
    api_key="*:*.project-1.api-token"
)

# Использование в бизнес-логике
def process_checkout(user_id: str, cart_total: float):
    context = {"user_id": user_id, "cart_total": str(cart_total)}
    
    if ff_service.is_enabled("checkout.payment.applepay.enabled", False, context):
        return process_applepay_checkout(user_id, cart_total)
    return process_standard_checkout(user_id, cart_total)
```

#### Go: Wrapper с конфигурацией

```go
package featureflags

import (
    "context"
    "log"
    "github.com/open-feature/go-sdk/openfeature"
)

type FlagService struct {
    client *openfeature.Client
}

func NewFlagService(providerName string, opts map[string]string) *FlagService {
    var provider openfeature.FeatureProvider
    
    switch providerName {
    case "unleash":
        // конфигурация Unleash провайдера
        provider = newUnleashProvider(opts)
    case "flipt":
        provider = newFliptProvider(opts)
    default:
        log.Fatalf("Unknown provider: %s", providerName)
    }
    
    openfeature.SetProvider(provider)
    client := openfeature.GetClient("default")
    return &FlagService{client: client}
}

func (s *FlagService) IsEnabled(ctx context.Context, flag string, defaultVal bool, userID string) bool {
    evalCtx := openfeature.NewEvaluationContext(userID)
    result, err := s.client.BooleanValue(ctx, flag, defaultVal, evalCtx)
    if err != nil {
        log.Printf("Flag evaluation failed for '%s': %v, using default: %v", flag, err, defaultVal)
        return defaultVal
    }
    return result
}
```

---

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

---

### OpenFeature Hooks: перехват оценки флагов

Hooks позволяют внедрять кастомную логику до/после/вместо оценки флага — валидацию контекста, логирование, метрики.

```python
from openfeature.hooks import Hook, HookContext
from openfeature.evaluation import FlagEvaluationDetails
from opentelemetry import trace
import time

tracer = trace.get_tracer(__name__)

class ValidationHook(Hook):
    """Hook для валидации контекста перед оценкой флага."""
    
    def before(self, hook_context: HookContext, hook_details: FlagEvaluationDetails, **kwargs):
        """Проверка наличия обязательных полей контекста."""
        eval_ctx = hook_context.evaluation_context
        if not eval_ctx or not eval_ctx.targeting_key:
            raise ValueError(f"Missing targeting_key in evaluation context for flag '{hook_context.flag_key}'")
        return None
    
    def after(self, hook_context: HookContext, hook_details: FlagEvaluationDetails, **kwargs):
        """Логирование результата оценки."""
        logger.info(
            f"Flag '{hook_context.flag_key}' evaluated: "
            f"value={hook_details.value}, variant={hook_details.variant}"
        )
        return None

class PerformanceHook(Hook):
    """Hook для измерения latency оценки флагов."""
    
    def before(self, hook_context: HookContext, hook_details: FlagEvaluationDetails, **kwargs):
        hook_details.flag_evaluation_start_time = time.perf_counter()
        return None
    
    def after(self, hook_context: HookContext, hook_details: FlagEvaluationDetails, **kwargs):
        start = getattr(hook_details, 'flag_evaluation_start_time', 0)
        duration = time.perf_counter() - start
        
        with tracer.start_as_current_span("flag.evaluation") as span:
            span.set_attribute("feature_flag.key", hook_context.flag_key)
            span.set_attribute("flag.evaluation.duration_ms", duration * 1000)
        
        if duration > 0.01:  # >10ms — алерт
            logger.warning(f"Slow flag evaluation: {hook_context.flag_key} took {duration*1000:.2f}ms")
        return None

# Регистрация хуков при инициализации
api.set_provider(UnleashProvider(...))
api.add_hooks([ValidationHook(), PerformanceHook()])
```

---

### Интеграция с наблюдаемостью (Observability)

В современных SRE-практиках проверка флага в коде обязана сопровождаться телеметрией:
- **Span Injection**: Состояние всех проверенных флагов за время запроса должно попадать в атрибуты спана **OpenTelemetry**.
- **Exposure Events**: Генерация события в момент, когда пользователь физически столкнулся с логикой флага (не просто при вычислении, а при фактическом выполнении ветки).

#### Полная реализация OTel-интеграции

```python
from opentelemetry import trace, metrics
from opentelemetry.trace import StatusCode
from openfeature import api

tracer = trace.get_tracer(__name__)
meter = metrics.get_meter(__name__)

# Метрики использования флагов
flag_evaluation_counter = meter.create_counter(
    name="feature_flag.evaluations.total",
    description="Total number of feature flag evaluations",
    unit="1"
)

flag_evaluation_duration = meter.create_histogram(
    name="feature_flag.evaluation.duration",
    description="Duration of feature flag evaluations",
    unit="ms"
)

class FlagAwareOperation:
    """Обертка для операций с полной OTel-трассировкой по флагам."""
    
    def __init__(self, flag_name: str, context: dict):
        self.flag_name = flag_name
        self.context = context
        self.client = api.get_client()
    
    def evaluate(self, default: bool = False) -> bool:
        with tracer.start_as_current_span(f"flag.evaluate.{self.flag_name}") as span:
            start_time = time.perf_counter()
            
            try:
                result = self.client.get_boolean_value(self.flag_name, default, self.context)
                
                # Метрики
                duration_ms = (time.perf_counter() - start_time) * 1000
                flag_evaluation_counter.add(1, {
                    "flag": self.flag_name,
                    "result": str(result)
                })
                flag_evaluation_duration.record(duration_ms, {"flag": self.flag_name})
                
                # Атрибуты спана
                span.set_attribute("feature_flag.key", self.flag_name)
                span.set_attribute("feature_flag.result", result)
                span.set_attribute("feature_flag.context.targeting_key", 
                                 self.context.get("targeting_key", "unknown"))
                
                return result
            except Exception as e:
                span.set_status(StatusCode.ERROR, str(e))
                span.set_attribute("feature_flag.error", str(e))
                flag_evaluation_counter.add(1, {
                    "flag": self.flag_name,
                    "result": "error"
                })
                return default

# Использование
def render_dashboard(user_id: str):
    flag_op = FlagAwareOperation("ui.dashboard.v2.enabled", {"targeting_key": user_id})
    
    with tracer.start_as_current_span("render_dashboard") as span:
        is_v2 = flag_op.evaluate(default=False)
        
        if is_v2:
            result = render_new_dashboard(user_id)
            span.set_attribute("dashboard.variant", "v2")
        else:
            result = render_legacy_dashboard(user_id)
            span.set_attribute("dashboard.variant", "legacy")
        
        return result
```

---

### Интеграция с flagd (локальная оценка)

При работе с flagd как sidecar оценка происходит через gRPC/HTTP на localhost без обращения к удаленному FFaaS.

#### Python: подключение к flagd

```python
from openfeature import api
from openfeature.contrib.provider.flagd import FlagdProvider

# flagd запущен как sidecar на localhost:8013
api.set_provider(FlagdProvider(
    host="localhost",
    port=8013,
    protocol="grpc"  # или "http"
))

client = api.get_client()
# Оценка через локальный flagd — без сетевого вызова во внешнюю систему
is_enabled = client.get_boolean_value("checkout.new-flow", False, {"user_id": "123"})
```

#### Go: подключение к flagd

```go
package main

import (
    "context"
    "github.com/open-feature/go-sdk/openfeature"
    flagd "github.com/open-feature/go-sdk-contrib/providers/flagd/pkg"
)

func main() {
    provider, err := flagd.NewProvider(
        flagd.WithInProcessResolver("checkout-service", "localhost:8013"),
    )
    if err != nil {
        log.Fatalf("Failed to create flagd provider: %v", err)
    }
    
    openfeature.SetProvider(provider)
    
    client := openfeature.GetClient("checkout-service")
    evalCtx := openfeature.NewEvaluationContext("user-123")
    
    isEnabled, err := client.BooleanValue(context.Background(), "checkout.new-flow", false, evalCtx)
    if err != nil {
        log.Printf("Flag evaluation error: %v, using default false", err)
        isEnabled = false
    }
}
```

#### Node.js: подключение к flagd

```typescript
import { OpenFeature } from "@openfeature/js-sdk";
import { FlagdProvider } from "@openfeature/flagd-provider";

const provider = new FlagdProvider({
  host: "localhost",
  port: 8013,
  tls: false,
});

OpenFeature.setProvider(provider);

const client = OpenFeature.getClient("checkout-service");
const context = { targetingKey: "user-123" };
const isEnabled = await client.getBooleanValue("checkout.new-flow", false, context);
```

---

## Тестирование реализации

### Юнит-тестирование (Pytest)

Для тестирования кода с флагами необходимо проверять **обе ветки** логики. Использование параметризации — лучший способ избежать дублирования.

```python
import pytest
from unittest.mock import MagicMock, patch

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

### Интеграционное тестирование (с реальным FFaaS)

```python
import pytest
from openfeature import api
from openfeature.contrib.provider.unleash import UnleashProvider

@pytest.fixture(scope="module")
def ff_client():
    """Настройка реального клиента для интеграционных тестов."""
    api.set_provider(UnleashProvider(
        url="http://localhost:4242",
        app_name="test-service",
        api_key="*:*.test-token"
    ))
    return api.get_client()

def test_flag_integration(ff_client):
    """Проверка, что флаг доступен и возвращает корректное значение."""
    context = {"user_id": "test-user-001"}
    result = ff_client.get_boolean_value("test.integration-flag", False, context)
    assert isinstance(result, bool)

def test_flag_variants_integration(ff_client):
    """Проверка вариантов экспериментального флага."""
    context = {"user_id": "test-user-001"}
    variant = ff_client.get_string_value("test.experiment-v2", "control", context)
    assert variant in ["control", "variant-a", "variant-b"]
```

### Контрактное тестирование (Provider-agnostic)

Проверяет, что бизнес-логика корректно работает с любым OpenFeature-провайдером.

```python
import pytest
from unittest.mock import MagicMock

@pytest.fixture
def mock_provider():
    """Универсальный мок провайдера — имитирует поведение любого FFaaS."""
    provider = MagicMock()
    provider.get_boolean_value.return_value = True
    provider.get_string_value.return_value = "variant-a"
    return provider

def test_checkout_with_any_provider(mock_provider):
    """Контракт: checkout работает одинаково с Unleash, Flipt или любым другим."""
    api.set_provider(mock_provider)
    client = api.get_client()
    
    result = process_checkout("user-123", 100.0)
    assert result["status"] == "ok"
```

### Chaos-тестирование (FFaaS недоступен)

```python
import pytest
from unittest.mock import patch, MagicMock

def test_checkout_when_ffaas_down():
    """Проверка fail-safe: при недоступности FFaaS checkout работает с дефолтами."""
    with patch("openfeature.api.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.get_boolean_value.side_effect = ConnectionError("FFaaS unreachable")
        mock_get_client.return_value = mock_client
        
        # При ошибке должен использоваться fallback
        result = process_checkout_with_fallback("user-123", 100.0)
        assert result["checkout_method"] == "standard"  # дефолт
        assert result["status"] == "ok"
```

---

### Validation Checklist

| Проверка | Метод | Ожидаемый результат |
| :--- | :--- | :--- |
| Wrapper/Facade изолирует логику от вендора | `grep "from openfeature" src/` = 0 в бизнес-логике | Все проверки флагов через wrapper |
| Fail-safe: fallback указан в каждом вызове | `rg "get_boolean_value" src/ \| wc -l` = `rg "get_boolean_value.*False" \| wc -l` | Каждый вызов содержит fallback |
| OTel-интеграция | `rg "span.set_attribute.*feature_flag" src/ \| wc -l` > 0 | Атрибуты флагов в спанах |
| Hook-валидация работает | Запуск `pytest tests/test_hooks.py` | Контекст с пустым targeting_key отклоняется |
| Wrapper смену вендора за 1 день | `grep "provider_name" src/feature_flags.py` → изменить на "flipt" | Код работает с новым провайдером |
| Интеграционные тесты | `pytest tests/integration/ -v` | Все тесты проходят с реальным FFaaS |
| Chaos-тесты | `pytest tests/chaos/ -v` | При недоступности FFaaS приложение работает |

---

## Типичные ошибки и диагностика (Troubleshooting)

| Симптом | Вероятная причина | Диагностические действия | Решение |
| :--- | :--- | :--- | :--- |
| `ConnectionError` при инициализации SDK | FFaaS сервер недоступен или неверный URL | `curl -v $UNLEASH_URL/api/admin/user` → проверить доступность; `telnet unleash.internal 4242` → проверить порт | Убедиться, что URL корректен и порт открыт; добавить retry-логику с exponential backoff |
| Флаг всегда возвращает default | SDK не получил Ruleset | `docker logs flagd-proxy` → проверить sync; проверить bootstrap.json | Убедиться, что bootstrap файл доступен SDK; проверить `refreshInterval` |
| `TypeError` при проверке флага | Отсутствует fallback-значение | `rg "get_boolean_value" src/` → найти вызовы без второго аргумента | Добавить fallback: `get_boolean_value("flag", False)` |
| Неконсистентность между Wrappers | Разные Wrapper-ы в разных сервисах | Сравнить реализации: `diff service-a/feature_flags.py service-b/feature_flags.py` | Использовать общую библиотеку wrapper для всех сервисов |
| Hook не выполняется | Hook не зарегистрирован или exceptions в before | Проверить `api.hooks` → список зарегистрированных хуков; проверить логи на ошибки | Убедиться, что `api.add_hooks([...])` вызван после `api.set_provider()` |
| Ложные алерты по OTel | Метрики дублируются из-за retry | `rg "start_as_current_span" src/` → проверить вложенность spans | Убедиться, что span создается один раз на операцию |
| Смена вендора ломает тесты | Тесты завязаны на конкретный SDK | `rg "UnleashProvider" tests/` → найти прямые зависимости | Использовать mock-провайдер для контрактных тестов |

---

## Ограничения и особые случаи (Edge Cases)

### Race conditions при并发评估е

В многопоточных приложениях параллельные проверки одного флага могут приводить к состоянию гонки. OpenFeature SDK Unsafe` для безопасного доступа к кешу. В Go используется `sync.RWMutex`.

### Отладка в生产环境

В production избегайте `console.log` / `print` для отладки флагов. Используйте OTel-трассировку: каждый вызов `get_boolean_value` автоматически попадает в spans.

### Кэширование в CDN/Браузере

Если флаг определяет видимость элемента UI, а страница кэшируется CDN или браузером, пользователь может видеть устаревшее состояние. Решение: не кэшировать страницы с активными флагами или добавлять `Cache-Control: no-cache`.

### Offline-режим (Mobile)

При отсутствии сети SDK не может получить обновленное значение флага. Используйте bootstrap-файл или hardcoded fallback.

---

## Дополнительная информация

### См. также
- **[Архитектура систем](./architecture.md)** — описание Relay, Proxy и Edge-вычислений, flagd.
- **[Лучшие практики](./best_practices.md)** — именование, жизненный цикл и TTL флагов.
- **[Сценарии использования](./scenarios.md)** — от Canary до Kill Switches.
- **[Антипаттерны](./antipatterns.md)** — как избежать «спагетти-логики» и утечки секретов.

### Внешние ресурсы
- [OpenFeature Standard Specification](https://openfeature.dev/docs/reference/intro) — детальное описание стандарта.
- [Python OpenFeature SDK](https://github.com/open-feature/python-sdk) — репозиторий официального SDK.
- [Go OpenFeature SDK](https://github.com/open-feature/go-sdk) — Go SDK с примерами.
- [Martin Fowler: Feature Toggles](https://martinfowler.com/articles/feature-toggles.html) — архитектурные основы.
