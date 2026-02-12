# Распространённые паттерны кеширования

*   **Cache-aside (lazy loading):** приложение читает из кеша, при промахе — из источника и записывает в кеш. Прост и универсален, но требует ручной инвалидации.
*   **Read-through:** кеш сам умеет «подтягивать» источник по промаху. Упрощает код клиента, но добавляет связность к провайдеру.
*   **Write-through:** запись в источник и немедленно в кеш синхронно. Консистентнее, но увеличивает латентность записи.
*   **Write-back (write-behind):** запись сначала в кеш, асинхронная доставка в источник. Быстро на запись, риск потери без персистентности.
*   **Refresh-ahead:** обновление ключей за некоторое время до истечения TTL, сглаживает задержки.
*   **Negative caching:** кеширование «пустых» результатов (например, 404) на короткий срок, снижает нагрузку на источник.
*   **Stampede prevention:** предотвращение «набегов» при единовременном истечении TTL — джиттер TTL, перезаполнение в фоне, мьютексы/локи.
*   **Sharding:** распределение ключей по множеству инстансов для масштабирования и уменьшения hot-spot.

## Пример: cache-aside с предотвращением stampede (Redis)

```python
def get_user_profile(user_id):
    key = f"user:{user_id}:profile"
    data = redis.get(key)
    if data:
        return decode(data)

    # Лёгкая блокировка на ключ, чтобы один продюсер заполнил кеш
    lock_key = f"lock:{key}"
    got_lock = redis.set(lock_key, "1", nx=True, ex=5)
    if got_lock:
        try:
            record = db.fetch_user(user_id)  # дорогой вызов
            ttl = jitter(300, 0.2)           # TTL с джиттером
            redis.set(key, encode(record), ex=ttl)
            return record
        finally:
            redis.delete(lock_key)
    else:
        # Ожидаем кратко и пробуем снова, избегая наводнения БД
        sleep(0.05)
        data = redis.get(key)
        if data:
            return decode(data)
        return db.fetch_user(user_id)
```
