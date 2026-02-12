# Преимущества и ограничения Unikernels

## Преимущества

### 1. Размер и эффективность

| Метрика | Linux VM | Container | Unikernel |
|---------|----------|-----------|-----------|
| **Размер образа** | 500MB - 2GB | 100MB - 1GB | 1MB - 50MB |
| **Boot time** | 30-60 сек | 1-5 сек | 10-50 мс |
| **Memory footprint** | 1GB+ | 100MB+ | 5-20MB |
| **Density** | 10s VMs/host | 100s containers | 1000s unikernels |

### 2. Безопасность

- **Minimal attack surface**: Нет лишних сервисов
- **No shell**: Невозможно залогиниться
- **Single address space**: Нет kernel/userspace boundary
- **Immutable**: Образ read-only
- **Type safety** (MirageOS): Компилятор предотвращает многие баги

### 3. Производительность

- **No context switches**: Single address space
- **No ring transitions**: Нет kernel/userspace переключений
- **Direct hardware access**: Без прослойки ОС
- **Lock-free**: Нет необходимости в сложной синхронизации

## Ограничения

### 1. Отладка

- Нет shell для troubleshooting
- Ограниченные инструменты мониторинга
- Сложнее диагностировать проблемы

### 2. Разработка

- Кривая обучения (новые языки/фреймворки)
- Ограниченная экосистема
- Не все библиотеки доступны

### 3. Многозадачность

- Single-process (обычно)
- Нет fork()
- Ограниченная поддержка многопоточности

### 4. Persistence

- Stateless по умолчанию
- Сложности с сохранением данных
- Требуется внешнее хранилище
