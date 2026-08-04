---
reliability: 10
updated: 2026-08-01
---

# Реализация Feature Toggles в коде

## Определения

**Реализация Feature Toggles** — это процесс интеграции логики переключения функциональности непосредственно в исходный код приложения, обеспечивающий выполнение различных веток кода в зависимости от состояния внешнего или внутреннего флага.

**OpenFeature** — открытый стандарт (CNCF) для управления флагами функций, предоставляющий унифицированный SDK для работы с любыми поставщиками (vendors) без привязки к их специфичному API.

---

## Основные концепции

### Выбор подхода: Свой код vs Готовый сервис

| Критерий | Собственная реализация | Специализированный сервис (Unleash, LaunchDarkly) |
| :--- | :--- | :--- |
| **Сложность внедрения** | Низкая (простые условия в коде). | Средняя (интеграция SDK/API). |
| **Управление** | Через файлы конфигурации или БД вручную. | Удобный веб-интерфейс для всех участников. |
| **Возможности** | Ограничены базовой логикой `if/else`. | Таргетинг, стратегии раскатки, аудит изменений. |
| **Надежность** | Зависит от качества собственного кода. | Высокая отказоустойчивость, встроенное кэширование. |

### Паттерн «Обертка» (Wrapper/Facade)

Для предотвращения жесткой привязки (vendor lock-in) к конкретному SDK рекомендуется использовать паттерн «Обертка». Это позволяет сменить поставщика флагов (например, с YAML на Unleash) без изменения бизнес-логики.

```python
# Интерфейс провайдера
class FeatureToggleService:
    def is_enabled(self, flag: str, context: dict) -> bool:
        raise NotImplementedError
```

---

## Практические сценарии

### Сценарий 1: Простая реализация на Python (YAML + Dataclasses)

Использование `dataclasses` для типизации контекста пользователя повышает надежность проверок.

```python
import yaml
from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class UserContext:
    user_id: str
    role: str

class YamlFeatureProvider:
    def __init__(self, config_path: str):
        with open(config_path) as f:
            self._config = yaml.safe_load(f).get('features', {})

    def is_enabled(self, flag_name: str, context: Optional[UserContext] = None) -> bool:
        flag = self._config.get(flag_name, {})
        if not flag.get('enabled', False):
            return False
            
        # Логика сегментации по ролям
        if flag.get('allowed_roles'):
            return context.role in flag['allowed_roles'] if context else False
            
        return True

# Использование
# context = UserContext(user_id="1", role="admin")
# provider = YamlFeatureProvider("flags.yaml")
# if provider.is_enabled("beta_dashboard", context):
#     render_new_ui()
```

### Сценарий 2: Промышленная реализация (Unleash + OpenFeature)

Использование стандарта OpenFeature позволяет абстрагироваться от конкретного вендора.

```python
from openfeature import api
from openfeature.contrib.provider.unleash import UnleashProvider

# 1. Настройка провайдера (один раз при запуске)
api.set_provider(UnleashProvider(
    url="https://unleash-server.local/api",
    app_name="order-service"
))

# 2. Получение клиента
client = api.get_client()

# 3. Проверка флага
context = {"user_id": "123", "region": "EU"}
if client.get_boolean_value("new-checkout-flow", False, context):
    execute_new_flow()
```

### Сценарий 3: Тестирование кода с флагами (Unit Testing)

Для тестирования функций, зависящих от флагов, следует использовать моки (mocks), чтобы проверить обе ветки логики (`if` и `else`).

```python
import pytest
from unittest.mock import MagicMock

def process_order(toggle_service, order_id):
    if toggle_service.is_enabled("fast-delivery", {"order_id": order_id}):
        return "Express Delivery"
    return "Standard Delivery"

def test_process_order_with_toggle_on():
    mock_service = MagicMock()
    mock_service.is_enabled.return_value = True
    assert process_order(mock_service, "123") == "Express Delivery"

def test_process_order_with_toggle_off():
    mock_service = MagicMock()
    mock_service.is_enabled.return_value = False
    assert process_order(mock_service, "123") == "Standard Delivery"
```

---

## Дополнительная информация

### См. также
- **[Архитектура систем](./architecture.md)** — описание взаимодействия компонентов (Relay, Proxy).
- **[Лучшие практики](./best_practices.md)** — правила именования и удаления флагов.
- **[Сценарии использования](./scenarios.md)** — Canary, A/B и Kill Switches.

### Внешние ресурсы
- [OpenFeature Documentation](https://openfeature.dev/docs/reference/intro) — спецификация стандарта.
- [Unleash Python SDK](https://github.com/Unleash/unleash-client-python) — официальный клиент.
- [Flagsmith Open Source FF](https://www.flagsmith.com/) — популярная альтернатива.
