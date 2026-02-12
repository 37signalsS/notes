# Реализация Feature Toggles

## Простая реализация на Python

```python
import yaml
from typing import Dict, Any, Optional

class FeatureFlagManager:
    def __init__(self, config_path: str):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        self.flags = self.config.get('features', {})
    
    def is_enabled(self, flag_name: str, 
                   context: Optional[Dict[str, Any]] = None) -> bool:
        """Проверить, включен ли toggle"""
        flag = self.flags.get(flag_name, {})
        
        if not flag.get('enabled', False):
            return False
        
        strategy = flag.get('strategy', 'default')
        
        if strategy == 'userId':
            user_id = context.get('user_id') if context else None
            return user_id in flag.get('userIds', [])
        
        elif strategy == 'percentage':
            import hashlib
            user_id = context.get('user_id', 'anonymous')
            hash_val = int(hashlib.md5(
                f"{flag_name}:{user_id}".encode()
            ).hexdigest(), 16)
            return hash_val % 100 < flag.get('percentage', 0)
        
        return True
    
    def get_variant(self, flag_name: str, 
                    context: Optional[Dict[str, Any]] = None,
                    default: str = 'control') -> str:
        """Получить вариант для A/B тестирования"""
        flag = self.flags.get(flag_name, {})
        
        if not flag.get('enabled', False):
            return default
        
        variants = flag.get('variants', [default])
        
        # Консистентное распределение по user_id
        user_id = context.get('user_id', 'anonymous')
        import hashlib
        hash_val = int(hashlib.md5(
            f"{flag_name}:{user_id}".encode()
        ).hexdigest(), 16)
        
        return variants[hash_val % len(variants)]

# Использование
ff_manager = FeatureFlagManager('features.yaml')

# Простая проверка
if ff_manager.is_enabled('dark-mode'):
    enable_dark_mode()

# С контекстом
if ff_manager.is_enabled('beta-feature', 
                          context={'user_id': user.id}):
    show_beta_ui()

# A/B тест
variant = ff_manager.get_variant('new-pricing-page',
                                 context={'user_id': user.id})
render_pricing_page(variant)
```

## Интеграция с Unleash (Open-source)

```python
from UnleashClient import UnleashClient

client = UnleashClient(
    url="https://unleash.mycompany.com/api",
    app_name="my-app",
    custom_headers={'Authorization': 'API_TOKEN'}
)

client.initialize_client()

# Проверка toggle
if client.is_enabled("new-payment-flow", 
                     context={'userId': user.id}):
    process_new_payment()
else:
    process_legacy_payment()

# A/B тест
variant = client.get_variant("checkout-redesign",
                             context={'userId': user.id})
```
