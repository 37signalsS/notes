# Диагностика причин перезагрузки Linux

## Definitions

**Диагностика перезагрузки** — систематический анализ системных логов, дампов памяти и аппаратных журналов для выявления триггера перезапуска ОС.

**Штатная перезагрузка (Initiated Reboot)** — перезапуск, вызванный преднамеренным вызовом системных функций (`reboot(2)`, `shutdown`) пользователем или процессом. Сопровождается корректным завершением (SIGTERM/SIGKILL) сервисов.

**Аварийная перезагрузка (System Crash/Reset)** — мгновенный перезапуск без выполнения процедур завершения. Происходит при критических ошибках ядра (Panic), оборудования (MCE) или срабатывании аппаратных защит (Watchdog, Power Loss).

**Magic SysRq Key** — механизм ядра для выполнения низкоуровневых команд напрямую, в обход зависших абстракций ОС (systemd, драйверы дисков).

**kdump** — механизм сохранения снимка оперативной памяти (`vmcore`) в момент Kernel Panic для последующего «посмертного» анализа.

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

### Связанные темы

- [**Использование journalctl**](../journalctl/journalctl_overview.md)
- [**Паника ядра (Kernel Panic)**](../../Core/kernel/kernel_panic.md)
- [**Диагностика OOM Killer**](../../Core/processes/oom_killer_diagnostics.md)
- [**Зависания: Soft/Hard Lockup**](../../Core/kernel/lockups.md)
- [**Общая методология диагностики**](./general_troubleshooting_methodology.md)
