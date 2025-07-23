# systemd

`systemd` — это системный менеджер и менеджер служб для Linux, который стал стандартом для многих дистрибутивов. Он управляет запуском служб во время загрузки системы и позволяет управлять ими в процессе работы.

## Анализ производительности

Для анализа времени загрузки служб и выявления узких мест используется `systemd-analyze`.

```sh
systemd-analyze
```
Эта команда покажет, сколько времени заняла загрузка ядра и пользовательского пространства.

```sh
systemd-analyze blame
```
Эта команда выведет список всех запущенных юнитов, отсортированный по времени, которое потребовалось на их запуск.

## Управление службами (Services)

### Основные команды

- **`start`**: Запустить службу.
  ```sh
  sudo systemctl start nginx.service
  ```
- **`stop`**: Остановить службу.
  ```sh
  sudo systemctl stop nginx.service
  ```
- **`restart`**: Перезапустить службу.
  ```sh
  sudo systemctl restart nginx.service
  ```
- **`reload`**: Перезагрузить конфигурацию без остановки службы (если служба это поддерживает).
  ```sh
  sudo systemctl reload nginx.service
  ```
- **`reload-or-restart`**: Попытаться перезагрузить конфигурацию, а если не получится — полностью перезапустить службу.
  ```sh
  sudo systemctl reload-or-restart nginx.service
  ```
- **`status`**: Проверить статус службы.
  ```sh
  systemctl status nginx.service
  ```
- **`enable`**: Включить автозапуск службы при загрузке системы.
  ```sh
  sudo systemctl enable nginx.service
  ```
- **`disable`**: Отключить автозапуск.
  ```sh
  sudo systemctl disable nginx.service
  ```

### Маскировка служб

Маскировка — это способ полностью запретить запуск службы, даже вручную. Это сильнее, чем `disable`.

```sh
sudo systemctl mask bluetooth.service
```
Для отмены маскировки:
```sh
sudo systemctl unmask bluetooth.service
```

### Управление зависимостями

Посмотреть, от каких юнитов зависит служба:
```sh
systemctl list-dependencies <имя-службы>
```

Посмотреть, какие юниты зависят от этой службы:
```sh
systemctl list-dependencies --reverse <имя-службы>
```

## Особенности зависимостей: Requires= и After=

У вас есть два сервиса: `backend.service` и `database.service`. В юните `backend.service` прописано:

```ini
[Unit]
Description=Backend Service
Requires=database.service
After=database.service
```

Однако после перезагрузки системы `backend.service` запускается, даже если `database.service` не смог стартовать (например, из-за ошибки конфигурации).

Такое поведение — не баг, а особенность работы `systemd`.

- `Requires=database.service`: Эта директива означает, что при запуске `backend.service` `systemd` *также попытается* запустить `database.service`. Если `database.service` не запустится, `systemd` не будет автоматически останавливать `backend.service`, который уже был поставлен в очередь на запуск. Эта зависимость работает в одну сторону при активации.
- `After=database.service`: Эта директива только определяет *порядок* запуска. `backend.service` будет запущен после `database.service`, но `systemd` не будет ждать успешного завершения запуска `database.service`.
- **`WantedBy=multi-user.target`**: Когда оба сервиса привязаны к `multi-user.target`, `systemd` может пытаться запустить их параллельно (соблюдая правило `After=`), и сбой одного не обязательно остановит другой, если нет более строгой зависимости.

### Правильная настройка "жёсткой" зависимости

Чтобы `backend.service` гарантированно не запускался без работающей базы данных, необходимо настроить его более строго.

```ini
[Unit]
Description=Backend Service
Requires=database.service
After=database.service
# Если database.service остановится или упадёт, backend.service тоже будет остановлен.
BindsTo=database.service

[Install]
WantedBy=multi-user.target
```

**Ключевые директивы для "жёсткой" связи:**

- `BindsTo=database.service`: Создаёт более сильную связь. Если `database.service` останавливается или падает, `backend.service` также будет немедленно остановлен.
- `PartOf=database.service`: Полезная директива. Если `database.service` останавливается или перезапускается, то же самое произойдёт и с `backend.service`.

## Юнит-файлы (Unit Files)

### Расположение

`systemd` ищет юнит-файлы в нескольких каталогах. Файлы в `/etc/systemd/system` имеют наивысший приоритет и переопределяют файлы из других каталогов.

- `/usr/lib/systemd/system/`: Юниты, поставляемые с установленными пакетами.
- `/etc/systemd/system/`: Юниты, созданные системным администратором.

После создания или изменения юнит-файла необходимо выполнить команду:
```sh
sudo systemctl daemon-reload
```

### Типы юнитов

- **`.service`**: Сервисы и скрипты.
- **`.target`**: Группы юнитов (аналог уровней запуска).
- **`.mount`**: Точки монтирования файловых систем.
- **`.timer`**: Задачи по расписанию (аналог `cron`).
- **`.socket`**: Активация службы при обращении к сокету.
- и другие (`.automount`, `.swap`, `.slice`, `.device`, `.path`).

### Структура юнит-файла

Пример файла `my_service.service`:
```ini
[Unit]
Description=My Example Service
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/my_command --run
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
User=myuser
Group=mygroup
WorkingDirectory=/opt/my_app
Environment="VAR=value"

[Install]
WantedBy=multi-user.target
```

**Секция `[Unit]`**
- `Description`: Описание юнита.
- `After`: Указывает, что юнит должен запускаться **после** указанных юнитов (например, `network.target`).

**Секция `[Service]`**
- `Type`: Тип запуска. `simple` — процесс запущен сразу; `forking` — главный процесс порождает дочерний.
- `ExecStart`: Команда для запуска сервиса.
- `ExecReload`: Команда для перезагрузки конфигурации. `$MAINPID` — это PID основного процесса.
- `Restart`: Политика перезапуска (`no`, `on-success`, `on-failure`, `always`).
- `User`, `Group`: Пользователь и группа, от имени которых будет запущен процесс.
- `WorkingDirectory`: Рабочая директория для процесса.
- `Environment`: Переменные окружения.

**Секция `[Install]`**
- `WantedBy`: Указывает, в каком `target` (уровне запуска) юнит должен быть активирован при выполнении `systemctl enable`. `multi-user.target` — стандартный многопользовательский режим.
