# Пользовательские службы systemd: Режим --user

## Определения

* **`systemd --user`** — экземпляр менеджера процессов, работающий от имени непривилегированного пользователя. Позволяет управлять собственными службами, таймерами, сокетами и точками монтирования без прав root, изолированными в рамках пользовательского контекста.
* **Пользовательская шина D-Bus (Session Bus)** — канал межпроцессного взаимодействия, через который `systemctl --user`, `systemd-run --user` и другие утилиты общаются с пользовательским экземпляром systemd. Обычно привязана к сокету `/run/user/$UID/bus`.
* **Linger (Постоянство)** — состояние пользователя в `logind`, при котором его экземпляр `systemd --user` запускается при старте ОС и не завершается после закрытия всех сессий.
* **`user@.service`** — системный шаблонный юнит, отвечающий за запуск пользовательского экземпляра менеджера. Активируется автоматически при логине или при включенном lingering.
* **`user-$UID.slice`** — системный слайс cgroups, в котором работают все процессы пользовательских служб. Позволяет централизованно ограничивать ресурсы всей сессии.
* **`XDG_RUNTIME_DIR`** — временная директория в памяти (`/run/user/$UID`), в которой размещаются сокеты D-Bus, podman/docker.sock и другие рантайм-файлы. Удаляется при завершении последней сессии, если linger отключен.

## Основные концепции

### Архитектура и жизненный цикл

При старте сессии (TTY, SSH, GUI) модуль PAM `pam_systemd.so` создает для пользователя экземпляр `user@<UID>.service` в системном менеджере. Этот экземпляр запускает дочерний процесс `systemd --user`, который:

1. Подключается к пользовательской шине D-Bus.
2. Загружает пользовательские юниты из `~/.config/systemd/user/`, `~/.local/share/systemd/user/` и `/etc/systemd/user/`.
3. Принимает запросы от `systemctl --user`, `systemd-run --user` и графических оболочек.
4. Управляет процессами в рамках `user-$UID.slice`.
5. Завершается при выходе из последней сессии, если linger отключен.

Если linger включен, `user@<UID>.service` активируется при загрузке ОС через target `graphical.target` (или `multi-user.target` в зависимости от дистрибутива) и остается активным независимо от сессий.

### Жизненный цикл и режим Linger

По умолчанию экземпляр `systemd --user` создается при первом логине пользователя и уничтожается при выходе из последней сессии. Для серверных задач (боты, мониторинг, безрутовые контейнеры) необходимо включить режим **Linger**.

```bash
# Включение постоянной работы менеджера для текущего пользователя
sudo loginctl enable-linger $USER

# Проверка: статус Linger в выводе loginctl
loginctl show-user $USER --property=Linger
# → Linger=yes

# Принудительное завершение всех сессий и процессов пользователя
sudo loginctl terminate-user $USER
```

> **Важно:** Включение lingering создает файл `/var/lib/systemd/linger/<username>`. Это не влияет на текущие сессии — пользователь может продолжать работать, а его фоновые службы не будут убиты при выходе.

### Переменные окружения

Пользовательские юниты **не наследуют** переменные из файлов `.bashrc`, `.zshrc` или `.profile`.

1. **`environment.d` (Рекомендуется):** Создайте файл `~/.config/environment.d/99-custom.conf`. Формат: `KEY=VALUE`. Эти переменные будут доступны всем пользовательским службам. Для принудительного применения перезапустите экземпляр:
   ```bash
   systemctl --user daemon-reload
   # Перезапуск сам user-менеджера обычно не требуется; изменения применяются к новым юнитам.
   ```
2. **`systemctl --user import-environment`:** Передает переменные из текущей оболочки в менеджер (полезно для `$DISPLAY`, `$XDG_RUNTIME_DIR`, `$SSH_AUTH_SOCK`).
3. **`DefaultEnvironment=`:** Можно задать в `~/.config/systemd/user.conf` для глобального применения.

### Ограничение ресурсов (Cgroups)

Все пользовательские службы работают внутри системного слайса **`user-$UID.slice`**.
* Вы можете накладывать лимиты на все службы пользователя сразу через системный `systemctl set-property user-$UID.slice MemoryMax=2G CPUQuota=50%`.
* **`--runtime`** делает лимиты временными (без перезаписи на диск, исчезают после перезагрузки): `systemctl set-property --runtime myapp.service MemoryMax=512M CPUQuota=50%`.
* Индивидуальные лимиты прописываются в секции `[Service]` пользователя так же, как в системных.

### Модель безопасности

Пользовательские службы работают в изолированном контексте:
* **Нет прав root:** Невозможно смонтировать ФС, изменить сетевые интерфейсы или управлять системными юнитами.
* **Ограничение портов:** Непривилегированные пользователи не могут слушать порты `< 1024`. Используйте порты `> 1024` или `IP_TRANSPARENT` с соответствующими `sysctl` (требует прав).
* **Изоляция cgroup:** Все процессы ограничены `user-$UID.slice`. Администратор может задать `MemoryMax=`, `CPUQuota=` для всего пользователя.
* **Запрет SUID:** В юнитах `NoNewPrivileges=yes` по умолчанию не стоит, но его добавление — стандарт hardening.

## Практические сценарии

### 1. Иерархия и пути конфигурации

Пользовательский менеджер ищет юниты в следующем порядке (по убыванию приоритета):
1. **`$XDG_CONFIG_HOME/systemd/user/`** (обычно `~/.config/systemd/user/`) — основные пользовательские конфиги.
2. **`$XDG_DATA_HOME/systemd/user/`** (обычно `~/.local/share/systemd/user/`) — юниты от установленного пользователем ПО.
3. **`/etc/systemd/user/`** — общие юниты для всех пользователей системы (управляются root).

### 2. Пример службы: Фоновый Python-скрипт

Создайте файл `~/.config/systemd/user/my-script.service`:
```ini
[Unit]
Description=My Background Python Script
After=network-online.target

[Service]
Type=simple
# %h раскрывается в путь к домашней директории
ExecStart=/usr/bin/python3 %h/scripts/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

**Активация и валидация:**
```bash
# Проверка синтаксиса перед деплоем
systemd-analyze --user verify ~/.config/systemd/user/my-script.service

# Перезагрузка конфигурации и запуск
systemctl --user daemon-reload
systemctl --user enable --now my-script.service

# Проверка статуса
systemctl --user status my-script.service
# → active (running) since ...
```

### 3. Пример службы: Таймер пользователя

Создайте сервис и таймер для периодической задачи.

**Файл `~/.config/systemd/user/cleanup.service`:**
```ini
[Unit]
Description=Cleanup temporary files

[Service]
Type=oneshot
ExecStart=/usr/bin/find %h/.cache/tmp -type f -mtime +7 -delete
```

**Файл `~/.config/systemd/user/cleanup.timer`:**
```ini
[Unit]
Description=Run cleanup daily

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now cleanup.timer

# Проверка времени следующего запуска
systemctl --user list-timers cleanup.timer
```

### 4. Пример службы: Мониторинг директории (Path Activation)

Автоматическая обработка файлов при их появлении в директории.

**Файл `~/.config/systemd/user/processor.path`:**
```ini
[Path]
PathModified=%h/incoming/
Unit=processor.service

[Install]
WantedBy=paths.target
```

**Файл `~/.config/systemd/user/processor.service`:**
```ini
[Service]
Type=oneshot
ExecStart=/usr/local/bin/process-file.sh %f
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now processor.path
```

### 5. Активация через сокеты (Socket Activation)

Позволяет запускать службу только при поступлении входящего соединения на порт (например, для личного HTTP-прокси).

**Файл `~/.config/systemd/user/proxy.socket`:**
```ini
[Socket]
ListenStream=8080

[Install]
WantedBy=sockets.target
```

При использовании socket activation `proxy.service` создавать не обязательно — systemd запустит сервис автоматически при первом подключении, если он существует и имеет стандартное имя.

```bash
systemctl --user daemon-reload
systemctl --user enable --now proxy.socket
```

### 6. Запуск через `systemd-run --user`

Для разовых задач без создания файлов конфигурации:

```bash
# Одноразовая задача с лимитом памяти
systemd-run --user --unit=one-time-job \
  --property=MemoryMax=512M \
  --property=CPUQuota=30% \
  /usr/local/bin/batch-process.sh

# Просмотр статуса transient-юнита
systemctl --user status one-time-job.service
```

### 7. Жесткая изоляция (Sandboxing)

Пример hardened-юнита для пользовательского веб-сервиса:

```ini
[Unit]
Description=Hardened Personal Web Server
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -m http.server 8080 --directory %h/public
Restart=on-failure
RestartSec=5

# Изоляция ФС
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=yes
ReadWritePaths=%h/public %h/logs

# Изоляция ядра и оборудования
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectControlGroups=yes
ProtectKernelModules=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

# Безопасность
NoNewPrivileges=yes
MemoryDenyWriteExecute=yes
RestrictSUIDSGID=yes
```

## Диагностика и управление

### Базовые команды

```bash
# Просмотр всех юнитов пользователя
systemctl --user list-units

# Просмотр всех юнитов (включая неактивные)
systemctl --user list-units --all

# Просмотр таймеров
systemctl --user list-timers

# Чтение журналов (journald фильтрует по UID автоматически)
journalctl --user -u my-script.service -f
journalctl --user --since "1 hour ago" -p err

# Проверка конфигурации на ошибки
systemd-analyze --user verify ~/.config/systemd/user/my-script.service

# Анализ безопасности юнита
systemd-analyze --user security my-script.service

# Мониторинг ресурсов пользовательского слайса
systemd-cgtop --user
systemd-cgls /user.slice/user-$(id -u).slice
```

### Расширенная диагностика

```bash
# Проверка активной сессии и пользовательских процессов
loginctl list-sessions
loginctl session-status $(loginctl | grep $USER | awk '{print $1}')

# Поиск процессов пользователя
systemctl --user show-environment
ps -u $USER -o pid,ppid,cmd,%cpu,%mem

# Проверка D-Bus
busctl --user list
busctl --user status my-script.service

# Проверкаlinger и статуса user@.service
systemctl status user-$(id -u).service
loginctl show-user $USER
```

### Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Failed to connect to bus** | Ошибка инициализации `$XDG_RUNTIME_DIR` или D-Bus при использовании `su` или `sudo`. | Используйте `machinectl shell $USER@.host` или явно задайте `export XDG_RUNTIME_DIR=/run/user/$UID`. |
| **Error: Permission denied (Socket)** | Попытка занять порт < 1024. | Непривилегированные пользователи не могут слушать системные порты. Используйте порты > 1024. |
| **Служба «забывает» переменные** | Ожидание переменных из `.bashrc`. | Перенесите переменные в `~/.config/environment.d/*.conf`. |
| **Linger не работает** | Пользователь не добавлен в `/var/lib/systemd/linger/` или `pam_systemd` отсутствует. | Выполните `sudo loginctl enable-linger $USER`. Убедитесь, что в `/etc/pam.d/system-login` есть строка с `pam_systemd.so`. |
| **Юнит не запускается после перезагрузки** | `WantedBy=default.target`, но `default.target` неактивен. | Проверьте `systemctl --user is-active default.target`. Если неактивен, используйте `WantedBy=default.target` вместе с `systemctl --user enable`. |
| **Окружение SSH_AUTH_SOCK не передается** | `systemctl --user` не знает о переменной текущей сессии. | Выполните `systemctl --user import-environment SSH_AUTH_SOCK` или задайте `Environment=SSH_AUTH_SOCK=%t/ssh-agent.socket` в юните. |
| **Служба падает после разрыва SSH** | Linger отключен, сессия завершена. | Включите `sudo loginctl enable-linger $USER`. |

## Рекомендации по эксплуатации

1. **Валидация перед деплоем:** Всегда запускайте `systemd-analyze --user verify <unit>` перед `enable`. Это предотвращает опечатки в именах директив и невалидные зависимости.
2. **Управление окружением:** Храните переменные в `~/.config/environment.d/*.conf`, а не в скриптах-обертках. Используйте `systemctl --user import-environment` только для одноразовой передачи значений из текущей сессии.
3. **Изоляция по умолчанию:** Добавляйте `ProtectSystem=strict`, `PrivateTmp=yes`, `NoNewPrivileges=yes` ко всем сервисам, которые не требуют доступа к домашней директории.
4. **Мониторинг ресурсов:** Периодически проверяйте `systemd-cgtop --user` и `systemd-cgls /user.slice/user-$(id -u).slice`, чтобы выявить runaway-процессы.
5. **Linger для серверов:** Включайте `loginctl enable-linger` для всех сервисных аккаунтов, чьи службы должны работать без активной сессии.
6. **Не используйте `sudo systemctl --user`:** Пользовательский менеджер работает от имени пользователя. Если вы используете `sudo`, вы обращаетесь к root-сессии, а не к пользовательской.
7. **Именование:** Используйте осмысленные имена юнитов с доменом (например, `dev-backup.service`, `monitoring-netdata.service`), чтобы избежать конфликтов с пакетами ПО.
8. **Дроп-ины вместо правки:** Для изменений используйте `systemctl --user edit <unit>`, который создает drop-in в `~/.config/systemd/user/<unit>.d/`. Это сохраняет возможность обновления исходных юнитов из пакетов.
9. **TasksMax:** Устанавливайте `TasksMax=` для защиты от fork-бомб, особенно для служб, обрабатывающих внешний ввод.
10. **Graceful shutdown:** Используйте `ExecStop=` и сигналы `SIGTERM` (по умолчанию) вместо `SIGKILL`, чтобы службы корректно сохраняли состояние при остановке.

## Ограничения и крайние случаи

* **Нет прав root:** Пользовательские службы не могут монтировать ФС, изменять `sysctl`, управлять сетевыми интерфейсами или запускать системные юниты.
* **Порты:** Ограничение портами `< 1024` без дополнительных прав. В современных дистрибутивах можно настроить `net.ipv4.ip_unprivileged_port_start=80` через `sysctl` (требует прав root).
* **cgroup delegation:** В某些 средах администратор может ограничить доступные контроллеры cgroup для пользовательского слайса. Проверяйте доступность `systemd-cgls /user.slice/user-$(id -u).slice`.
* **Зависимость от сессии:** Без linger службы завершаются при выходе из последней сессии. Даже с linger при перезагрузке экземпляр `systemd --user` стартует только после `user@.service`.
* **SSH и screen/tmux:** При отключении SSH сессия завершается, но linger сохраняет фоновые процессы. Для tmux/screen это не требуется, так как процессы переparent'ятся в init, но `KillUserProcesses=yes` в `logind.conf` может их убить.
* **Поведение при перезагрузке:** Все пользовательские transient-юниты (запущенные через `systemd-run --user`) уничтожаются при перезагрузке. Persistent-таймеры восстанавливают состояние только если linger включен и таймер был `enable`.
* **cgroup v1:** Полноценная изоляция пользовательских служб требует cgroups v2. На cgroup v1某些 директивы (например, `MemoryMax=`) могут не работать в пользовательском контексте.
* **SELinux/AppArmor:** Полики MLS/MAC могут ограничивать доступ пользовательских процессов к файлам и сокетам. Проверяйте `audit.log` при отказe в доступе.

## Очистка и обслуживание

### Остановка и отключение служб

```bash
# Остановка и отключение
systemctl --user stop my-script.service
systemctl --user disable my-script.service

# Удаление unit-файла
rm ~/.config/systemd/user/my-script.service
rm -r ~/.config/systemd/user/my-script.service.d  # если есть дроп-ины

# Перезагрузка и проверка
systemctl --user daemon-reload
systemctl --user list-units | grep my-script
```

### Удаление orphaned transient-юнитов

```bash
# Просмотр transient-юнитов
systemctl --user list-units --type=service --state=actived | grep "\.service"

# Остановка всех пользовательских служб
systemctl --user stop '*.service'

# Отключение lingering (при необходимости)
sudo loginctl disable-linger $USER
```

### Ротация логов пользовательских служб

Логи хранятся в `journald` и автоматически ротируются через `/etc/systemd/journald.conf`. Для персонального контроля:

```bash
# Проверка размера журналов пользователя
journalctl --user --disk-usage

# Очистка старых записей (например, старше 30 дней)
journalctl --user --vacuum-time=30d
```

### Мониторинг состояния

```bash
# Проверка активности user@.service
systemctl is-active user-$(id -u).service

# Проверка lingering
loginctl show-user $USER -p Linger

# Проверка ресурсов слайса
systemd-cgtop --batch --raw | grep "/user.slice/user-$(id -u).slice"
```

## Дополнительная информация

### См. также

* [Обзор юнитов systemd](./systemd_units_overview.md) — классификация, состояния и механизмы активации.
* [Управление сессиями (logind)](./logind_session_management.md) — детали linger, ингибиторов и PAM-интеграции.
* [Журналирование (journald)](../../SystemAdministration/Logging/journald.md) — работа с логами без прав root.
