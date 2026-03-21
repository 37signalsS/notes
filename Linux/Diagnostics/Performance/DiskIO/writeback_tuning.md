# Настройка writeback: параметры ядра

## Определения

- **Dirty Pages (Грязные страницы)**: Страницы в оперативной памяти (page cache), которые были изменены, но ещё не записаны на диск.
- **Writeback**: Фоновый процесс записи dirty pages из кэша памяти на диск.

## Основные концепции

### Параметры ядра для tuning writeback

| Параметр | По умолчанию | Описание | Рекомендация |
| :--- | :--- | :--- | :--- |
| `vm.dirty_ratio` | 20 | % RAM, при котором запись блокируется | 10–40 (медленные диски: больше) |
| `vm.dirty_background_ratio` | 10 | % RAM для фоновой записи | 5–10 |
| `vm.dirty_expire_centisecs` | 3000 | Время до сброса старой dirty page | 3000–6000 |
| `vm.dirty_writeback_centisecs` | 500 | Интервал проверки dirty pages | 300–500 |
| `vm.swappiness` | 60 | Агрессивность использования swap | 1–10 (БД), 60 (общие) |

## Практические сценарии

### Просмотр текущих значений

```bash
# Все параметры dirty pages
sysctl -a | grep vm.dirty

# Или через /proc
cat /proc/sys/vm/dirty_ratio
cat /proc/sys/vm/dirty_background_ratio
cat /proc/sys/vm/dirty_expire_centisecs
cat /proc/sys/vm/dirty_writeback_centisecs
```

### Временное изменение (до перезагрузки)

```bash
# Уменьшить пороги для более частой, но менее интенсивной записи
sudo sysctl -w vm.dirty_ratio=10
sudo sysctl -w vm.dirty_background_ratio=5
sudo sysctl -w vm.dirty_writeback_centisecs=300
```

### Постоянное изменение

```bash
# Добавить в /etc/sysctl.conf
cat >> /etc/sysctl.conf << EOF
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5
vm.dirty_expire_centisecs = 3000
vm.dirty_writeback_centisecs = 300
EOF

# Применить
sudo sysctl -p
```

### Рекомендации для разных сценариев

**Веб-сервер / Общее назначение:**
```bash
vm.dirty_ratio = 20
vm.dirty_background_ratio = 10
vm.dirty_writeback_centisecs = 500
```

**База данных (низкая латентность записи):**
```bash
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5
vm.dirty_writeback_centisecs = 300
vm.swappiness = 1
```

**Файловый сервер / Бэкапы (высокая пропускная способность):**
```bash
vm.dirty_ratio = 40
vm.dirty_background_ratio = 20
vm.dirty_writeback_centisecs = 500
```

**Медленные диски (HDD, сетевое хранилище):**
```bash
vm.dirty_ratio = 30
vm.dirty_background_ratio = 15
vm.dirty_writeback_centisecs = 300
```

## Дополнительная информация

### См. также

- [Роль kworker/u*:flush-*](./kworker_flush.md)
- [Сценарии диагностики I/O](./troubleshooting_scenarios.md)
- [Оптимизация памяти](../../../FileSystems/performance_tuning.md)
