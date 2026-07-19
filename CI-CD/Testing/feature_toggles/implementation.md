# Реализация Feature Toggles в коде

## Определения

**Реализация Feature Toggles** — это процесс интеграции логики переключения функциональности непосредственно в исходный код приложения, обеспечивающий выполнение различных веток кода в зависимости от состояния внешнего или внутреннего флага.

---

## Основные концепции

### Выбор подхода: Свой код vs Готовый сервис

| Критерий | Собственная реализация | Специализированный сервис (Unleash, LaunchDarkly) |
| :--- | :--- | :--- |
| **Сложность внедрения** | Низкая (простые условия в коде). | Средняя (интеграция SDK/API). |
| **Управление** | Через файлы конфигурации или БД вручную. | Удобный веб-интерфейс для всех участников. |
| **Возможности** | Ограничены базовой логикой `if/else`. | Таргетинг, стратегии раскатки, аудит изменений. |
| **Надежность** | Зависит от качества собственного кода. | Высокая отказоустойчивость, встроенное кэширование. |

**Рекомендация:** Начинайте с конфигурационных файлов для простых задач. Переходите на внешние сервисы при росте команды (>5 человек) и усложнении сценариев тестирования (A/B, Canary).

---

## Практические сценарии

### Сценарий 1: Простая реализация на Python (Менеджер флагов)

Пример базового класса, который читает состояние из YAML и поддерживает простую проверку по списку ID пользователей.

```python
import yaml
from typing import Dict, Any, Optional

class FeatureFlagProvider:
    def __init__(self, config_path: str):
        with open(config_path) as f:
            self._config = yaml.safe_load(f).get('features', {})

    def is_enabled(self, flag_name: str, context: Optional[Dict] = None) -> bool:
        flag = self._config.get(flag_name, {})
        if not flag.get('enabled', False):
            return False
            
        # Проверка по стратегии (например, список разрешенных пользователей)
        if flag.get('strategy') == 'user_list':
            allowed_users = flag.get('users', [])
            current_user = context.get('user_id') if context else None
            return current_user in allowed_users
            
        return True

# --- Пример использования ---
# provider = FeatureFlagProvider('config.yaml')
# if provider.is_enabled('new-feature', context={'user_id': 'admin'}):
#     do_new_thing()
```

### Сценарий 2: Использование промышленного SDK (Unleash)

Профессиональный подход с использованием централизованного сервера управления флагами.

```python
import os
from UnleashClient import UnleashClient

# Настройка клиента
unleash = UnleashClient(
    url="https://unleash-server.local/api",
    app_name="order-service",
    custom_headers={'Authorization': os.getenv('UNLEASH_TOKEN')}
)
unleash.initialize_client()

# Проверка с богатым контекстом
context = {
    'userId': '123',
    'remoteAddress': '192.168.1.1',
    'properties': {'region': 'EU', 'tier': 'premium'}
}

if unleash.is_enabled("premium-support-chat", context=context):
    activate_chat()
```

---

## Дополнительная информация

### См. также
- **[Архитектура систем](./architecture.md)** — описание взаимодействия компонентов.
- **[Лучшие практики](./best_practices.md)** — правила чистоты кода при работе с флагами.
- **[Сценарии использования](./scenarios.md)** — когда и зачем применять флаги.

### Внешние ресурсы
- [Unleash Python SDK Documentation](https://github.com/Unleash/unleash-client-python)
- [Flagsmith: Open Source Feature Flagging](https://www.flagsmith.com/)
