# systemd

`systemd` — это современный менеджер системы и служб для Linux, стандарт для большинства дистрибутивов. Он инициализирует систему, управляет службами, сокетами, точками монтирования и другими ресурсами.

## Управление службами

Основные команды для управления службами выполняются с помощью утилиты `systemctl`.

### Базовые команды

- **Запустить службу:**
  ```sh
  sudo systemctl start nginx.service
  ```
- **Остановить службу:**
  ```sh
  sudo systemctl stop nginx.service
  ```
- **Перезапустить службу:**
  ```sh
  sudo systemctl restart nginx.service
  ```
- **Перезагрузить конфигурацию (без перезапуска):**
  ```sh
  sudo systemctl reload nginx.service
  ```
- **Проверить статус службы:**
  ```sh
  systemctl status nginx.service
  ```

### Автозапуск служб

- **Включить автозапуск при загрузке системы:**
  ```sh
  sudo systemctl enable nginx.service
  ```
- **Отключить автозапуск:**
  ```sh
  sudo systemctl disable nginx.service
  ```
- **Запретить запуск службы (даже вручную):**
  Это называется маскировкой.
  ```sh
  sudo systemctl mask bluetooth.service
  ```
- **Отменить маскировку:**
  ```sh
  sudo systemctl unmask bluetooth.service
  ```

## Журналирование с journald

`systemd` интегрирован с `journald`, централизованной системой логирования. Весь вывод (stdout и stderr) от служб автоматически направляется в журнал.

- **Просмотреть логи конкретной службы:**
  ```sh
  journalctl -u nginx.service
  ```
- **Отслеживать логи в реальном времени (как `tail -f`):**
  ```sh
  journalctl -f -u nginx.service
  ```
- **Показать логи с начала текущей загрузки:**
  ```sh
  journalctl -b
  ```
- **Фильтровать по времени:**
  ```sh
  journalctl --since "1 hour ago"
  journalctl --since "2025-08-03 12:00:00"
  ```

## Работа с юнит-файлами

### Расположение юнит-файлов

- `/usr/lib/systemd/system/`: Юниты из установленных пакетов (не рекомендуется изменять).
- `/etc/systemd/system/`: Юниты, созданные администратором. Имеют наивысший приоритет.

После создания или изменения юнит-файла необходимо обновить конфигурацию `systemd`:
```sh
sudo systemctl daemon-reload
```

### Структура юнит-файла

Юнит-файл состоит из секций. Пример (`my_app.service`):

```ini
[Unit]
Description=My Application
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
ExecStart=/usr/bin/my_app --config /etc/my_app.conf
Restart=on-failure
RestartSec=5
User=app_user
Group=app_group
WorkingDirectory=/opt/my_app
Environment="ENV_VAR=production"

[Install]
WantedBy=multi-user.target
```

- **`[Unit]`**: Метаданные и зависимости.
  - `Description`: Описание юнита.
  - `After`, `Before`: Определяют порядок запуска. `my_app` запустится *после* сети и PostgreSQL.
  - `Requires`: "Жёсткая" зависимость. Если `postgresql.service` не запустится, `my_app.service` также не будет запущен.
- **`[Service]`**: Конфигурация службы.
  - `Type`: Тип запуска (`simple`, `forking`, `oneshot`).
  - `ExecStart`: Команда для запуска.
  - `Restart`: Политика перезапуска (`no`, `on-failure`, `always`).
  - `User`, `Group`: Запуск от имени непривилегированного пользователя.
- **`[Install]`**: Информация для `systemctl enable`.
  - `WantedBy`: Указывает, что юнит должен быть частью `multi-user.target` (стандартный режим работы).

### Редактирование юнитов через `systemctl edit`

Чтобы изменить параметры юнита, не трогая его оригинальный файл (например, из `/usr/lib/systemd/system/`), используйте `systemctl edit`.

```sh
sudo systemctl edit nginx.service
```

Эта команда создаст "override"-файл в `/etc/systemd/system/nginx.service.d/override.conf`, где можно указать только те директивы, которые нужно изменить или добавить.

Например, чтобы добавить автоматический перезапуск для `nginx`:
```ini
[Service]
Restart=always
RestartSec=10
```

### Зависимости между юнитами

- **`After=` / `Before=`**: Управляют только **порядком** запуска, но не создают реальной зависимости.
- **`Wants=`**: "Мягкая" зависимость. `systemd` попытается запустить указанный юнит, но если тот не запустится, это не повлияет на основной юнит.
- **`Requires=`**: "Жёсткая" зависимость. Если юнит, указанный в `Requires=`, не сможет запуститься, то и зависимый от него юнит тоже не запустится.
- **`BindsTo=`**: Самая сильная связь. Работает как `Requires=`, но дополнительно привязывает жизненные циклы. Если связанный юнит останавливается или падает, `systemd` немедленно остановит и этот юнит.
- **`PartOf=`**: Похоже на `BindsTo=`, но работает в одну сторону. Если юнит, указанный в `PartOf=`, останавливается или перезапускается, то же самое произойдёт и с этим юнитом.

## Задачи по расписанию: Timers

Таймеры — это современная замена `cron`. Они представляют собой `.timer` юниты, которые активируют `.service` юниты.

**1. Создайте `.service` файл (что делать):**
`/etc/systemd/system/my_backup.service`
```ini
[Unit]
Description=Run my backup script

[Service]
Type=oneshot
ExecStart=/usr/local/bin/backup.sh
```

**2. Создайте `.timer` файл (когда делать):**
`/etc/systemd/system/my_backup.timer`
```ini
[Unit]
Description=Run backup script daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```
- `OnCalendar=daily`: Запускать раз в день в 00:00. Можно использовать форматы вроде `*-*-* 02:00:00` (каждый день в 2 часа ночи) или `hourly` (раз в час).
- `Persistent=true`: Если система была выключена во время планового запуска, задача выполнится сразу после следующей загрузки.

**3. Включите и запустите таймер:**
```sh
sudo systemctl enable my_backup.timer
sudo systemctl start my_backup.timer
```

## Анализ производительности загрузки

`systemd-analyze` помогает выявить узкие места при загрузке системы.

- **Общее время загрузки:**
  ```sh
  systemd-analyze
  ```
- **Время запуска каждого юнита:**
  ```sh
  systemd-analyze blame
  ```
- **Критическая цепь зависимостей:**
  Показывает, какие юниты больше всего замедлили процесс загрузки.
  ```sh
  systemd-analyze critical-chain
  ```

## Управление параметрами ядра (`sysctl`)

`systemd` управляет применением параметров ядра из файлов в `/etc/sysctl.d/`.

1.  **Создайте `.conf` файл:**
    ```sh
    sudo nano /etc/sysctl.d/99-custom.conf
    ```
2.  **Добавьте параметры:**
    ```
    # Увеличить лимит открытых файлов
    fs.file-max = 2097152
    ```
3.  **Примените изменения без перезагрузки:**
    ```sh
    sudo sysctl --system
    ```

## Пользовательские службы

`systemd` может управлять службами для конкретного пользователя. Эти юниты хранятся в `~/.config/systemd/user/`. Управлять ими можно, добавив флаг `--user`.

```sh
systemctl --user start my_app.service
systemctl --user enable my_app.service
```
Пользовательские службы запускаются при первом входе пользователя в систему и завершаются после окончания его последней сессии.