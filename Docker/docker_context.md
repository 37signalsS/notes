# Docker Context — управление профилями подключения

**Актуально для:** Docker Engine 29.8.x, Docker CLI 29.x

## Определения

- **Docker Context:** Механизм Docker CLI для управления именованными профилями подключения к Docker Engine. Контекст инкапсулирует адрес хоста (Endpoint), сертификаты безопасности и метаданные в отдельный профиль, переключение между которыми не требует изменения команд.
- **Endpoint:** Точка входа для взаимодействия с Docker API. Поддерживаются локальные сокеты (`unix://`), удалённый доступ через `ssh://` и защищённый `tcp://` (mTLS).
- **Context Switching:** Мгновенное переключение активного профиля в CLI, определяющее, какому демону будут отправляться команды по умолчанию.
- **Виртуальный контекст `default`:** Зарезервированное имя, которое не хранится в каталоге контекстов. Оно всегда указывает на локальный `unix:///var/run/docker.sock` и служит точкой отката при любых проблемах с остальными профилями.
- **Контекстный каталог (context store):** Локальное хранилище метаданных и TLS-материала контекстов. Путь по умолчанию — `~/.docker`, переопределяется переменной `DOCKER_CONFIG` или глобальным флагом `--config`.

## Основные концепции

### Назначение и преимущества

1. **Безопасное удалённое управление:** Использование SSH как основного транспорта позволяет управлять серверами без открытия портов Docker-демона в сеть.
2. **Управление гибридными средами:** Удобное переключение между Docker Desktop, Colima, OrbStack, Rootless Docker и удалёнными VPS без правки скриптов и переменных окружения.
3. **Абстракция инфраструктуры:** Команды развёртывания (`docker stack deploy`, `docker compose up`) остаются неизменными; меняется только целевой контекст.
4. **Отсутствие секретов в командной строке:** Сертификаты хранятся в отдельном каталоге с правами `0600`, а не передаются аргументами командной строки, попадая в историю оболочки и вывод CI-логов.

### Анатомия контекста

Контекст состоит из четырёх частей: имя, описание, конфигурация endpoint и TLS-материал. Реальная структура видна в выводе `docker context inspect`:

```console
$ docker context inspect default
[
    {
        "Name": "default",
        "Metadata": {},
        "Endpoints": {
            "docker": {
                "Host": "unix:///var/run/docker.sock",
                "SkipTLSVerify": false
            }
        },
        "TLSMaterial": {},
        "Storage": {
            "MetadataPath": "<IN MEMORY>",
            "TLSPath": "<IN MEMORY>"
        }
    }
]
```

Обратите внимание на `Storage` виртуального контекста `default` — пути указывают `<IN MEMORY>`, потому что этот контекст не имеет записи в каталоге. У пользовательского контекста вместо этого выводятся реальные пути.

Поля `Endpoints.docker` соответствуют ключам, которые принимает флаг `--docker`:

| Ключ | Назначение |
|:---|:---|
| `host` | Адрес демона: `unix://`, `tcp://` или `ssh://` |
| `ca` | CA-сертификат, которому доверяет клиент |
| `cert` | Клиентский сертификат |
| `key` | Клиентский приватный ключ |
| `skip-tls-verify` | Отключить проверку сертификата сервера |
| `from` | Скопировать конфигурацию endpoint из существующего контекста |

#### Метаданные, влияющие на поведение CLI

Помимо описания, в секции `Metadata` файла `meta.json` может присутствовать поле `GODEBUG`. CLI читает его и устанавливает соответствующую переменную окружения, если она не задана пользователем. Механизм используется для обхода ограничений Go-библиотеки x509 — например, `GODEBUG=x509negativeserial=1` разрешает приём сертификатов с отрицательным серийным номером. Это поведение устарело и не соответствует RFC 5280: оно ослабляет защиту от коллизий и подделки сертификатов, поэтому применяйте его только для совместимости с legacy-инфраструктурой и никогда в продакшене.

Docker Desktop автоматически проставляет это поле в своём контексте `desktop-linux`; удалять его руками не нужно.

### Как Docker работает поверх SSH

Механизм подключения через `ssh://` часто понимают неверно как проброс порта (туннель). Фактически CLI не создаёт локальный сокет и не пробрасывает порты — он запускает на удалённой машине вспомогательную команду демона и передаёт поток HTTP API через SSH-канал:

```bash
# Что фактически выполняет CLI для контекста ssh://deploy@host
ssh -l deploy -- host "docker system dial-stdio"
```

`docker system dial-stdio` — служебная команда, проксирующая поток stdin/stdout в сокет демона. Она присутствует в Docker Engine начиная с версии 18.09 и не должна вызываться вручную.

Если в URL указать путь к сокету, отличному от стандартного, CLI добавит `--host` к удалённой команде:

```console
$ docker context create ssh-custom --docker "host=ssh://deploy@host/var/run/docker-rootless/docker.sock"
```

```bash
# Что выполняется на удалённом хосте
docker --host=unix:///var/run/docker-rootless/docker.sock system dial-stdio
```

Это единственный способ управлять демоном с нестандартным путём сокета по SSH и основная причина существования синтаксиса с компонентом пути в URL.

Ограничения синтаксиса `ssh://`, проверяемые при создании контекста:

- пароль в URL не допускается — только ключевая аутентификация;
- query-параметры и fragment запрещены;
- порт задаётся через `:порт`, пользователь — через `@пользователь`.

### Хранение контекстов на диске

Файлы контекстов лежат внутри каталога конфигурации клиента:

- **`~/.docker/config.json`** — поле `"currentContext"`, определяющее активный профиль. Если поле отсутствует, используется `default`.
- **`~/.docker/contexts/meta/<хэш>/meta.json`** — метаданные и endpoint каждого контекста.
- **`~/.docker/contexts/tls/<хэш>/docker/`** — сертификаты и ключи (`ca.pem`, `cert.pem`, `key.pem`).

Имя каталога — это SHA-256 от имени контекста в hex-виде. Проверить соответствие можно вручную:

```bash
# → fe9c6bd7a66301f49ca9b6a70b217107cd1284598bfc254700c989b916da791e
printf 'desktop-linux' | sha256sum      # Linux
printf 'desktop-linux' | shasum -a 256  # macOS

# Имя каталога контекста desktop-linux
ls ~/.docker/contexts/meta/
# → fe9c6bd7a66301f49ca9b6a70b217107cd1284598bfc254700c989b916da791e
```

Структура и права доступа:

```bash
find ~/.docker/contexts -type f -o -type d | sed "s|$HOME|~|"
# → ~/.docker/contexts/meta
# → ~/.docker/contexts/meta/fe9c.../meta.json
# → ~/.docker/contexts/tls
# → ~/.docker/contexts/tls/fe9c...            # права 0700
# → ~/.docker/contexts/tls/fe9c.../docker     # права 0700
# → ~/.docker/contexts/tls/fe9c.../docker/ca.pem   # права 0600
# → ~/.docker/contexts/tls/fe9c.../docker/cert.pem # права 0600
# → ~/.docker/contexts/tls/fe9c.../docker/key.pem  # права 0600
```

Содержимое `meta.json` для контекста с SSH-эндпоинтом:

```json
{
  "Name": "prod-vps",
  "Metadata": { "Description": "Production VPS" },
  "Endpoints": {
    "docker": {
      "Host": "ssh://deploy@prod.example.com",
      "SkipTLSVerify": false
    }
  }
}
```

**TLS-файлы копируются в хранилище контекста, а не читаются по исходному пути.** После создания контекста исходные `.pem` можно удалить — контекст продолжит работать. Это делает каталог контекстов самодостаточным, но означает, что ротация сертификатов требует явного обновления контекста.

### Изоляция каталога контекстов

Переменная `DOCKER_CONFIG` и глобальный флаг `--config` перенаправляют весь каталог конфигурации клиента, включая контексты. Это основной инструмент для тестирования и для изоляции нескольких профилей на одной машине:

```bash
# Отдельный набор контекстов без влияния на основной
export DOCKER_CONFIG=/tmp/docker-cfg
docker context create test-ssh --docker "host=ssh://deploy@10.0.0.5"
docker context ls
# → NAME     DESCRIPTION   DOCKER ENDPOINT            ERROR
# → default *               unix:///var/run/docker.sock
# → test-ssh                ssh://deploy@10.0.0.5

# Значение по умолчанию задаётся флагом
docker --config /tmp/docker-cfg context ls
```

Актуальное значение каталога всегда видно в справке:

```console
$ docker --help | grep -- --config
      --config string      Location of client config files (default "/home/user/.docker")
```

## Практические сценарии

### Сценарий 1: Удалённое управление через SSH (рекомендуемый)

Самый безопасный способ управления удалённым сервером: использует существующую SSH-инфраструктуру и не требует открытия портов Docker-демона.

**Предварительные требования:** на удалённом хосте установлен Docker Engine 18.09 или новее, а пользователь имеет доступ к сокету демона (членство в группе `docker` либо права на чтение/запись в `/var/run/docker.sock`).

1. Создайте контекст, указав SSH-адрес:
   ```bash
   docker context create remote-vps --description "Production VPS" --docker "host=ssh://deploy@server-ip"
   # → remote-vps
   # → Successfully created context "remote-vps"
   ```
2. Переключитесь на него:
   ```bash
   docker context use remote-vps
   # → remote-vps
   # → Current context is now "remote-vps"
   ```
3. Проверьте, что CLI действительно работает с удалённым демоном:
   ```bash
   docker info | grep -E "Context|Server Version"
   # → Context:    remote-vps
   # → Server Version: 29.8.2
   ```
4. Для выполнения разовой команды без переключения используйте флаг `--context`:
   ```bash
   docker --context remote-vps ps
   ```

**Ограничение SSH-ключа.** Поскольку удалённо выполняется ровно `docker system dial-stdio`, ключ можно зажать на эту команду в `~/.ssh/authorized_keys` на сервере:

```bash
command="docker system dial-stdio",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA... docker-deploy
```

Опция `command=` делает ключ бесполезным для любой другой задачи: даже при компрометации ключа атакующий не получит интерактивную сессию на сервере, а только канал к Docker API. Учтите, что доступ к Docker API эквивалентен root-доступу к хосту, поэтому ограничение `command=` снижает, но не устраняет риск.

Для ускорения повторных подключений включите мультиплексирование в `~/.ssh/config`:

```text
Host *
    ControlMaster auto
    ControlPath ~/.ssh/control-%C
    ControlPersist yes
```

Без этого каждая команда `docker ps` открывает новый SSH-сеанс с полным циклом аутентификации.

### Сценарий 2: Удалённое управление через mTLS (корпоративный стандарт)

Применяется, когда SSH недоступен или требуется аутентификация через корпоративный PKI. Генерация CA и сертификатов описана в **[Защита хоста и демона Docker](./Docker_security/host_daemon_hardening.md)** и **[daemon.json — полный референс](./docker_daemon_config.md)**; здесь — только создание контекста.

1. Разместите сертификаты в каталоге конфигурации клиента:
   ```bash
   mkdir -pv ~/.docker
   cp -v ca.pem cert.pem key.pem ~/.docker/
   chmod 0400 ~/.docker/key.pem
   chmod 0444 ~/.docker/ca.pem ~/.docker/cert.pem
   ```
2. Создайте контекст, указав пути к сертификатам:
   ```bash
   docker context create prod-swarm \
     --description "Swarm manager, mTLS" \
     --docker "host=tcp://manager.example.com:2376,ca=~/.docker/ca.pem,cert=~/.docker/cert.pem,key=~/.docker/key.pem"
   ```
3. Проверьте, что TLS-материал действительно сохранён в контексте:
   ```bash
   docker context inspect prod-swarm
   # → "TLSMaterial": { "docker": [ "ca.pem", "cert.pem", "key.pem" ] }
   ```
4. Переключитесь и убедитесь в успешном соединении:
   ```bash
   docker context use prod-swarm
   docker info | grep -E "Context|Server Version"
   ```

**Отладка проверки сертификата.** Если нужно временно исключить проверку сертификата сервера (только для диагностики — не для продакшена):

```bash
docker context create debug-tls --docker "host=tcp://manager:2376,ca=~/.docker/ca.pem,skip-tls-verify"
```

Если после диагностики причина не найдена, удалите такой контекст и восстановите рабочий.

**Ротация сертификатов.** Пути в контексте фиксируются один раз, поэтому после выпуска новых сертификатов обновите контекст:

```bash
docker context update prod-swarm --docker "host=tcp://manager:2376,ca=~/.docker/ca-new.pem,cert=~/.docker/cert-new.pem,key=~/.docker/key-new.pem"
```

### Сценарий 3: Локальные рантаймы и Rootless Docker

Установка rootless-демона создаёт контекст `rootless` автоматически и сразу переключается на него:

```console
$ dockerd-rootless-setuptool.sh install
[INFO] Creating CLI context "rootless"
Successfully created context "rootless"
[INFO] Using CLI context "rootless"
Current context is now "rootless"
[INFO] Some applications may require the following environment variable too:
export DOCKER_HOST=unix:///run/user/1000/docker.sock
```

Повторный `docker context create rootless` завершится ошибкой `context "rootless" already exists`. Вместо этого проверьте состояние и при необходимости переключитесь:

```bash
docker context ls
docker context use rootless
docker info | grep -A2 "Security Options"
# →  seccomp
# →   Profile: builtin
# →  rootless
```

Сокет rootless-демона лежит по пути, зависящему от UID, поэтому значение `/run/user/1000/` подставляется автоматически. Для сторонних приложений, которые читают только `DOCKER_HOST`, документированный обходной путь — экспорт переменной (как в выводе `setuptool`), но для самого Docker CLI контекст предпочтительнее.

Переключение между стандартным Docker Desktop и альтернативами вроде Colima выполняется теми же командами — каждая среда регистрирует свой контекст:

```bash
docker context ls
docker context use colima
docker info | grep Context
# → Context:    colima
```

Если контекст указывает на сокет, который больше не существует (например, после остановки Colima), рабочий контекст не восстановит соединение — вернитесь на `default` или на контекст Docker Desktop:

```bash
docker context use default
```

### Сценарий 4: Перевод скриптов с `DOCKER_HOST` на контексты

Скрипты, экспортирующие `DOCKER_HOST`, можно перевести на контексты без переписывания тела скрипта. Создайте контекст в окружении, где переменная уже выставлена, — CLI сохранит текущий endpoint как новый профиль:

```bash
# Внутри setup-скрипта
export DOCKER_HOST=tcp://manager.example.com:2376
export DOCKER_TLS_VERIFY=1

docker context create legacy-host
# → legacy-host
# → Successfully created context "legacy-host"

unset DOCKER_HOST DOCKER_TLS_VERIFY
docker context use legacy-host
```

Это также удобный способ «заморозить» адрес хоста, который раньше задавался вручную в `.bashrc`.

Полное клонирование контекста вместе с сертификатами выполняется флагом `--from`:

```bash
docker context create prod-vps-clone --from prod-vps --description "Клон прода"
docker context inspect prod-vps-clone | grep -A4 TLSMaterial
# → "TLSMaterial": { "docker": [ "ca.pem", "cert.pem", "key.pem" ] }
```

Ключевое различие: `--docker from=<имя>` копирует **только конфигурацию endpoint**, без TLS-материала. Для mTLS-контекста такой клон останется без сертификатов:

```console
$ docker context create endpoint-only --docker from=prod-swarm
endpoint-only
Successfully created context "endpoint-only"

$ docker context inspect endpoint-only
    "TLSMaterial": {},
```

Используйте `--from`, если нужна полная копия, и `--docker from=` — если нужно переиспользовать адрес и схему, а сертификаты задать заново.

### Сценарий 5: Передача контекста между хостами

Контексты переносимы через архив, что избавляет от повторной генерации сертификатов на каждой машине.

Экспорт (имя файла по умолчанию — `<имя>.dockercontext`, права `0600`):

```console
$ docker context export prod-swarm
Written file "prod-swarm.dockercontext"
```

Импорт на целевом хосте:

```console
$ docker context import prod-swarm prod-swarm.dockercontext
prod-swarm
Successfully imported context "prod-swarm"

$ docker context ls
```

Поддерживаются форматы tar и zip, общий размер импортируемых данных ограничен 10 МиБ.

**Архив содержит приватные ключи** в `tls/docker/key.pem`. Передавайте его по защищённому каналу, не коммитьте в репозиторий и удаляйте после импорта:

```bash
chmod 600 prod-swarm.dockercontext
# Передача
scp prod-swarm.dockercontext admin@target:/tmp/
# Импорт на целевом хосте
docker context import prod-swarm /tmp/prod-swarm.dockercontext
shred -u /tmp/prod-swarm.dockercontext   # или rm -f
```

Для передачи по stdout используйте `-`:

```bash
docker context export prod-swarm - | ssh admin@target 'docker context import prod-swarm -'
```

### Сценарий 6: Отображение активного контекста в prompt

Для предотвращения ошибок рекомендуется интегрировать имя текущего контекста в prompt оболочки.

- **Starship:** Автоматически отображает значок Docker и имя контекста.
- **Oh My Zsh:** Используйте плагин `docker` и тему, поддерживающую отображение контекста.

Быстрая проверка без сторонних модулей:

```bash
PS1='[\u@\h $(docker context show 2>/dev/null)]\w \$ '
```

## Операции и команды

### Справочник CLI

| Команда | Описание |
|:---|:---|
| `docker context ls` | Список всех контекстов; активный отмечен `*` |
| `docker context ls -q` | Только имена контекстов |
| `docker context ls --format json` | Машиночитаемый вывод |
| `docker context show` | Показать имя текущего активного контекста |
| `docker context use <NAME>` | Установить контекст по умолчанию |
| `docker context create <NAME>` | Создать новый профиль |
| `docker context update <NAME>` | Изменить описание или endpoint существующего контекста |
| `docker context inspect <NAME>...` | Подробная информация в формате JSON; допускает несколько имён |
| `docker context export <NAME> [FILE]` | Экспорт контекста в архив (по умолчанию `<NAME>.dockercontext`) |
| `docker context import <NAME> <FILE>` | Импорт контекста из архива tar или zip |
| `docker context rm <NAME>...` | Удаление профиля (`-f` — для активного) |

Полезные шаблоны форматирования:

```bash
# Показать имя и endpoint каждого контекста
docker context ls --format '{{.Name}} → {{.DockerEndpoint}}'
# → default → unix:///var/run/docker.sock
# → prod-vps → ssh://deploy@prod.example.com

# Вывести только текущий контекст
docker context ls --format '{{.Current}}' | grep true
```

Извлечение полей из `inspect` (шаблоны Go применяются к структуре `store.Metadata`, поэтому описание доступно через вложенный `Metadata.Description` только в части команд; универсальный способ — разбор JSON):

```bash
docker context inspect prod-swarm | jq -r '.[0].Metadata.Description'
# → Swarm manager, mTLS
```

### Приоритет переменных окружения и флагов

Docker CLI разрешает целевой демон в строгом порядке. Первый подходящий источник выигрывает, остальные игнорируются:

1. Флаг `--context` / `-c` — абсолютный приоритет.
2. Флаг `--host` / `-H` — подключение напрямую по адресу, контексты не используются.
3. Переменная `DOCKER_HOST` — подключение напрямую по адресу, контексты не используются.
4. Переменная `DOCKER_CONTEXT` — выбор контекста по имени.
5. Поле `currentContext` в `~/.docker/config.json` — результат `docker context use`.
6. Контекст `default`.

Важное следствие: если установлена `DOCKER_HOST`, `docker context show` вернёт `default`, даже если активным выбран другой профиль. Проверить окружение:

```bash
env | grep -E '^DOCKER'
# → DOCKER_HOST=ssh://deploy@prod.example.com
```

Одновременное указание `--host` и `--context` считается неоднозначным и приводит к ошибке:

```console
$ docker --context prod-vps --host tcp://10.0.0.5:2376 ps
conflicting options: cannot specify both --host and --context
```

Обратите внимание на порядок пунктов 2 и 3 относительно `DOCKER_CONTEXT`: переменная `DOCKER_HOST` проверяется раньше, поэтому при заданных `DOCKER_HOST` и `DOCKER_CONTEXT` побеждает `DOCKER_HOST`.

**Рекомендация:** если команды Docker ведут себя неожиданно, проверьте `env | grep DOCKER`. Для корректной работы контекстов выполните `unset DOCKER_HOST`.

## Диагностика (Troubleshooting)

### Ошибки создания и изменения контекста

| Сообщение | Причина | Решение |
|:---|:---|:---|
| `context "prod-vps" already exists` | Контекст с таким именем уже есть | Выберите другое имя либо измените существующий через `docker context update` |
| `"default" is a reserved context name` | Попытка создать контекст с зарезервированным именем | Переименуйте профиль; `default` всегда доступен как виртуальный контекст |
| `context name "a" is invalid, names are validated against regexp "^[a-zA-Z0-9][a-zA-Z0-9_.+-]+$"` | Имя короче двух символов либо содержит недопустимые символы | Допустимы латинские буквы, цифры и разделители `_`, `.`, `+`, `-`; первый символ — буква или цифра |
| `cannot use --docker flag when --from is set` | Одновременно заданы взаимоисключающие флаги | Используйте только `--from` либо только `--docker` |
| `ssh host connection is not valid: invalid SSH URL: plain-text password is not supported` | В URL `ssh://` указан пароль | Уберите пароль, настройте ключевую аутентификацию |
| `ssh host connection is not valid: invalid SSH URL: query parameters are not allowed: "x=1"` | В URL `ssh://` передан query-параметр | Оставьте только `ssh://user@host[:port][/path]` |
| `unable to create docker endpoint config: invalid docker endpoint options: ...` | Некорректный набор ключей в `--docker` | Проверьте имена ключей: `host`, `ca`, `cert`, `key`, `skip-tls-verify`, `from` |

### Ошибки подключения

- **`Cannot connect to the Docker daemon at ssh://...`** — проверьте доступность SSH: `ssh deploy@server-ip true`. Если вход работает, а Docker CLI — нет, скорее всего у пользователя нет доступа к сокету демона на удалённом хосте; проверьте членство в группе `docker` или права на `/var/run/docker.sock`.
- **`Permission denied while trying to connect to the Docker daemon socket`** — та же причина на локальном хосте: текущий пользователь не в группе `docker`. Требуется перелогинивание в систему, чтобы членство в группе вступило в силу.
- **`Error response from daemon: ... certificate has expired`** — истёк срок действия сертификата сервера. Обратите внимание: транспорт `ssh://` не использует TLS на стороне клиента, поэтому такая ошибка указывает именно на mTLS-подключение к порту 2376.
- **`x509: certificate signed by unknown authority`** — в контексте указан не тот CA. Сверьте `ca` с сертификатом, которым подписан сертификат сервера, и проверьте, что имя из `subjectAltName` сертификата сервера соответствует имени хоста из `host`.
- **`Context ignored` / команды идут не туда** — перекрыта переменная `DOCKER_HOST` или флаг `-H`. Выполните `env | grep DOCKER` и `docker context show`; если выводится `default` при ожидаемом другом имени, причина найдена.
- **`unable to resolve docker endpoint: context "ghost": context not found`** — имя контекста указано с опечаткой либо каталог контекстов удалён вручную. Проверьте `docker context ls` и наличие каталога `~/.docker/contexts/meta/`.
- **Ошибка подключения к локальному сокету после смены рантайма** — контекст указывает на сокет, который исчез (например, после остановки Colima). Вернитесь на рабочий контекст: `docker context use default`.

### Проверка состояния

Для быстрой диагностики используйте следующие команды:

```bash
# Какой контекст активен прямо сейчас (с учетом всех переменных и флагов)
docker context show

# Какой демон отвечает — читается из раздела Client в docker info
docker info | grep -E "Context|Server Version|Operating System"

# Не пуст ли столбец ERROR — признак того, что метаданные контекста не читаются
docker context ls
```

Столбец `ERROR` в `docker context ls` заполняется, когда CLI не смог загрузить метаданные контекста и подставил в список заглушку с текстом ошибки. Отсутствующие или повреждённые TLS-файлы в этом столбце **не** отражаются — они проявляются уже при подключении. Если контекст создан с сертификатами, а при подключении возникает ошибка TLS, проверьте наличие файлов:

```bash
ls -l ~/.docker/contexts/tls/*/docker/
```

### Удаление и откат

Удаление контекста необратимо — удаляются и метаданные, и скопированные сертификаты.

```bash
# Активный контекст требует подтверждения
docker context rm prod-vps
# → context "prod-vps" is in use, set -f flag to force remove

# Принудительное удаление
docker context rm -f prod-vps
# → prod-vps
```

Полная очистка:

```bash
# Вернуться к локальному демону
docker context use default

# Удалить все пользовательские контексты
docker context ls -q | grep -v '^default$' | xargs docker context rm -f

# Удалить хранилище целиком (контексты и скопированные сертификаты)
rm -rf ~/.docker/contexts
```

Порядок важен: сначала `docker context use default`. Если удалить каталог контекстов, не сбросив `currentContext` в `~/.docker/config.json`, каждая команда Docker будет падать с `context not found` до тех пор, пока значение не перезапишется:

```console
$ docker ps
Failed to initialize: unable to resolve docker endpoint: context "prod-vps": context not found
```

Если после любых манипуляций клиент ведёт себя непредсказуемо, контекст `default` не зависит ни от одного файла в `~/.docker/contexts`, поэтому `docker context use default` — надёжная точка отката.

## Лучшие практики

1. **Давайте контекстам осмысленные имена.** Имя попадает в приглашение оболочки и в CI-логи. Формат `<среда>-<хост>` (`prod-manager-1`, `stage-build`) читается лучше, чем `ctx1` или `my-context`. Имя нельзя изменить — `docker context update` правит только описание и endpoint, поэтому ошибку в имени приходится исправлять удалением и пересозданием.
2. **Храните описания.** `--description` — единственное место, где можно зафиксировать, для чего предназначен контекст: `docker context ls` показывает его в колонке `DESCRIPTION`.
3. **Не коммитьте `.dockercontext` и `key.pem`.** Архив экспорта содержит приватный ключ клиента; доступ к Docker API равен root-доступу к хосту.
4. **Ограничивайте SSH-ключ через `command=`.** Ограничение `command="docker system dial-stdio"` бесплатно убирает интерактивный доступ к серверу по ключу, предназначенному для Docker.
5. **Не используйте `skip-tls-verify` в постоянных контекстах.** Это диагностическая настройка: она отключает проверку сертификата сервера, и злоумышленник в сети может подменить демон.
6. **Включайте мультиплексирование SSH.** `ControlMaster auto` в `~/.ssh/config` убирает повторную аутентификацию из каждой команды Docker.
7. **Изолируйте тестовые окружения через `DOCKER_CONFIG`.** Это позволяет проверять конфигурацию, не затрагивая рабочие профили.
8. **Помните о копировании сертификатов.** Контекст хранит копию `.pem`, поэтому ротация сертификатов требует явного `docker context update` — иначе CLI продолжит предъявлять отозванный сертификат.
9. **В CI не полагайтесь на локальный `currentContext`.** Явно передавайте имя контекста (`docker --context <NAME>` или `DOCKER_CONTEXT`) — состояние домашнего каталога раннера не контролируется вами.

## Дополнительная информация

### Docker Context vs Build Context

Не путайте эти понятия — они никак не связаны:

- **Docker Context:** Определяет, **куда** (на какой сервер) отправляются команды CLI.
- **Build Context:** Набор локальных файлов, передаваемых демону для сборки образа. Подробнее см. **[Контекст сборки (Build Context)](./Dockerfile/dockerfile_build_context.md)**.

### Ограничения и особенности

- Имя контекста изменить нельзя — только описание и endpoint.
- Тип эндпоинта всегда один — `docker`. Поддержка Kubernetes в `docker context create --kubernetes` была удалена в Docker CLI v23.0 (депрекация с v20.10); для кластеров Kubernetes используйте нативные контексты `kubectl`.
- Имя из одного символа не проходит валидацию — минимум два символа.
- `docker context inspect` для несуществующего контекста печатает `[]` в stdout и текст ошибки в stderr, поэтому при разборе вывода проверяйте код возврата.
- Колонки `docker context ls` зависят от версии: в Docker CLI 29.x выводятся `NAME`, `DESCRIPTION`, `DOCKER ENDPOINT`, `ERROR`. Не полагайтесь на порядок колонок в скриптах — используйте `--format` с явными именами полей.

### См. также

- **[Docker Context в CI/CD для Docker Swarm](../Docker_swarm/CI_CD/docker_context_setup.md)** — настройка mTLS-контекстов для пайплайнов, ротация сертификатов, изоляция окружений на раннерах.
- **[Безопасность Docker-демона](./Docker_security/host_daemon_hardening.md)** — защита сокета, ограничение SSH-доступа, hardening демона.
- **[daemon.json — полный референс](./docker_daemon_config.md)** — настройка TLS и портов на стороне демона.
- **[Команды Docker CLI](./docker_commands.md)** — справочник команд Docker.
- **[Docker Buildx](./Dockerfile/dockerfile_buildkit.md)** — сборщики и работа с rootless-демоном.
- **[Защита Docker-хоста по SSH](./Docker_security/ssh-agent-rootless.md)** — ssh-agent и rootless-контексты в связке.
