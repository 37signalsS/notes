# Отладка через Coredump в Linux

## Definitions

**Coredump (дамп памяти)** — снимок адресного пространства процесса в момент аварии или по запросу. Содержит состояние регистров, стека вызовов, кучи и глобальных переменных. Используется для «посмертного» (post-mortem) анализа причин сбоя.

**gcore** — утилита (часть GDB), генерирующая дамп работающего процесса без его принудительного завершения.

**core_pattern** — параметр ядра (`/proc/sys/kernel/core_pattern`), определяющий именование и способ обработки дампов (запись в файл или передача обработчику через pipe).

**ELF Core Format** — стандартный формат файла дампа памяти (ELF, Executable and Linkable Format). Содержит заголовок ELF, сегмент `PT_NOTE` с метаданными (регистры, сигнал, PID, аргументы командной строки) и сегменты `PT_LOAD` с копиями страниц памяти процесса.

**Apport** — система автоматического сбора дампов и отчётов об ошибках в дистрибутивах Debian/Ubuntu. Аналог `systemd-coredump`, использует pipe-обработчик для сохранения дампов в `/var/crash/`.

**dumpable** — флаг процесса (`PR_SET_DUMPABLE`), определяющий, разрешено ли ядру создавать coredump для данного процесса. По умолчанию `1` (разрешено); сбрасывается в `0` после `setuid()`/`setgid()` или при включённом `fs.suid_dumpable=0`.

**ptrace_scope** — параметр безопасности Yama (`kernel.yama.ptrace_scope`), ограничивающий возможность `ptrace`-аттача к процессам. Значение `1` (по умолчанию в Ubuntu) разрешает аттач только к потомкам; `0` — разрешает любые аттачи (требует `CAP_SYS_PTRACE`).

## Basic Concepts

### Снятие дампа без остановки процесса

В production-средах использование `gdb attach` приводит к остановке процесса (SIGSTOP) на все время работы отладчика, что может вызвать срабатывание health-checks или таймаутов. Снятие coredump позволяет минимизировать время простоя (пауза только на время записи памяти).

| Метод | Механизм | Особенности |
| :--- | :--- | :--- |
| **`gcore`** | Ptrace-аттач | Стандартный инструмент. Пауза пропорциональна объему RAM. |
| **`gdb -batch`** | Автоматизация GDB | Используется при отсутствии `gcore` в системе. |
| **`/proc/<PID>/mem`** | Прямое чтение | Самый быстрый, но требует сохранения заголовков ELF (инструменты типа `elf-coredump-utils`). |

### Механизм генерации ядром (Core Dump Generation Flow)

При получении сигнала с действием `Core` (`SIGSEGV`, `SIGABRT`, `SIGBUS`, `SIGFPE`, `SIGILL`, `SIGQUIT`) ядро выполняет последовательность:

1. **Проверка лимитов:** Проверяется `RLIMIT_CORE` (`ulimit -c`). Если `0` — дамп не создаётся.
2. **Проверка dumpable:** Проверяется флаг `dumpable` процесса. Если `0` (например, после `setuid`) и `fs.suid_dumpable=0` — дамп запрещён.
3. **Формирование ELF:** Ядро создаёт ELF-файл с:
   - Заголовком ELF (ident, type=ET_CORE)
   - Сегментом `PT_NOTE` с `prpsinfo` (имя процесса, аргументы), `prstatus` (регистры, сигнал), `fpregset` (FPU-регистры), `siginfo` (причина сигнала)
   - Сегментами `PT_LOAD` с копиями доступных страниц памяти (согласно `coredump_filter`)
4. **Запись или pipe:** Если `core_pattern` начинается с `|` — дамп передаётся обработчику (например, `systemd-coredump` или `apport`). Иначе записывается в файл по шаблону.

### Взаимодействие systemd-coredump и core_pattern

В современных дистрибутивах `core_pattern` часто указывает на `systemd-coredump`:

```bash
cat /proc/sys/kernel/core_pattern
# → |/usr/lib/systemd/systemd-coredump %p %u %g %s %t %e
```

В этом случае:
1. Ядро передаёт дамп через pipe в `systemd-coredump`
2. Демон сжимает дамп (если `Compress=yes`) и сохраняет в `/var/lib/systemd/coredump/`
3. Метаданные (включая базовый backtrace) записываются в journald
4. Управление размером: `ProcessSizeMax=` и `ExternalSizeMax=` в `/etc/systemd/coredump.conf`

**Важно:** При использовании pipe-обработчика настройки `ulimit -c` должны быть `unlimited`, иначе ядро обрежет дамп до `RLIMIT_CORE` байт перед передачей в pipe.

### Apport (Ubuntu/Debian)

В Ubuntu/Debian используется `apport`:

```bash
# Проверка статуса
systemctl status apport

# Включение
sudo systemctl enable --now apport

# Дампы сохраняются в /var/crash/
ls -la /var/crash/
# → myapp.1000.1234567890.crash
```

`apport` создаёт два файла:
- `.crash` — JSON-отчёт с backtrace, путями к бинарнику и debuginfo
- `.upload` — если включена отправка в репозитории ошибок

### Фильтрация содержимого (core_filter)

Параметр `/proc/<PID>/coredump_filter` (битовая маска) определяет, какие типы сегментов памяти попадут в дамп. Это критично для уменьшения размера файла.

| Бит | Описание сегмента | По умолчанию |
| :--- | :--- | :--- |
| 0 | Анонимная приватная память (Anonymous private memory) | Да |
| 1 | Анонимная общая память (Anonymous shared memory) | Да |
| 2 | Отображаемая приватная память (File-backed private memory) | Нет |
| 3 | Отображаемая общая память (File-backed shared memory) | Нет |
| 4 | ELF-заголовки | Да |

### Лимиты и ограничения

| Ограничение | Параметр | Значение по умолчанию | Влияние |
| :--- | :--- | :--- | :--- |
| Максимальный размер | `RLIMIT_CORE` | `0` (отключено) | Полный отказ в создании |
| Размер для SUID | `fs.suid_dumpable` | `0` | Запрет дампов SUID-процессов |
| Путь сохранения | `core_pattern` | `core` | pipe или файл |
| Фильтрация сегментов | `coredump_filter` | `0x23` | Какие области памяти попадут в дамп |
| Включение PID в имени | `core_uses_pid` | `0` | `core` → `core.<PID>` |

### Обнаружение проблем с coredump на уровне ядра

Если дамп не создаётся, проверьте:

```bash
# 1. Проверка dmesg на segfault
dmesg | grep -i "segfault\|core\|killed"
# → [12345.678] myapp[1234]: segfault at 0000000000000010 ip 0000000000400526 sp 00000000ff...

# 2. Проверка прав на директорию сброса
namei -l /var/crash/
# → drwxrwxrwt root root /var/   (sticky bit + world-writable)

# 3. Проверка места на диске
df -h /var/crash

# 4. Проверка RLIMIT_CORE процесса
cat /proc/<PID>/limits | grep "core file size"
# → Max core file size        unlimited            unlimited            bytes
```

## Practical Scenarios

### Сценарий 1: Генерация дампа «живого» процесса

**Использование gcore (Рекомендуемый):**
```bash
# Генерация дампа. Процесс будет «заморожен» на время записи.
sudo gcore -o /tmp/app_snapshot <PID>
# → Saved corefile /tmp/app_snapshot.<PID>
```

**Использование GDB (Пакетный режим):**
```bash
sudo gdb -p <PID> -batch -ex "gcore /tmp/app_snapshot.core" -ex detach
# → (Вывод GDB с подтверждением записи)
```

### Сценарий 2: Глубокий анализ в GDB

Для анализа необходим оригинальный бинарный файл и, желательно, отладочные символы (`debug symbols`).

```bash
gdb /usr/bin/myapp /tmp/app_snapshot.core
```

**Основные команды диагностики:**

| Команда | Назначение |
| :--- | :--- |
| `thread apply all bt` | Показать стек вызовов всех потоков (самая важная команда). |
| `thread apply all bt full` | Стек + локальные переменные каждого кадра. |
| `info registers` | Состояние регистров процессора. |
| `info proc mappings` | Карта памяти процесса (помогает найти повреждения кучи). |
| `list *0x4005f6` | Сопоставить адрес инструкции с исходным кодом. |
| `print my_var` | Вывести значение переменной. |
| `x/16gx $rsp` | Дамп 16 строк по 8 байт со стека. |
| `p/x $rsp` | Адрес стека в hex. |
| `frame 3` | Перейти к кадру 3 в стеке. |
| `up` / `down` | Навигация по стеку. |
| `info args` | Аргументы текущей функции. |
| `info locals` | Локальные переменные текущего кадра. |

### Сценарий 3: Настройка системы для сбора дампов

**1. Настройка лимитов (ulimit):**
По умолчанию лимит на размер core-файла равен 0.
```bash
# Для текущей сессии
ulimit -c unlimited

# Для сервиса systemd (в секции [Service] юнита)
LimitCORE=infinity
```

**2. Шаблон имени (core_pattern):**
```bash
# Настройка пути и метаданных
# %h — hostname, %p — PID, %e — имя бинарника, %t — timestamp
echo "/var/crash/core.%h.%e.%p.%t" | sudo tee /proc/sys/kernel/core_pattern
```

**3. Сжатие «на лету» (Pipe-обработка):**
Если на диске мало места, дамп можно сжимать сразу при записи:
```bash
echo "|/usr/bin/gzip -1 > /var/crash/core.%e.%p.gz" | sudo tee /proc/sys/kernel/core_pattern
```

**4. Дампы для SUID-процессов:**
По умолчанию ядро запрещает дампы для процессов, изменивших привилегии.
```bash
sudo sysctl -w fs.suid_dumpable=1
```

**5. Постоянная настройка через sysctl.d:**
```bash
# /etc/sysctl.d/99-coredump.conf
kernel.core_uses_pid = 1
fs.suid_dumpable = 1

# Применение
sudo sysctl --system
```

### Сценарий 4: Работа с systemd-coredump

В дистрибутивах с systemd (Ubuntu 22.04+, RHEL 8+) дампы собираются автоматически.

**Просмотр и извлечение:**
```bash
# Список всех дампов в системе
coredumpctl list

# Извлечение дампа в файл
coredumpctl dump <PID> --output=/tmp/recovered.core

# Интерактивный вход в GDB
coredumpctl gdb <PID>
```

**Конфигурация (`/etc/systemd/coredump.conf`):**
```ini
[Coredump]
Storage=external
Compress=yes
ProcessSizeMax=2G
ExternalSizeMax=10G
MaxUse=5G
MaxFileSize=500M
```

**Информация о последнем дампе:**
```bash
# Подробная информация
coredumpctl info <PID>

# Только сигнал и время
coredumpctl info <PID> | grep -E "Signal|Timestamp"
```

### Сценарий 5: Coredump в контейнерах (Docker/Kubernetes)

В контейнерах ядро хоста обрабатывает сигналы, но namespace изолирует PID и файловую систему.

**Docker (ручная настройка):**
```bash
# Запуск с unlimited core size
docker run --ulimit core=-1 --rm myapp:latest

# Для изоляции — монтируйте tmpfs для дампов:
docker run --tmpfs /tmp/cores --ulimit core=-1 myapp

# Просмотр дампов внутри контейнера
docker exec <container> ls -la /tmp/cores/
```

**Kubernetes:**
```yaml
# В pod spec для сбора дампов через emptyDir
volumes:
  - name: coredumps
    emptyDir:
      sizeLimit: 2Gi

containers:
  - name: myapp
    image: myapp:latest
    volumeMounts:
      - name: coredumps
        mountPath: /tmp/cores
    resources:
      limits:
        memory: "2Gi"
    securityContext:
      allowPrivilegeEscalation: false
```

**Извлечение дампа из Kubernetes:**
```bash
# Через kubectl debug (ephemeral container с debug-образом)
kubectl debug <pod> -it --image=busybox:1.36 --share-processes -- /bin/sh

# Копирование дампа на локальную машину
kubectl cp <namespace>/<pod>:/tmp/cores/app.core ./app.core
```

**Важно для SRE:**
- В Kubernetes дамп, созданный в контейнере, привязывается к namespace пода. Если под перезапущен (CrashLoopBackOff), предыдущий дамп теряется.
- Для сохранения дампа монтируйте `emptyDir` + sidecar-контейнер, который копирует дампы в PersistentVolume или отправляет в локальное объектное хранилище (MinIO, Ceph RGW).

### Сценарий 6: Диагностика проблем с coredump

| Проблема | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| Нет файла дампа | Процесс падает, но `core` не появился | `RLIMIT_CORE=0` | `ulimit -c unlimited` или `LimitCORE=infinity` |
| `Permission denied` | `coredump` не пишется | Директория не `1777` или `700` | `chmod 1777 /var/crash/` |
| `No space left` | Дамп обрезан или не создан | Диск полон | Использовать pipe с gzip или tmpfs |
| `not a core file` в GDB | Дамп повреждён | Обрезка при записи, неверный бинарник | Проверить `file core.*`, `readelf -h core.*` |
| `ptrace: Operation not permitted` | GDB не аттачится | `ptrace_scope=1` или неправильный UID | `sysctl -w kernel.yama.ptrace_scope=0` |
| Дамп пустой/0 байт | Файл создан, но пуст | SUID-процесс при `fs.suid_dumpable=0` | `sysctl -w fs.suid_dumpable=1` |
| `SIGKILL` вместо core | Процесс убит без дампа | OOM Killer | Проверить `dmesg | grep oom` |

### Сценарий 7: Автоматизация сбора и интеграция с мониторингом

**Скрипт сбора и уведомления:**
```bash
#!/bin/bash
# /usr/local/bin/coredump-collect.sh
CORE_DIR="/var/crash"

# Мониторинг новых дампов (запуск через cron или systemd path)
inotifywait -m -e create --format '%f' "$CORE_DIR" | while read -r filename; do
    if [[ "$filename" == core.* ]]; then
        # Сжатие и проверка
        gzip -9 "$CORE_DIR/$filename"
        # Уведомление (пример для Slack/Telegram webhook)
        curl -X POST -H 'Content-type: application/json' \
            --data "{\"text\":\"Core dump создан: $filename\"}" \
            https://hooks.example.com/notify
    fi
done
```

**Интеграция с Prometheus (node_exporter textfile collector):**
```bash
# textfile collector для метрик
cat > /var/lib/prometheus/node-exporter/coredump.prom <<EOF
# HELP coredump_count Total coredumps generated
# TYPE coredump_count gauge
coredump_count{host="$(hostname)"} $(ls /var/crash/core.* 2>/dev/null | wc -l)
EOF
```

**Автоматическая очистка через systemd-tmpfiles:**
```ini
# /etc/tmpfiles.d/coredump.conf
d /var/crash 1777 root root -
# Автоматическое удаление файлов старше 7 дней
q /var/crash/core.* 7d
```

### Сценарий 8: Анализ без GDB (readelf, eu-stack, pstack)

Для быстрого анализа без интерактивного GDB:

```bash
# Проверка типа файла
file core.1234
# → core.1234: ELF 64-bit LSB core file, x86-64, version 1 (SYSV), SVR4-style

# Список загруженных библиотек
readelf -n core.1234 | grep -A30 "NT_FILE"

# Карта сегментов памяти (PT_LOAD)
readelf -l core.1234 | grep -A2 "LOAD"

# Извлечение информации о сигнале
readelf -n core.1234 | grep -A10 "siginfo"

# Быстрый backtrace через gdb batch mode
gdb -batch -ex "thread apply all bt" -ex "detach" -ex "quit" \
    /usr/bin/myapp core.1234

# eu-stack из elfutils (если установлен)
eu-stack -e /usr/bin/myapp -c core.1234

# pstack для live-процесса
sudo pstack <PID>
```

**Интерпретация backtrace (SRE):**

| Паттерн | Вероятная причина |
| :--- | :--- |
| `0x0` или `0x1` в адресе | Разыменование нулевого/невалидного указателя (SIGSEGV). |
| `__kernel_vsyscall` в начале стека | Падение в системном вызове; проверьте `siginfo`. |
| Несколько `pthread_create` | Проблема в отдельном потоке; используйте `thread apply all bt`. |
| `malloc`/`free` подозрение | Коррупция кучи; ищите несоответствие alloc/free. |
| `??` вместо имён функций | Отсутствуют отладочные символы; установите `debuginfo`. |

### Сценарий 9: SRE Workflow — инцидент с аварийным завершением

**Когда приложение падает в production:**

1. **Сбор контекста (60 секунд):**
   ```bash
   # Когда упало?
   journalctl -u myapp --since "10 min ago"
   # Какие сигналы?
   dmesg | grep -i "segfault\|core dumped\|killed process"
   # Статус systemd-сервиса
   systemctl status myapp -l
   ```

2. **Сохранение дампа (если он ещё существует):**
   ```bash
   # Если systemd-coredump
   MAINPID=$(systemctl show -p MainPID --value myapp)
   coredumpctl dump $MAINPID --output=/tmp/app.core

   # Если pipe в /var/crash
   cp /var/crash/core.* /tmp/
   ```

3. **Анализ (параллельно с восстановлением):**
   ```bash
   # Быстрый backtrace
   gdb -batch -ex "thread apply all bt" -ex "quit" /usr/bin/myapp /tmp/app.core
   # Проверка сигнала
   coredumpctl info $MAINPID | grep "Signal"
   ```

4. **Восстановление сервиса:**
   ```bash
   systemctl restart myapp
   # Документировать инцидент с временем и PID
   ```

5. **Постинцидентный анализ (Postmortem):**
   - Сохранить дамп и бинарник (версия!)
   - Создать RCA-документ
   - Проверить, не повторяется ли падение на staging через нагрузочное тестирование

## Additional Information

### Установка отладочных символов

Если в стеке вызовов вместо имен функций отображается `??`, необходимо установить пакеты `debuginfo` или `dbgsym`.

```bash
# Ubuntu/Debian
sudo apt install myapp-dbgsym

# RHEL/CentOS/Rocky
sudo dnf debuginfo-install myapp
```

**Поиск debuginfo для бинарника:**

```bash
# Определение архитектуры и бинарника
readelf -h /usr/bin/myapp | grep Machine

# Проверка наличия debuginfo
rpm -q --queryformat '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' myapp-debuginfo
```

### Безопасность и комплаенс

Дампы памяти содержат конфиденциальные данные.

1. **Шифрование:** Храните дампы на зашифрованных разделаes (LUKS).
2. **Права доступа:** Убедитесь, что директория сброса имеет права `1777` (sticky bit) или `700` для ограниченного доступа.
3. **Очистка:** Настройте автоматическое удаление старых дампов через `tmpfiles.d` или параметры `systemd-coredump`.
4. **tmpfs для production:** Для минимизации диск I/O используйте дампы в tmpfs (`/dev/shm` или `tmpfs`):
   ```ini
   # /etc/systemd/system/myapp.service.d/coredump.conf
   [Service]
   Environment=COREDUMP_TMPFS=/dev/shm/coredumps
   ExecStartPre=/bin/mkdir -p /dev/shm/coredumps
   LimitCORE=infinity
   ```
5. **Права на debuginfo:** Ограничьте доступ к отладочным символам:
   ```bash
   sudo chmod 750 /usr/lib/debug/
   sudo chown root:adm /usr/lib/debug/
   ```

### Troubleshooting (Типовые ошибки)

**"Core dumped" но файл не создаётся:**
```bash
# Проверка RLIMIT_CORE
cat /proc/<PID>/limits | grep "core file size"
# Проверка sysctl
sysctl kernel.core_uses_pid
# Проверка sticky bit на директории
ls -ld /var/crash/
```

**GDB: "Not a core file":**
```bash
# Проверка ELF magic
xxd core.1234 | head -2
# → 00000000: 7f45 4c46 0101 0100 0000 0000 0000 0000  .ELF............

# Проверка архитектуры
readelf -h core.1234 | grep Machine
# → Machine:                           Advanced Micro Devices X86-64
```

**GDB: "Failed to read" или обрыв:**
```bash
# Проверка размера
ls -la core.1234
# Если размер равен RLIMIT_CORE — дамп обрезан
# Если размер 0 — проблеммы с правами или dumpable=0
```

**coredumpctl не видит дамп:**
```bash
# Проверка journald
journalctl --since "1 hour ago" | grep coredump
# Переиндексация
sudo journalctl --rotate
```

### Retention и Cleanup

**systemd-coredump retention:**

```ini
# /etc/systemd/coredump.conf
[Coredump]
Storage=external
Compress=yes
ProcessSizeMax=2G
ExternalSizeMax=10G
MaxUse=5G
MaxFileSize=500M
```

**Очистка старых дампов:**
```bash
# Удаление дампов старше 14 дней (systemd-coredump)
sudo coredumpctl vacuum 14d

# Или через find
find /var/crash -name "core.*" -mtime +7 -delete
find /var/lib/systemd/coredump -type f -mtime +7 -delete
```

### Интеграция с journald

```bash
# Поиск сообщений о segfault
journalctl -g "segfault|core dumped|SIGSEGV" --since yesterday

# Фильтр по сервису
journalctl -u myapp -g "segfault"

# Экспорт в файл для RCA
journalctl -u myapp --since "2024-01-01" --until "2024-01-02" > myapp_crash.log
```

### Инструменты и матрица

| Задача | Инструмент | Уровень | Примечание |
| :--- | :--- | :--- | :--- |
| Быстрый дамп live-процесса | `gcore` | User Space | Ptrace, требует того же UID или root |
| Пакетный анализ стека | `gdb -batch` | User Space | Без интерактивного режима |
| Просмотр дампов systemd | `coredumpctl` | User Space | Требует systemd-coredump |
| Быстрый стек live | `pstack` | User Space | Обёртка над gdb |
| ELF-анализ без GDB | `readelf`, `eu-stack` | User Space | Из пакетов elfutils |
| Анализ vmcore (ядро) | `crash` | Kernel Space | Требует `kernel-debuginfo` |
| Поиск segfault в логах | `journalctl -g` | User Space | Фильтр по regex |

### Связанные темы

- [Трассировка и отладка в Linux](./tracing_and_debugging.md)
- [Поиск потока, потребляющего CPU](../Processes/thread_cpu_troubleshooting.md)
- [Управление журналами systemd](../../SystemAdministration/Logging/journald.md)
- [Сигналы процессов в Linux](../../Core/processes/signals.md)
- [Анализ ошибок и сбоев](../../SystemAdministration/Logging/error_and_crash_analysis.md)
- [Ограничения ресурсов (rlimits)](../../Core/processes/resource_limits_concepts.md)
- [Интерфейсы ядра (prctl, ptrace)](../../Core/kernel/kernel_interfaces.md)
