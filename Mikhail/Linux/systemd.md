# **Анализ запуска systemd служб и выяснение узкого места:**

```sh
systemd-analyze
```

 # **После создания новой systemd-службы необходимо перезагрузить systemd, чтобы распознать новую службу.**

```
sudo systemctl daemon-reload
```

Не все службы поддерживают мягкую перезагрузку - sudo systemctl reload(отправляет процуссу сигнал SIGHUP). Если вы не уверены, используйте reload-or-restart. Сначала выполняется попытка перезагрузки, а если она не поддерживается, выполняется полный перезапуск.

```
systemctl reload-or-restart nginx
```

# **Маскировка systemd-службы, для предовращения запуска(навсегда)**

```sh
systemctl mask bluetooth.service
```

Размаскировать systemd-службу:

```
systemctl unmask bluetooth.service
```

# **Зависимости systemd-службы**

```sh
systemctl list-dependencies service-name
```

Что зависит от systemd-службы

```sh
systemctl list-dependencies --reverse service-name
```
# **В зависимости от дистрибутива, юнит-файлы находятся в каталогах:**

- `/lib/systemd/system/`
- `/usr/lib/systemd/user/`
- `/usr/lib/systemd/system/` - файлы предоставляемые пакетом

Дополнительные юнит-файлы можно добавить в `/etc/systemd/system/`, они имеют приоритет выше.

Существующие типы юнитов `systemd`:

- `target` — группирует сервисы (аналог `runlevel`).
- `service` — запускает сервисы и пользовательские скрипты.
- `mount` — монтирует файловые системы.
- `automount` — автоматическое монтирование.
- `swap` — подключение файла подкачки.
- `timer` — выполняет задачи по расписанию (аналог `cron`).
- `socket` — запуск по подключению к сокету.
- `slice` — группировка модулей в `cgroups`.
- `device` — реакция на подключение устройства.
- `path` — запуск модуля при доступе к файлу.

#### Пример юнит-файла `my_example_service.service`

``` ini
[Unit]
Description=My Example Service
Documentation=http://example.com/service-doc
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/my_example_command --option value
ExecReload=/usr/bin/my_example_command --reload
ExecStop=/usr/bin/my_example_command --stop
Restart=always
RestartSec=10
User=exampleuser
Group=examplegroup
Environment="MY_ENV_VAR=value"
EnvironmentFile=-/etc/default/my_example_service
WorkingDirectory=/var/my_example_service
LimitNOFILE=1024
LimitNPROC=100
TimeoutStartSec=30s
TimeoutStopSec=30s
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=my_example_service

[Install]
WantedBy=multi-user.target
```

**1. `[Unit]` — Описание юнита**

- **`After=network.target`**: Указывает, что сервис должен запускаться **после** того, как будет доступна сеть. Это важно для сервисов, которые используют сеть, например, веб-сервисы.

**2. `[Service]` — Описание работы сервиса**

- **`Type=simple`**: Тип сервиса, который будет считаться запущенным сразу после выполнения команды `ExecStart`. Это самый простой тип сервиса, подходит для большинства приложений.
    
- **`ExecStart=/usr/bin/my_example_command --option value`**: Команда, которая будет выполняться при старте сервиса. Здесь это пример команды с параметром.
    
- **`ExecReload=/usr/bin/my_example_command --reload`**: Команда, которая будет выполнена при перезагрузке сервиса (например, для применения новых настроек).
    
- **`ExecStop=/usr/bin/my_example_command --stop`**: Команда для остановки сервиса.
    
- **`Restart=always`**: Указывает, что сервис будет перезапускаться, если он завершится с ошибкой или аварийно.
    
- **`RestartSec=10`**: Устанавливает задержку в 10 секунд перед перезапуском сервиса.
    
- **`User=exampleuser`**: Сервис будет выполняться от имени пользователя `exampleuser`.
    
- **`Group=examplegroup`**: Сервис будет выполняться от имени группы `examplegroup`.
    
- **`Environment="MY_ENV_VAR=value"`**: Устанавливает переменные окружения, которые будут доступны сервису.
    
- **`EnvironmentFile=-/etc/default/my_example_service`**: Загружает переменные окружения из файла `/etc/default/my_example_service`. Символ `-` перед путем означает, что если файл не существует, ошибки не будет.
    
- **`WorkingDirectory=/var/my_example_service`**: Указывает директорию, в которой будет работать сервис. Это полезно, если нужно, чтобы сервис выполнялся из конкретной папки.
    
- **`LimitNOFILE=1024`**: Ограничение на количество открытых файлов, которые может использовать сервис.
    
- **`LimitNPROC=100`**: Ограничение на количество процессов, которые может создать сервис.
    
- **`TimeoutStartSec=30s`**: Время ожидания для успешного старта сервиса. Если сервис не запускается за это время, он будет остановлен.
    
- **`TimeoutStopSec=30s`**: Время ожидания для завершения работы сервиса после команды остановки. Если сервис не завершает работу за это время, он будет принудительно завершен.
    
- **`StandardOutput=syslog`**: Направляет стандартный вывод в системный журнал (`syslog`).
    
- **`StandardError=syslog`**: Направляет стандартный вывод ошибок в системный журнал (`syslog`).
    
- **`SyslogIdentifier=my_example_service`**: Устанавливает идентификатор для логов, чтобы можно было легче идентифицировать их в системном журнале.

**3. `[Install]` — Установка и активация юнита**

- **`WantedBy=multi-user.target`**: Указывает, что сервис должен быть активирован при запуске в многопользовательском режиме (обычно при запуске системы). Это означает, что сервис будет автоматически запускаться после загрузки системы в обычном режиме.