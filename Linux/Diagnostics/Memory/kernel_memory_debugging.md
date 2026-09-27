# Отладка памяти ядра (kmemleak, KASAN, KCSAN)

## Определения

**kmemleak** — механизм ядра Linux для обнаружения утечек памяти в пространстве ядра (kernel space). Работает как «сборщик мусора» для ядра: сканирует все возможные ссылки на выделенные объекты и помечает те, на которые нет активных указателей. Результаты доступны через `debugfs` (`/sys/kernel/debug/kmemleak`).

**KASAN (Kernel Address Sanitizer)** — инструмент динамического анализа памяти, выявляющий buffer-overflow и use-after-free ошибки в коде ядра. Работает на уровне каждого обращения к памяти, добавляя проверку «красных зон» (redzones) вокруг выделенных блоков. Требует пересборки ядра с `CONFIG_KASAN=y`.

**KCSAN (Kernel Concurrency Sanitizer)** — инструмент обнаружения гонок данных (data races) в коде ядра. Использует подход «watchpoints» для мониторинга параллельных обращений к одним и тем же адресам памяти. Доступен с ядра 5.8.

**KMSAN (Kernel Memory Sanitizer)** — инструмент обнаружения использования неинициализированной памяти в пространстве ядра. Аналог MSAN для userspace. Доступен с ядра 5.17.

**slab leak** — утечка объектов в слаб-аллокаторе ядра (SLUB/SLAB). Проявляется как постоянный рост `SUnreclaim` в `/proc/meminfo` без видимых причин в userspace-процессах.

**debugfs** — виртуальная файловая система ядра (`/sys/kernel/debug/`), предоставляющая интерфейс к различным механизмам отладки, включая kmemleak, ftrace и динамический debug.

**vmlinux** — несжатый бинарник ядра Linux, содержащий символы отладки. Необходим для `crash`-анализа и工作的 kmemleak/kasan.

## Основные концепции

### Архитектура kmemleak

kmemleak работает в фоновом режиме, периодически сканируя память ядра:

**Принцип работы:**
1. При каждом вызове `kmalloc`, `kzalloc`, `vmalloc` и аналогичных функций ядро регистрирует выделенный объект в битовой карте.
2. Фоновый поток (период — по умолчанию 60 секунд) сканирует всю память ядра, ищущую ссылки на зарегистрированные объекты.
3. Объекты, на которые не найдено активных ссылок, помечаются как «potentially leaked».
4. Результаты доступны для чтения через `/sys/kernel/debug/kmemleak`.

**Overhead:** kmemleak добавляет ~5-10% к времени выполнения каждого аллокационного вызова. На production-системах рекомендуется отключать (см. раздел «Best Practices»).

**Ограничения:**
- Ложные срабатывания (false positives): объекты, сохраненные в нетипичных местах (нестандартные ссылки, битовые операции).
- Не видит утечки в userspace (используйте `valgrind`, `memleak` BCC).
- Зависимость от `CONFIG_DEBUG_KMEMLEAK=y` при сборке ядра.

### Архитектура KASAN

KASAN добавляет instrumentацию на каждый доступ к памяти:

**Механизм shadow memory:**
1. KASAN выделяет область «тени» (shadow memory), которая отражает состояние каждой 8-байтовой ячейки основной памяти.
2. Каждый байт тени кодирует состояние соответствующих 8 байт: доступно, защищено (redzone), освобождено (freed).
3. При каждом обращении к памяти KASAN проверяет состояние тени и вызывает `BUG()` при нарушении.

**Типы проверок:**
- **Out-of-bounds:** Доступ за пределы выделенного блока (buffer overflow).
- **Use-after-free:** Доступ к освобожденной памяти.
- **Double-free:** Повторное освобождение одного блока.
- **Memory corruption:** Запись в защищенные зоны.

**Overhead:** KASAN добавляет ~2-3x к потреблению памяти и ~1.5-2x к времени выполнения. Категорически запрещен на production.

### Архитектура KCSAN

KCSAN использует подход «dynamic race detection»:

1. Устанавливает «watchpoint» на адрес памяти.
2. Мониторит другие потоки на предмет обращений к этому адресу.
3. Если обнаружено параллельное чтение/запись без синхронизации — фиксирует data race.

**Применение:** Выявление гонок в коде драйверов, планировщика и других компонентов ядра.

### Взаимодействие с slab allocator

Для диагностики slab-утечек kmemleak работает в паре со `slabinfo`:

```bash
# Проверка slab-статистики
cat /proc/slabinfo | sort -k 3 -nr | head -10
# → carmy_inode_cache  100000  100000   640   25    8 : tunables    0    0    0 : slabdata  4000  4000    0

# Проверка на утечки через kmemleak
cat /sys/kernel/debug/kmemleak | grep -A 5 "carime_inode_cache"
```

**Дифференциальная диагностика:**
- Если `SUnreclaim` растет, но kmemleak не показывает утечек — проблема в другом аллокаторе (vmalloc, page allocator).
- Если kmemleak показывает утечки, но `SUnreclaim` стабилен — это может быть ложное срабатывание.

## Практические сценарии

### Предварительные требования

**Аппаратные и программные требования:**
- ОС: Linux с ядром 2.6.30+ (kmemleak), 3.14+ (KASAN), 5.8+ (KCSAN).
- Ядро должно быть собрано с соответствующими опциями:
  - `CONFIG_DEBUG_KMEMLEAK=y` (kmemleak)
  - `CONFIG_KASAN=y` (KASAN)
  - `CONFIG_KCSAN=y` (KCSAN)
- Права: `root` (доступ к debugfs).
- Пакеты: `kernel-debuginfo` (для `crash` и符号解析а).

**Проверка поддержки:**
```bash
# Проверка kmemleak
[ -f /sys/kernel/debug/kmemleak ] && echo "kmemleak available" || echo "kmemleak not available"

# Проверка KASAN
grep -i kasan /boot/config-$(uname -r)
# → CONFIG_KASAN=y (если включен)

# Проверка KCSAN
grep -i kcsan /boot/config-$(uname -r)
# → CONFIG_KCSAN=y (если включен)
```

### 1. Базовый сбор kmemleak

```bash
# 1. Убедитесь, что kmemleak включен
sudo mount -t debugfs none /sys/kernel/debug 2>/dev/null
cat /sys/kernel/debug/kmemleak | head -20

# 2. Если kmemleak пуст, запустите сканирование вручную
sudo sh -c 'echo scan > /sys/kernel/debug/kmemleak'

# 3. Просмотр результатов
sudo cat /sys/kernel/debug/kmemleak
# → unreferenced object 0xffff888012345678 (size 256 bytes):
# →   comm "kworker/0:1", pid 123, jiffies 4294967295
# →   backtrace:
# →     [<0000000000000000>] kmem_cache_alloc+0x13a/0x290
# →     [<0000000000000000>] alloc_vmap_area+0x162/0x3a0
```

**Интерпретация вывода:**
- `unreferenced object` — объект без активных ссылок (потенциальная утечка).
- `comm` и `pid` — процесс, выполнивший аллокацию.
- `backtrace` — стек вызовов на момент выделения.

### 2. Настройка периода сканирования

```bash
# Текущий интервал (в секундах)
cat /sys/kernel/debug/kmemleak interval
# → 60

# Установка интервала 10 секунд (для отладки)
sudo sh -c 'echo 10 > /sys/kernel/debug/kmemleak interval'

# Полное сканирование с отключением интервала
sudo sh -c 'echo scan=off > /sys/kernel/debug/kmemleak'
```

### 3. Очистка предыдущих результатов

```bash
# Очистка всех записей kmemleak
sudo sh -c 'echo clear > /sys/kernel/debug/kmemleak'

# Проверка
cat /sys/kernel/debug/kmemleak | wc -l
# → 0
```

### 4. Использование KASAN на тестовой системе

```bash
# 1. Установите ядро с KASAN (обычно из пакетов debug)
# Ubuntu/Debian:
sudo apt install linux-image-generic-hwe-22.04-dbg
# CentOS/RHEL:
sudo debuginfo-install kernel

# 2. Перезагрузитесь с ядром KASAN
# 3. Проверьте dmesg на наличие ошибок
dmesg | grep -i kasan
# → BUG: KASAN: slab-out-of-bounds in ...
```

**Пример лога KASAN:**
```text
[  123.456789] ==================================================================
[  123.456790] BUG: KASAN: slab-out-of-bounds in kmalloc+0x123/0x456
[  123.456791] Write of size 4 at addr ffff888012345678 by task kworker/0:1/1234
[  123.456792]
[  123.456793] CPU: 0 PID: 1234 Comm: kworker/0:1 Not tainted 5.15.0-41-generic #44
[  123.456794] Hardware name: QEMU Standard PC (Q35 + ICH9, 2009), BIOS 1.14.0-1 04/01/2014
[  123.456795] Workqueue: events test_func
[  123.456796] Call Trace:
[  123.456797]  dump_stack+0x9c/0xc3
[  123.456798]  print_address_description+0x6d/0x3c0
[  123.456799]  kasan_report+0x1a4/0x1e0
[  123.456800]  __asan_store4+0x7d/0xa0
[  123.456801]  kmalloc+0x123/0x456
```

### 5. Диагностика slab leak через kmemleak и slabtop

```bash
# Шаг 1: Поиск аномального slab через slabtop
sudo slabtop -o | head -20
# →  OBJS ACTIVE  USE OBJ SIZE  SLABS OBJ/SLAB CACHE SIZE
# → 100000 100000 100%  0.50K   5000        20     50000K

# Шаг 2: Поиск объектов в kmemleak для этого slab
sudo cat /sys/kernel/debug/kmemleak | grep -B 5 -A 10 "carime_inode_cache"
# → unreferenced object 0xffff888012345678 (size 512 bytes):
# →   comm "myservice", pid 5678, jiffies 4294967295
# →   backtrace:
# →     [<0000000000000000>] kmem_cache_alloc+0x13a/0x290

# Шаг 3: Проверка rusage
cat /proc/5678/status | grep -i vm
# → VmRSS:    123456 kB  (если растет — подозрение на утечку)
```

### 6. Отладка memory corruption через KASAN

```bash
# 1. Включите динамический debug для модуля (если ошибка в модуле)
echo 'module mymodule +p' | sudo tee /sys/kernel/debug/dynamic_debug/control

# 2. Запустите тест, вызывающий ошибку
sudo ./run_test.sh

# 3. Проверьте dmesg на KASAN-отчет
dmesg | grep -A 30 "BUG: KASAN"

# 4. Извлеките backtrace для анализа
dmesg | grep -A 30 "BUG: KASAN" | grep "Call Trace" -A 15
```

### 7. Использование KCSAN для обнаружения гонок

```bash
# 1. Убедитесь, что KCSAN включен в ядре
grep CONFIG_KCSAN /boot/config-$(uname -r)

# 2. Запустите нагрузку, вызывающую параллельный доступ
sudo ./concurrent_test.sh

# 3. Проверьте dmesg на KCSAN-сообщения
dmesg | grep -i "kcsan"
# → BUG: KCSAN: data-race in test_func+0x123/0x456 / test_func2+0x789/0xabc
```

### 8. Анализ vmcore через crash (для post-mortem)

```bash
# 1. Установите crash и kernel-debuginfo
sudo dnf install crash kernel-debuginfo   # RHEL/CentOS
sudo apt install crash linux-image-*-dbgsym  # Ubuntu

# 2. Анализ vmcore (если система упала из-за memory corruption)
crash /usr/lib/debug/lib/modules/$(uname -r)/vmlinux /var/crash/*/vmcore

# 3. Внутри crash:查看 kmemleak-подобной информации
crash> kmem -o
crash> kmem -i
crash> sys | grep -i kasan
```

### 9. Мониторинг kmemleak через cron

```bash
#!/bin/bash
# /usr/local/bin/kmemleak_monitor.sh

LOG="/var/log/kmemleak_$(date +%Y%m%d_%H%M%S).log"

# Сканирование
sudo sh -c 'echo scan > /sys/kernel/debug/kmemleak'

# Сбор отчета
LEAKS=$(sudo cat /sys/kernel/debug/kmemleak | grep -c "unreferenced")

if [ "$LEAKS" -gt 0 ]; then
    sudo cat /sys/kernel/debug/kmemleak > "$LOG"
    echo "ALERT: $LEAKS potential kernel memory leaks detected" | \
        logger -t kmemleak_monitor
fi
```

## Типичные ошибки и их решение

### 1. kmemleak не найден

**Симптом:** `cat /sys/kernel/debug/kmemleak` → No such file or directory.

**Причина:** kmemleak не включен при сборке ядра или debugfs не смонтирован.

**Решение:**
```bash
# Проверка debugfs
mount | grep debugfs
# → none on /sys/kernel/debug type debugfs (rw,relatime)

# Если не смонтирован
sudo mount -t debugfs none /sys/kernel/debug

# Проверка конфигурации ядра
grep CONFIG_DEBUG_KMEMLEAK /boot/config-$(uname -r)
# → CONFIG_DEBUG_KMEMLEAK=y (если включен)
```

### 2. Ложные срабатывания kmemleak

**Симптом:** kmemleak показывает «утечки», которые не являются реальными.

**Причина:** Нестандартные mechanisms хранения ссылок (битовые операции, нестандартные аллокаторы).

**Решение:**
```bash
# Добавление Known-good зон в исключения
sudo sh -c 'echo 0xffffffffXXXXXXXX > /sys/kernel/debug/kmemleak ignore'

# Или полная очистка и повторное сканирование
sudo sh -c 'echo clear > /sys/kernel/debug/kmemleak'
sudo sh -c 'echo scan > /sys/kernel/debug/kmemleak'
```

### 3. KASAN: ложные срабатывания из-за компилятора

**Симптом:** KASAN сообщает об ошибке, которая не воспроизводится.

**Причина:** Агрессивная оптимизация компилятора (O2/O3) может нарушать redzones.

**Решение:**
```bash
# Используйте -O1 для модулей, где KASAN ругается
# В Makefile модуля:
EXTRA_CFLAGS += -O1 -g -fsanitize=kernel-address
```

### 4. KASAN: высокий overhead на production

**Симптом:** Система с KASAN работает медленно (>2x slowdown).

**Причина:** KASAN добавляет проверку на каждый доступ к памяти.

**Решение:** Не используйте KASAN на production. Только для тестирования и staging.

### 5. kmemleak: memory overhead

**Симптом:** После включения kmemleak потребление RAM ядра выросло на 5-10%.

**Причина:** kmemleak хранит метаданные о каждом выделенном объекте.

**Решение:**
```bash
# Временное отключение kmemleak (без перезагрузки)
sudo sh -c 'echo 0 > /sys/kernel/debug/kmemleak interval'

# Полное отключение (требует rebuild ядра)
# В конфигурации ядра установить CONFIG_DEBUG_KMEMLEAK=n
```

## Best Practices

1. **Только для отладки.** kmemleak, KASAN, KCSAN — это инструменты разработки/отладки. Не используйте их на production без крайней необходимости.

2. **Используйте ядро debuginfo.** Для корректного символического разрешения backtrace необходим `kernel-debuginfo` или `vmlinux` с символами.

3. **Комбинируйте со slabtop.** kmemleak показывает «что утекает», slabtop — «сколько» и «какой slab».

4. **Для production используйте kmemleak в фоне.** Установите длинный интервал (300-600 секунд) для минимизации overhead.

5. **Проверяйте false positives.** Всегда проверяйте kmemleak-отчеты вручную. Многие «утечки» оказываются ложными.

6. **Для userspace утечек используйте memleak BCC.** kmemleak работает только для ядра. Для пользовательских процессов используйте `memleak` из BCC или `valgrind`.

7. **Храните vmcore и vmlinux.** Для post-mortem анализа необходимы `vmcore` (от `kdump`) и `vmlinux` (или `kernel-debuginfo`).

8. **Используйте KASAN на staging.** Перед обновлением ядра в production протестируйте модули с KASAN на staging-системе.

## Дополнительная информация

### Сравнение инструментов

| Инструмент | Тип проверки | Overhead | Где использовать | Ядро |
| :--- | :--- | :--- | :--- | :--- |
| **kmemleak** | Утечки памяти (kernel) | 5-10% | Development, staging | 2.6.30+ |
| **KASAN** | Buffer overflow, use-after-free | 1.5-2x slowdown, 2-3x RAM | Testing, staging | 3.14+ |
| **KCSAN** | Data races | 2-5x slowdown | Development | 5.8+ |
| **KMSAN** | Uninitialized memory | ~3x slowdown | Testing | 5.17+ |
| **slabtop** | Slab utilization | Минимальный | Production | Все |
| **memleak (BCC)** | Userspace leaks | 5-10% | Production (briefly) | 4.1+ |

### Связанные темы

- [Кэширование и освобождение памяти](../../Core/memory/caching_and_reclaiming.md) — как ядро управляет страницами.
- [Slab allocator](../../Core/memory/slab_allocator.md) — SLUB/SLAB, `slabinfo`, shrinkers.
- [Диагностика OOM Killer](../../Core/processes/oom_killer_diagnostics.md) — анализ принудительного завершения процессов.
- [pmap](./pmap.md) — карта памяти процесса (userspace).
- [smem](./smem.md) — точный анализ PSS/USS.

### Литература

- [Kernel Address Sanitizer (KASAN)](https://www.kernel.org/doc/html/latest/dev-tools/kasan.html)
- [kmemleak: Kernel memory leak detector](https://www.kernel.org/doc/html/latest/dev-tools/kmemleak.html)
- [Kernel Concurrency Sanitizer (KCSAN)](https://www.kernel.org/doc/html/latest/dev-tools/kcsan.html)
