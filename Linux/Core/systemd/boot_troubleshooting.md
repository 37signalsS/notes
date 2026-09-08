# Диагностика загрузки и проблем запуска сервисов

## Определения

* **Контекст загрузки (Boot Context)** — специфическая среда выполнения, в которой `systemd` активирует юниты во время старта системы. Отличается от интерактивной сессии отсутствием многих переменных окружения, поэтапной готовностью ресурсов (сеть, файловые системы) и жесткими системными тайм-аутами.
* **Rescue Mode (Режим спасения)** — состояние системы (`rescue.target`), предназначенное для ремонта, когда базовая конфигурация исправна. Монтирует все локальные файловые системы, но запускает минимум сервисов. Требует пароль root.
* **Emergency Mode (Аварийный режим)** — минимальное состояние (`emergency.target`), используемое при критических сбоях. Монтирует только корень в `ro`. Сеть и дополнительные диски не активны.
* **Генераторы (Generators)** — вспомогательные программы (в `/usr/lib/systemd/system-generators/`), которые динамически создают юниты при каждой загрузке (например, превращают записи `/etc/fstab` в `.mount` юниты).
* **systemd-fstab-generator** — встроенный генератор, который преобразует записи `/etc/fstab` в `.mount` юниты. При ошибках в `fstab` (неверный UUID, опции) генератор создает юниты с состоянием `failed`, блокируя загрузку зависимых сервисов.
* **Condition* директивы** — условия в секции `[Unit]` (`ConditionPathExists=`, `ConditionDirectoryNotEmpty=`, `ConditionSecurity=`, `ConditionACPower=`), которые проверяются перед стартом. При невыполнении условия юнит пропускается (не считается сбоем).
* **Boot ID** — уникальный идентификатор текущей загрузки, хранящийся в `/proc/sys/kernel/random/boot_id`. Используется journald для группировки логов конкретной сессии загрузки.

## Основные концепции

### Сравнение режимов восстановления

| Характеристика | Rescue Mode | Emergency Mode |
| :--- | :--- | :--- |
| **Цель в systemd** | `rescue.target` | `emergency.target` |
| **Файловые системы** | Монтирует всё из `/etc/fstab` | Только корень (`/`) |
| **Уровень изоляции** | Выше (запущены udev, сокеты) | Минимальный (только PID 1 и shell) |
| **Когда использовать** | Сброс пароля, ремонт сервисов | Ошибки монтирования, повреждение ФС |

### Архитектура загрузки systemd

Процесс загрузки разделен на фазы, каждая из которых может быть источником проблем:

1. **Firmware (UEFI/BIOS)** — инициализация оборудования. Не управляется systemd, но ошибки здесь (например, некорректный порядок загрузки дисков) проявляются позже.
2. **Загрузчик (GRUB/systemd-boot)** — передает управление ядру. Параметры строки `linux` влияют на ранние этапы.
3. **Ядро (Kernel)** — распаковка и инициализация. Драйверы дисков, LVM, RAID, LUKS загружаются здесь.
4. **initramfs** — временная ФС в RAM. Здесь происходит монтирование корня, настройка LVM/RAID, расшифровка. Сбой на этом этапе приводит к приглашению `(initramfs)`.
5. **PID 1 (systemd)** — переход к основной системе инициализации. Начинается активация юнитов согласно таргету по умолчанию.
6. **Userspace** — параллельный запуск сервисов, таймеров, монтирование разделов. На этом этапе работает `systemd-analyze` для измерения времени.

### Причины сбоев при автозапуске

Если сервис успешно запускается вручную, но падает при загрузке, причина обычно в одном из факторов:
1.  **Гонка зависимостей:** Сервис требует ресурс (БД, сеть, диск), который еще не готов. `systemd` может убить юнит по тайм-ауту (`DefaultTimeoutStartSec=90s`).
2.  **Пути и окружение:** Использование относительных путей или переменных, доступных только в shell администратора.
3.  **Ошибки генераторов:** Сбой в работе `systemd-fstab-generator` или других скриптов блокирует создание необходимых юнитов.
4.  **Права и контекст:** Различия в контекстах SELinux/AppArmor или запуск от имени другого пользователя без нужных привилегий в раннем окружении.
5.  **Условия (Condition*):** Директивы `ConditionPathExists=` или `ConditionDirectoryNotEmpty=` возвращают `false`, если путь еще не создан другим сервисом.
6.  **Заблокированные юниты (mask):** Юнит находится в состоянии `masked` из-за предыдущего сбоя или административного действия.

### Генераторы и их диагностика

Генераторы запускаются на ранних этапах (до активации большинства сервисов) и создают временные юниты в `/run/systemd/generator/`.

```bash
# Просмотр логов генераторов
journalctl -b -t systemd-fstab-generator

# Проверка созданных юнитов
systemctl list-unit-files --type=generator
```

Частые проблемы генераторов:
- **Неверный UUID в `/etc/fstab`** → `.mount` юнит переходит в `failed` → блокирует `local-fs.target` → зависание загрузки.
- **Пропущены опции `x-systemd.*`** → монтирование происходит без таймаутов systemd, используя классический механизм.
- **Сетевые файловые системы (NFS, CIFS)** без `_netdev` → generator создает `.mount` юнит, который стартует до поднятия сети и падает.

## Практические сценарии

### 1. Отладка через параметры ядра (GRUB)

При «зависшей» загрузке добавьте эти параметры в строку `linux`:

* **`systemd.debug_shell`** — запускает root-оболочку на **TTY9** (`Ctrl+Alt+F9`). Позволяет выполнять `systemctl` прямо во время старта.
* **`systemd.confirm_spawn=yes`** — интерактивный запуск: система просит (y/n) для каждого сервиса.
* **`systemd.mask=problem.service`** — временная блокировка юнита, вызывающего сбой.
* **`systemd.log_level=debug`** — вывод максимально подробных логов инициализации прямо на консоль.
* **`systemd.unit=emergency.target`** — принудительная загрузка в аварийный режим.

### 2. Анализ журналов загрузки

```bash
# Логи текущей (последней) загрузки
journalctl -b

# Только ошибки и критические сообщения текущей сессии
journalctl -p err -b

# Поиск сообщений о циклических зависимостях
journalctl -b | grep "ordering cycle"
# → Found ordering cycle on ...

# Логи конкретного failed-юнита
journalctl -u myapp.service -b -p err

# Логи генераторов (fstab, cryptsetup, etc.)
journalctl -b -t systemd-fstab-generator
journalctl -b -t systemd-cryptsetup
```

#### Сохранение логов для анализа после перезагрузки

По умолчанию логи хранятся в `/run/log/journal/` (tmpfs) и удаляются при выключении. Для постоянного хранения:

```bash
# Создание директории для persistent журналов
sudo mkdir -p /var/log/journal
sudo systemctl restart systemd-journald

# Проверка режима хранения
journalctl --disk-usage
```

### 3. Поиск узких мест и зависимостей

Для диагностики загрузки используйте `systemd-analyze`. Подробные сценарии, таблицы и методики устранения задержек см. в **[Анализ производительности (systemd-analyze)](./performance.md)**.

### 4. Исправление ошибок в Emergency Mode

Если система требует `Ctrl+D` для продолжения:
1.  Перемонтируйте корень в режим записи: `mount -o remount,rw /`.
2.  Найдите виновника: `journalctl -xb` (ищите строки красного цвета).
3.  Если проблема в диске: `fsck -y /dev/sdXN`.
4.  Если проблема в конфиге: исправьте `/etc/fstab`.
5.  Перезагрузитесь: `systemctl reboot`.

### 5. Превентивная проверка юнитов

```bash
# Проверка синтаксиса и логических ошибок перед деплоем
systemd-analyze verify /etc/systemd/system/myapp.service

# Проверка всех юнитов в каталоге
find /etc/systemd/system -name '*.service' -exec systemd-analyze verify {} +
```

### 6. Диагностика сбоев после загрузки

Когда система загрузилась, но некоторые сервисы не стартовали:

```bash
# Список failed-юнитов
systemctl --failed
systemctl --type=service --state=failed

# Детализация конкретного юнита
systemctl status myapp.service
systemctl show myapp.service -p ActiveState -p SubState -p Result -p ExecMainStatus

# Дамп внутреннего состояния (таймауты, лимиты, NRestarts)
systemd-analyze dump myapp.service | grep -E 'NRestarts|Timeout|Limit'

# Рекурсивный список зависимостей
systemctl list-dependencies myapp.service
systemctl list-dependencies --reverse myapp.service
```

### 7. Исправление конфигурации systemd

Если проблема в unit-файле или переопределениях:

```bash
# Просмотр реального конфигурационного файла (с учетом drop-ins)
systemctl cat myapp.service

# Поиск конфликтов между файлами
systemd-delta

# Редактирование с автоматическим созданием drop-in
sudo systemctl edit myapp.service

# Полное редактирование (перезапись основного файла)
sudo systemctl edit --full myapp.service

# Применение изменений
sudo systemctl daemon-reload
sudo systemctl restart myapp.service
```

### 8. Работа с fstab и systemd-fstab-generator

```bash
# Проверка синтаксиса fstab без перезагрузки
sudo systemd-analyze verify /etc/fstab

# Просмотр созданных генератором mount-юнитов
systemctl list-unit-files --type=mount --state=failed

# Проверка конкретного mount-юнита
systemctl status tmp.mount
journalctl -u tmp.mount -b

# Применение изменений в fstab без перезагрузки
sudo systemctl daemon-reload
sudo systemctl restart local-fs.target
```

### 9. Диагностика Condition* директив

```bash
# Проверка, какие условия не выполнились
systemd-analyze verify myapp.service 2>&1 | grep -i condition

# Ручная проверка условий
test -e /path/to/file && echo "OK" || echo "ConditionPathExists failed"
```

### 10. Очистка состояний после диагностики

```bash
# Сброс failed-состояния для повторного запуска
sudo systemctl reset-failed myapp.service
sudo systemctl start myapp.service

# Сброс всех failed-юнитов
sudo systemctl reset-failed

# Проверка отсутствия orphaned transient-юнитов
systemctl --type=service --state=running | grep '^run-'
```

## Дополнительная информация

### См. также

* [Анализ производительности (systemd-analyze)](./performance.md) — детальный разбор команд профилирования.
* [Управление зависимостями](./systemd_dependencies.md) — решение проблем со связями `After/Before`.
* [Журналирование через journald](../../SystemAdministration/Logging/journald.md) — работа с фильтрами журналов.
* [Восстановление системы (общее)](../../Diagnostics/Troubleshooting/boot_failure_recovery.md) — стратегии LiveCD и chroot.
* [Загрузчик GRUB](../../SystemAdministration/grub.md) — параметры ядра и восстановление загрузчика.
* [Структура юнит-файлов](./systemd_unit_file_structure.md) — директивы и синтаксис.

## Диагностика и устранение неисправностей

### Таблица типичных ошибок загрузки

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `systemd[...]: Failed to start ...` | Ошибка в конфигурации сервиса | `journalctl -u <unit> -b -p err` | Исправьте ExecStart, права, зависимости; `systemctl daemon-reload && systemctl restart <unit>` |
| `Job failed` при `start` | Отсутствует бинарный файл или ошибка прав доступа | `journalctl -u <unit> -n 50` | Проверьте `ExecStart` и права на файл |
| `Dependency failed` | Не удалось запустить зависимый юнит (`Requires=`/`Wants=`) | `systemctl list-dependencies <unit>` | Проверьте failed-юниты в цепочке |
| `Ordering cycle` | Противоречивые `After=`/`Before=` | `systemd-analyze critical-chain <unit>` | Пересмотрите порядок зависимостей |
| `Reload failed` | Юнит не поддерживает `SIGHUP` | `journalctl -u <unit> -n 20` | Используйте `restart` вместо `reload` |
| `Timeout stop failed` | `ExecStop=` не завершился | `journalctl -u <unit> -n 50` | Увеличьте `TimeoutStopSec=` или исправьте скрипт |
| `Failed at step cgroup` | Ошибка delegation или права cgroup | `journalctl -u <unit> -n 30` | Проверьте `Delegate=yes` в родительском slice |
| `Unit entered failed state` | Процесс завершился с ненулевым кодом | `systemctl status <unit>`; `journalctl -u <unit> -n 100` | Проверьте `Restart=on-failure` и счетчик сбоев |
| `Found ordering cycle on ...` | Циклические зависимости | `systemd-analyze critical-chain <unit>` | Разорвите цикл; пересмотрите `After=`/`Before=` |
| `Mount unit failed` | Ошибка в `/etc/fstab` или устройство недоступно | `journalctl -b -t systemd-fstab-generator`; `systemctl status <mount>` | Проверьте UUID, опции монтирования, наличие устройства |
| `Unit is masked` | Юнит заблокирован | `systemctl status <unit>` | `systemctl unmask <unit> && systemctl daemon-reload` |
| `ConditionPathExists=... failed` | Файл/директория не существует | `systemd-analyze verify <unit>` | Создайте путь или настройте `ConditionPathExists=` |

### Дополнительные сценарии

#### Сброс состояний и очистка

```bash
# Сброс failed-состояния (очищает счетчик сбоев)
sudo systemctl reset-failed nginx.service

# Поиск failed-транзиентных юнитов
systemctl --failed --type=service --no-legend | awk '{print $1}' | grep '^run-'
```

#### Ограничения и крайние случаи

* **Циклические зависимости:** `systemd` принудительно разрывает циклы, удаляя одну из зависимостей. Это может привести к неожиданному поведению. Используйте `systemd-analyze critical-chain` для визуализации.
* **Masked dependencies:** Если `A Requires B`, а `B` замаскирован, `A` не запустится с ошибкой `Dependency failed`. Разблокируйте `B` через `systemctl unmask B`.
* **Condition* директивы:** При невыполнении условия юнит помечается как `inactive (condition)`, что не считается сбоем. При отладке проверяйте `systemctl status <unit>` на наличие строки `Condition: ...`.
* **daemon-reload и running процессы:** `daemon-reload` перечитывает конфигурацию, но не останавливает уже запущенные сервисы. После `daemon-reload` требуется явный `restart` для применения изменений.
* **KillMode=control-group:** По умолчанию systemd убивает все процессы в cgroup при остановке. Для приложений, запускающих дочерние процессы (supervisord, s6), используйте `KillMode=mixed`, чтобы SIGTERM получил только основной процесс.
* **Socket activation латентность:** При первом подключении к сокету systemd запускает сервис. Если сервис долго стартует, клиент получит таймаут. Используйте `Accept=no` для долгоживущих сервисов.
* **Static units:** Юниты без `[Install]` секции (`Type=oneshot` с `RemainAfterExit=yes`) нельзя включить через `systemctl enable`. Они активируются автоматически через зависимости.

#### Рекомендации по эксплуатации

1. **Валидируйте unit-файлы перед деплоем:** `systemd-analyze verify /etc/systemd/system/myapp.service`.
2. **Используйте try-* в скриптах:** `try-restart` и `try-reload-or-restart` безопасны для неактивных юнитов.
3. **Анализируйте critical-chain, а не blame:** Долгий параллельный сервис не замедляет загрузку.
4. **Храните конфигурацию в Git:** Коммит-хук с `systemd-analyze verify` предотвращает опечатки.
5. **Настройте persistent journal:** Без `/var/log/journal` логи загрузки теряются после перезагрузки.
6. **Ограничивайте таймауты:** `TimeoutStartSec=5s` для быстрых сервисов, по умолчанию 90s слишком много.
7. **Отключайте ненужное:** `systemctl disable --now <service>` для неиспользуемых сервисов.
8. **Используйте systemd-delta для аудита:** Обнаруживает переопределения vendor-файлов.
9. **Мониторинг:** Настройте алерты на появление новых failed-юнитов после деплоя.
10. **Документируйте изменения:** Любое изменение конфигурации должно быть связано с тикетом или коммитом.

#### Очистка и обслуживание

```bash
# Удаление unit-файлов
sudo rm /etc/systemd/system/myapp.service
sudo systemctl daemon-reload

# Снятие блокировки (unmask)
sudo systemctl unmask myapp.service
sudo systemctl daemon-reload

# Проверка после изменений
systemctl is-active myapp.service
systemctl is-enabled myapp.service
systemd-analyze verify /etc/systemd/system/myapp.service
```
