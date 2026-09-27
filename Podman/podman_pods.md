# Поды в Podman

## Определения

**Под (Pod)** — это группа из одного или нескольких контейнеров, которые совместно используют определенные пространства имен Linux (Linux namespaces) и ресурсы. Эта концепция заимствована из Kubernetes и позволяет объединять тесно связанные сервисы в единую логическую единицу, управляемую как целое.

**Infra-контейнер** — служебный контейнер, который создается первым и "удерживает" пространства имен пода открытыми. По умолчанию (флаг `--infra`, значение `true`) Podman собирает собственный локальный образ pause (аналог `pause`-образа Kubernetes) с командой `/pause` — загрузка образа из реестра при этом не требуется. Даже если все основные контейнеры пода остановлены, пространства имен сохраняются благодаря infra-контейнеру, что позволяет сохранять IP-адрес и другие настройки при перезапуске компонентов. Если разделение пространств имен не требуется, infra-контейнер отключается флагом `--infra=false`.

**Сетевое пространство имен (Network Namespace)** — изолированный сетевой стек (интерфейсы, IP-адреса, таблицы маршрутизации, правила фаервола). Единый network namespace для всех контейнеров пода — ключевое свойство, ради которого и создается infra-контейнер.

**Exit Policy** — политика поведения пода после выхода последнего контейнера:

- `continue` (по умолчанию) — под продолжает работать, infra-контейнер остается живым, IP-адрес и пространства имен сохраняются;
- `stop` — под (включая infra-контейнер) корректно останавливается, когда завершается последний контейнер. Применяется по умолчанию в `podman kube play` и в Quadlet.

**pinns** — вспомогательная утилита Podman, отвечающая за создание и подготовку совместных пространств имен (PID, IPC, UTS) для пода. В отличие от контейнерного runtime, pinns не запускает процессы — только настраивает неймспейсы через системные вызовы. Используется как при создании пода через CLI, так и при генерации Quadlet-юнитов. В daemonless-архитектуре это отдельный процесс, что позволяет Podman управлять неймспейсами пода без центрального координатора.

**SQLite-бэкенд (Podman 6.x)** — с Podman 4.9 SQLite стала базой данных метаданных по умолчанию для новых установок, а в Podman 6.0 поддержка BoltDB полностью удалена. Метаданные подов (ID, конфигурация, связь с контейнерами) хранятся в локальной SQLite-базе, что ускоряет операции `podman pod ps`, `podman pod inspect` и обеспечивает целостность данных при асинхронном доступе. Автоматическая миграция BoltDB → SQLite выполняется при первом запуске Podman 6.0; для контролируемой миграции используется `podman system migrate --migrate-db`.

**conmon-rs** — экспериментальная реализация монитора контейнеров на Rust (проект `containers/conmon-rs`), которая в перспективе заменит C-версию conmon. Ключевое преимущество для подов: один экземпляр conmon-rs на весь под вместо одного на контейнер, что снижает потребление памяти (целевой RSS 3–4 МБ) и упрощает переиспользование для `podman exec`. На момент Podman 6.x conmon-rs находится в стадии оценки.

---

## Основные концепции

### Сетевая модель: localhost

Ключевое преимущество пода — общая сеть. Все контейнеры внутри одного пода разделяют один и тот же сетевой стек (Network Namespace) и IP-адрес.

- **Взаимодействие**: Контейнеры видят друг друга через `127.0.0.1` (localhost).
- **Порты**: Порты пробрасываются (publish) исключительно на уровне пода — публиковать порт отдельного контейнера пода нельзя (`podman run -p 80:80 --pod web-app-pod` вернет ошибку). Если под слушает порт 80, ни один контейнер внутри него не может занять этот же порт повторно. Проброс портов нельзя изменить после создания пода — для смены опубликованных портов под необходимо пересоздать.
- **DNS**: Внутри пода не требуется внутренний DNS для связи между контейнерами, достаточно обращения по портам к `localhost`; DNS-имена контейнеров внутри пода не резолвятся.

### Совместное использование ресурсов

По умолчанию (`--share=ipc,net,uts`, что соответствует дефолту Kubernetes) Podman разделяет между контейнерами пода следующие пространства имен:

- **Network**: общий IP и порты.
- **IPC**: разделяемая память (POSIX/System V IPC).
- **UTS**: общее имя хоста (hostname).

На уровне пода общими являются также файлы `/etc/hosts` и `/etc/resolv.conf` (настраиваются флагами `--add-host`, `--dns`, `--dns-search` при создании пода).

Дополнительно совместное использование настраивается через флаг `--share` при создании пода. Допустимые значения: `cgroup`, `ipc`, `net`, `pid`, `uts`. Если значение начинается с `+`, пространство имен добавляется к набору по умолчанию; в противном случае оно заменяет весь набор, а `""` отключает совместное использование полностью:

- **PID**: позволяет контейнерам видеть процессы друг друга (по умолчанию выключено для изоляции). В rootless-режиме для этого требуется, чтобы контейнеры находились в одном и том же user namespace (например, под, созданный с `--userns=keep-id`); в противном случае процесс не сможет присоединиться к чужому PID namespace.
- **Cgroup**: общее пространство имен cgroups (требует root).
- **User**: общее пространство имен пользователей (важно для rootless) задается не через `--share`, а флагом `--userns` на уровне пода.

Лимиты ресурсов пода (`--memory`, `--cpus`, `--cpu-shares` и др.) применяются через cgroup-родителя пода. Контейнер, входящий в под, может задать меньший лимит, но не больший; контейнеры со своим собственным cgroup namespace (`--cgroupns=host`) лимиты пода не получают. По умолчанию под выступает cgroup-родителем всех своих контейнеров (`--share-parent=true`), и этот режим конфликтует с `--share=cgroup`.

### Сетевой стек: Netavark, Aardvark и Pasta

- **Netavark** — сетевой бэкенд Podman для rootful-режима, написанный на Rust. Он создает виртуальные мосты и настраивает правила фаервола. Сеть по умолчанию имеет имя `podman` и подсеть `10.88.0.0/16`. DNS-резолвинг имен в пользовательских сетях обеспечивает вспомогательный процесс **Aardvark**.
- **Pasta** — пользовательский сетевой стек для rootless-режима (по умолчанию с Podman 5.0). Не использует NAT, копирует IP-адреса с основного интерфейса хоста и обеспечивает производительность, близкую к нативной.
- **Пользовательские сети** (`podman network create`) — сети с DNS по именам контейнеров; под подключается к ним флагом `--network`. Внутри пода взаимодействие все равно выполняется через `localhost`, тогда как *между* подами — по именам через DNS.
- **Статические IP**: поду назначается фиксированный IP флагом `--ip` либо через `--network mynet:ip=10.88.0.10`. Начиная с Podman 6.0 одному поду или контейнеру можно назначить несколько IP-адресов: `--network mynet:ip=10.88.0.10,ip=10.88.0.11`.

### Эволюция сетевого стека (устаревшие компоненты)

- **slirp4netns** — исторический rootless-драйвер: был по умолчанию до Podman 5.0, оставался альтернативой в Podman 5.x и полностью удален в Podman 6.0 (вместе с глобальной опцией `--network-cmd-path`). Заменен стеком **Pasta**.
- **CNI** — прежний сетевой бэкенд; в Podman 6.0 удален полностью, используется только **Netavark** (в паре с Aardvark 2.0).
- **iptables** — в Podman 6.0 / Netavark 2.0 поддержка удалена, файрвол настраивается через **nftables**.

### Безрутовый режим (Rootless) и сеть

В rootless-режиме (запуск от обычного пользователя) Podman использует пользовательские сетевые стеки вместо полноценного bridge:

- **pasta** (по умолчанию в Podman 5.0+): высокая производительность и прозрачная передача портов, сохраняет исходный IP отправителя;
- **slirp4netns**: классический вариант для старых версий (до удаления в Podman 6.0).

При использовании подов в rootless-режиме важно помнить, что все контейнеры пода будут использовать один и тот же пользовательский сетевой драйвер, настроенный для infra-контейнера.

Экспериментальная опция `rootless_port_forwarder="pasta"` в `containers.conf` (секция `[network]`) переключает проброс портов rootless bridge-сетей с процесса `rootlessport` на kernel-level проброс через Pasta/Pesto. Это сохраняет исходный IP-адрес клиента внутри контейнера — важно для reverse-прокси и веб-серверов, которые доверяют `client IP`. По умолчанию действует `rootlessport`.

---

## Практические сценарии

### 1. Создание пода и управление через CLI

#### Создание пода с лимитами ресурсов
Вы можете ограничить потребление ресурсов для всего пода сразу. Лимиты будут распределяться между всеми контейнерами пода через общий cgroup-родителя.

```bash
# Создание пода с лимитом 1 ГБ ОЗУ и 0.5 CPU
podman pod create --name web-app-pod \
  --memory 1g --cpus 0.5 \
  -p 8080:80

# Проверка параметров пода
podman pod inspect web-app-pod --format "{{.Config.ResourceLimits}}"
# → {Memory:1073741824 NanoCPUs:500000000 ...}
```

Контейнер внутри пода может опустить лимит ниже заданного, но не выше:

```bash
# Контейнер ограничивает себя сильнее, чем позволяет под
podman run -d --pod web-app-pod --name sidecar-stats --cpus 0.25 busybox \
  sh -c "while true; do wget -qO- localhost:80; sleep 10; done"
```

#### Запуск контейнеров внутри пода
```bash
# Основное приложение
podman run -d --pod web-app-pod --name nginx-server nginx

# Контейнер для мониторинга (sidecar), обращающийся к nginx через localhost
podman run -d --pod web-app-pod --name sidecar-stats busybox \
  sh -c "while true; do wget -qO- localhost:80; sleep 10; done"

# Просмотр контейнеров с фильтром по поду
podman ps --pod
```

#### Жизненный цикл пода
```bash
# Запуск остановленного пода (вместе с infra-контейнером)
podman pod start web-app-pod

# Плавная остановка всех контейнеров пода (SIGTERM, затем SIGKILL)
podman pod stop web-app-pod

# Перезапуск
podman pod restart web-app-pod

# Пауза (SIGSTOP) и возобновление (SIGCONT) всех процессов пода
podman pod pause web-app-pod
podman pod unpause web-app-pod

# Удаление пода вместе с контейнерами (--force для запущенного пода)
podman pod rm --force web-app-pod

# Удаление всех неиспользуемых подов
podman pod prune

# Проверка существования пода (exit code 0/1, удобно для скриптов)
podman pod exists web-app-pod
```

#### Клонирование пода
Копирует под вместе со всей конфигурацией и всеми его контейнерами (Podman 5.0+):

```bash
# Клонирование по умолчанию: имя <оригинал>-clone
podman pod clone web-app-pod
# → 6b2c73ff8a1982828c9ae2092954bcd59836a131960f7e05221af9df5939c584

# Клонирование с новым именем, лимитами и немедленным запуском
podman pod clone web-app-pod --name web-app-staging --cpus 1 --start

# Клонирование с удалением исходного пода
podman pod clone web-app-pod --destroy --name web-app-rebuilt
```

#### Настройка инфра-контейнера
```bash
# Под без инфраструктурного контейнера (независимые пространства имен)
podman pod create --name simple-pod --infra=false

# Нестандартный образ и команда инфра-контейнера
podman pod create --name custom-infra \
  --infra-image docker.io/library/alpine:3.19 \
  --infra-command "/bin/sleep 86400"

# Собственное имя infra-контейнера и файл для conmon pid
podman pod create --name named-infra --infra-name infra-holder \
  --infra-conmon-pidfile /tmp/infra.pid

# Политика: под останавливается вместе с последним контейнером
podman pod create --name short-lived --exit-policy stop
```

#### Совместные пространства имен на практике
```bash
# Под с общим PID-пространством имен (+ добавляет pid к набору по умолчанию)
podman pod create --name debug-pod --share +pid

# Под без общих пространств имен (полная изоляция, без infra-контейнера)
podman pod create --name isolated-pod --share ""

# Rootless: совместный PID требует общего user namespace
podman pod create --name debug-pod --share +pid --userns keep-id
```

#### Статические IP-адреса и пользовательские сети
```bash
# Пользовательская сеть с DNS по именам сервисов
podman network create app-net --subnet 10.99.0.0/24

# Под с фиксированным IP, подключенный к пользовательской сети
podman pod create --name api-pod --network app-net --ip 10.99.0.5 -p 8080:80

# Несколько статических IP-адресов на один под (Podman 6.0+)
podman pod create --name multi-ip-pod --network app-net:ip=10.99.0.5,ip=10.99.0.6
```

### 2. Мониторинг и инспекция

Podman предоставляет специализированные команды для наблюдения за состоянием подов.

```bash
# Список всех подов и количество контейнеров в них
podman pod ps
# → POD ID        NAME          STATUS      CREATED       # OF CONTAINERS  INFRA ID
# → 5a4b3c2d1e0f  web-app-pod   Running     5 minutes ago 3                a1b2c3d4e5f6

# Форматированный вывод (для скриптов)
podman pod ps --format "{{.Name}}: {{.Status}} ({{.Containers}})"
# → web-app-pod: Running (3)

# Статистика потребления ресурсов в реальном времени
podman pod stats web-app-pod
# → NAME         CPU %  MEM USAGE / LIMIT  NET I/O     BLOCK I/O   PIDS
# → web-app-pod  0.15%  45MB / 1GB         1.2kB/0B    0B/0B       12

# Просмотр агрегированных логов всех контейнеров пода
podman pod logs -f web-app-pod

# Полная инспекция конфигурации и состояния (включая InfraContainerID)
podman pod inspect web-app-pod

# Список процессов, запущенных внутри контейнеров пода
podman pod top web-app-pod
```

### 3. Управление через Quadlet (systemd)

Quadlet — это современный стандарт деплоя Podman в production. Для пода создается файл `.pod`, который генерирует systemd-юнит с `Type=forking`; контейнеры присоединяются через `Pod=`. Контейнеры, объявленные в поде, по умолчанию запускаются и останавливаются вместе с подом (`StartWithPod=true`).

**Файл:** `~/.config/containers/systemd/app.pod`

```ini
[Unit]
Description=Application Pod with Nginx and Stats
After=network-online.target

[Pod]
PodName=app-stack
PublishPort=8080:80
# Пользовательская сеть (можно ссылаться на app-net.network) и статический IP
Network=app-net
IP=10.99.0.10
# Политика выхода: под останавливается, когда завершается последний контейнер
# (значение по умолчанию для Quadlet)
ExitPolicy=stop

[Service]
# Лимиты ресурсов всего пода можно задать либо через PodmanArgs в [Pod],
# либо системными cgroup-директивами systemd здесь:
MemoryMax=1G
CPUWeight=50

[Install]
WantedBy=default.target
```

> **Важно:** в секции `[Pod]` Quadlet нет прямых ключей для лимитов ресурсов (`Memory`, `CPUShares`) и для флагов пространств имен (`Share`, `Infra`). Такие опции передаются через `PodmanArgs` в секции `[Pod]` или настраиваются cgroup-директивами systemd в секции `[Service]` (`MemoryMax=`, `CPUWeight=`, `CPUQuota=` и т.д.). Обратите также внимание, что у `.container`-юнитов по умолчанию `CgroupsMode=split` — чтобы лимиты уровня пода эффективно применялись к его контейнерам, этот режим стоит сменить на `no-conmon` или `enabled`.

**Файл:** `~/.config/containers/systemd/nginx.container`

```ini
[Unit]
Description=Nginx Server
[Container]
Pod=app.pod
Image=docker.io/library/nginx:latest
# Автообновление образа
AutoUpdate=registry
```

### 4. Интеграция с Kubernetes

Podman позволяет экспортировать поды в манифесты Kubernetes и запускать их обратно. Это основной путь миграции из локальной среды в кластер.

```bash
# Генерация YAML манифеста из существующего пода (Podman 4.3+)
podman kube generate web-app-pod > web-app.yaml

# Экспорт в виде Deployment, а не отдельного Pod
podman kube generate --type deployment web-app-pod > web-app.yaml

# Запуск пода из Kubernetes манифеста (--replace позволяет заменить существующий)
podman kube play web-app.yaml
podman kube play --replace web-app.yaml

# Удаление ресурсов, развернутых через play
podman kube down web-app.yaml
```

> **Примечание:** В версиях Podman до 4.3 использовались команды `podman generate kube` и `podman play kube`. Сейчас они считаются устаревшими (deprecated) в пользу группы команд `podman kube`. Ресурсы, запускаемые через `podman kube play`, используют политику выхода `exit-policy=stop`.

### 5. Динамическое управление и отладка (Podman 6.x)

Podman 6.x позволяет изменять параметры уже запущенных подов без пересоздания, что критично для production-сред, где простой пода недопустим.

#### Изменение параметров пода на лету

Команда `podman update` применяет новые ограничения ресурсов и параметры конфигурации к запущенному поду. Изменения затрагивают все контейнеры пода, которые не задали собственный лимит выше нового значения пода.

```bash
# Уже running под с лимитом 1 CPU
podman pod stats web-app-pod
# → NAME         CPU %  MEM USAGE / LIMIT  NET I/O     BLOCK I/O   PIDS
# → web-app-pod  0.15%  45MB / 1GB         1.2kB/0B    0B/0B       12

# Повышение лимита CPU до 2 (без перезапуска контейнеров)
podman pod update web-app-pod --cpus 2

# Изменение лимита памяти
podman pod update web-app-pod --memory 2g

# Проверка новых значений
podman pod inspect web-app-pod --format "{{.Config.ResourceLimits}}"
# → {Memory:2147483648 NanoCPUs:2000000000 ...}
```

Динамически изменяемые параметры пода: `--cpus`, `--memory`, `--cpuset-cpus`, `--cpuset-mems`, `--pids-limit`, `--shm-size`, а также флаги healthcheck (`--health-interval`, `--health-retries`, `--health-cmd` и т.д.). Физические устройства (`--device`), публикация портов (`-p`) и выбор сети (`--network`) изменить после создания пода нельзя — для этого требуется пересоздание пода.

#### Сравнение конфигурации пода (`podman pod diff`)

Команда показывает отличия текущего состояния пода от его исходной конфигурации. Полезна для аудита изменений, примененных через `podman update`, и для отладки неожиданного поведения:

```bash
# Показать diff
podman pod diff web-app-pod
# → Memory: original 1073741824, current 2147483648
# → Cpus: original 500000000, current 2000000000

# В комбинации с inspect — полная картина изменений
podman pod inspect web-app-pod --format "{{json .HostConfig.PodUpdateCommand}}" | jq
```

#### Валидация после создания пода

Проверка корректности создания пода и сетевой доступности:

```bash
# Создание пода с пробросом портов
podman pod create --name web-app-pod -p 8080:80

# Запуск контейнеров
podman run -d --pod web-app-pod --name nginx-server nginx
podman run -d --pod web-app-pod --name sidecar busybox \
  sh -c "while true; do wget -qO- localhost:80; sleep 10; done"

# Проверка: под запущен, infra-контейнер жив
podman ps --pod --filter name=web-app-pod
# → CONTAINER ID  IMAGE       COMMAND  CREATED   STATUS    PORTS   NAMES
# → a1b2c3d4e5f   k8s.gcr.io/pause  ...     2m ago    Up 2m    8080->80/tcp  web-app-pod-infra
# → b2c3d4e5f6g   nginx       ...      2m ago    Up 2m    8080->80/tcp  nginx-server

# Сетевой тест: контейнеры видят друг друга через localhost
podman exec nginx-server wget -qO- localhost:80
# → <html>...</html>

# Внешний тест (с хоста)
curl -s http://localhost:8080
# → <html>...</html>

# DNS: внешний DNS резолвится внутри пода (через Aardvark/host)
podman exec nginx-server nslookup google.com
# → Non-authoritative answer:
# → google.com has address 142.250.185.14
```

### 6. Безопасность

#### Контекст SELinux

SELinux работает в режиме enforcing на RHEL, Fedora, CentOS и других дистрибутивах. Для контейнеров и томов Podman автоматически назначает контекст `container_file_t`, но при монтировании каталогов хоста может потребоваться явное relabeling:

```bash
# Монтирование с автоматическим relabeling (SELinux)
podman run -d --pod web-app-pod \
  -v /srv/app/data:/var/lib/app:Z \
  my-app-image

# :Z — exclusive relabel (только для этого контейнера)
# :z — shared relabel (разрешено нескольким контейнерам)
```

В rootless-режиме с user namespace используется расширение `:U` (relabel в контексте user namespace):

```bash
podman run -d --pod web-app-pod \
  -v /srv/app/data:/var/lib/app:U \
  my-app-image
```

Без флага `:Z`/`:z`/`:U` монтирование в enforcing-режиме завершится ошибкой `permission denied`.

#### Контекст безопасности контейнера (Security Context)

```bash
# Запуск без привилегий (по умолчанию)
podman run -d --pod web-app-pod --name app my-app

# Отключение SELinux внутри контейнера (не рекомендуется)
podman run -d --pod web-app-pod --security-opt label=disable my-app

# Добавление capabilities
podman run -d --pod web-app-pod --cap-add=NET_ADMIN my-app

# Полный привилегированный режим
podman run -d --pod web-app-pod --privileged my-app
```

В Quadlet флаги безопасности задаются в секции `[Container]`:

```ini
[Container]
Image=my-app:latest
SecurityOptDisableSeccomp=true
SecurityOptLabelDisable=false
AddCapability=NET_ADMIN
```

### 7. Типичные проблемы и диагностика

#### Порт уже занят

```bash
# Симптом: Error creating pod: container_linux.go:380:
#   starting container process caused "process_linux.go:380:
#   container init caused \"listen tcp:8080:bind: address already in use\""

# Диагностика
ss -tlnp | grep 8080
# → LISTEN 0 128 *:8080 *:* users:(("nginx",pid=1234,fd=6))

# Решение 1: освободить порт на хосте
sudo kill 1234

# Решение 2: изменить проброс портов пода
podman pod rm --force web-app-pod
podman pod create --name web-app-pod -p 8081:80
```

#### Permission denied при создании пода

```bash
# Симптом: Error: creating container storage: lstat /proc/1234/ns/net:
#   permission denied

# Причина: не настроены subuid/subgid для пользователя
cat /etc/subuid
# → user:100000:65536

# Решение (от root)
sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER
podman system migrate
```

#### DNS не резолвится внутри пода

```bash
# Симптом: контейнер не может разрешить внешние имена
podman exec nginx-server nslookup google.com
# ;; connection timed out; no servers could be reached

# Диагностика: проверка /etc/resolv.conf внутри пода
podman exec nginx-server cat /etc/resolv.conf
# → nameserver 10.88.0.1 (Aardvark)
# → search podman

# Решение 1: указать внешний DNS при создании пода
podman pod create --name web-app-pod \
  --dns 8.8.8.8 --dns 1.1.1.1 \
  -p 8080:80

# Решение 2: использовать сеть хоста (внимание: теряется изоляция)
podman pod create --name web-app-pod --network host -p 8080:80
```

#### Контейнер не видит localhost внутри пода

```bash
# Симптом: wget localhost:80 не работает, хотя порт проброшен
# Причина: контейнер в поде с `--share=` (без общего network namespace)
# Это поведение по умолчанию в podman-compose

# Решение 1: для нативного пода убедитесь, что infra-контейнер активен
podman ps --filter name=web-app-pod-infra
# Если infra не найден — под создан с --infra=false

# Решение 2: проверка shared namespaces
podman pod inspect web-app-pod --format "{{.ShareNamespaces}}"
# → net,ipc,uts (должно включать net)
```

#### Infra-контейнер завис и не останавливается

```bash
# Симптом: podman pod stop не завершается, контейнеры в статусе "Stopping"
# Диагностика
podman ps -a --filter name=web-app-pod
# → STATUS: Up 2 hours (или Stuck)

# Решение: принудительная остановка
podman pod kill web-app-pod
podman pod rm --force web-app-pod
```

#### Полярные контейнеры (orphans) после удаления пода

```bash
# Проверка: существуют ли контейнеры без родительского пода
podman ps -a --filter "pod=!web-app-pod" --filter "label=io.podman.namespace=web-app-pod"

# Очистка всех неиспользуемых контейнеров
podman container prune -f
```

---

## Нюансы и сравнение с Podman Compose

Подробнее о компоновке сервисов и совместимости см. **[Podman Compose](./podman-compose.md)**.

| Характеристика | Нативный Pod (CLI/Quadlet) | Podman Compose |
| :--- | :--- | :--- |
| **Сетевая модель** | Строгий `localhost` через Network Namespace. | Bridge-сеть (по умолчанию), связь по именам сервисов. |
| **Infra-контейнер** | Обязателен (удерживает ресурсы и пространства имен). | Обычно отсутствует, используется модель Docker. |
| **Взаимодействие** | Только через порты на `localhost`. | Через DNS (имена контейнеров). |
| **Публикация портов** | Только на уровне всего пода (`-p` нельзя менять после создания). | На уровне отдельных сервисов. |
| **Производительность** | Чуть выше из-за отсутствия лишних сетевых мостов. | Зависит от сложности сети Compose. |
| **Лимиты ресурсов** | На уровне пода через cgroup-родителя; контейнер может только уменьшить. | На уровне отдельных сервисов (`cpus`, `mem_limit`, `deploy.resources`). |
| **Политика выхода** | `exit-policy` на уровне пода (`continue`/`stop`). | Управляется на уровне сервисов; при `podman-compose down` контейнеры удаляются. |
| **Безопасность** | SELinux-контексты применяются к infra-контейнеру и всем контейнерам пода. | Применяется к каждому контейнеру отдельно. |
| **Экспорт в Kubernetes** | Нативный: `podman kube generate <pod>` → манифест K8s. | Требует доп. шагов: `podman pod ps` → найти ID → `podman kube generate`. |
| **Режим rootless** | Полная поддержка через Pasta; порты пробрасываются на host-интерфейс. | Поддерживается, но сетевые стеки настраиваются индивидуально для каждого сервиса. |

### Важные ограничения нативного подхода

- **Порты нельзя опубликовать после создания**: если потребовался другой порт, под необходимо пересоздать. Для zero-downtime деплоя используйте внешний reverse proxy (например, запущенный в отдельном поде) или DNS/load-balancer.
- **Порты внутри пода уникальны**: два контейнера пода не могут слушать один и тот же порт — второй получит ошибку `bind: address already in use`.
- **Без `--share=net` нет localhost**: если под создан с отключенным общим сетевым namespace (например, `--share=""` или через Compose с `--share=`), контейнеры не видят друг друга по `127.0.0.1`. Используйте DNS-имена сервисов.
- **Обновление образа требует перезапуска контейнера**: `podman pod update` изменяет лимиты, но не обновляет образы. Для обновления образа используйте `podman container update --image new:tag <container>` или пересоздайте контейнер.
- **Зависимости внутри пода**: порядок запуска контейнеров внутри пода не гарантирован. Если требуется запуск БД перед приложением, используйте либо Quadlet с `After=`/`Requires=`, либо скрипт ожидания готовности (healthcheck loop).

---

## Дополнительная информация

### Жизненный цикл и зависимости
- **Запуск**: При запуске любого контейнера в поде автоматически запускается infra-контейнер.
- **Остановка**: Команда `podman pod stop` корректно завершает работу всех контейнеров (сначала отправляет SIGTERM, затем при необходимости SIGKILL). `podman pod pause` замораживает процессы сигналом SIGSTOP.
- **Политики перезапуска**: Флаг `--restart no|on-failure|always|unless-stopped` при `podman pod create` задает политику перезапуска для всех контейнеров пода. Восстановление после перезагрузки системы обеспечивает юнит `podman-restart.service`.
- **Зависимости**: Podman не гарантирует порядок запуска контейнеров внутри пода. Для управления порядком используйте внешние инструменты или проверки готовности.

Подробнее: **[Управление зависимостями и готовностью](./podman-dependencies.md)**.

### Хранение метаданных и миграция

Поды, как и контейнеры, хранят метаданные в локальной базе данных:

```bash
# Проверка бэкенда базы данных
podman info --format '{{.Host.DatabaseBackend}}'
# → sqlite

# Принудительная миграция BoltDB → SQLite (Podman 6.0)
podman system migrate --migrate-db
```

С Podman 6.0 BoltDB полностью удален; автоматическая миграция выполняется при первом запуске. Для больших инсталляций (>10 000 контейнеров/подов) рекомендуется выполнить миграцию вручную, остановив systemd-активируемые сервисы.

### Namespace-модель и pinns

Для создания подов Podman использует утилиту **pinns** (Podman INitialize Namespaces). Её задача — подготовить неймспейсы до запуска контейнеров:

```bash
# Внутренний вызов (не требует ручного запуска)
pinns --ipc --net --uts --pid /proc/1234/ns /var/run/podman/...

# Просмотр созданных неймспейсов (через podman unshare)
podman unshare ls /proc/1234/ns
# → ipc -> 'ipc:[12345]'
# → net -> 'net:[67890]'
# → uts -> 'uts:[11111]'
```

pinns создает неймспейсы один раз при создании пода, после чего все контейнеры пода присоединяются к уже существующим неймспейсам. Это эффективнее, чем создавать новый неймспейс для каждого контейнера, и гарантирует их общность.

### Kubernetes: расширенная интеграция

`podman kube generate` поддерживает больше типов ресурсов и опций, чем базовый Pod. При экспорте пода учитываются:

```bash
# Полный манифест с Deployment, Service и PersistentVolumeClaim
podman kube generate --type deployment web-app-pod > web-app.yaml
```

**Тома:** если контейнеры пода используют именованные тома (`podman volume create`), манифест генерирует соответствующие `PersistentVolumeClaim`. Для bind-mountов создаются `hostPath`-тома с абсолютными путями хоста — при переносе в кластер такие тома требуют адаптации.

**Переменные окружения и секреты:** переменные окружения пода переносятся в `env` секции контейнеров Deployment. `podman secret` экспортируется как `Secret` с типом `Opaque` (требуется `type=env` или `type=mount` в Quadlet).

**Метки и аннотации:** метки пода (`--label`) и контейнеров переносятся в `metadata.labels` и `metadata.annotations` манифеста.

```bash
# Проверка сгенерированного манифеста
podman kube generate --type deployment web-app-pod | yq '.spec.template.spec.containers[0].env'
```

### Очистка и рекомендации

```bash
# Удаление одного пода (при остановленном поде)
podman pod rm web-app-pod

# Удаление запущенного пода (принудительно)
podman pod rm --force web-app-pod

# Удаление ВСЕХ неиспользуемых подов (без контейнеров)
podman pod prune -f

# Удаление неиспользуемых контейнеров (включая "осиротевшие")
podman container prune -f

# Полная очистка: контейнеры, тома, сети, образы
podman system prune -a --volumes
```

**Рекомендации по очистке:**
- Перед `podman pod rm` убедитесь, что контейнеры пода остановлены, или используйте `--force`.
- `podman pod prune` удаляет только поды с статусом `Created` или `Exited`; запущенные поды не затрагиваются.
- `podman system prune` НЕ удаляет тома по умолчанию — добавьте `--volumes` для их удаления.
- Организуйте регулярный `podman system prune` через cron/timer для development-сред.

### Мониторинг и наблюдаемость

```bash
# Статистика потребления ресурсов в реальном времени
podman pod stats web-app-pod
# → NAME         CPU %  MEM USAGE / LIMIT  NET I/O     BLOCK I/O   PIDS
# → web-app-pod  0.15%  45MB / 1GB         1.2kB/0B    0B/0B       12

# Агрегированные логи всех контейнеров пода
podman pod logs -f web-app-pod

# События systemd-юнита пода (если используется Quadlet)
journalctl --user -u app-stack-pod.service -f
```

Для сброса статистики `podman pod stats` используйте `podman system reset` (останавливает все контейнеры).

### См. также
- **[Healthchecks в Podman](./podman_healthchecks.md)** — проверка готовности сервисов внутри пода.
- **[Daemonless архитектура](./podman_daemonless_architecture.md)** — как работают процессы `conmon` и инфраструктура подов.
- **[Миграция с Docker (Compose → Quadlet)](./migration-from-docker.md)** — подробнее о переходе на Quadlet и различиях в сетевом стеке.
- **[Podman Compose](./podman-compose.md)** — компоновка сервисов через Compose-спецификацию.