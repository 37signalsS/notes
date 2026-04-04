# Debugging процессов: утечки памяти, coredump, зомби

## Definitions

**Debugging процессов** — диагностика и устранение проблем с памятью, аварийными завершениями и зомби-процессами.

---

## Basic Concepts

### Типичные проблемы процессов

- **Утечки памяти** — процесс не освобождает выделенную память, что ведёт к постепенному росту потребления RAM и eventual OOM
- **Coredump** — дамп памяти процесса при аварийном завершении (сигналы `SIGSEGV`, `SIGFPE`, `SIGQUIT`); используется для посмертной отладки — см. [Troubleshooting index](./index.md#дамп-памяти-coredump)
- **Зомби-процессы** — завершённые процессы, не «забранные» родителем через `wait()`; занимают записи в таблице процессов — см. [additional_info](../additional_info.md#чем-опасны-зомби-процессы)

---

## Practical Scenarios

### Диагностика утечек памяти

#### 1. Valgrind

Инструмент для обнаружения утечек памяти:

```bash
valgrind --leak-check=full --show-leak-kinds=all ./your-program
```

#### 2. strace для анализа памяти

Отслеживание системных вызовов `mmap` и `munmap`:

```bash
strace -e trace=mmap,munmap -p <PID>
```

> Подробнее: [Трассировка и отладка](../../../Diagnostics/Troubleshooting/tracing_and_debugging.md)

#### 3. /proc/<PID>/status

```bash
# Проверить потребление памяти процессом
cat /proc/<PID>/status | grep -E 'VmSize|VmRSS|VmSwap'

# Мониторить в реальном времени
watch -n1 'cat /proc/<PID>/status | grep -E "VmSize|VmRSS"'
```

---

### Анализ сбоев: Coredump

#### 1. Разрешить создание coredump

```bash
# Разрешить создание coredump неограниченного размера
ulimit -c unlimited

# Проверить текущий лимит
ulimit -c
```

#### 2. Настроить шаблон имени файла

```bash
# Посмотреть текущий шаблон
cat /proc/sys/kernel/core_pattern

# Установить свой шаблон (требует root)
echo '/var/cores/core.%e.%p.%t' > /proc/sys/kernel/core_pattern
```

#### 3. systemd-coredump

В современных системах с `systemd` процесс создания и управления дампами централизован.

**Конфигурация:** `/etc/systemd/coredump.conf`

**Утилита `coredumpctl`:**

```bash
# Показать список всех сохранённых дампов
coredumpctl list

# Показать подробную информацию о последнем сбое
coredumpctl info

# Извлечь дамп в файл для анализа в gdb
coredumpctl dump <PID> -o my_coredump

# Запустить gdb с последним дампом
coredumpctl debug
```

#### 4. Анализ в gdb

```bash
gdb /path/to/binary my_coredump

# Внутри gdb:
(gdb) bt          # Получить backtrace
(gdb) info locals # Показать локальные переменные
(gdb) print var   # Показать значение переменной
```

---

### Зомби-процессы

#### Диагностика

```bash
# Найти все зомби-процессы
ps aux | grep ' Z '

# Посчитать количество зомби
ps aux | awk '$8 ~ /Z/ {print}' | wc -l

# Узнать родителя зомби-процесса
ps -eo pid,ppid,stat,cmd | grep ' Z '
```

> Подробно о рисках зомби-процессов: [additional_info](../additional_info.md#чем-опасны-зомби-процессы)

#### Устранение

1. **Отправить SIGCHLD родителю:**

    ```bash
    # Найти PPID зомби
    ps -o ppid= -p <ZOMBIE_PID>

    # Отправить сигнал родителю
    kill -CHLD <PPID>
    ```

2. **Если родитель не реагирует — завершить его:**

    ```bash
    kill -TERM <PPID>
    # Или, если не помогает
    kill -KILL <PPID>
    ```

3. **Если зомби породил systemd (PID 1):**

    Зомби будут очищены автоматически при следующем вызове `wait()` со стороны systemd.

---

## Additional Information

- Трассировка системных вызовов — [`strace`](../../../Diagnostics/Troubleshooting/tracing_and_debugging.md)
- Обзор наблюдаемости системы — [Observability Overview](../../../../Concepts/Observability_and_Monitoring/observability_definitions.md)
- Сигналы и их обработка — [`signals`](../signals.md)
- Мониторинг процессов — [`practical_scenarios`](../practical_scenarios.md)
