# Использование dmesg: просмотр, фильтрация, OOM Killer

## Определения

**Использование dmesg** — практические сценарии просмотра, фильтрации и управления сообщениями ядра.

> **Навигация:** [Главная dmesg](./index.md) | [Troubleshooting](./troubleshooting.md)

---

## Practical Scenarios

### Базовый просмотр логов

```bash
# Вывод с постраничной навигацией
dmesg | less

# Вывод с читаемым форматом времени и раскрашиванием
dmesg -T -H
```

---

### Мониторинг в реальном времени

Эта команда работает аналогично `tail -f`, позволяя отслеживать новые сообщения ядра в реальном времени.

```bash
dmesg --follow # или dmesg -w
```

---

### Фильтрация вывода

- **По содержимому (аналог `grep`):**

    ```bash
    # Поиск сообщений, связанных с USB
    dmesg | grep -i usb
    ```

- **По уровню важности:**

    ```bash
    # Показать только ошибки и критические сообщения
    dmesg --level=err,crit
    ```

    _Доступные уровни: `emerg`, `alert`, `crit`, `err`, `warn`, `notice`, `info`, `debug`._

- **По источнику (подсистеме):**

    ```bash
    # Показать сообщения, относящиеся только к процессам аутентификации
    dmesg --facility=auth
    ```

    _Основные источники: `kern`, `user`, `mail`, `daemon`, `auth`, `syslog`, `lpr`, `news`._

- **Комбинация флагов для удобного анализа:**

    ```bash
    # Человекочитаемый вывод (-H), отображение времени (-T) и источника/уровня (-x)
    dmesg -HTx | less
    ```

---

### Управление буфером

```bash
# Очистить кольцевой буфер (требует прав root)
# Полезно перед отладкой для изоляции новых сообщений.
sudo dmesg -C

# Посмотреть текущий размер буфера
dmesg --buffer-size
```

---

### Диагностика OOM Killer

**OOM Killer (Out Of Memory Killer)** — механизм ядра, который принудительно завершает процессы при нехватке оперативной памяти. Сообщения об этом записываются в кольцевой буфер.

```bash
# Поиск сообщений об OOM Killer
dmesg -T | grep -i "oom\|killed process"

# Поиск процессов, убитых из-за нехватки памяти
dmesg -T | grep -i "out of memory"

# Детальная информация об OOM-событии
dmesg -T | grep -A 20 "Out of memory"
```

**Типичный вывод OOM Killer:**

```text
[12345.678901] Out of memory: Killed process 1234 (java) total-vm:8048576kB, anon-rss:7340032kB, file-rss:0kB
[12345.678902] oom_reaper: reaped process 1234 (java), now anon-rss:0kB, file-rss:0kB
```

**Поля в сообщении:**

- `total-vm`: Общий объём виртуальной памяти процесса
- `anon-rss`: Объём анонимной памяти (heap, стек)
- `file-rss`: Объём памяти, отображённой из файлов (mapped files)

**Что делать при OOM:**

1. **Идентифицировать процесс:** По имени и PID в сообщении
2. **Проверить лимиты памяти:** [`ulimit -a`](../../../Core/processes/limits.md), cgroups, Docker/Kubernetes limits
3. **Анализ потребления:** Использовать [`htop`](../../Processes/htop.md), [`ps`](../../Processes/ps.md), [`smem`](../../Memory/smem.md)
4. **Настроить swap:** Временно увеличить swap-пространство или добавить [`zswap`](../../../Core/memory/swap_management.md)
5. **Оптимизировать приложение:** Уменьшить потребление памяти (heap size, кэши)

> **См. также:** [OOM Killer в Kubernetes](../../../Kubernetes/Troubleshooting/Common_Errors/oomkilled_pods.md), [Управление памятью процессов](../../../Core/processes/limits.md)

---

## Additional Information

### Связанные темы

- **[journalctl](../../journalctl.md)** — просмотр системных логов
- **[htop](../../Processes/htop.md)** — мониторинг процессов
- **[OOM Killer в Kubernetes](../../../../Kubernetes/Troubleshooting/Common_Errors/oomkilled_pods.md)** — диагностика в Kubernetes
