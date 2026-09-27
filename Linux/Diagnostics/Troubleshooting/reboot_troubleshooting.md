# Диагностика причин перезагрузки Linux

## Definitions

**Диагностика перезагрузки** — систематический анализ системных логов, дампов памяти и аппаратных журналов для выявления триггера перезапуска ОС.

**Штатная перезагрузка (Initiated Reboot)** — перезапуск, вызванный преднамеренным вызовом системных функций (`reboot(2)`, `shutdown`) пользователем или процессом. Сопровождается корректным завершением (SIGTERM/SIGKILL) сервисов.

**Аварийная перезагрузка (System Crash/Reset)** — мгновенный перезапуск без выполнения процедур завершения. Происходит при критических ошибках ядра (Panic), оборудования (MCE) или срабатывании аппаратных защит (Watchdog, Power Loss).

**OOM-induced Reboot** — перезагрузка, вызванная активацией механизма `panic_on_oom=1`. При исчерпании всей физической памяти ядро вызывает панику вместо последовательного убийства процессов.

**Watchdog-triggered Reboot** — принудительная перезагрузка аппаратным или программным watchdog-таймером. Происходит, когда ядро или прикладной процесс не сбрасывает таймер в течение порогового значения. В аппаратном варианте запись фиксируется в IPMI SEL, в программном — в `dmesg`.

**Hard Lockup** — состояние, при котором CPU полностью перестает реагировать на любые события, включая прерывания. Вызывается бесконечным циклом в критической секции с программно отключенными прерываниями. При `kernel.hardlockup_panic=1` приводит к Kernel Panic.

**Tainted Kernel** — состояние загрязнения ядра, при котором оно помечается флагами в `/proc/sys/kernel/tainted`. Возникает при загрузке вне-деревянных модулей, проприетарных драйверов, аппаратных ошибок (MCE) или срабатывании `WARN_ON()`. После Oops или Panic флаги помогают определить причину.

**Magic SysRq Key** — механизм ядра для выполнения низкоуровневых команд напрямую, в обход зависших абстракций ОС (systemd, драйверы дисков).

**kdump** — механизм сохранения снимка оперативной памяти (`vmcore`) в момент Kernel Panic для последующего «посмертного» анализа.

**kexec** — механизм ядра, позволяющий загрузить и запустить новое ядро Linux напрямую из текущего, минуя этапы инициализации оборудования (BIOS/UEFI) и POST. Используется в `kdump` для быстрого переключения на аварийное ядро.

**pstore** — механизм сохранения логов ядра в энергонезависимую память (NVRAM, EFI или зарезервированная RAM — `ramoops`), которая доступна после перезагрузки.

**ramoops** — бэкенд pstore, использующий зарезервированную область оперативной памяти для хранения `dmesg` ring buffer после Kernel Panic или аппаратного сброса.

**erst** — бэкенд pstore (Error Record Serialization Table), использующий аппаратную NVRAM на серверном железе для сохранения аппаратных ошибок (MCE).

## Basic Concepts

### Типы и признаки перезагрузок

| Тип | Инициатор | Следы в логах | Примеры |
| :--- | :--- | :--- | :--- |
| **User/Process** | `root`, `apt`, `ansible` | Полные логи завершения | `reboot`, `shutdown -r`, обновление ядра |
| **Kernel Panic** | Баги драйверов, ФС | Сообщения в `dmesg`, `vmcore` | Null pointer dereference, Soft lockup |
| **OOM-induced** | Нехватка памяти | `Out of memory` (при `panic_on_oom=1`) | Утечка RAM в БД или Java-приложении |
| **Watchdog** | Зависание CPU/Ядра | Пустота в логах ОС, записи в IPMI SEL | Глубокое аппаратное зависание |
| **Hardware Fail** | БП, RAM, MCE | Обрыв логов, сообщения `MCE` | Перегрев, битая планка памяти |

### Почему `reboot` может не работать

В критических ситуациях (сбой RAID, IO-wait 100%) стандартные команды (`systemctl reboot`) виснут, так как:
1.  **Отсутствие доступа к бинарникам:** `/usr/bin/reboot` находится на недоступном/зависшем диске.
2.  **Блокировка на `sync`:** Процесс перезагрузки пытается сбросить кэши на диск (вызов `sync`), который перешел в состояние `D` (uninterruptible sleep).
3.  **Зависание PID 1:** Если `systemd` заблокирован, он не может обработать запрос на смену таргета.

В таких случаях необходимо использовать **Magic SysRq**.

### Матрица прав доступа к инструментам диагностики

При аварийной перезагрузке важна скорость реакции. Некоторые инструменты требуют `root`, другие работают из-под обычного пользователя, а третьи доступны только через BMC/IPMI.

| Инструмент | Минимальные права | Примечание |
| :--- | :--- | :--- |
| `journalctl -b -1` | `systemd-journal` group или `root` | Для просмотра логов предыдущей сессии. |
| `last reboot` | Чтение `/var/log/wtmp` | Обычно доступно всем. |
| `cat /proc/sys/kernel/tainted` | Чтение `/proc` | Доступно всем. |
| `cat /sys/fs/pstore/*` | `root` или capabilities | pstore обычно доступен только root. |
| `ipmitool sel list` | `root` или IPMI пользователь | Требует загрузки модуля `ipmi_devintf`. |
| `kdumpctl` | `root` | Полное управление kdump. |
| `crash` | `root` | Анализ vmcore. |
| `echo c > /proc/sysrq-trigger` | `root` (обычно) | При включенном `kernel.sysrq`. |

### Параметры загрузки ядра для диагностики

Правильная конфигурация GRUB упрощает анализ причин перезагрузки. Добавляйте параметры в `GRUB_CMDLINE_LINUX_DEFAULT` в `/etc/default/grub`:

```bash
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash loglevel=7 crashkernel=256M"
```

| Параметр | Описание |
| :--- | :--- |
| `loglevel=7` | Максимальный уровень логирования ядра. Сохраняет больше информации в `dmesg`. |
| `crashkernel=256M` | Резервирует 256 МБ RAM для `kdump`. На системах с 4–8 ГБ RAM достаточно 256 МБ. |
| `earlyprintk=ttyS0,115200n8` | Вывод сообщений ядра на раннем этапе (до инициализации консоли). Критично для диагностики ранних паник. |
| `panic=10` | Автоматическая перезагрузка через 10 секунд после Kernel Panic (если kdump не сработал). |
| `mce=0` или `mce=1` | Управление обработкой Machine Check Exceptions. `mce=1` — включить (по умолчанию), `mce=0` — отключить (не рекомендуется). |
| `initcall_debug` | Вывод времени выполнения каждого initcall (полезно для диагностики медленной загрузки). |
| `debug` | Включает расширенную отладочную информацию. |
| `no_console_suspend` | Не приостанавливать консоль при переходе в suspend (если используется). |
| `rd.systemd.show_status=1` | Показывает статус загрузки юнитов systemd в initramfs. |

После изменения `/etc/default/grub` выполните:
```bash
sudo update-grub
```

## Practical Scenarios

### Шаг 1: Определение времени и истории

```bash
# Время текущей загрузки
who -b
# → system boot  2026-08-09 18:00

# История последних перезагрузок из /var/log/wtmp
last reboot | head -n 3
# → reboot   system boot  6.8.0-40-generic Sun Aug  9 18:00   still running
# → reboot   system boot  6.8.0-40-generic Sun Aug  9 12:30 - 17:55  (05:25)

# Детальная история с продолжительностью сессий
last -x | grep -E 'reboot|runlevel' | head -n 20
# → reboot   system boot  6.8.0-40-generic Sun Aug  9 18:00   still running
# → shutdown system down  6.8.0-40-generic Sun Aug  9 17:55 (00:00)
```

---

### Шаг 2: Анализ системных журналов (journald)

Поиск событий непосредственно перед обрывом лога.

```bash
# Список всех загрузок (позволяет выбрать индекс)
journalctl --list-boots

# Логи ПРЕДЫДУЩЕЙ сессии в обратном порядке
journalctl -b -1 -r
# → Aug 09 17:55:00 server systemd[1]: Reached target Shutdown. (Штатно)
# → Aug 09 17:55:01 server systemd[1]: Finished Reboot.
```
**Для старых систем (syslog):**
```bash
grep -iE 'shutdown|reboot|power|panic|mce' /var/log/messages
```

---

### Шаг 3: Аппаратный аудит (IPMI/SEL)

Если в ОС логи обрываются внезапно, причина почти всегда аппаратная.

```bash
# Опрос лога BMC через IPMI
sudo ipmitool sel list | tail -n 5
# → 2026-08-09 | 17:55:05 | Watchdog 2 | Timer expired | Asserted
# → 2026-08-09 | 17:55:10 | Power Supply | Failure detected | Asserted
```
*   `Timer expired` — ядро не смогло сбросить таймер (зависание).
*   `Asserted` — событие произошло, `Deasserted` — проблема устранена.

**Детальный анализ SEL:**
```bash
# Просмотр всех записей System Event Log
sudo ipmitool sel elist

# Очистка SEL (после фиксации проблемы)
sudo ipmitool sel clear

# Проверка состояния датчиков (SDR)
sudo ipmitool sdr list

# Проверка температуры и напряжения
sudo ipmitool sensor reading 0x01 0x02
```

**Интеграция с Prometheus (ipmi_exporter):**
```bash
# В blackbox_exporter или ipmi_exporter:
# ipmitool sensor | grep -E 'Temp|Volt|Fan'
# Автоматизация опроса через cron:
*/5 * * * * /usr/bin/ipmitool sel list > /var/log/ipmi_sel.log 2>&1
```

---

### Шаг 4: Посмертный анализ (kdump / pstore)

**Анализ vmcore (kdump):**
```bash
# Проверка наличия дампа
ls -R /var/crash/
# → /var/crash/202608091756/vmcore

# Запуск анализа (требует vmlinux и crash)
crash /usr/lib/debug/.../vmlinux /var/crash/.../vmcore
```

**Диагностика через pstore (ERST/Ramoops):**
Позволяет читать логи `dmesg` даже если диск не успел записать данные.
```bash
mount -t pstore pstore /sys/fs/pstore
cat /sys/fs/pstore/dmesg-ramoops-0
# → <1>[ 1234.567890] Kernel panic - not syncing: Fatal exception
```

**Анализ доступных бэкендов pstore:**
```bash
# Просмотр всех записей pstore
ls -la /sys/fs/pstore/
# → dmesg-ramoops-0         4096  2026-08-09 17:55:01
# → dmesg-erst-0            4096  2026-08-09 17:55:01
# → mce-0                   4096  2026-08-09 17:55:00

# Проверка модулей pstore
lsmod | grep pstore
# → pstore         16384  0
# → ramoops         24576  0
```

**Анализ MCE через pstore:**
```bash
# Просмотр записей Machine Check Exceptions
cat /sys/fs/pstore/mce-* 2>/dev/null | head -n 50
# → MCE records с аппаратными ошибками CPU/памяти
```

---

### Шаг 5: Аварийная перезагрузка (Magic SysRq — REISUB)

Когда система не реагирует на ввод, используйте низкоуровневую последовательность (Alt + SysRq + [Key]):

1.  **`r`** (Raw) — забрать управление клавиатурой у X-сервера.
2.  **`e`** (Terminate) — послать SIGTERM всем процессам.
3.  **`i`** (Kill) — послать SIGKILL всем процессам.
4.  **`s`** (Sync) — сбросить кэши на диски (критично для целостности).
5.  **`u`** (Unmount) — перемонтировать все ФС в read-only.
6.  **`b`** (Reboot) — немедленная жесткая перезагрузка.

**Триггер через /proc (если есть SSH, но reboot не работает):**
```bash
echo 1 > /proc/sys/kernel/sysrq
for x in r e i s u b; do echo $x > /proc/sysrq-trigger; sleep 1; done
```

**Другие полезные SysRq команды:**
```bash
# Полный дамп всех задач (для анализа зависаний)
echo t > /proc/sysrq-trigger

# Вывод информации о регистрах всех CPU
echo p > /proc/sysrq-trigger

# Отключение аппаратного Watchdog
echo w > /proc/sysrq-trigger
```

---

### Шаг 6: Анализ OOM-induced перезагрузки

Если `vm.panic_on_oom=1`, при исчерпании памяти система перезагружается. Диагностика через журналы предыдущей сессии:

```bash
# Поиск событий OOM в логах предыдущей загрузки
journalctl -b -1 -g "Out of memory" | tail -n 20
# → Aug 09 17:54:01 server kernel: Out of memory: Kill process 1234 (java)

# Проверка vmcore (если kdump настроен)
ls -R /var/crash/

# Проверка pstore
cat /sys/fs/pstore/dmesg-ramoops-0 | grep -i "out of memory"
```

**Пост-фактум анализ:**
```bash
# Статистика cgroup-ов после перезагрузки
journalctl -b -1 -g "oom\|memory" | tail -n 30

# Если используется systemd-coredump
coredumpctl list | grep -i oom

# Проверка swap (возможно, был исчерпан)
swapon --show
free -h
```

**Профилактика:**
```bash
# Отключение auto-panic на OOM (если не требуется)
sysctl -w vm.panic_on_oom=0

# Настройка OOM killer score для критичных сервисов
# /etc/systemd/system/myservice.service.d/oom.conf
[Service]
OOMScoreAdjust=-500
```

---

### Шаг 7: Анализ аппаратных ошибок (MCE / EDAC)

Machine Check Exceptions (MCE) — аппаратные ошибки, обнаруженные процессором. Требуют расшифровки через `mcelog` или `rasdaemon`.

```bash
# Поиск MCE в dmesg предыдущей сессии
journalctl -b -1 -g "mce\|edac\|machine check" | tail -n 30
# → [ 1234.567890] MCE: CPU 0: Machine Check Exception: ...
# → [ 1234.567891] MCE: PID 0, TID 0; ...

# Текущий статус EDAC
sudo edac-util -v
# → edac-util: CE count on MC0 (RAM idx 0): 0
# → edac-util: UE count on MC0 (RAM idx 0): 1  ← фатальный сбой

# Детальная информация о модулях памяти
sudo edac-util -s
# → Bus 0, Device 0, Function 0: 8192 MB (4096 bits wide, ECC enabled)

# Альтернатива: rasdaemon
sudo ras-mc-ctl --summary
# → MCE records: 15
# → Corrected Errors: 12
# → Uncorrected Errors: 3
```

**Действие при UE (Uncorrectable Error):**
1. Определите физический модуль по `row`/`channel` из dmesg.
2. Найдите слот через `dmidecode -t memory`.
3. Для Dell/HP используйте `ipmitool sdr type memory` для корреляции с физическими слотами.
4. Замените модуль RAM.

---

### Шаг 8: Диагностика после перезагрузки (Post-Reboot Failure)

Когда сервис работал до перезагрузки, но не запустился после неё. Частые причины:
1. Проблемы с автозапуском (systemd enable/disable).
2. Не смонтированы ФС (ошибки в `/etc/fstab`).
3. Изменились сетевые параметры (MAC, bonding).
4. Устарели сертификаты/ключи (rotated).

```bash
# 1. Проверка статуса сервиса
systemctl status myservice
# → loaded, but inactive (dead)

# 2. Поиск ошибок в journal текущей сессии
journalctl -u myservice --since "10 minutes ago" --no-pager
# → Failed to start ...

# 3. Проверка монтирования ФС
mount -a
# → ошибка монтирования (проверьте /etc/fstab)

# 4. Проверка network (если сервис зависит от сети)
ip addr show
journalctl -b | grep -i "network\|bond\|vlan"

# 5. Проверка сертификатов (если применимо)
openssl x509 -in /etc/ssl/certs/mycert.pem -noout -dates
# → notAfter=...

# 6. Проверка зависимостей systemd
systemctl list-dependencies myservice
```

---

### Шаг 9: Автоматизированный мониторинг перезагрузок

Для проактивного обнаружения перезагрузок настройте мониторинг через `systemd` и `cron`.

**Скрипт мониторинга kdump:**
```bash
#!/bin/bash
# /usr/local/bin/check_kdump.sh
STATUS=$(kdumpctl status 2>&1)
if echo "$STATUS" | grep -qi "not operational\|failed\|inactive"; then
    echo "CRITICAL: kdump is not operational: $STATUS"
    # Отправка алерта: mail, slack, pagerduty
    exit 2
elif echo "$STATUS" | grep -qi "operational"; then
    echo "OK: kdump is operational"
    exit 0
else
    echo "UNKNOWN: kdump status unclear: $STATUS"
    exit 3
fi
```

**Systemd timer для периодической проверки:**
```ini
# /etc/systemd/system/check-kdump.service
[Unit]
Description=Check kdump operational status

[Service]
Type=oneshot
ExecStart=/usr/local/bin/check_kdump.sh

# /etc/systemd/system/check-kdump.timer
[Unit]
Description=Run check_kdump every 5 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
Persistent=true

[Install]
WantedBy=timers.target
```

Активация:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now check-kdump.timer
```

## Additional Information

### Проактивная настройка (Hardening)

Для облегчения диагностики в будущем:
1.  **Постоянный лог:** `Storage=persistent` в `/etc/systemd/journald.conf`.
2.  **Настройка паники:**
     ```bash
     # Перезагрузка через 10 сек после паники
     sysctl -w kernel.panic = 10
     # Паника при OOM (если нужно быстро восстановить сервис)
     sysctl -w vm.panic_on_oom = 1
     ```
3.  **Auditd:** мониторинг системных вызовов `reboot`.
4.  **kdump:** включение и проверка статуса через `kdumpctl status`.
5.  **pstore:** настройка `ramoops` через параметры загрузки ядра.

### Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `kdump` не срабатывает | Недостаточно памяти `crashkernel`, модуль `kexec` не загружен | Проверьте `cat /proc/cmdline | grep crashkernel`, `lsmod \| grep kexec` |
| `pstore` пустой | Не настроен `ramoops`, не хватило места в NVRAM | Добавьте `memmap=1M$0x60000000 ramoops.mem_size=0x100000` в параметры GRUB |
| Логи `journalctl -b -1` пустые | `Storage=volatile` в `journald.conf` | Измените на `Storage=persistent` и перезапустите `systemd-journald` |
| `ipmitool` не подключается | Модуль `ipmi_devintf` не загружен, BMC отключен | `modprobe ipmi_devintf`, проверьте настройки BMC в BIOS/UEFI |
| SysRq не работает | `kernel.sysrq=0` | `echo 1 > /proc/sys/kernel/sysrq` (или добавьте в `/etc/sysctl.conf`) |
| `vmcore` слишком большой | По умолчанию сохраняются все страницы | Настройте `makedumpfile -l -d 31` в `/etc/kdump.conf` для сжатия |

### Best Practices

1.  **Всегда настраивайте kdump на production-серверах.** Даже если кажется, что паника невозможна, аппаратные ошибки (MCE) и баги драйверов случаются.
2.  **Используйте `Storage=persistent` в journald.** Без этого после перезагрузки вы потеряете все логи предыдущей сессии.
3.  **Настройте `kernel.panic_on_oops` и `kernel.softlockup_panic`.** Это превращает недетерминированные зависания в предсказуемые перезагрузки с сохранением дампа.
4.  **Регулярно проверяйте IPMI SEL.** Аппаратные ошибки (Watchdog, MCE, перегрев) часто фиксируются там задолго до фатального сбоя.
5.  **Тестируйте kdump в staging.** Принудительная паника (`echo c > /proc/sysrq-trigger`) должна создавать `vmcore`. Если нет — исправьте конфигурацию до production.
6.  **Храните `vmlinux` и debuginfo.** Без символов `crash` не сможет расшифровать backtrace. Настройте `debuginfod` или установите пакеты `kernel-debuginfo`.
7.  **Мониторите kdump статус.** Добавьте проверку в cron или systemd timer. Если kdump не operational — сервис должен алертить.
8.  **Не отключайте Watchdog в production.** Он — последний шанс восстановить сервис при глубоком зависании.

### Cleanup

После завершения диагностики:
1.  **Отключите SysRq** (если временно включали):
    ```bash
    echo 0 > /proc/sys/kernel/sysrq
    ```
2.  **Очистите старые дампы** (если они больше не нужны):
    ```bash
    sudo rm -rf /var/crash/*
    ```
3.  **Очистите pstore** (если заполнен):
    ```bash
    sudo rm -f /sys/fs/pstore/*
    ```
4.  **Остановите tracing/ftrace** (если использовали):
    ```bash
    echo 0 > /sys/kernel/debug/tracing/tracing_on
    echo nop > /sys/kernel/debug/tracing/current_tracer
    ```
5.  **Верните `nmi_watchdog`** (если отключали для `perf`):
    ```bash
    echo 1 > /proc/sys/kernel/nmi_watchdog
    ```
6.  **Удалите временные файлы** дампов приложений:
    ```bash
    sudo coredumpctl list
    sudo coredumpctl rm <PID>
    ```

### Связанные темы

- [**Паника ядра (Kernel Panic)**](../../Core/kernel/kernel_panic.md)
- [**Зависания: Soft/Hard Lockup**](../../Core/kernel/lockups.md)
- [**Выключение и перезагрузка Linux**](../../SystemAdministration/shutdown_and_reboot.md)
- [**Анализ ошибок и сбоев**](../../SystemAdministration/Logging/error_and_crash_analysis.md)
- [**Диагностика dmesg**](../../Diagnostics/Kernel/dmesg/troubleshooting.md)
