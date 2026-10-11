# SSH-agent в rootless Docker без экспозиции приватного ключа

**Актуально для:** Docker Engine 29.x. rootless Docker (начиная с Docker 20.10). Linux (ядро 5.11+ с поддержкой user namespaces и непривилегированного overlayfs; на ядрах 4.18–5.10 требуется fuse-overlayfs — см. «Граничные случаи и ограничения»).

SSH‑доступ используется повсеместно: для работы с репозиториями, серверами, автоматизации и множества других задач. Но как часто мы задумываемся о том, что доступный приложению приватный ключ может быть украден?

Можно заменить SSH другим способом аутентификации, например токеном. Но если этот токен доступен самому процессу, проблема остаётся прежней: при компрометации его тоже можно прочитать и унести. Мы лишь заменим один секрет другим. Поэтому задача здесь не в выборе SSH, токена или другого механизма, а в том, чтобы сам секрет вообще не был доступен процессу.

Даже если мы доверяем собственному ПО, в нём и его зависимостях могут появиться уязвимости. При компрометации процесса доступные ему секреты тоже оказываются под угрозой. Эта проблема особенно важна для автоматизированных систем, где процессы получают доступ к инфраструктуре от имени пользователя: любой компонент в цепочке аутентификации может стать пунктом компрометации секрета.

Данный документ описывает архитектуру, в которой процесс может полноценно пользоваться SSH‑доступом, но возможность получить сам приватный ключ исключается на уровне архитектуры.

## Предварительные требования

- **Docker Engine 29.x** с включённым rootless режимом (т.е. `dockerd` запущен через `dockerd-rootless.sh` от имени непривилегированного пользователя; установка и диагностика — в [Установке Docker на Ubuntu](../docker_install_ubuntu.md))
- **Linux** с ядром 5.11+ и включёнными user namespaces (`kernel.unprivileged_userns_clone=1` или `user.max_user_namespaces > 0`). Ядро 5.11+ необходимо для непривилегированного overlayfs в user namespace, который используется контейнерным хранилищем (containerd snapshotter) Docker 29 по умолчанию; на ядрах ниже 5.11 rootless-контейнеры с Docker 29 не стартуют (moby/moby#53029)
- **cgroups v2 и systemd** — rootless-режим поддерживает управление cgroup только через делегирование systemd (проверка и настройка — в [Защите хоста и демона](./host_daemon_hardening.md))
- **Пакет `uidmap`** на хосте (предоставляет `newuidmap` и `newgidmap`, необходимые для rootless Docker)
- **Файлы `/etc/subuid` и `/etc/subgid`** с минимум 65 536 подчинёнными UID/GID для пользователя rootless
- **Пакет `util-linux`** на хосте (предоставляет `setpriv` для запуска `ssh-agent` с нужным UID/GID)
- **OpenSSH** на хосте (`ssh-agent`, `ssh-keyscan`)
- **Приватный SSH-ключ** на хосте с минимальными правами доступа (`0600` или `0400`)
- **Docker контейнер** с установленным `openssh-client` внутри

## Определения

**SSH-агент (`ssh-agent`)** — фоновый процесс, хранящий расшифрованные приватные ключи в оперативной памяти и выполняющий операции аутентификации от имени клиентов через Unix‑сокет.

**SSH_AUTH_SOCK** — переменная окружения, указывающая путь к Unix‑сокету `ssh-agent`. Клиенты OpenSSH используют её для обращения к агенту вместо работы с файлом ключа напрямую.

**Rootless Docker** — режим работы, при котором демон и контейнеры запускаются от имени непривилегированного пользователя через пользовательские пространства имён (user namespaces).

**UID/GID mapping** — сопоставление идентификаторов пользователей и групп между пространством имён контейнера и хостом. В rootless‑режиме UID 0 внутри контейнера отображается на непривилегированный UID хоста, а остальные UID берутся из диапазона subordinate UID.

**Subordinate UID/GID range** — диапазон идентификаторов, задаваемый в `/etc/subuid` и `/etc/subgid`, которые ядро использует для маппинга в user namespaces.

**Unix-сокет (AF_UNIX)** — механизм межпроцессного взаимодействия в Linux, при котором проверка доступа выполняется на стороне ядра по учётным данным (UID/GID) процесса, подключившегося к сокету (на Linux — через `SO_PEERCRED` / `getpeereid()`).

**setpriv** — утилита из пакета `util-linux`, позволяющая запускать процесс с заданными UID/GID и минимальными привилегиями без создания отдельного пользователя или SUID-битов на бинарнике.

## Базовые концепции

### Проблема: секрет доступен процессу

Прямое монтирование `~/.ssh` или передача приватного ключа через переменные окружения / секреты делает материал ключа доступным для чтения процессу внутри контейнера. При компрометации контейнера ключ может быть передан злоумышленнику.

Задача не в замене SSH на другой механизм, а в том, чтобы секрет вообще не попадал в пространство имён контейнера.

### Архитектура: сокет ssh-agent вместо ключа

Вместо передачи приватного ключа в контейнер передаётся только Unix‑сокет `ssh-agent`. Процесс внутри контейнера работает с SSH через этот сокет, используя переменную `SSH_AUTH_SOCK`. При этом материал ключа остаётся на хосте в памяти `ssh-agent`.

Схема:
```
Хост: ssh-agent (загруженный приватный ключ)
  ↓ Unix-сокет (bind mount)
Контейнер: OpenSSH клиент → SSH_AUTH_SOCK → ssh-agent
```

Контейнер может использовать выданные ему SSH‑права для доступа к разрешённым ресурсам, но не получает доступ к приватному ключу.

### Ограничения схемы

- **Делегированный доступ:** процесс внутри контейнера может использовать загруженную SSH‑идентичность через агент, пока имеет доступ к сокету. При компрометации работающего контейнера злоумышленник может выполнять SSH‑операции от имени ключа.
- **Без прямого чтения ключа:** файл приватного ключа не монтируется в контейнер и не доступен его процессам.
- **Разделение идентичностей:** для разных контейнеров можно использовать отдельные ssh‑agent и ключи, ограничивая тем самым blast radius.

## Практические сценарии

### Зачем контейнеру SSH

Типичные сценарии:
- работа с приватными Git‑репозиториями по SSH;
- выполнение команд на удалённых серверах;
- передача файлов через `scp` или `rsync`;
- автоматизированное развёртывание;
- доступ к Git‑сабмодулям через SSH;
- работа инструментов, использующих OpenSSH и `SSH_AUTH_SOCK`.

Сборка образов (build-time) — отдельный сценарий: для него в BuildKit есть нативный проброс SSH (`docker buildx build --ssh default=$SSH_AUTH_SOCK`), который не требует монтирования сокета в работающий контейнер. См. [Безопасность builder'а BuildKit](./buildx_builder_security.md) и [Контекст сборки Dockerfile](../Dockerfile/dockerfile_build_context.md). Данный документ описывает именно runtime-доступ.

### Альтернатива: внешний сервис для операций с Git

Вместо передачи SSH в контейнер можно выносить операции с Git на отдельный сервис (например, CI/CD runner или bastion host). Однако такой сервис не всегда заменяет локальный git, особенно когда приложению нужна собственная рабочая копия в контейнере.

Если контейнер и внешний сервис используют общую записываемую рабочую копию, процесс внутри контейнера может изменить её содержимое, в том числе Git hooks. Если сервис запускает Git hooks из этой копии, изменённый hook может выполниться в окружении сервиса с его правами доступа, включая доступные ему секреты.

Этот сценарий применим только тогда, когда сервис использует общую рабочую копию, запускает Git hooks и не изолирует их выполнение. Если hooks отключены или выполняются в изолированной среде без секретов, такой сценарий невозможен.

При использовании стороннего сервиса его реализация и модель доступа становятся дополнительной границей доверия, которую необходимо отдельно оценивать.

В рассматриваемом сценарии контейнеру нужен именно локальный OpenSSH с доступом к собственной рабочей копии.

### Теория: UID/GID mapping в rootless Docker

В Linux ядро проверяет права доступа по UID/GID. В конфигурации без user namespace UID процесса внутри контейнера численно совпадает с его UID на хосте.

В rootless Docker используется user namespace, поэтому UID внутри контейнера и на хосте различаются. Например, процесс с UID 1000 внутри контейнера может быть представлен на хосте как UID 100999.

Важно различать:
- **UID внутри контейнера** — идентификатор в контейнерном окружении;
- **UID на хосте** — идентификатор того же процесса, каким его видит хост;
- **/etc/subuid и /etc/subgid** — диапазоны идентификаторов, используемые Docker для преобразования.

Для `ssh-agent` важен именно UID на стороне хоста, потому что проверка клиента Unix‑сокета выполняется ядром и процессом `ssh-agent` в окружении хоста.

В rootless‑режиме Docker запускает daemon и контейнеры от непривилегированного пользователя хоста. Пример сопоставления:

```
host  UID 999 (rootless-docker) → container UID 0 (root)
host  GID 999 → container GID 0 (root)
```

```
container UID 1000 (app) → host UID 100999 (UNDEFINED)
container GID 1000 (app) → host GID 100999 (UNDEFINED)
```

Так можно посмотреть текущее сопоставление внутри контейнера:

```bash
cat /proc/self/uid_map
```

Предположим, у нас много пользователей. Вот такие UID они будут получать:

```
container UID 0     → host UID 999
container UID 1     → host UID 100000
container UID 2     → host UID 100001
...
container UID 1000  → host UID 100999
```

Проглядывается формула для UID N >= 1:

```
host UID = subuid_start + N - 1
```

Docker использует такую схему в rootless‑режиме: UID 0 контейнера отображается на пользователя, запустившего rootless Docker, а остальные UID берутся из subordinate UID range. Для GID применяется аналогичный механизм.

Диапазоны определяются файлами `/etc/subuid` и `/etc/subgid` для пользователей и групп соответственно.

Пример файла `/etc/subuid`:

```
rootless-docker:100000:65536
john:165536:65536
ci-runner:231072:65536
```

Подробнее: [Rootless UID/GID mapping](https://docs.docker.com/engine/security/rootless/uid-gid-mapping/).

### Почему прямое монтирование SSH_AUTH_SOCK не работает для non-root UID

Обычный пример проброса ssh-agent в Docker:
```bash
docker run \
    -e SSH_AUTH_SOCK=/ssh-agent \
    -v "$SSH_AUTH_SOCK:/ssh-agent" \
    image-name
```

В конфигурациях без user namespace это часто работает. Но в rootless‑контейнере процесс работает от UID 1000, который на хосте представлен как UID 100999. Если `ssh-agent` на хосте запущен пользователем `rootless-docker` с UID 999, то с точки зрения хоста это разные пользователи. В результате `ssh-agent` отклонит соединение из-за несовпадения UID.

Открытие файлового доступа к сокету всем пользователям (например, `chmod 0666 agent.sock`) не решает проблему: после успешного `connect()` `ssh-add -l` всё равно завершится ошибкой, потому что `ssh-agent` проверяет учётные данные подключившегося процесса (`getpeereid()`, на Linux — `SO_PEERCRED`) и отклоняет соединение, если UID пира не совпадает с UID процесса агента. Исключение — только пир с UID 0 (root), что недостижимо для non-root контейнера. Проверка выполняется в окружении хоста, поэтому сравниваются именно хостовые UID.

Поэтому вместо расширения прав сокета необходимо согласовать UID клиента и `ssh-agent`.

### Вычисление mapped UID/GID для контейнерного пользователя

Чтобы настроить сокет, нужно вычислить, какому UID/GID на хосте соответствует пользователь контейнера.

```bash
ROOTLESS_USER=rootless-docker
ROOTLESS_UID=$(id -u "$ROOTLESS_USER")

CONTAINER_UID=$(sudo -H -u "$ROOTLESS_USER" env DOCKER_HOST="unix:///run/user/$ROOTLESS_UID/docker.sock" docker run --rm image-name id -u app)
CONTAINER_GID=$(sudo -H -u "$ROOTLESS_USER" env DOCKER_HOST="unix:///run/user/$ROOTLESS_UID/docker.sock" docker run --rm image-name id -g app)

SUBUID_START=$(awk -F: -v user="$ROOTLESS_USER" '$1 == user { print $2; exit }' /etc/subuid)
SUBGID_START=$(awk -F: -v user="$ROOTLESS_USER" '$1 == user { print $2; exit }' /etc/subgid)

echo "host UID: $((SUBUID_START + CONTAINER_UID - 1))"
echo "host GID: $((SUBGID_START + CONTAINER_GID - 1))"
```

При `SUBUID_START=100000` и `CONTAINER_UID=1000` результат:
```
UID: 1000 -> 100999
GID: 1000 -> 100999
```

В дальнейшем `100999` используется как UID и GID процесса `ssh-agent` на хосте.

В системе автоматизации эти UID/GID следует рассчитывать автоматически. Изменять уже используемые диапазоны `/etc/subuid` и `/etc/subgid` следует только с учётом существующих файлов и запущенных контейнеров.

Если изменить UID/GID пользователя внутри контейнера или диапазоны в `/etc/subuid` и/или `/etc/subgid`, числовые UID/GID уже созданных на хосте файлов не изменятся, но изменится их соответствие владельцу внутри контейнера. В результате контейнер может перестать воспринимать эти файлы как принадлежащие ожидаемому пользователю.

### Настройка хоста

#### Структура каталогов

```
/opt/ssh-access/
├── .ssh/
│   └── git/
│       ├── key
│       └── key.pub
├── sockets/
│   └── git/
│       └── agent.sock
└── ssh_known_hosts
```

Каталог `.ssh` в контейнер не монтируется. Контейнер получает доступ только к `sockets/git/` и файлу доверенных ключей SSH‑серверов `ssh_known_hosts`.

#### Создание каталогов

```bash
BASE=/opt/ssh-access
MAPPED_UID=100999
MAPPED_GID=100999
ROOTLESS_USER=rootless-docker
ROOTLESS_GID=$(id -g "$ROOTLESS_USER")

sudo install -d \
    -o "$ROOTLESS_USER" \
    -g "$ROOTLESS_GID" \
    -m 0711 \
    "$BASE"

sudo install -d \
    -o "$MAPPED_UID" \
    -g "$ROOTLESS_GID" \
    -m 0710 \
    "$BASE/sockets"

sudo install -d \
    -o "$MAPPED_UID" \
    -g "$ROOTLESS_GID" \
    -m 0710 \
    "$BASE/sockets/git"
```

Права `0711` на корневом каталоге позволяют процессу с mapped UID пройти по известному пути внутри каталога, но не получать список содержимого. Владельцем каталогов с сокетами и самих сокетов будет mapped UID, от которого работает `ssh-agent`.

Группа rootless‑пользователя позволяет Docker использовать эти каталоги как источник bind mount.

Для каждой SSH‑идентичности создаётся отдельный каталог, потому что в контейнер будет монтироваться именно каталог, а не сам файл `agent.sock`. Это позволяет `ssh-agent` пересоздавать сокет внутри уже примонтированного каталога.

Схема позволяет использовать несколько независимых `ssh-agent` и сокетов. В нашей конфигурации каждый сокет соответствует отдельной SSH‑идентичности. Например, можно создать идентичности `git`, `gitlab` или отдельные `git-read` и `git-write` с соответствующими SSH‑ключами, имеющими разные уровни доступа.

Каждому контейнеру можно предоставить доступ только к каталогу нужной идентичности. Таким образом контейнер получает только тот SSH‑доступ, который ему разрешён.

#### Создание SSH‑ключа

```bash
sudo install -d \
    -o root \
    -g root \
    -m 0700 \
    "$BASE/.ssh/git"

sudo ssh-keygen \
    -t ed25519 \
    -f "$BASE/.ssh/git/key" \
    -C 'container-git' \
    -N ''
```

Каталог с ключом должен быть доступен только пользователю `root`. Будет создана пара ключей:
- `.ssh/git/key`
- `.ssh/git/key.pub`

Добавьте `key.pub` в сервисы, к которым требуется предоставить доступ.

#### Systemd-сервис для ssh-agent

```ini
# /etc/systemd/system/container-ssh-agent@.service

[Unit]
Description = SSH agent for container identity %i

[Service]
Type = simple

Environment = SSH_AUTH_SOCK=/opt/ssh-access/sockets/%i/agent.sock MAPPED_UID=100999 MAPPED_GID=100999

ExecStartPre = /usr/bin/rm -f -- /opt/ssh-access/sockets/%i/agent.sock

ExecStart = /usr/bin/setpriv \
            --reuid=${MAPPED_UID} \
            --regid=${MAPPED_GID} \
            --clear-groups --inh-caps=-all --bounding-set=-all --no-new-privs \
            /usr/bin/ssh-agent \
            -D \
            -a /opt/ssh-access/sockets/%i/agent.sock

# Ограниченное ожидание сокета (до 30 с), затем загрузка ключа
ExecStartPost = /bin/sh -c 'for i in $(seq 1 600); do [ -S "$SSH_AUTH_SOCK" ] && break; sleep 0.05; done; exec /usr/bin/ssh-add /opt/ssh-access/.ssh/%i/key'

Restart = on-failure

# Песочница службы: файловая система доступна только для чтения,
# кроме каталога сокета; ssh-agent использует только AF_UNIX
ProtectSystem = strict
ReadWritePaths = /opt/ssh-access/sockets/%i
ProtectHome = yes
PrivateTmp = yes
NoNewPrivileges = yes
ProtectKernelTunables = yes
ProtectControlGroups = yes
ProtectKernelModules = yes
RestrictAddressFamilies = AF_UNIX

[Install]
WantedBy = multi-user.target
```

`setpriv` запускает процесс с заданными UID/GID без создания отдельного пользователя или пользовательской сессии.

Используем `--clear-groups`, `--inh-caps=-all`, `--bounding-set=-all` и `--no-new-privileges`, чтобы убрать дополнительные группы, inheritable и bounding capabilities и не передавать процессу лишние привилегии. Такой набор флагов соответствует рекомендации `man setpriv` для максимально ограниченного запуска процесса.

Например, если запускающий пользователь состоит в группе `docker`, процесс формально сможет обращаться к `/var/run/docker.sock`, если права сокета это позволяют. `ssh-agent` этого штатно не делает, но при уязвимости или подмене процесса такие права уже становятся важны.

Цепочка запуска выглядит так: unit-файл остаётся root-службой, а только сам `ssh-agent` запускается с mapped UID с помощью `setpriv`. Это позволяет `ExecStartPost` прочитать приватный ключ, принадлежащий `root`.

Запуск службы:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now container-ssh-agent@git.service
systemctl status container-ssh-agent@git.service --no-pager -l
ls -ln /opt/ssh-access/sockets/git/agent.sock
ps -o pid,uid,gid,cmd -C ssh-agent
```

Ожидаемый результат: служба `active (running)`, сокет существует, а `ps` показывает процесс `ssh-agent` с UID/GID, равными mapped UID/GID (в примере — `100999`).

#### Ключи с паролем

Пример выше создаёт ключ без пароля (`-N ''`), что типично для автоматизации. Если ключ защищён паролем, `ssh-add` в `ExecStartPost` не сможет запросить его интерактивно — терминала нет. Решение — askpass-скрипт:

1. Создать скрипт, выводящий пароль ключа, доступный только `root`:
```bash
sudo install -o root -g root -m 0700 /dev/null /opt/ssh-access/askpass
# Содержимое — одна строка, выводящая пароль, например: printf '%s\n' 'пароль-ключа'
```
2. Добавить в unit-файл переменные окружения (отдельной строкой в `[Service]`):
```ini
Environment = SSH_ASKPASS=/opt/ssh-access/askpass SSH_ASKPASS_REQUIRE=force
```

`SSH_ASKPASS_REQUIRE=force` (OpenSSH 8.4+) заставляет `ssh-add` использовать askpass для ввода пароля всегда, даже без `DISPLAY`. Askpass-скрипт содержит секрет: он должен быть доступен только `root` (`0700`), иначе пароль ключа становится доступен процессам с тем же UID. Пример скрипта — иллюстративный; в production пароль лучше получать из менеджера секретов, а не хранить в файле.

#### Подготовка ssh_known_hosts

Не отключайте проверку ключа удалённого сервера через `StrictHostKeyChecking=no`. При такой настройке SSH‑клиент перестаёт проверять, действительно ли он подключается к ожидаемому серверу.

В рассматриваемой схеме используется отдельный файл `/opt/ssh-access/ssh_known_hosts`, в который заранее помещается проверенный ключ сервера.

Сначала создайте файл:
```bash
sudo install -o root -g root -m 0644 /dev/null /opt/ssh-access/ssh_known_hosts
```

Затем добавьте ключи серверов:
1. Получите публичный host key сервера: `ssh-keyscan -p 22 -t ed25519 git.example.com`
2. Сравните его fingerprint с ключом на самом сервере или с официально опубликованным fingerprint
3. Добавьте полученную строку в конец файла `/opt/ssh-access/ssh_known_hosts`

В примере запрашивается host key Ed25519. Если сервер использует ключ с другим алгоритмом, укажите его явно.

Как убедиться, что ключ настоящий?
- если сервер ваш, сравните результат с его публичным host key непосредственно на сервере
- повторный `ssh-keyscan` с другого компьютера может быть только дополнительной, но не основной проверкой

После проверки файл можно монтировать в контейнер только для чтения.

### Запуск контейнера

#### Образ контейнера

В Dockerfile необходимо создать непривилегированного пользователя:

```dockerfile
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 app \
    && useradd -m -u 1000 -g 1000 app && install -d -o app -g app /workspace

USER 1000:1000
```

#### Запуск

```bash
sudo -H -u "$ROOTLESS_USER" env DOCKER_HOST="unix:///run/user/$ROOTLESS_UID/docker.sock" docker run --rm -it \
    --user 1000:1000 \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m \
    --tmpfs /workspace:rw,uid=1000,gid=1000 \
    --workdir /workspace \
    -e SSH_AUTH_SOCK=/ssh-agent/agent.sock \
    -v /opt/ssh-access/sockets/git:/ssh-agent:ro \
    -v /opt/ssh-access/ssh_known_hosts:/etc/ssh/ssh_known_hosts:ro \
    ssh-client:test \
    sh
```

| Параметр | Назначение |
| :--- | :--- |
| `--rm` | Удалить контейнер после завершения. |
| `-it` | Интерактивный режим с терминалом. |
| `--user 1000:1000` | Непривилегированный пользователь. |
| `--read-only` | Корневая ФС только для чтения. |
| `--cap-drop ALL` | Удалить все Linux capabilities. |
| `--security-opt no-new-privileges` | Запретить получение дополнительных привилегий. |
| `--tmpfs /tmp` | Временная ФС с `nosuid`, `nodev`, `noexec`. |
| `--tmpfs /workspace` | Рабочий каталог в памяти с владельцем `1000:1000`. |
| `-e SSH_AUTH_SOCK` | Путь к сокету ssh-agent внутри контейнера. |
| `-v sockets/git:/ssh-agent:ro` | Каталог с сокетом только для чтения. |
| `-v ssh_known_hosts:/etc/ssh/ssh_known_hosts:ro` | Доверенные host keys только для чтения. |

### Проверка работы

На хосте:
```bash
# Проверить rootless-режим: в разделе Security Options должен быть указан `rootless`.
sudo -H -u "$ROOTLESS_USER" env DOCKER_HOST="unix:///run/user/$ROOTLESS_UID/docker.sock" docker info
# → Security Options:
#   seccomp
#    Profile: builtin
#   rootless
#   cgroupns

# Показать таблицу сопоставления UID внутри контейнера с UID на хосте.
# В выводе будет видно, какой диапазон UID внутри контейнера сопоставлен с subordinate UID-диапазоном на хосте.
# Эти значения должны соответствовать расчётам, выполненным выше.
sudo -H -u "$ROOTLESS_USER" env DOCKER_HOST="unix:///run/user/$ROOTLESS_UID/docker.sock" docker run --rm ssh-client:test cat /proc/self/uid_map
# →          0        999          1
# →          1     100000      65536
```

В контейнере:
```bash
id
# → uid=1000(app) gid=1000(app)

# Проверить права доступа к каталогу с сокетом
ls -ldn /ssh-agent
# → drwxr-x--- 1 1000 0 4096 ... /ssh-agent
# Права на хосте: `100999:<ROOTLESS_GID>`; внутри контейнера те же числа видны как `1000:0`

# Проверить права доступа к сокету
ls -ln /ssh-agent/agent.sock
# → srwxr-xr-x 1 1000 1000 0 ... agent.sock
# Сокетом владеет внутренний пользователь контейнера (1000:1000)

# Проверить ssh-agent
ssh-add -l
# → 256 SHA256:XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX container-git (ED25519)

# Проверить SSH
ssh git@git.example.com
# или
git clone git@git.example.com:group/project.git
```

После успешной проверки SSH‑доступ готов к работе. Осталось учесть особенности эксплуатации сокета и границы защиты этой схемы.

## Устранение неполадок

### Bind mount обновляет источник, но не каталог

При работе с каталогом сокета необходимо учитывать поведение bind mount.

Представим, что контейнер уже запущен с монтированием:

```
/opt/ssh-access/sockets/git
        ↓
/ssh-agent
```

Затем каталог на хосте удаляется, а затем добавляется заново:

```bash
rm -rf /opt/ssh-access/sockets/git
mkdir /opt/ssh-access/sockets/git
```

Путь снова имеет то же имя, но новый каталог является другим объектом файловой системы.

Существующий bind mount продолжает ссылаться на старый объект.

Проверить источник монтирования можно внутри контейнера:

```bash
findmnt -T /ssh-agent -o TARGET,SOURCE,FSTYPE,OPTIONS -n
```

В такой ситуации источник может отображаться как:

```
/opt/ssh-access/sockets/git//deleted
```

Создание нового каталога с тем же путём не изменяет существующее bind‑монтирование.

Если вы столкнётесь с такой проблемой, контейнер необходимо перезапустить или пересоздать.

Поэтому не следует удалять и пересоздавать сам каталог, используемый как источник bind mount. Файлы внутри него можно удалять и создавать заново.

### Перезапуск ssh-agent без пересоздания контейнера

Поскольку контейнер монтирует каталог, а не файл `agent.sock` напрямую, перезапуск службы `ssh-agent` не требует пересоздания контейнера:

```bash
sudo systemctl restart container-ssh-agent@git.service
```

Новый сокет создаётся внутри существующего каталога и становится доступен внутри контейнера.

### Проверка соответствия UID

Если `ssh-add -l` возвращает ошибку доступа, проверьте:
1. Какой UID/GID имеет процесс `ssh-agent` на хосте (`ps -o pid,uid,gid,cmd -C ssh-agent`).
2. Какой mapped UID соответствует пользователю контейнера (расчёт по `/etc/subuid`).
3. Что UID/GID каталога с сокетом совпадают с mapped UID/GID `ssh-agent`.
4. Что группу каталога составляет rootless‑пользователь, чтобы Docker мог смонтировать его.

### Типичные ошибки

| Симптом | Причина | Диагностика и решение |
| :--- | :--- | :--- |
| `ssh-add: Error connecting to agent: No such file or directory` | Сокет не создан или неверный путь в `SSH_AUTH_SOCK` внутри контейнера | `systemctl status container-ssh-agent@git`; `ls -ln /opt/ssh-access/sockets/git/` на хосте; сверить путь в `-e SSH_AUTH_SOCK` |
| `ssh-add: Error connecting to agent: Connection refused` | Источник bind mount удалён и создан заново (stale mount, см. выше) | Перезапустить или пересоздать контейнер |
| `The agent has no identities` | Ключ не загружен: `ExecStartPost` не отработал | `journalctl -u container-ssh-agent@git`; проверить права на ключ (`root:root`, `0600`) |
| `sign_and_send_pubkey: signing failed: agent refused operation` или `Agent admitted failure to sign using the key` | Агент отказал в подписи: агент заблокирован (`ssh-add -x`), ключ загружен с ограничениями (`ssh-add -c`, destination constraints) | `ssh-add -l` на хосте; разблокировать агент (`ssh-add -u`) или убрать ограничения при загрузке ключа |
| `Permission denied (publickey)` при `ssh`/`git` | Ключ предложен, но не авторизован на сервере | Сравнить fingerprint из `ssh-add -l` с `key.pub`, развёрнутым на сервере; проверить пользователя в `authorized_keys` / настройках Git‑хостинга |
| `uid mismatch: peer euid ... != uid ...` в журнале `ssh-agent` | Mapped UID контейнера не совпадает с UID процесса агента | Пересчитать mapped UID по `/etc/subuid`; проверить `--user` контейнера и владельца каталога с сокетом |

## Лучшие практики

1. **Никогда не монтируйте `~/.ssh` или приватные ключи в контейнер.** Всегда используйте сокет `ssh-agent` — агент выполняет подписи на хосте и никогда не передаёт материал ключа по своему каналу (`man ssh-agent`: «The agent will never send a private key over its request channel»).
2. **Используйте `setpriv` с минимальными привилегиями для `ssh-agent`.** Флаги `--clear-groups --inh-caps=-all --bounding-set=-all --no-new-privileges` убирают лишние группы и capabilities, снижая поверхность атаки хост-процесса.
3. **Песочница службы `ssh-agent`.** Директивы `ProtectSystem=strict` с `ReadWritePaths` и `RestrictAddressFamilies=AF_UNIX` ограничивают root-службу, читающую приватный ключ, даже при компрометации самого `ssh-agent`.
4. **Разделяйте идентичности для разных контейнеров.** Используйте отдельные ssh‑агенты и ключи (например, `git-read` и `git-write`) с разными уровнями доступа — это ограничивает blast radius при компрометации.
5. **Жёстко ограничивайте контейнер на этапе запуска.** Применяйте `--read-only`, `--cap-drop ALL`, `--security-opt no-new-privileges` и `--tmpfs` для рабочих каталогов, чтобы секреты и временные файлы не сохранялись на диск.
6. **Регулярно ротационируйте SSH-ключи** (процедура — в разделе «Ротация ключей и очистка»). Для сценариев со Swarm-секретами используйте versioning (`_v2`) для rolling update.
7. **Проверяйте соответствие UID перед деплоем.** Автоматизируйте расчёт mapped UID/GID и валидацию в CI/CD, чтобы избежать ошибок доступа к сокету в проде.

## Ротация ключей и очистка

### Ротация ключей

Рекомендуемый порядок замены ключа без простоя:

1. Создайте новую пару ключей в новой идентичности (например, `git-v2`):
```bash
sudo install -d -o "$MAPPED_UID" -g "$ROOTLESS_GID" -m 0710 "$BASE/sockets/git-v2"
sudo install -d -o root -g root -m 0700 "$BASE/.ssh/git-v2"
sudo ssh-keygen -t ed25519 -f "$BASE/.ssh/git-v2/key" -C 'container-git-v2' -N ''
```
2. Разверните `key.pub` на сервере или в настройках Git‑хостинга и дождитесь применения.
3. Запустите службу для новой идентичности и пересоздайте контейнеры с новым каталогом сокета:
```bash
sudo systemctl enable --now container-ssh-agent@git-v2.service
# В docker run замените: -v /opt/ssh-access/sockets/git-v2:/ssh-agent:ro
```
4. Убедитесь, что контейнеры работают с новым ключом (`ssh-add -l`, тестовый `git clone`).
5. Отключите старую идентичность и удалите старый ключ с сервера:
```bash
sudo systemctl disable --now container-ssh-agent@git.service
sudo rm -rf /opt/ssh-access/sockets/git /opt/ssh-access/.ssh/git
```

Для принудительного сброса загруженных идентичностей без остановки агента можно отправить ему `SIGUSR1` — `ssh-agent` удаляет все загруженные ключи при получении этого сигнала:

```bash
sudo kill -SIGUSR1 "$(systemctl show -p MainPID --value container-ssh-agent@git.service)"
```

После `SIGUSR1` ключи нужно загрузить заново (перезапуск службы выполняет `ssh-add` автоматически).

### Очистка (откат изменений)

Чтобы полностью удалить схему с хоста, для каждой созданной идентичности выполните:

```bash
sudo systemctl disable --now container-ssh-agent@git.service
sudo rm -f /etc/systemd/system/container-ssh-agent@.service
sudo systemctl daemon-reload
sudo rm -rf /opt/ssh-access
```

Не забудьте удалить развёрнутые публичные ключи из `authorized_keys` серверов и настроек Git‑хостинга — иначе они останутся действующими учётными данными.

## Граничные случаи и ограничения

- **Размер секрета:** SSH-ключи не имеют жёсткого лимита на размер, но слишком большие ключи могут вызвыть проблемы с буферами агента. Используйте Ed25519 (минимальный размер, максимальная безопасность).
- **Rootless Docker и `--user`:** При запуске без rootless (root-режим) с `--user 1000:1000` UID внутри контейнера совпадает с UID на хосте. Алгоритм mapped UID нужно применять только для rootless Docker.
- **Ядра ниже 5.11:** Docker 29 по умолчанию использует контейнерное хранилище (containerd snapshotter), которое требует непривилегированного overlayfs и не откатывается на `fuse-overlayfs` (moby/moby#53029). На ядрах 4.18–5.10 rootless-контейнеры не стартуют с настройками по умолчанию; варианты — обновить ядро до 5.11+ или вернуть графдрайвер `overlay2` (с fallback на `fuse-overlayfs`) через `daemon.json`.
- **SELinux и AppArmor:** При включённом SELinux дополнительная метка контекста может блокировать доступ к сокету. Проверяйте `ls -lZ` на хосте и используйте `--security-opt label=disabled`, если требуется. На Ubuntu 24.04+ AppArmor ограничивает непривилегированные user namespaces — профиль `rootlesskit` поставляется в составе deb-пакета `docker-ce-rootless-extras` (см. [Установку Docker на Ubuntu](../docker_install_ubuntu.md)).
- **systemd сервисы и `XDG_RUNTIME_DIR`:** В некоторых дистрибутивах `ssh-agent` запускается автоматически через `ssh-agent.service` в пользовательском systemd. Убедитесь, что ваш `setpriv`-подход не конфликтует с автозапуском.
- **Ключи с паролем:** в автоматизации без терминала требуется askpass-скрипт (см. «Ключи с паролем»); хранение пароля в открытом виде — отдельная граница доверия, оцените её перед применением.
- **macOS/Linux (Docker Desktop):** Rootless Docker доступен только на Linux. Docker Desktop на macOS и Linux предоставляет встроенный проброс SSH‑агента через специальный сокет `/run/host-services/ssh-auth.sock`, который монтируется в контейнер вместе с `SSH_AUTH_SOCK=/run/host-services/ssh-auth.sock`; при этом `$SSH_AUTH_SOCK` хоста не используется напрямую (см. [Docker docs: SSH agent forwarding](https://docs.docker.com/desktop/features/networking/networking-how-tos/#ssh-agent-forwarding)). На Windows встроенный проброс ssh‑агента недоступен.

## Итоговая архитектура

Цепочка SSH‑аутентификации:
```
Контейнер (UID 1000)
  → SSH_AUTH_SOCK=/ssh-agent/agent.sock
  → bind mount (ro)
  → Хост: /opt/ssh-access/sockets/git/agent.sock
  → ssh-agent (UID 100999 на хосте)
  → PrivKey (только на хосте, в памяти агента)
  → Удалённый SSH‑сервер
```

Одновременно применяемые ограничения:
- Docker daemon работает в rootless‑режиме;
- процесс внутри контейнера работает без root‑привилегий;
- корневая файловая система контейнера доступна только для чтения;
- Linux capabilities удалены;
- включён `no-new-privileges`;
- приватный SSH‑ключ отсутствует в контейнере;
- из SSH‑учётных данных контейнер получает доступ только к сокету требуемого `ssh-agent`.

Ключевой технический элемент — совпадение UID процесса `ssh-agent` на хосте с UID, в который преобразуется пользователь контейнера через rootless user namespace. Расширение прав сокета для решения этой проблемы не требуется.

## Дополнительная информация

**Связанные документы:**
- **[Управление секретами в Docker](./secrets_management.md)** — общие методы доставки секретов в контейнеры.
- **[Защита хоста и демона](./host_daemon_hardening.md)** — rootless‑режим, userns-remap, делегирование cgroups, сопоставление UID/GID.
- **[Укрепление безопасности контейнеров](./container_hardening.md)** — capabilities, seccomp, read-only root FS.
- **[Обзор безопасности Docker](./overview.md)** — векторы угроз и базовые принципы.
- **[Безопасность builder'а BuildKit](./buildx_builder_security.md)** — проброс SSH на этапе сборки (`--ssh default`).
- **[Контекст сборки Dockerfile](../Dockerfile/dockerfile_build_context.md)** — `--ssh` и приватные репозитории при сборке.
- **[Установка Docker на Ubuntu](../docker_install_ubuntu.md)** — `dockerd-rootless-setuptool.sh`, ограничения AppArmor на Ubuntu 24.04+.
- **[Секреты и конфигурации в Swarm](../../Docker_swarm/swarm_secrets_configs.md)** — кластерный режим управления секретами.
- **[Интеграция Vault с Docker](../../Vault/guides/vault_docker_integration.md)** — динамические секреты через Vault Agent.

**Внешние ресурсы:**
- **Docker Documentation:** [Rootless mode](https://docs.docker.com/engine/security/rootless/).
- **Docker Documentation:** [UID/GID mapping](https://docs.docker.com/engine/security/rootless/uid-gid-mapping/).
- **Docker Documentation:** [SSH agent forwarding](https://docs.docker.com/desktop/features/networking/networking-how-tos/#ssh-agent-forwarding) (Docker Desktop на macOS и Linux).
- **moby/moby#53029** — регрессия rootless Docker 29 на ядрах ниже 5.11 (containerd snapshotter без fallback на fuse-overlayfs).
- **man ssh-agent:** флаги `-D` (foreground), `-a` (socket path); сигнал `SIGUSR1` удаляет все загруженные ключи.
- **man ssh-add:** `SSH_ASKPASS`, `SSH_ASKPASS_REQUIRE=force` (OpenSSH 8.4+) для ключей с паролем; `-x`/`-u` — блокировка/разблокировка агента.
- **man setpriv:** `--reuid`, `--regid`, `--clear-groups`, `--inh-caps=-all`, `--bounding-set=-all`, `--no-new-privileges`.
