# Anti-patterns Feature Toggles

## 1. Слишком много toggles

```python
# ❌ Плохо: сложная логика
if (ff.is_enabled('feature-a') and 
    ff.is_enabled('feature-b') and 
    not ff.is_enabled('feature-c')):
    do_something()
```

## 2. Вложенные toggles

```python
# ❌ Плохо: сложно понять
if ff.is_enabled('outer-feature'):
    if ff.is_enabled('inner-feature'):
        do_complex_thing()
    else:
        do_simple_thing()
else:
    do_legacy_thing()
```

## 3. Database schema changes внутри toggle

```sql
-- ❌ Плохо: опасно!
-- Миграция должна выполняться всегда
ALTER TABLE users ADD COLUMN new_field VARCHAR(255);
-- Toggle управляет только кодом, не схемой
```
