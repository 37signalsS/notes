# Роль kworker/u*:flush-* в дисковом I/O

## Определения

- **Dirty Pages (Грязные страницы)**: Страницы в оперативной памяти (page cache), которые были изменены, но ещё не записаны на диск.
- **Writeback**: Фоновый процесс записи dirty pages из кэша памяти на диск.
- **`kworker/u*:flush-*`**: Ядерные потоки, отвечающие за сброс dirty pages на блочные устройства (например, `flush-8:0` для `/dev/sda`, где 8:0 — мажорное:минорное число устройства).

## Основные концепции

### Механизм работы

1. Приложения пишут в page cache (быстро, асинхронно)
2. Ядро накапливает dirty pages
3. При достижении порога (`vm.dirty_background_ratio`) ядро запускает фоновую запись
4. Потоки `kworker/u*:flush-*` сбрасывают данные на диск

### Почему 100% I/O

- Накопление большого объёма dirty pages перед сбросом
- Медленный диск не успевает за скоростью записи в RAM
- Много мелких файлов — высокий overhead на операцию
- Достигнут `vm.dirty_ratio` — процессы блокируются до сброса

## Практические сценарии

### Диагностика kworker I/O

```bash
# Проверить kworker потоки
ps aux | grep kworker

# Проверить dirty pages в памяти
cat /proc/meminfo | grep -E "Dirty|Writeback"

# Детальная трассировка I/O запросов от kworker
sudo biosnoop | grep kworker

# Мониторинг файловых операций
sudo fatrace | grep -E "WRITE|OPEN"
```

### Решение проблем с writeback

```bash
# Временно уменьшить пороги dirty pages (меньше залпы, но чаще)
sudo sysctl -w vm.dirty_ratio=10
sudo sysctl -w vm.dirty_background_ratio=5
sudo sysctl -w vm.dirty_writeback_centisecs=300

# Постоянно: добавить в /etc/sysctl.conf
cat >> /etc/sysctl.conf << EOF
vm.dirty_ratio = 10
vm.dirty_background_ratio = 5
vm.dirty_expire_centisecs = 3000
vm.dirty_writeback_centisecs = 300
EOF
```

## Дополнительная информация

### См. также

- [Невидимый I/O](./invisible_io.md)
- [Настройка writeback](./writeback_tuning.md)
- [Диагностический чеклист I/O](./diagnostic_checklist.md)
- [Оптимизация памяти](../../../FileSystems/performance_tuning.md)
