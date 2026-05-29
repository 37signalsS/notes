# Реализация Feature Toggles в коде

## Определения

- **Реализация Feature Toggles** — это практическое встраивание логики проверки флагов в исходный код приложения. Как правило, это сводится к вызову метода `is_enabled()` из специализированного клиента или SDK.

---

## Базовые концепции

### Ключевые решения: Свой код или готовый сервис?

Выбор между собственной реализацией и использованием готового сервиса (SaaS или self-hosted) — ключевое архитектурное решение.

- **Собственная реализация** подходит для:
  - Простых случаев с небольшим количеством флагов.
  - Систем, где нет необходимости в сложном таргетинге и A/B-тестах.
  - Когда нет возможности или желания зависеть от внешних сервисов.

- **Готовый сервис** предпочтителен, когда:
  - Требуется сложная логика таргетинга (по регионам, версиям приложения и т.д.).
  - Необходим удобный UI для управления флагами не-разработчиками (менеджерами, QA).
  - Нужны встроенные инструменты для A/B-тестирования, аудита и мониторинга.
  - Важна высокая производительность и отказоустойчивость, обеспечиваемая провайдером.

Архитектурные компоненты описаны в документе **[Архитектура систем Feature Toggles](./architecture.md)**.

---

## Практические сценарии

### Сценарий 1: Простая реализация на Python

Базовый менеджер флагов, который читает конфигурацию из YAML и поддерживает стратегии по ID пользователя и проценту трафика.

```python
import yaml
from typing import Dict, Any, Optional
import hashlib

class FeatureFlagManager:
    def __init__(self, config_path: str):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        self.flags = self.config.get('features', {})

    def is_enabled(self, flag_name: str,
                   context: Optional[Dict[str, Any]] = None) -> bool:
        """Проверяет, включен ли флаг для данного контекста."""
        flag_config = self.flags.get(flag_name, {})

        if not flag_config.get('enabled', False):
            return False

        strategy = flag_config.get('strategy', 'default')

        if strategy == 'userId':
            user_id = context.get('user_id') if context else None
            return user_id in flag_config.get('userIds', [])

        elif strategy == 'percentage':
            user_id = context.get('user_id', 'anonymous')
            hash_val = int(hashlib.md5(f"{flag_name}:{user_id}".encode()).hexdigest(), 16)
            return hash_val % 100 < flag_config.get('percentage', 0)

        return True

# --- Использование ---
# if ff_manager.is_enabled('dark-mode', context={'user_id': user.id}):
#    enable_dark_mode()
```

### Сценарий 2: Интеграция с готовым решением (Unleash)

Использование готового SDK значительно упрощает работу, так как вся сложная логика (кэширование, стратегии, A/B-тесты) реализована внутри клиента.

```python
import os
from UnleashClient import UnleashClient

# Инициализация клиента
client = UnleashClient(
    url="https://unleash.mycompany.com/api",
    app_name="my-app",
    custom_headers={'Authorization': os.getenv('UNLEASH_API_TOKEN', '')}
)
client.initialize_client()

# Проверка флага с передачей контекста
context = {'userId': user.id, 'sessionId': session.id}
if client.is_enabled("new-payment-flow", context=context):
    process_new_payment()
else:
    process_legacy_payment()
```

---

## Дополнительная информация

**Связанные документы:** [Сценарии использования](./scenarios.md), [Лучшие практики](./best_practices.md), [Архитектура систем Feature Toggles](./architecture.md).
