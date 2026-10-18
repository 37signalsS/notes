# Архитектура SaltStack

**Актуально для:** Salt 3008 LTS

## Определения

- **Архитектура SaltStack**: Модель управления конфигурацией, построенная на взаимодействии центрального узла **Master** и агентов **Minion** через асинхронную шину сообщений по схеме «издатель-подписчик» (Pub/Sub).
- **Master**: Центральный сервер управления, который отправляет команды, хранит Pillar-данные и управляет ключами.
- **Minion**: Агент на управляемом узле, исполняющий команды и сообщающий о результатах.
- **Grains**: Статические данные о миньоне (ОС, версия ядра, архитектура CPU, RAM), собираемые локально при старте агента. Используются для таргетинга.
- **Pillar**: Динамические конфиденциальные и целевые данные (пароли, ключи, переменные), которые Master безопасно передает конкретным миньонам.
- **Event Bus**: Шина событий (ZeroMQ или TCP), обеспечивающая мгновенную связь между компонентами.
- **Runners**: Модули, исполняемые на Master для управления инфраструктурой Salt (работа с ключами, очередями заданий).
- **Beacons**: Механизм мониторинга на Minion, отправляющий события в шину при изменении состояния (например, падение процесса).
- **Reactors**: Логика на Master, которая реагирует на события Beacons для автоматического исправления дрейфа или сбоев.
- **Proxy Minion**: Прокси-агент для управления устройствами без поддержки Python (коммутаторы, API-сервисы).
- **SLS (Salt State File)**: YAML-файл (опционально с Jinja-шаблонами), описывающий желаемое состояние ресурсов (пакеты, сервисы, файлы, пользователи). Хранится в `file_roots` и применяется миньоном через State Modules.
- **Highstate**: Процесс полного применения всех состояний, назначенных миньону через `top.sls` ([подробнее](Highstate_and_Execution_Order.md)).
- **Job**: Задание — единица работы, рассылаемая мастером миньонам и идентифицируемая уникальным номером (JID, Job ID).
- **Salt File Server**: Файловый сервер на мастере, раздающий миньонам SLS-файлы, статические файлы и шаблоны из `file_roots`.
- **Returner**: Модуль, отправляющий результаты выполнения заданий во внешние системы (базы данных, Redis, SIEM) для хранения, аудита и анализа.
- **Schedule**: Встроенный планировщик на миньоне, периодически запускающий состояния или команды по расписанию (реализует Pull-модель).
- **Salt-API**: REST-интерфейс (модули `netapi`), позволяющий выполнять команды Salt через HTTP, обычно с внешней аутентификацией (eAuth).
- **Wheel**: Интерфейс управления мастером (аналогично Runners, но для операций управления ключами, конфигурацией и инфраструктурой мастера). Доступен через `salt-run wheel.` или Salt-API с маркером `@wheel`.
- **Job Cache (Кэш заданий)**: Хранилище на мастере, сохраняющее результаты выполнения заданий (JID, таргетинг, возвращённые данные). Настраивается через `master_job_cache` (встроенный `localjob`) или внешние системы (`ext_job_cache`) — PostgreSQL, Redis, Elasticsearch.
- **ext_pillar**: Механизм динамической подгрузки данных в Pillar из внешних источников (Vault, Consul и др.) в момент компиляции на мастере.
- **saltenv / pillarenv**: Именованные окружения для `file_roots` и `pillar_roots`, позволяющие использовать разные версии состояний и секретов для dev/staging/prod.
- **Grains Cache**: Локальный кэш на миньоне (`/var/cache/salt/minion/grains`), хранящий собранные Grains для ускорения запусков. Обновляется при перезапуске миньона или по команде `salt '*' saltutil.refresh_grains`.
- **Salt-SSH**: Агентский режим (Agentless), управляющий узлами через SSH без установки миньона. Использует `roster`-файл для хранения списка хостов и `thin mode` для временной установки библиотек Salt на целевом узле.
- **Salt Syndic**: Узел-посредник между «Мастером Мастеров» и локальными мастерами. Передаёт команды сверху вниз и возвращает результаты обратно, позволяя масштабировать инфраструктуру на десятки тысяч узлов.

---

## Основные концепции

### Коммуникационная модель

Взаимодействие Master и Minion строится по схеме «издатель-подписчик» (Pub/Sub):

1.  **Порт 4505 (Publisher)**: Мастер публикует сообщения. Все миньоны слушают этот порт.
2.  **Порт 4506 (Retriever)**: Миньоны возвращают данные (результаты выполнения, запросы файлов или Pillar) на мастер.

Для сетевой изоляции важно: **миньоны инициируют постоянные исходящие соединения к мастеру**, а не наоборот. Поэтому достаточно открыть входящие порты 4505/4506 только на мастере.

**Транспортные протоколы:**
- **ZeroMQ (по умолчанию)**: Высокая производительность, асинхронность. Требует установки библиотек в ОС.
- **TCP**: Альтернатива без зависимостей от ZeroMQ, полезная в сетях с жесткими правилами фильтрации трафика.

**Аутентификация и шифрование.**

Безопасность обеспечивается PKI-инфраструктурой на базе AES-256 и RSA ([подробнее о безопасности](Security_Approaches.md)). При первом запуске Minion генерирует ключевую пару и отправляет публичный ключ на Master. После принятия ключа администратором (`salt-key -A`) весь трафик между Master и Minion шифруется.

### Жизненный цикл задания (Job Lifecycle)

Выполнение любой команды Salt проходит через несколько этапов:

1.  Клиент (`salt`) отправляет команду мастеру; мастер назначает заданию уникальный идентификатор **JID** и сохраняет его в кэше заданий (Job Cache).
2.  Мастер публикует задание в шину публикаций (порт 4505) для целевого множества миньонов.
3.  Каждый миньон, соответствующий таргетингу, исполняет задание локально и отправляет результат обратно мастеру (порт 4506).
4.  Мастер генерирует событие `salt/job/<JID>/ret` в Event Bus и (при необходимости) передаёт результат в Returner для хранения.
5.  Клиент получает результаты, сопоставляя их с JID.

При этом важно различать два канала:
- **Job Bus**: публикация заданий (4505) и возврат результатов (4506).
- **Event Bus**: непрерывный поток событий с миньонов и мастера (изменения Beacons, старт/завершение заданий, появление/исчезновение миньонов). Наблюдается через `salt-run state.event` и обрабатывается в [Reactor](Orchestration_and_Automation_Methods.md).

### Таргетинг (Targeting)

Таргетинг позволяет выбирать целевые узлы для команд:

| Сокращение | Описание | Пример |
| :--- | :--- | :--- |
| — (Globbing) | Подстановочные шаблоны | `salt 'web-*' test.ping` |
| `-E` | Регулярные выражения | `salt -E '^(web\|db)\.prod' test.ping` |
| `-L` | Список адресов | `salt -L 'web-01,web-02' test.ping` |
| `-G` | Grains | `salt -G 'os:Ubuntu' test.ping` |
| `-P` | Grains через RegExp | `salt -P 'os_family:(Debian\|RedHat)' test.ping` |
| `-I` | Pillar | `salt -I 'role:cache' test.ping` |
| `-J` | Pillar через RegExp | `salt -J 'env:^(dev\|qa)$' test.ping` |
| `-S` | Подсеть (CIDR) | `salt -S 10.0.0.0/24 test.ping` |
| `-N` | Группы узлов (Nodegroups) | `salt -N webservers test.ping` |
| `-R` | Range-сервер | `salt -R 'range:cluster' test.ping` |
| `-C` | Составной (Compound) | `salt -C 'G@os:Debian and not web-01*' test.ping` |

**Nodegroups** задаются в конфигурации мастера и позволяют переиспользовать составные выражения:

```yaml
nodegroups:
  webservers: 'G@role:web and S@10.0.0.0/24'
```

**Составной таргетинг** поддерживает операторы `and`, `or`, `not`, скобки, а также префиксы `G` (Grains), `P` (Grains через RegExp), `I` (Pillar), `J` (Pillar через RegExp), `L` (список), `N` (nodegroup), `S` (подсеть), `E` (регулярное выражение), `R` (range).

### Декларативный и императивный подходы

1.  **Императивный (Execution Modules)**: Прямые команды «здесь и сейчас». Пример: `salt '*' pkg.install vim`.
2.  **Декларативный (State Modules)**: Описание *желаемого* состояния в SLS-файлах (YAML + Jinja). Salt сам вычисляет необходимые изменения ([модели управления конфигурацией](../Concepts/configuration_management_models.md)).
    *   Процесс применения состояний: [Highstate и порядок выполнения](Highstate_and_Execution_Order.md).

### Salt File Server

Файловый сервер мастера обслуживает миньонов по протоколу `salt://`. Конфигурация в `/etc/salt/master`:

```yaml
file_roots:
  base:
    - /srv/salt
  production:
    - /srv/salt/prod
  staging:
    - /srv/salt/staging
```

**Бэкенды (backends):**
- **`roots`** (по умолчанию): локальная файловая система мастера.
- **`gitfs`**: хранение SLS и шаблонов в Git-репозитории. Поддерживаются HTTPS/SSH, ветки (`branch`), теги (`root_type: tag`), каталоги (`mountpoint`).
- **`svn`**: аналогично gitfs для Subversion.
- **`minionfs`**: доступ к файлам на самом миньоне (например, для сбора артефактов).

**Важные параметры:**
- **`hash_type`**: алгоритм контрольных сумм файлов (`sha256`, `sha512`, `md5`). По умолчанию `sha256`; `md5` ускоряет сравнение, но снижает безопасность.
- **`env_order`** / **`saltenv`**: порядок и выбор окружения. Миньон запрашивает `saltenv`, мастер ищет файлы в `file_roots[saltenv]`. По умолчанию `base` → `prod` → `staging` и т.д.
- **`file_ignore_regex`** / **`file_ignore_glob`**: исключения при синхронизации (например, `*.tmp`, `.git/`).

Практическое применение: хранение SLS в Git позволяет версионировать инфраструктуру, использовать code review и откатываться на любой коммит. При использовании `gitfs` Salt кэширует репозиторий; принудительное обновление — `salt-run fileserver.clear_cache`.

### Pillar (Динамические данные)

Pillar — иерархическая система конфиденциальных данных, компилируемая на мастере в момент выполнения задания и передаваемая миньону по зашифрованному каналу.

**Структура:**
- **`pillar_roots`**: каталоги с Pillar-SLS, аналогичные `file_roots` и поддерживающие окружения (`base`, `prod`).
- **Pillar SLS**: YAML-файлы, рендеримые через Jinja. Пример: `/srv/pillar/users.sls`.
- **Pillar Cache**: кэш отрендеренных Pillar на мастере (`pillar_cache: True`). Ускоряет повторные вызовы, но хранит данные в открытом виде — использовать только при необходимости и при защищённом каталоге кэша.

**Динамическая подгрузка (ext_pillar):**
```yaml
ext_pillar:
  - vault: path=secret/salt
  - consul: 
      host: consul.example.com
      port: 8500
      prefix: salt/pillar
```

Каждый `ext_pillar` драйвер запрашивает данные из внешней системы в момент компиляции Pillar и объединяет их с данными из SLS-файлов. Приоритет: данные из SLS переопределяют данные из `ext_pillar` при совпадении ключей.

**SDB (Salt Data Backend):**
Универсальный URI-интерфейс для получения секретов по требованию: `sdb://<profile>/<path>/<key>`. Используется внутри SLS-файлов для подстановки значений из Vault, keyring, env и других хранилищ без предварительной компиляции в Pillar.

**Pillar и окружения:**
- **`pillarenv`**: выбор окружения Pillar (по умолчанию совпадает с `saltenv`). Передаётся при вызове: `salt '*' state.apply pillar=foo pillarenv=prod`.
- **`pillar_source_merging`**: стратегия слияния Pillar из разных источников (`merge`, `overwrite`).

### Grains (Статические данные узла)

Grains собираются на миньоне при старте и представляют собой статические факты (неизменяемые без перезапуска агента). Используются для таргетинга и шаблонизации.

**Встроенные Grains:** `id`, `os`, `os_family`, `kernel`, `kernelrelease`, `cpuarch`, `num_cpus`, `hostname`, `domain`, `fqdn`, `ipv4`, `ipv6`, `mem_total` и сотни других.

**Custom Grains (пользовательские):**
Размещаются в `/etc/salt/grains` (статический YAML) или генерируются через Python-скрипт в `/etc/salt/grains/` (динамические). Пример динамического grain:

```python
# /etc/salt/grains/role.py
def role():
    with open('/etc/myapp/role') as f:
        return {'role': f.read().strip()}
```

После добавления/изменения grains требуется обновление кэша:
```bash
salt '*' saltutil.refresh_grains
salt '*' grains.items
```

**Grains Cache:** хранится в `/var/cache/salt/minion/grains` (формат `pickle`). Ускоряет запуск Salt-команд, но при изменении окружения (обновление ОС, переконфигурация сети) требует принудительного обновления.

**sync_grains:** загрузка grains из модулей Salt (`salt://_grains/`) позволяет централизованно управлять grains на множестве миньонов без правки локальных файлов.

### Wheel

Wheel — интерфейс управления мастером (в отличие от Runners, которые управляют инфраструктурой Salt, Wheel управляет самим мастером). Доступен через:

```bash
salt-run wheel key.accept match='web-*'
salt-run wheel key.delete match='old-node'
salt-run wheel config.values saltmaster
```

Через Salt-API с eAuth и маркером `@wheel`:
```bash
curl -sk https://salt-master:8000/run \
  -H "X-Auth-Token: $TOKEN" \
  -d client='wheel' \
  -d fun='key.accept' \
  -d match='web-*'
```

Основные Wheel-модули: `key.*` (accept, delete, reject, list), `config.*` (values, get), `file_roots.*` (update), `pillar_roots.*` (update).

---

## Практические сценарии

### 1. Базовая настройка

Минимальная конфигурация мастера (`/etc/salt/master`):

```yaml
interface: 0.0.0.0
file_roots:
  base:
    - /srv/salt
pillar_roots:
  base:
    - /srv/pillar
```

Минимальная конфигурация миньона (`/etc/salt/minion`):

```yaml
id: web-01.example.com
master: <ip_or_dns_of_master>
```

### 2. Пример декларативного состояния (SLS)

Файл `/srv/salt/webserver.sls`:

```yaml
install_nginx:
  pkg.installed:
    - name: nginx

nginx_service:
  service.running:
    - name: nginx
    - enable: True
    - watch:
      - pkg: install_nginx
```

Применение: `salt 'web-*' state.apply webserver`.

### 3. Пример таргетинга

Выполнить `test.ping` на всех машинах с ОС Debian, которые также являются веб-серверами или кэш-серверами:

```bash
salt -C 'G@os:Debian and (web* or cache*)' test.ping
```

### 4. Первое подключение миньона и управление ключами

После установки миньон генерирует ключевую пару и отправляет публичный ключ мастеру. Администратор принимает ключ:

```bash
salt-key -L                          # Список: принятые, неподтверждённые и отвергнутые ключи
salt-key -a web-01.example.com       # Принять конкретный ключ
salt-key -A                          # Принять все ожидающие ключи (использовать с осторожностью)
salt-key -d web-01.example.com       # Удалить (отозвать) ключ
```

Проверка доступности миньонов: `salt '*' test.ping`.

### 5. Мониторинг и отладка

Наблюдение за потоком событий шины в реальном времени (полезно при настройке Beacons/Reactors и диагностике):

```bash
salt-run state.event pretty=True     # Трансляция событий Event Bus
```

Работа с кэшем заданий:

```bash
salt-run jobs.list_jobs              # Последние задания: JID, таргетинг, функция
salt-run jobs.lookup_jid 20260811120000123456   # Результаты задания по JID
salt '*' job.list_jobs               # Задания, доступные с конкретного миньона
```

### 6. Планировщик (Schedule)

Периодический запуск состояний непосредственно на миньоне (Pull-модель), без участия оператора:

```yaml
# /etc/salt/minion.d/schedule.conf
schedule:
  daily_highstate:
    function: state.highstate
    hours: 4
    minutes: 30
```

Каждое выполнение по расписанию порождает событие на шине и может дополнительно обрабатываться Reactor'ом на мастере.

### 7. Salt-API (netapi)

Выполнение команд через REST-интерфейс (обычно с внешней аутентификацией eAuth):

```bash
curl -sSk https://salt-master:8000/login -H "Content-Type: application/json" \
  -d '{"username":"devops","password":"***","eauth":"pam"}'
# → получаем токен

curl -sSk https://salt-master:8000/run -H "X-Auth-Token: <token>" \
  -d client='local' -d tgt='*' -d fun='test.ping'
```

### 8. Управление без агента (Salt-SSH)

Управление узлами через SSH без установки миньона. Подходит для начальной настройки, периодических проверок или закрытых сегментов, где установка постоянного агента невозможна.

```bash
salt-ssh '*' test.ping
salt-ssh '*' state.apply webserver
```

**Roster-файл** (`/etc/salt/roster`):
```yaml
web-01:
  host: 192.168.1.10
  user: root
  port: 22
  sudo: True
  priv: /root/.ssh/id_rsa

db-01:
  host: 192.168.1.20
  user: admin
  ssh_options:
    - StrictHostKeyChecking=no
```

**Thin mode:** Salt-SSH копирует минимальный набор библиотек (`salt-ssh`) в `/tmp/` на целевом узле и запускает команды через Python без установки. При последующих вызовах используется кэш (`--priv` или `--roster-file`). Удаление thin-файлов: `salt-ssh --clean`.

**Ограничения:** Salt-SSH не поддерживает Beacons, Reactors, Schedule на миньоне и постоянные исходящие соединения. Для полноценной событийной автоматизации требуется переход на классический Minion.

### 9. Failover с несколькими мастерами (Multi-Master)

Подключение миньона к нескольким мастерам для отказоустойчивости. Минон периодически проверяет доступность мастеров и автоматически переключается при падении основного.

```yaml
# /etc/salt/minion
master:
  - salt-master-01.example.com
  - salt-master-02.example.com
master_retry_timeout: 30
master_retry_interval: 10
```

**Синхронизация данных:** все мастера должны иметь доступ к одним `file_roots` (NFS, Git) и `pillar_roots`. Ключи миньонов хранятся на каждом мастере независимо; при добавлении миньона ключ должен быть принят на всех мастерах вручную (`salt-key -a <id>`) или синхронизированы через общий доступ к `/etc/salt/pki/master/`.

### 10. Возврат результатов (Returners)

Returners отправляют результаты заданий во внешние системы для хранения, аудита и построения отчётов.

**Встроенные returners:**
```yaml
# /etc/salt/master.d/returners.conf
ext_job_cache: redis
master_job_cache: mysql
```

```yaml
# /etc/salt/minion.d/returners.conf
return: redis
```

**Пример настройки PostgreSQL (master_job_cache):**
```yaml
mysql.user: salt
mysql.pass: secure_password
mysql.db: salt
mysql.host: localhost
mysql.port: 3306
```

**Пример настройки Redis (ext_job_cache + returner):**
```yaml
# /etc/salt/master.d/redis.conf
redis.host: redis.example.com
redis.port: 6379
redis.db: 0

# /etc/salt/minion.d/redis.conf
redis.host: redis.example.com
redis.port: 6379
```

Проверка работы:
```bash
salt '*' test.ping
salt-run jobs.list_jobs
# данные о задании появятся в PostgreSQL/Redis
```

### 11. Резервное копирование и аварийное восстановление

Для аварийного восстановления мастера необходимо регулярно резервировать ключевые компоненты. Полное руководство — в [Backup и восстановление SaltStack](Backup_Restore.md).

**Ключевые компоненты (частота бэкапа):**

| Компонент | Путь | Частота |
|:---|:---|:---|
| **PKI Keys** | `/etc/salt/pki/master/` | Ежедневно |
| **Master Config** | `/etc/salt/master`, `/etc/salt/master.d/` | Ежедневно |
| **file_roots** | `/srv/salt/` | Ежедневно |
| **pillar_roots** | `/srv/pillar/` | Ежедневно |
| **Job Cache** | PostgreSQL/Redis | Ежедневно |

**Критически важно:** перед восстановлением проверьте, что миньоны не смогли подключиться с неправильным мастером (MITM-атака), используя `master_finger` на миньонах.

### 12. Соответствие стандартам (Compliance)

Salt может использоваться для автоматической проверки соответствия инфраструктуры стандартам безопасности (CIS, PCI-DSS, HIPAA).

**Паттерн:**
1. Написать SLS-состояния, проверяющие конфигурацию (например, `file.managed` с нужными permissions, `service.running`, `pkg.installed` с конкретной версией).
2. Запустить `salt '*' state.apply compliance.cis_ubuntu_2204`.
3. Результаты сохранить в Returner (Elasticsearch) для формирования отчётов.

**Пример:**
```yaml
# /srv/salt/compliance/sshd_config.sls
sshd_config:
  file.managed:
    - name: /etc/ssh/sshd_config
    - source: salt://compliance/files/sshd_hardened.conf
    - mode: 600
    - user: root
    - group: root
    - require:
      - pkg: openssh-server
```

### 13. Мониторинг инфраструктуры Salt

Контроль за состоянием Salt-инфраструктуры. Полное руководство — в [Мониторинг Salt Infrastructure](Salt_Monitoring.md).

**Ключевые команды для healthcheck:**
- **Статус миньонов:** `salt-run manage.up` (активные), `salt-run manage.status` (все с статусом)
- **Активные задания:** `salt-run jobs.active`
- **Event Bus:** `salt-run state.event pretty=True`
- **Логи:** `tail -f /var/log/salt/master` / `tail -f /var/log/salt/minion`

**Что мониторить:** нагрузка CPU/RAM мастера, количество подключённых миньонов, задержки выполнения заданий, наличие ошибок в Event Bus, размер Job Cache.

**Интеграция:** через `event_return` в Elasticsearch/Splunk и `master_job_cache` в PostgreSQL/Redis для последующего анализа в Prometheus/Grafana.

## Операции и команды

### Управление ключами и подключением миньонов

| Команда | Назначение | Пример |
|:---|:---|
| `salt-key -L` | Список всех ключей (accepted, pending, rejected) | |
| `salt-key -A` | Принять все pending ключи | |
| `salt-key -a <id>` | Принять конкретный ключ | `salt-key -a web-01.example.com` |
| `salt-key -d <id>` | Удалить отозванный ключ | `salt-key -d old-node` |
| `salt-key -F master` | Показать отпечаток ключа мастера (для сверки `master_finger` на миньонах) | |

### Проверка и диагностика

| Команда | Назначение | Пример |
|:---|:---|
| `salt '*' test.ping` | Проверка доступности миньонов | |
| `salt-run manage.up` | Список активных миньонов | |
| `salt-run manage.status` | Статус всех миньонов (up/down) | |
| `salt-run jobs.active` | Активные задания | |
| `salt-run jobs.list_jobs` | История заданий | |
| `salt-run jobs.lookup_jid <JID>` | Результаты конкретного задания | `salt-run jobs.lookup_jid 20260101120000123456` |
| `salt-run state.event pretty=True` | Трансляция событий Event Bus в реальном времени | |
| `salt '*' grains.items` | Просмотр Grains конкретного миньона | |
| `salt '*' saltutil.sync_all` | Синхронизация кастомных модулей, грайнов, состояний | |
| `salt '*' saltutil.refresh_grains` | Обновить кэш Grains | |
| `salt '*' saltutil.refresh_pillar` | Обновить Pillar | |

### Применение состояний

| Команда | Назначение | Пример |
|:---|:---|
| `salt '*' state.apply <sls>` | Применить SLS-состояние | `salt 'web-*' state.apply nginx` |
| `salt '*' state.apply test=True` | Dry-run (просмотр изменений без применения) | |
| `salt '*' state.highstate` | Полное применение всех состояний через top.sls | |
| `salt '*' state.sls <sls>` | Применить конкретный SLS-файл | `salt 'web-*' state.sls nginx` |
| `salt '*' state.sls_id <id> <sls>` | Применить конкретный ID из SLS | `salt 'web-*' state.sls_id install_nginx webserver` |

**Диагностические команды (SRE):**
```bash
salt-run manage.status                  # статус всех миньонов
salt-run state.event pretty=True        # события шины
tail -f /var/log/salt/master            # логи мастера
tail -f /var/log/salt/minion            # логи миньона
salt '*' saltutil.sync_all              # синхронизация модулей/грайнов/статов
```

## Устранение неполадок

| Проблема | Причина | Решение |
|:---|:---|:---|
| `Minion did not return` | Минон не запущен или недоступен | `systemctl status salt-minion`; проверить сеть (порты 4505/4506 на мастере); `salt '*' test.ping` |
| `Key rejected` | Ключ не принят на мастере, или миньон уже имеет другой ключ | `salt-key -L`, `salt-key -a <minion_id>`; проверить отпечаток (`salt-key -F`); если ключ конфликтует — `salt-key -d <id>` и перезапустить миньона |
| `Authentication failure` | Несовпадение ключей, MitM-атака | Проверить `master_finger` на миньоне; включить `master_sign_pubkey: True` и `verify_master_pubkey_sign: True` на мастере |
| `Grains устарели` | Изменение окружения без обновления кэша | `salt '*' saltutil.refresh_grains` |
| `Pillar не подгружается` | Ошибка Jinja/SLS, отсутствие прав | `salt '*' saltutil.refresh_pillar`; `salt '*' pillar.items`; `salt-run pillar.show_pillar` |
| `State не идемпотентен` | Плохое состояние, меняющее систему без проверки | Использовать `test=True` перед применением; проверять логи миньона (`/var/log/salt/minion`) |
| `Salt-SSH connection refused` | Отсутствие ключа SSH, неправильный пользователь | Проверить `ssh-copy-id`; roster-файл; права на ключ (`chmod 600`) |
| `Event Bus перегружен` | Слишком много Beacons/реакций | Увеличить `interval` у Beacons; добавить фильтры; использовать `disable_during_state_run: True` |
| `Циклические зависимости` | Ошибка в SLS-файле | Salt сообщает на этапе компиляции; проверить `require`/`watch`/`prereq` |
| `Master не видит нового миньона` | Minion подключился, но ключ pending | `salt-key -L` → принять через `salt-key -a <id>` |

**Диагностика map.jinja и компиляции состояний:**
```bash
salt '*' state.show_highstate --out=json                    # → компиляция highstate (проверка map.jinja)
salt-run state.orchestrate orch.deploy test=True            # → dry-run оркестрации
salt-run state.orchestrate orch.deploy                       # → применение оркестрации
```

## Рекомендованные практики

### Масштабирование на 10 000+ узлов

**Рекомендации SRE:**
- **Железо мастера:** 4+ CPU ядер, 8+ GB RAM (на 10 000 миньонов — 16+ ядер, 32+ GB RAM).
- **ZeroMQ:** использовать аппаратный тюнинг (`tcp_keepalive`, `tcp_keepcnt`, `tcp_keepidle`) в `/etc/salt/master`.
- **Batching:** при массовом обновлении использовать `batch: 20%` или фиксированное число, чтобы избежать шторма.
- **Job Cache:** внешнее хранилище (PostgreSQL/Redis) вместо локального файлового кэша.
- **Salt Syndic / Multi-Master:** распределение нагрузки между несколькими мастерами (см. [Salt Syndic](Syndic_detailed.md)).
- **gitfs:** кэширование репозиториев на мастере (`gitfs_provider: gitpython`), уменьшение количества файлов в одном окружении.

### Производительность и тюнинг

- **Parallel execution:** состояния на миньонах выполняются параллельно по умолчанию. Для длинных задач на одном узле используйте `parallel: True` (отдельный процесс).
- **Batch:** ограничение количества одновременно обновляемых миньонов (`batch: 20%` или `batch: 100`).
- **State Aggregate:** объединение одинаковых состояний в один вызов менеджера пакетов (`state_aggregate: True`).
- **Cache:** `file_list_cache` для кэширования списка файлов; `pillar_cache` для Pillar; `grains_cache` для Grains.
- **ZeroMQ tuning:** в `/etc/salt/master`:
  ```yaml
  zeromq:
    tcp_keepalive: 1
    tcp_keepcnt: 5
    tcp_keepidle: 60
  ```
- **Job Cache cleanup:** `keep_jobs: 24` (часы) для автоматической очистки старых заданий.
- **Minion threads:** `multiprocessing: True` (по умолчанию) использует пул процессов; для очень больших сред можно ограничить `process_count_max`.

### Практики безопасности

- **Verify:** всегда используйте `auto_accept: False` и принимайте ключи вручную через `salt-key -a`.
- **Segregation:** `publisher_acl_blacklist` для блокировки опасных модулей (`cmd`, `state`) и пользователей (`root`) на мастере.
- **Transport security:** включайте `master_sign_pubkey: True` и `verify_master_pubkey_sign: True` для предотвращения MitM-атак на миньонах.
- **Salt-API hardening:** размещайте Salt-API за reverse proxy с HSTS; ограничьте доступ через `external_auth` (LDAP/PAM) с короткоживущими токенами и минимальными правами.
- **PKI backup:** регулярно бэкапите `/etc/salt/pki/master/` и проверяйте целостность ключей.

### Практики DevOps / SRE

1. **Версионирование:** храните SLS, Pillar и оркестрацию в Git (через gitfs). Используйте Git-ветки для окружений (`base`, `prod`, `staging`).
2. **Изоляция окружений:** `saltenv` и `pillarenv` должны соответствовать веткам Git; никогда не храните production-секреты в `base`.
3. **Идемпотентность:** все состояния должны быть безопасными для повторного запуска. Тестируйте через `test=True` перед применением в продакшене.
4. **Наблюдаемость:** интегрируйте Salt с SIEM (Splunk, Elasticsearch) через `event_return` и `master_job_cache`. Мониторьте Event Bus на аномалии.
5. **Аварийное восстановление:** регулярный бэкап PKI, `file_roots`, `pillar_roots` и Job Cache. Тестируйте восстановление на стенде.
6. **Документация:** для каждого SLS-файла указывайте `__doc__` в YAML; ведите changelog оркестрации в Git.

## Дополнительная информация

### Клиентские утилиты (CLI)

| Утилита | Назначение |
|:---|:---|
| `salt` | Выполнение команд и состояний на выбранном множестве миньонов. |
| `salt-call` | Локальный вызов функций на самом миньоне (включая Masterless-режим через `--local`). |
| `salt-key` | Управление ключами миньонов (принятие, удаление, проверка статуса). |
| `salt-run` | Запуск Runners на мастере (jobs, state.event, state.orchestrate). |
| `salt-cp` | Копирование файлов с мастера на миньоны. |

### Топологии развертывания

- **Один мастер**: Стандартная и наиболее распространенная топология. Подходит для небольших и средних инфраструктур.
- **Иерархия (Syndic)**: Узел-посредник (Syndic), который передаёт команды от «Мастера Мастеров» локальным мастерам. Позволяет масштабироваться на десятки тысяч узлов ([подробнее](Syndic_detailed.md)).
- **Multi-Master**: Подключение миньона к нескольким мастерам для отказоустойчивости. Допускает потерю одного мастера без простоя.
- **Salt-SSH**: Агентский режим (Agentless). Управление через SSH без установки миньона. Идеально для начальной настройки или закрытых сегментов ([подробнее](Salt_SSH_Advanced.md)).
- **Masterless**: Использование `salt-call --local` для применения состояний без мастера (например, при сборке образов Packer или в изолированных средах).

### Экосистема и свежесть (2026)

- **Salt 3008 LTS**: Актуальная ветка (3008.0 — 27 мая 2026, текущий релиз 3008.2 — 1 июля 2026). Улучшенная поддержка Python 3.12+, оптимизация ZeroMQ. Активная поддержка до 30 июня 2027, CVE-фиксы — до 30 июня 2028 ([жизненный цикл версий](https://endoflife.date/salt)).
- **Salt 3006 LTS / 3007 STS**: Ветка 3006 (LTS) переведена в режим только критических CVE-фиксов до 30 июня 2027; поддержка 3007 (STS) завершена 31 июля 2026. Рекомендуется планировать миграцию на 3008 (см. [Миграция и обновление](Migration_Upgrade.md)).
- **Python 3**: Начиная с версии 3000+ требуется только Python 3; в 3008 поддерживается Python 3.12+.
- **Salt-API**: REST-интерфейс для интеграции Salt с внешними системами (CI/CD, порталы самообслуживания), обычно с внешней аутентификацией (eAuth).
- **Tiamat / Onedir**: Современный метод распространения Salt в виде единого бинарного файла со всеми зависимостями (упрощает установку в изолированных ОС).
- **Контейнеризация**: Управление контейнерами Docker, Podman; интеграция с Kubernetes через Salt-модули.
- **Event-Driven Automation**: Использование связки [Beacon + Reactor](Orchestration_and_Automation_Methods.md) для создания самовосстанавливающейся инфраструктуры.
- **Push/Pull модель**: Salt поддерживает оба подхода — [сравнение Push и Pull моделей](../Concepts/configuration_management_push_vs_pull.md).

**Полезные ссылки:**
- [Архитектура и концепции: сравнительный обзор инструментов](../Concepts/configuration_management_tools.md)
- [Официальный жизненный цикл версий](https://endoflife.date/salt)
- [Официальная документация Salt](https://docs.saltproject.io/)
- [Формулы SaltStack](Formulas.md) — переиспользуемые пакеты состояний
- [Тестирование состояний](Testing_States.md) — CI/CD для Salt states
- [Безопасность SaltStack](Security_Approaches.md) — PKI, eAuth, шифрование