# Выключение и перезагрузка Linux-систем

## Определения

- **Graceful Shutdown (Корректное выключение):** Процесс планового завершения работы ОС, включающий уведомление пользователей, остановку служб, сброс дисковых кэшей и размонтирование файловых систем.
- **Halt:** Состояние системы, при котором все процессы остановлены и ЦП прекращает выполнение инструкций, но питание физически может оставаться включенным (зависит от ACPI).
- **Power Off:** Полное отключение электропитания системы после завершения процесса `halt`.
- **Reboot:** Полный цикл перезапуска системы (эквивалент `poweroff` + включение).
- **Soft-reboot (Userspace Reboot):** Современный механизм (systemd 254+), позволяющий перезапустить только пользовательское окружение (userspace) без перезагрузки ядра.
- **kexec:** Механизм ядра, позволяющий загрузить и запустить новое ядро Linux напрямую из текущего, минуя этапы инициализации оборудования (BIOS/UEFI) и POST.
- **Rescue Target (`rescue.target`):** systemd-target, запускающий минимальное многопользовательское окружение с корневой ФС в read-write. Используется для восстановления после сбоев конфигурации.
- **Emergency Target (`emergency.target`):** Самый минимальный режим — только root ФС в read-only, нет сети, нет большинства служб. Используется при критических повреждениях системы.
- **ACPI (Advanced Configuration and Power Interface):** Стандарт взаимодействия ОС с BIOS/UEFI для управления питанием, Sleep/Suspend, кнопками питания и термоуправлением.
- **Magic SysRq:** Низкоуровневый интерфейс ядра для выполнения критических команд (sync, unmount, reboot) даже при полном зависании ОС.
- **TimeoutStopSec:** Параметр systemd, ограничивающий время graceful shutdown службы перед отправкой SIGKILL (по умолчанию 90 секунд).
- **KillMode:** Параметр systemd, определяющий, какие процессы в cgroup будут убиты при остановке службы (`control-group`, `main`, `mixed`, `none`).

## Основные концепции

### Жизненный цикл завершения (systemd)

В современных дистрибутивах процессом выключения управляет `systemd`. Основные этапы:

1.  **Генерация транзакции:** `systemd` создает очередь заданий для остановки всех запущенных юнитов в порядке, обратном их зависимостям.
2.  **Отправка SIGTERM:** Службам посылается сигнал корректного завершения. Время ожидания ограничено параметром `DefaultTimeoutStopSec` (обычно 90с).
3.  **Отправка SIGKILL:** Если служба не завершилась вовремя, ядро принудительно убивает процесс.
4.  **Синхронизация (Sync):** Ядро принудительно сбрасывает грязные страницы памяти (Page Cache) на физические диски.
5.  **Размонтирование:** Перевод ФС в режим `read-only` и размонтирование.
6.  **Final Jump:** Переход в `poweroff.target`, `reboot.target` или вызов `kexec`.

### Инструменты управления

| Команда | Назначение | Особенности |
| :--- | :--- | :--- |
| **`shutdown`** | Плановое управление | Традиционная команда. Пример: `shutdown +10 "Update"` (через 10 мин). |
| **`systemctl poweroff`** | Выключение | Современный стандарт. Безопаснее прямого вызова `poweroff`. |
| **`systemctl reboot`** | Перезагрузка | Стандартный метод полного перезапуска. |
| **`systemctl soft-reboot`** | Быстрый перезапуск | Перезапуск только ОС без ядра (systemd 254+). |
| **`kexec -e`** | Смена ядра | Немедленный переход в новое ядро без участия BIOS. |
| **`systemctl isolate rescue.target`** | Rescue mode | Переключение в минимальное окружение для восстановления. |
| **`systemctl isolate emergency.target`** | Emergency mode | Минимальный режим только с root ФС (read-only). |
| **`systemctl reboot --firmware-setup`** | UEFI Setup | Перезагрузка в интерфейс прошивки. |

### Targets systemd

В systemd вместо классических runlevel'ов используются targets:

| Target | Аналог runlevel | Назначение |
| :--- | :--- | :--- |
| `poweroff.target` | 0 | Выключение системы |
| `reboot.target` | 6 | Перезагрузка |
| `rescue.target` | S, 1 | Одноразовый режим восстановления |
| `emergency.target` | 1b | Emergency shell (root ФС read-only) |
| `multi-user.target` | 2, 3, 4 | Многопользовательский режим (без GUI) |
| `graphical.target` | 5 | Многопользовательский с GUI |

### Поведение служб при остановке

Для управления тем, как systemd останавливает службу, используются параметры в `[Service]` секции юнит-файла:

| Директива | Назначение | Значение по умолчанию |
| :--- | :--- | :--- |
| `TimeoutStopSec=` | Максимальное время на graceful shutdown | 90s |
| `KillMode=` | Какие процессы убивать | `control-group` |
| `KillSignal=` | Сигнал для graceful shutdown | `SIGTERM` |
| `SendSIGKILL=` | Отправлять ли SIGKILL после таймаута | `yes` |
| `ExecStop=` | Команда, выполняемая перед остановкой | — |

**KillMode:**
- `control-group` — убивает все процессы в cgroup (опасно для дочерних процессов)
- `main` — только главный процесс (PID 1 в cgroup)
- `mixed` — SIGTERM главному, SIGKILL остальным
- `none` — не отправлять сигналы автоматически

### ACPI и управление питанием

ACPI (Advanced Configuration and Power Interface) — стандарт, который позволяет ОС взаимодействовать с аппаратным обеспечением для управления питанием. При корректной работе ACPI:
- `systemctl poweroff` отключает питание после остановки всех служб
- `systemctl reboot` инициирует тепловую перезагрузку (warm reboot)
- Closing the lid на ноутбуке вызывает `systemd-suspend` или `systemctl suspend`
- Нажатие кнопки питания генерирует событие, обрабатываемое `systemd-logind`

**Условия корректной работы ACPI:**
- Драйверы ACPI загружены в ядрах
- BIOS/UEFI не находится в режиме "Legacy" без ACPI
- Нет конфликтов с `acpi=off` в параметрах загрузки

## Практические сценарии

### 1. Плановое обслуживание и отмена

```bash
# Выключить систему немедленно
sudo shutdown -h now

# Перезагрузить в 03:00 ночи
sudo shutdown -r 03:00

# Отмена запланированного выключения
sudo shutdown -c
```

### 2. Управление физическими серверами (IPMI/iDRAC/iLO)

На физических серверах и blade-системах выключение/перезагрузку можно инициировать тремя способами:

- **OS Shutdown (`systemctl poweroff`):** Корректное завершение работы ОС. Питание отключается после остановки всех служб и синхронизации дисков.
- **Remote Console Reset (IPMI/iDRAC/iLO):** Аналог нажатия кнопки питания или аппаратного сброса. Если ОС поддерживает ACPI, происходит Graceful Shutdown. Если зависла — Hard Reset.
- **Graceful Reset (IPMI):** Некоторые BMC поддерживают `power cycle` с задержкой, дающей ОС время на корректное завершение.
- **Force Off/On (IPMI):** Мгновенное отключение и включение питания. Аналог выдергивания кабеля. Риск повреждения ФС.

**Важно:** Всегда предпочитайте OS Shutdown или Graceful Reset. Force Off допустим только при полном зависании системы.

### 3. Режимы восстановления (Rescue/Emergency)

Система может загружаться в специальные режимы для восстановления:

- **Rescue Mode (`systemctl rescue` / `init S` / `init 1`):** Монтирует основные ФС в read-write, запускает только базовые службы (network, logging). Полезен для исправления конфигураций, восстановления паролей, проверки дисков.
- **Emergency Mode (`systemctl emergency` / `init emergency` / `init 1b`):** Монтирует только корневую ФС в read-only. Сеть не поднимается. Используется при повреждении fstab, невозможности запустить rescue.target, или если root-раздел не монтируется.

```bash
# Переключиться в rescue mode из работающей системы
sudo systemctl rescue

# Переключиться в emergency mode
sudo systemctl emergency

# С текущего режима вернуться в нормальный
sudo systemctl default
```

### 4. Перезагрузка с выбором загрузчика (Boot Loader Entry)

Systemd поддерживает перезагрузку напрямую в определенную запись загрузчика:

```bash
# Перезагрузиться в UEFI Setup
sudo systemctl reboot --firmware-setup

# Перезагрузиться в определенный boot entry (systemd-boot)
sudo systemctl reboot --boot-loader-entry=entry-name

# Отобразить доступные entries
sudo bootctl list
```

Это особенно полезно для:
- Входа в UEFI Setup без физического доступа к клавиатуре
- Переключения между ядрами при проблемах с обновлением
- Загрузки в Windows dual-boot среде

### 5. Graceful restart службы без перезагрузки системы

Перезагрузка всего сервера — крайняя мера. Часто достаточно перезапустить отдельную службу:

```bash
# Graceful restart nginx (сохраняет соединения)
sudo systemctl reload nginx

# Полный restart (сброс соединений)
sudo systemctl restart nginx

# Проверить статус после restart
systemctl status nginx
# → Active: active (running) since ...

# Для приложений, которые не умеют reload, используйте ExecStop/ExecStart
sudo systemctl restart my-app.service
```

Для кастомных приложений настройте graceful shutdown через `ExecStop`:

```ini
# /etc/systemd/system/my-app.service
[Service]
ExecStart=/usr/local/bin/my-app
ExecStop=/usr/local/bin/my-app --graceful-shutdown
TimeoutStopSec=30
KillMode=mixed
```

### 6. Анализ времени выключения

Systemd может показать, какие службы тормозят выключение:

```bash
# Показать время настройки и загрузки юнитов при последней загрузке
sudo systemd-analyze blame

# Показать критические chain (что мешает загрузке/выключению)
sudo systemd-analyze critical-chain

# Включить debug для shutdown в journal
sudo journalctl -u systemd -b -1 --grep="Stopping"
```

### 7. Обработка зависших служб при выключении

Если служба не завершается за `TimeoutStopSec`, systemd отправляет `SIGKILL`. Чтобы диагностировать:

```bash
# Просмотреть failed-транзакции shutdown
sudo journalctl -b -1 -u systemd | grep -i "timeout\|kill\|stop"

# Принудительно сбросить failed-состояние
sudo systemctl reset-failed

# Для stubborn-служб настройте ForceStop в override
sudo systemctl edit --full my-app.service
# → KillMode=control-group
# → TimeoutStopSec=10
```

### 8. Отключение Ctrl+Alt+Del

На production-серверах предотвратите случайную перезагрузку по Ctrl+Alt+Del:

```bash
# Отключить (mask)
sudo systemctl mask ctrl-alt-del.target

# Или переопределить на no-op
sudo systemctl edit ctrl-alt-del.target
# → [Unit]
# → Description=Disabled Ctrl-Alt-Delete

# Проверить статус
systemctl status ctrl-alt-del.target
# → Loaded: masked
```

### 3. Аварийная перезагрузка (Magic SysRq)

Если система полностью зависла (не работает SSH, клавиатура), используйте низкоуровневый механизм ядра.

**Последовательность REISUB (Alt + SysRq + клавиша):**
1.  **R** (un**R**aw): Перехват управления клавиатурой у X-сервера.
2.  **E** (t**E**rm): Послать SIGTERM всем процессам.
3.  **I** (**I**ll): Послать SIGKILL (тем, кто не сдался).
4.  **S** (**S**ync): Сброс кэшей на диск (критично для целостности ФС).
5.  **U** (**U**nmount): Перемонтирование всех ФС в Read-Only.
6.  **B** (re**B**oot): Немедленная перезагрузка ядра.

*Для активации через SSH (если шелл еще жив):*
```bash
echo 1 | sudo tee /proc/sys/kernel/sysrq
for x in r e i s u b; do echo $x | sudo tee /proc/sysrq-trigger; sleep 1; done
```

## Диагностика проблем

### Типичные причины "зависания" при выключении

| Симптом | Вероятная причина | Действие |
| :--- | :--- | :--- |
| **90s Timeout** | Служба не реагирует на SIGTERM | Проверьте `journalctl -b -1 -u systemd` на таймауты. Увеличьте `TimeoutStopSec` или настройте `ExecStop`. |
| **Hanging on Sync** | Проблемы с сетевыми ФС (NFS/iSCSI) | Добавьте `_netdev` в fstab, настройте `nfs.stop=` или `xfs/forceudm` mount-опции. Убедитесь, что network.target останавливается после remote-fs.target. |
| **Hanging on umount** | Открытые файлы на смонтированных ФС | Используйте `lsof +D /mnt` или `fuser -vm /mnt` перед shutdown. |
| **Kernel Panic** | Баг в драйвере при выгрузке | Настройте **[Диагностика причин перезагрузки Linux](../Diagnostics/Troubleshooting/reboot_troubleshooting.md)** для анализа vmcore и kdump. |
| **System hangs on reboot** | Зависший процесс в `D` state | Используйте Magic SysRq (REISUB) или `echo b > /proc/sysrq-trigger`. |
| **NMI watchdog** | Аппаратный watchdog сбросил систему | Проверьте `dmesg \| grep -i nmi\|watchdog`. Настройте `kernel.nmi_watchdog=0` или замените бракованное железо. |
| **ACPI not working** | Отключен ACPI в BIOS или ядре | Проверьте `dmesg \| grep -i acpi`, параметр загрузки `acpi=on`. |

## Дополнительная информация

### Смежные темы

- **[Диагностика причин перезагрузки Linux](../Diagnostics/Troubleshooting/reboot_troubleshooting.md):** Типы перезагрузок, kdump, pstore, анализ vmcore.
- **[Живое обновление ядра (kexec)](../Core/kernel/live_patching.md):** kexec, kpatch, kgraft — замена ядра без перезагрузки.
- **[Восстановление загрузки](../Diagnostics/Troubleshooting/boot_failure_recovery.md):** Grub rescue, initramfs, chroot.
- **[GRUB](grub.md):** Управление загрузчиком и параметрами ядра.
- **[Базовый чеклист производительности](performance_baseline.md):** Параметры ядра и limits для стабильной работы.
