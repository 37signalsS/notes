# Оркестрация и методы автоматизации в SaltStack

## Определения

- **Оркестрация (Orchestration)**: Процесс координации задач на множестве узлов с учётом их взаимозависимостей. Выполняется на Salt Master через runner `state.orchestrate`, который обобщает систему состояний до уровня всей инфраструктуры: в отличие от [Highstate](Highstate_and_Execution_Order.md), оркестрация управляет порядком применения состояний между разными миньонами и может остановить весь прогон при сбое на одном из узлов. Система пришла на смену механизму OverState (заменена в Salt 2015.8.0).
- **state.orch**: Синоним runner `state.orchestrate`, используемый для краткости в CLI и документации.
- **orch (каталог)**: Рекомендуемый подкаталог в `file_roots` для SLS-файлов оркестрации (например, `/srv/salt/orch/`). Выделение отдельного каталога предотвращает конфликты имён с состояниями, применяемыми на миньонах.
- **Runner**: Модуль, исполняемый на Salt Master. Раннеры обеспечивают логику управления инфраструктурой (например, `state.orchestrate`, `cloud.profile`, `jobs.lookup_jid`).
- **Wheel**: Интерфейс управления мастером (аналогично Runners, но для операций управления ключами, конфигурацией и инфраструктурой мастера). Доступен через `salt-run wheel.` или Salt-API с маркером `@wheel`.
- **Beacon (Маяк)**: Лёгкий процесс на Minion, который периодически отслеживает системные события (изменения файлов, нагрузку, статус сервисов, дисковое пространство) и отправляет уведомления на шину событий с тегом `salt/beacon/<minion>/<beacon>`.
- **Reactor (Реактор)**: Компонент на Master, который слушает шину событий и в ответ на совпадение тега запускает действия: применение состояний на миньонах (`local.*`), выполнение раннеров (`runner.*`) или wheel-функций (`wheel.*`) на мастере.
- **Событие (Event)**: Сообщение на шине событий, состоящее из тега (tag) и структуры данных (data). Тег используется для быстрой фильтрации, данные содержат информацию о событии.
- **Salt-Cloud**: Инструмент для автоматизированного создания и уничтожения виртуальных машин и их последующей привязки к мастеру.
- **Salt-API**: REST-интерфейс (модули `netapi` — `rest_cherrypy`, `rest_tornado`) для интеграции Salt с внешними системами: CI/CD, порталы самообслуживания, вебхуки. Обычно используется с внешней аутентификацией eAuth.
- **eAuth (External Authentication)**: Система делегирования аутентификации внешним провайдерам (LDAP, Active Directory, PAM, OAuth2/JWT) для доступа к Salt-API или CLI с выдачей короткоживущих токенов ([подробнее](Security_Approaches.md)).
- **batch**: Параметр оркестрации, ограничивающий количество одновременно обновляемых миньонов. Принимает процент (`batch: 20%`) или фиксированное число (`batch: 50`). Используется для предотвращения «шторма» запросов к базе данных или API при массовом обновлении.
- **expect_minions**: Ожидаемое минимальное количество миньонов, от которых должны поступить результаты. Если фактическое количество меньше — runner завершается с ошибкой. Полезно для обнаружения частичного таргетинга или недоступных узлов.
- **allow_fail**: Допустимое количество или процент миньонов, которые могут завершиться с ошибкой, не прерывая весь прогон оркестрации. Пример: `allow_fail: 10%`.
- **fail_function**: Функция на мастере, которая проверяет результат выполнения `salt.function` до перехода к следующим состояниям. Позволяет реализовать сложную логику проверки (например, парсинг вывода команды), недоступную через стандартные реквизиты.
- **subset**: Случайная выборка подмножества целей (`subset: 10`) для канареечных проверок перед полным развертыванием.
- **retry**: Параметр, указывающий количество повторных попыток выполнения состояния при ошибке. Доступен с версии 2019.2.0. Пример: `retry: 3` с `retry_interval: 30` (пауза 30 секунд между попытками).
- **salt.wait_for_event**: Состояние оркестрации, блокирующее пайплайн до получения события с заданным тегом. Используется для ожидания возврата миньонов после перезагрузки или завершения асинхронных задач.
- **salt.parallel_runners**: Состояние оркестрации для параллельного запуска нескольких runner-функций на мастере (доступно с версии 2018.3.0).
- **salt.environment**: Параметр окружения для runner-вызовов внутри оркестрации, позволяющий выбирать версии состояний и Pillar.

---

## Основные концепции

### Модели автоматизации

| Модель | Назначение | Инструмент |
| :--- | :--- | :--- |
| **Push** | Мгновенное управление «сверху вниз» | `salt`, `state.apply` |
| **Pull** | Автоматическая коррекция дрейфа конфигурации | `schedule` на миньонах |
| **Event-Driven** | Реактивная инфраструктура (Self-healing) | `Beacons` + `Reactor` |
| **Orchestration** | Сложные многошаговые пайплайны | `state.orchestrate` |

### Жизненный цикл оркестрации

Оркестрация проходит следующие этапы:

1. **Компиляция SLS**: Мастер читает SLS-файл оркестрации, рендерит Jinja-шаблоны и строит внутреннее представление (High State) так же, как для миньонных состояний.
2. **Разрешение таргетинга**: Для каждого `salt.*` состояния мастер вычисляет целевое множество миньонов через `tgt`/`tgt_type` (glob, grain, pillar, compound).
3. **Выполнение по порядку**: Состояния выполняются последовательно в порядке объявления в SLS. Реквизиты (`require`, `watch`, `prereq`, `onchanges`, `onfail`) определяют зависимости между блоками.
4. **Параллелизм внутри блока**: Все миньоны внутри одного `salt.*` состояния обрабатываются параллельно. Параметр `batch` разбивает их на очереди.
5. **Сбор результатов**: Мастер ожидает результаты от целевых миньонов. Если включён `expect_minions`, проверяется минимальное количество ответивших.
6. **Обработка ошибок**: При ошибке runner проверяет `allow_fail` (разрешённый процент неудач) и `failhard` (глобальная остановка). Если состояние имеет `retry`, выполняется повторная попытка.
7. **Возврат результатов**: Результаты оркестрации отправляются в Returner и генерируют событие `salt/job/<JID>/ret` в Event Bus.

### Механизмы оркестрации (`state.orchestrate`)

Оркестрация выполняется через Runner `state.orchestrate` и использует SLS-файлы на мастере (каталоги `file_roots`). Для SLS оркестрации и реакций рекомендуется выделять отдельные подкаталоги (`orch/`, `react/` и т.п.), чтобы избежать конфликтов имён с состояниями миньонов.

Запуск оркестрации выполняется на мастере:

```bash
salt-run state.orchestrate orch.web_update            # применить SLS orch/web_update.sls
salt-run state.orch orch.web_update                   # синоним state.orchestrate
salt-run state.orchestrate orch.web_update test=True  # пробный прогон (dry run)
salt-run state.orchestrate orch.web_update pillarenv=prod  # Pillar-окружение
salt-run state.orchestrate orch.web_update saltenv=prod    # окружение состояний
salt-run state.orchestrate orch.web_update retry=3         # повторные попытки (с 2019.2.0)
# → master_web01:
#   ----------
#   Summary for master_web01
#   ------------
#   Succeeded: 2
#   Failed:    0
```

В Masterless-режиме доступен вариант `salt-call --local state.orchestrate` (из интерфейсов `salt.*` в нём поддерживается только `salt.state`).

Оркестрационные SLS используют специальные состояния `salt.*`, предоставляющие доступ к управляющим интерфейсам Salt:

| Интерфейс | Назначение |
| :--- | :--- |
| `salt.state` | Применение состояний (список `sls`) или highstate (`highstate: True`) к группе миньонов. |
| `salt.function` | Выполнение произвольной функции (execution module) на миньонах. |
| `salt.runner` | Выполнение runner-функции на мастере (например, `cloud.profile`, `manage.up`). |
| `salt.wheel` | Выполнение wheel-функции на мастере для управления ключами (например, `key.accept`). |
| `salt.wait_for_event` | Блокировка пайплайна до получения события с заданным тегом. |
| `salt.parallel_runners` | Параллельный запуск нескольких runner-функций на мастере (с версии 2018.3.0). |

**Ключевые параметры:**

- **Таргетинг**: `tgt` (целевое множество) и `tgt_type` (glob, grain, pillar, compound и др.).
- **Окружения**: `saltenv` (окружение состояний) и `pillarenv` (окружение Pillar). Позволяют использовать разные версии SLS и секретов для dev/staging/prod.
- **Реквизиты**: для `salt.*`-состояний работают все реквизиты (включая `require`, `watch`), ссылки на другие блоки — через `- salt: <id>`. Именно они обеспечивают межминьонные зависимости.
- **Управление потоком**: `batch` (выполнение по частям), `subset` (случайное подмножество), `failhard` (остановка при первой ошибке).
- **Контроль выполнения**: `expect_minions` (ошибка, если часть миньонов не ответила), `allow_fail` (допустимое число неудачных миньонов), `fail_function` для `salt.function` (проверка результата на мастере), `retry` (повторные попытки).
- **Передача данных**: параметр `pillar` передаёт данные в state run; `pillarenv` / `saltenv` выбирают окружения; `ret` / `ret_config` отправляют результаты в returner'ы.

Пример комбинированной оркестрации — применение состояния, дымовая проверка функцией и приём ключа нового миньона:

```yaml
# /srv/salt/orch/scale_out.sls
install_backend:
  salt.state:
    - tgt: 'role:web'
    - tgt_type: grain
    - sls:
        - web.app

smoke_test:
  salt.function:
    - name: cmd.run
    - tgt: 'role:web'
    - tgt_type: grain
    - arg:
        - 'curl -fsS http://127.0.0.1/healthz'
    - require:
        - salt: install_backend

accept_new_key:
  salt.wheel:
    - name: key.accept
    - match: 'web-*'
    - require:
        - salt: smoke_test
```

### Модель выполнения Reactor SLS

Reactor SLS — это YAML + Jinja, который выполняется на мастере асинхронно при получении события. В отличие от оркестрации, reactor SLS:

- **Не поддерживает реквизиты**: нет `require`, `watch`, `order`. Логика упорядочивания должна быть выражена через последовательность состояний или через вызов `runner.state.orchestrate`.
- **Не поддерживает условные конструкции состояния**: Jinja может использоваться для генерации YAML, но не для ветвления внутри выполнения.
- **Имеет ограниченный контекст**: доступны переменные `tag` (тег события) и `data` (данные события). Для доступа к Pillar используйте `pillar.get` внутри Jinja.
- **Требует уникальности ID**: поскольку reactor SLS может выполняться параллельно для нескольких событий, повторяющиеся ID состояний могут привести к перезаписи или непредсказуемому поведению.

Типичный паттерн: Reactor ловит событие и запускает `runner.state.orchestrate`, перенаправляя сложную логику в полноценный оркестрационный SLS.

### Событийная модель: Beacon → Event Bus → Reactor

Ключевое преимущество Salt перед push-only инструментами — реактивная автоматизация. Поток данных строится по цепочке:

1. **Beacon** на миньоне обнаруживает событие (изменение файла, рост нагрузки, падение сервиса).
2. Событие с тегом `salt/beacon/<minion>/<beacon>` попадает на шину событий мастера.
3. **Reactor** на мастере сопоставляет тег с SLS-файлом реакций и выполняет действия (применение состояний, запуск оркестрации).

**Beacons (настройка на миньоне).** Конфигурируются в `/etc/salt/minion`, `/etc/salt/minion.d/beacons.conf`, Pillar или Grains. По умолчанию проверка выполняется раз в секунду (`interval`). Встроенные типы: `load`, `inotify`, `service`, `diskusage`, `ps`, `journald`, `network_info`, `status` и др.

Управление на лету, без перезапуска миньона:

```bash
salt '*' beacons.list                    # текущая конфигурация beacon'ов
salt '*' beacons.enable_beacon load      # включить beacon
salt '*' beacons.disable_beacon load     # выключить beacon
salt '*' beacons.save                    # сохранить в /etc/salt/minion.d/beacons.conf
```

Важно: если реакция (например, `state.apply`) сама изменяет файл, за которым следит beacon, возникает событийная петля. Защита — параметр `disable_during_state_run: True`, отключающий beacon на время прогона состояний.

**Reactor (настройка на мастере).** Сопоставление тегов событий и SLS-файлов задаётся в конфигурации мастера:

```yaml
# /etc/salt/master.d/reactor.conf
reactor:
  - 'salt/minion/*/start':          # шаблоны (glob) по тегам событий
    - /srv/salt/reactor/start.sls   # локальный путь на мастере
  - 'myco/custom/event':
    - salt://reactor/custom.sls     # или файл с файлового сервера
```

Reactor SLS — это обычный YAML + Jinja. В шаблоне доступны переменные `tag` (тег события) и `data` (данные события). Типы реакций:

| Тип | Назначение |
| :--- | :--- |
| `local.*` | Выполнение функции/состояния на целевых миньонах (`local.state.apply`). |
| `runner.*` | Выполнение runner-функции на мастере (`runner.state.orchestrate`). |
| `wheel.*` | Выполнение wheel-функции на мастере (`wheel.key.delete`). |
| `caller.*` | Выполнение функции на masterless-миньоне. |

Ограничения: reactor SLS не поддерживает реквизиты, упорядочивание и условные конструкции состояния. Сложную логику следует выносить в оркестрацию — распространённый паттерн: Reactor ловит событие и запускает `runner.state.orchestrate`. ID состояний runner/wheel-реакций должны быть уникальны, иначе реакции могут перезаписывать друг друга в асинхронной очереди.

**Основные теги событий:**

| Тег | Событие |
| :--- | :--- |
| `salt/minion/<id>/start` | Подключение миньона к мастеру (старт, перезагрузка). |
| `salt/auth` | Попытка аутентификации миньона. |
| `salt/key` | Действия с ключами миньонов. |
| `salt/cloud/<vm>/created` / `destroyed` | Создание/уничтожение ВМ через Salt-Cloud. |
| `salt/beacon/<minion>/<beacon>` | Событие от beacon. |
| `salt/job/<jid>/new` / `ret` | Новое задание / возврат результата. |
| `salt/netapi/hook/<path>` | Вебхук Salt-API. |
| произвольные | Пользовательские события через `salt-call event.send <tag> data='{...}'`. |

### Возврат результатов (Returners) в оркестрации

Returners позволяют отправлять результаты выполнения оркестрации во внешние системы для хранения, аудита и построения отчётов. В оркестрации returners настраиваются через параметры `ret` (имя returner-модуля) и `ret_config` (путь к конфигурационному файлу). Пример:

```bash
salt-run state.orchestrate orch.deploy_app ret=redis ret_config=/etc/salt/master.d/redis.conf
```

На мастере returner получает детализированные результаты по каждому `salt.*` состоянию, включая JID, таргетинг, время выполнения и выходные данные. Это позволяет интегрировать оркестрацию с SIEM, Elasticsearch, PostgreSQL или Prometheus Pushgateway.

### saltenv и pillarenv в оркестрации

Окружения позволяют использовать разные версии состояний и секретов для dev/staging/prod. В оркестрации окружение выбирается при запуске runner:

```bash
salt-run state.orchestrate orch.deploy_app saltenv=prod pillarenv=prod
```

Внутри SLS оркестрации окружение можно переопределить для отдельных состояний через параметры `saltenv` и `pillarenv` в блоке `salt.state`. Это полезно, когда разные этапы пайплайна требуют разных версий SLS (например, тестовые состояния из `staging`, продакшен — из `prod`).

### Планировщик заданий мастера (Master Schedule)

В отличие от `schedule` на миньонах (Pull-модель), расписание на мастере позволяет автоматизировать Push/Orchestration-сценарии без участия оператора:

```yaml
# /etc/salt/master.d/schedule.conf
schedule:
  nightly_rollout:
    runner: state.orchestrate
    args:
      - orch.nightly_deploy
    when: 02:30
```

Управление заданиями мастера:

```bash
salt-run schedule.list                      # список запланированных заданий
# → nightly_rollout:
#     runner: state.orchestrate
#     args: ['orch.nightly_deploy']
salt-run schedule.enable nightly_rollout    # включить задание
salt-run schedule.disable nightly_rollout   # приостановить задание
```

Каждое выполнение по расписанию порождает задание с уникальным JID, отправляет результаты в Returner и генерирует событие на шине, которое может обрабатываться Reactor'ом.

---

## Практические сценарии

### 1. Многоуровневое развертывание (Blue-Green)

Оркестрация для обновления балансировщика только после успешного обновления бэкендов.

```yaml
# /srv/salt/orch/web_update.sls

update_backend_pool:
  salt.state:
    - tgt: 'role:web'
    - tgt_type: grain
    - sls: web.app
    - batch: 20%          # обновлять по 20% серверов за раз
    - failhard: True      # остановить прогон при первой ошибке

reload_load_balancer:
  salt.function:
    - name: service.reload
    - tgt: 'role:lb'
    - tgt_type: grain
    - arg:
        - angie
    - require:
        - salt: update_backend_pool
```

Запуск: `salt-run state.orchestrate orch.web_update`.

### 2. Автоматическое масштабирование (Event-Driven)

Beacon на миньоне следит за нагрузкой, Reactor на мастере запускает новую ВМ через Salt-Cloud.

**Настройка Beacon (на миньоне):**

```yaml
# /etc/salt/minion.d/beacons.conf
beacons:
  load:
    - averages:
        1m:
          - 2.0      # событие, когда Load Average (1 мин) попадает в диапазон [2.0; 100.0]
          - 100.0
        5m:
          - 0.0
          - 1.5
        15m:
          - 0.1
          - 1.0
    - onchangeonly: True   # событие только при переходе через порог
    - interval: 10         # проверка каждые 10 секунд
```

**Сопоставление события с реакцией (на мастере):**

```yaml
# /etc/salt/master.d/reactor.conf
reactor:
  - 'salt/beacon/*/load':
    - /srv/salt/reactor/autoscale.sls
```

**Настройка Reactor (на мастере):**

```yaml
# /srv/salt/reactor/autoscale.sls
{% set load_1m = data.get('data', {}).get('load', {}).get('1m', 0) %}
{% if load_1m >= 2.0 %}
provision_new_node:
  runner.cloud.profile:
    - args:
        - profile: web_node
        - name: web-node-{{ range(1, 1000) | random }}
{% endif %}
```

Примечание: событие от beacon приходит на мастер «обёрнутым» — полезная нагрузка находится в `data['data']`, а `data['id']` содержит ID миньона. Запуск ВМ в этом примере выполняет runner `cloud.profile` (Salt-Cloud); при необходимости сложного жизненного цикла реакцию лучше переадресовать на оркестрацию через `runner.state.orchestrate`.

### 3. Интеграция с CI/CD (Salt-API и Webhooks)

Запуск оркестрации из внешнего пайплайна (например, GitLab CI). Общие принципы пайплайнов — в [обзоре CI/CD](../CI-CD/ci_cd_overview.md).

**Вариант A — прямой вызов runner через `/run`:**

```bash
curl -sk https://salt-master:8000/run \
  -H "X-Auth-Token: $TOKEN" \
  -d client='runner' \
  -d fun='state.orchestrate' \
  -d mods='orch.deploy_app' \
  -d pillar='{"version": "v1.2.3"}'
# → {"return": [{"master_web01": {"comment": "States ran successfully.", "result": true}}]}
```

**Вариант B — вебхук `/hook` (событийный подход).** POST-запрос к Salt-API порождает событие с тегом `salt/netapi/hook/<path>`, которое обрабатывает Reactor:

```bash
curl -sS https://salt-master:8000/hook/deploy/prod \
  -H 'Content-Type: application/json' \
  -d '{"version": "v1.2.3", "commit": "abc123"}'
# → true  (событие salt/netapi/hook/deploy/prod опубликовано в шину)
```

```yaml
# /etc/salt/master.d/reactor.conf
reactor:
  - 'salt/netapi/hook/deploy/*':
    - /srv/salt/reactor/deploy.sls
```

```yaml
# /srv/salt/reactor/deploy.sls
deploy:
  runner.state.orchestrate:
    - args:
        - mods: orch.deploy_app
        - pillar:
            event_tag: {{ tag }}
            event_data: {{ data | json }}
```

Безопасность вебхуков: endpoint `/hook` по умолчанию не требует аутентификации — используйте SSL, секретный ключ в теле запроса (проверяемый внутри реактора) и ограничение источника по файрволу. Ограничение прав eAuth на запуск только конкретных оркестраций — в [подходах к безопасности](Security_Approaches.md).

### 4. Канареечное развертывание (Canary с subset)

Перед полным развертыванием проверяем случайное подмножество миньонов:

```yaml
# /srv/salt/orch/canary.sls

canary_deploy:
  salt.state:
    - tgt: 'role:web'
    - tgt_type: grain
    - sls: web.app
    - subset: 3            # случайные 3 миньона
    - failhard: True

full_deploy:
  salt.state:
    - tgt: 'role:web'
    - tgt_type: grain
    - sls: web.app
    - require:
        - salt: canary_deploy
    - onfail:
        - salt: canary_deploy
```

Примечание: `subset` выбирает случайные миньоны из таргета. Для детерминированной канарейки используйте grain/pillar-фильтр (например, `tgt: 'canary:True'`).

### 5. Ожидание перезагрузки парка (`salt.wait_for_event`)

Паттерн rolling-reboot: сначала перезагружаются все миньоны, затем оркестрация блокируется до тех пор, пока каждый из них не вернётся на шину событий (тег `salt/minion/<id>/start`).

```yaml
# /srv/salt/orch/rolling_reboot.sls
reboot_all_minions:
  salt.function:
    - name: system.reboot
    - tgt: 'role:web'
    - tgt_type: grain

wait_for_reboots:
  salt.wait_for_event:
    - name: salt/minion/*/start
    - id_list:
        - web-01
        - web-02
        - web-03
    - timeout: 600        # ждать не более 10 минут
    - require:
        - salt: reboot_all_minions
```

`id_list` — список ID миньонов. При каждом совпадении тега Salt извлекает из данных события ключ `event_id` (по умолчанию `id`) и удаляет его из списка. Когда список пуст — состояние возвращает успех и пайплайн продолжается.

### 6. Частичные сбои: allow_fail + expect_minions

При обновлении больших парков часть миньонов может быть временно недоступна. Комбинация `allow_fail` и `expect_minions` позволяет детерминированно обработать такие ситуации:

```yaml
# /srv/salt/orch/bulk_update.sls

update_web:
  salt.state:
    - tgt: 'role:web'
    - tgt_type: grain
    - sls: web.app
    - batch: 10%
    - allow_fail: 5%       # до 5% миньонов могут упасть
    - expect_minions: 95%   # минимум 95% от таргета должны ответить
    - retry: 2
    - retry_interval: 60
```

- `expect_minions: 95%` — runner завершится с ошибкой, если ответят менее 95% миньонов из таргета.
- `allow_fail: 5%` — даже если часть миньонов ответила с ошибкой, прогон считается успешным.
- `retry: 2` — при недоступности миньонов выполняется повторная попытка через 60 секунд.

### 7. Параллельные runner-задачи на мастере

`salt.parallel_runners` позволяет запускать независимые runner-функции параллельно, ускоряя операции на мастере (с версии 2018.3.0):

```yaml
# /srv/salt/orch/parallel_checks.sls

health_checks:
  salt.parallel_runners:
    - runners:
        - manage.up
        - fileserver.file_list
        - pillar.get_pillar_roots
    - require:
        - salt: prerequisite_state
```

Каждый runner выполняется в отдельном процессе. Результаты возвращаются в порядке завершения. Для зависимых runner используйте обычные `salt.runner` состояния с реквизитами.

### 8. failhard в оркестрации

Глобальный `failhard` в конфиге миньона останавливает весь прогон на миньоне. В оркестрации (`state.orchestrate`) доступен параметр `failhard` на уровне runner, который останавливает весь пайплайн оркестрации при сбое на любом миньоне. Не путайте их: `failhard` в SLS-состоянии действует локально, а `failhard` в `state.orchestrate` — глобально для всей инфраструктуры.

```yaml
# /srv/salt/orch/critical_deploy.sls
deploy_app:
  salt.state:
    - tgt: 'role:web'
    - tgt_type: grain
    - sls: web.app
    - failhard: True       # остановить всю оркестрацию при ошибке
```

### 9. Реактор с инъекцией Pillar

Reactor может передавать данные события как Pillar в оркестрацию:

```yaml
# /srv/salt/reactor/deploy.sls
trigger_deploy:
  runner.state.orchestrate:
    - args:
        - mods: orch.deploy_app
        - pillar:
            event_tag: {{ tag }}
            event_data: {{ data | json }}
            version: {{ data.get('version', 'latest') }}
```

Внутри `orch/deploy_app.sls` данные доступны через `{{ pillar.get('version') }}`. Это позволяет использовать один оркестрационный SLS для разных сценариев, изменяя поведение через события.

### 10. Masterless-оркестрация

В изолированных сегментах или при сборке образов доступен masterless-режим:

```bash
salt-call --local state.orchestrate orch.local_setup
```

Ограничения masterless-оркестрации:
- Нет `salt.runner`, `salt.wheel`, `salt.parallel_runners` — только `salt.state` (локальное применение).
- Нет Reactor и Beacons — только локальные состояния.
- Нет межминьонных зависимостей — `salt.state` применяется на локальном узле.
- `expect_minions`, `allow_fail` не работают — нет группы миньонов.

Подходит для: golden images, air-gapped сред, edge-устройств без постоянного подключения к мастеру.

### 11. Автоматизация приёма ключей через Wheel

Оркестрация может автоматически принимать ключи новых миньонов после успешного smoke-test:

```yaml
# /srv/salt/orch/bootstrap.sls

wait_for_minion:
  salt.wait_for_event:
    - name: salt/minion/*/start
    - id_list:
        - new-node-01
    - timeout: 300
    - require:
        - salt: provision_new_node

accept_key:
  salt.wheel:
    - name: key.accept
    - match: 'new-node-*'
    - require:
        - salt: wait_for_minion
```

Для защиты от неавторизованных ключей используйте `match` с точным префиксом и комбинируйте с `expect_minions` на уровне `salt.wait_for_event`.

### 12. Возврат результатов оркестрации в SIEM

Отправка результатов оркестрации в Elasticsearch для аудита:

```bash
salt-run state.orchestrate orch.deploy_app \
  ret=elasticsearch \
  ret_config=/etc/salt/master.d/elasticsearch.conf
```

Конфигурация returner:

```yaml
# /etc/salt/master.d/elasticsearch.conf
elasticsearch:
  hosts:
    - http://elasticsearch.example.com:9200
  index: salt-orchestration
  doc_type: _doc
```

Каждый `salt.*` блок создаёт отдельный документ в индексе, содержащий JID, таргет, результат, время выполнения и выходные данные. Это позволяет строить отчёты по успешности развертываний и временам выполнения.

### 13. Периодическая оркестрация (Schedule на мастере)

Оркестрацию можно запускать по расписанию на самом мастере — например, ежедневный rollout обновлений или периодическая сверка конфигураций:

```yaml
# /etc/salt/master.d/schedule.conf
schedule:
  nightly_rollout:
    runner: state.orchestrate
    args:
      - orch.nightly_deploy
    when: 02:30
```

Управление заданиями мастера:

```bash
salt-run schedule.list                      # список запланированных заданий
# → nightly_rollout:
#     runner: state.orchestrate
#     args: ['orch.nightly_deploy']
salt-run schedule.enable nightly_rollout    # включить задание
salt-run schedule.disable nightly_rollout   # приостановить задание
```

В отличие от `schedule` на миньонах (Pull-модель), расписание на мастере — способ автоматизации Push/Orchestration-сценариев без участия оператора.

### 14. Dry run оркестрации

Пробный прогон без внесения изменений:

```bash
salt-run state.orchestrate orch.web_update test=True
# → dry-run: показаны изменения, но они не применены
```

Для детализации low-state используйте:

```bash
salt-run state.show_sls orch.web_update     # скомпилированный High State
salt-run state.show_lowstate orch.web_update # Low State (после рендеринга Jinja)
```

---

## Дополнительная информация

### Оптимизация и масштабирование

- **Batching**: `batch` в `salt.state` / `salt.function` позволяет избежать «шторма запросов» к базе данных или API при одновременном обновлении тысяч узлов (задаётся процентом или фиксированным числом).
- **Subset**: случайная выборка подмножества целей (`subset: 10`) для канареечных проверок.
- **Throttling**: ограничение количества одновременно выполняемых заданий на мастере.
- **Параллелизм**: `salt.parallel_runners` для независимых runner-задач на мастере; состояния на миньонах выполняются параллельно по умолчанию.
- **Event Bus**: в ветке 3008 LTS оптимизирована работа шины событий для высоконагруженных сред с 10,000+ миньонами ([архитектура](Architecture.md)).

### Сравнение подходов

- **Ansible**: работает преимущественно в Push-модели (SSH). Salt Orchestration выигрывает за счёт постоянных агентов и шины событий, что позволяет реализовать реактивные сценарии (Beacon + Reactor) и межминьонные зависимости с детерминированным порядком.
- **Terraform**: лучше подходит для создания базовой инфраструктуры (Networking, VPC). Salt-Cloud и оркестрация эффективнее для управления жизненным циклом приложений и оперативного масштабирования.
- **Kubernetes/GitOps**: для контейнерных сред чаще используются Argo CD / Flux; Salt остаётся инструментом для традиционных ОС, физических и виртуальных машин, edge-узлов.

### Лучшие практики (2026)

1. **Разделение ответственности**: SLS для миньонов описывают *состояние*, SLS оркестрации — *процесс*. Храните их в отдельных каталогах (`orch/`, `react/`).
2. **Использование Pillar**: передавайте динамические данные (версии ПО, флаги функций) через `pillar` в момент запуска оркестрации; из реактора данные события пробрасываются как inline Pillar.
3. **Безопасность**: ограничивайте права eAuth на запуск только конкретных оркестраций и целей; вебхуки Salt-API защищайте SSL и секретным ключом ([безопасность](Security_Approaches.md)).
4. **Мониторинг**: интегрируйте Beacons со стеком Prometheus/Grafana для визуализации инфраструктурных событий в реальном времени.
5. **Dry run**: перед применением оркестрации в проде выполняйте пробный прогон с `test=True`.
6. **Контроль отказов**: используйте `failhard`, `expect_minions`, `allow_fail` и `fail_function` для детерминированного поведения при частичных сбоях.
7. **Идемпотентность и защита от петель**: состояния, запускаемые реактором, должны быть идемпотентными; для beacon, реагирующих на файлы, включайте `disable_during_state_run: True`.
8. **Уникальность ID реакций**: ID состояний в reactor SLS для runner/wheel должны быть уникальны, иначе реакции могут перезаписывать друг друга.
9. **Версионирование**: храните SLS оркестрации и реакций в Git (в т.ч. через gitfs) и версионируйте схемы Pillar.
10. **Masterless-осторожность**: не используйте masterless-оркестрацию для сценариев, требующих межминьонных зависимостей или реакторной модели.

---

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Reactor SLS не срабатывает | Неверный тег события или путь к SLS | `salt-run reactor.list`; проверить точность тега в `reactor.conf`; убедиться, что файл существует и читаем (`ls -la /srv/salt/reactor/`) |
| Event не получен `salt.wait_for_event` | Таймаут или неверный тег | Увеличить `timeout`; проверить тег через `salt-run state.event pretty=True`; убедиться, что событие имеет корректный `event_id` |
| Миньоны не отвечают при `batch` | Недоступность узлов, шторм запросов | Уменьшить `batch`; проверить `salt '*' test.ping`; увеличить `timeout` в конфиге миньона |
| `expect_minions` завершается с ошибкой | Часть миньонов не входит в таргет или недоступна | Уменьшить процент `expect_minions`; проверить таргет через `salt -G 'role:web' test.ping` |
| `allow_fail` не работает в оркестрации | Параметр указан в неверном блоке или устаревшая версия Salt | Указать `allow_fail` внутри `salt.*` состояния; проверить версию (`salt --version`) |
| `fail_function` возвращает ошибку | Функция возвращает неожидаемый результат или не существует | Проверить синтаксис функции на мастере: `salt-run cmd.run "test.ping"`; убедиться, что функция возвращает булево значение |
| Reactor вызывает петлю событий | Beacon реагирует на изменения, которые сам же и вызывает | Включить `disable_during_state_run: True` в конфигурацию beacon; добавить проверку источника события |
| Wheel `key.accept` не работает в реакторе | Недостаточно прав eAuth или неверный `match` | Проверить права eAuth на `@wheel`; проверить синтаксис `match`; убедиться, что ключ в статусе `pending` |
| Salt-API вебхук не триггерит реактор | Ошибка сети, SSL или аутентификация | Проверить доступность порта 8000; тест через `curl -v`; проверить конфигурацию `netapi` и права доступа |

**Диагностика:**

```bash
salt-run state.event pretty=True          # наблюдение за событиями шины в реальном времени
salt-run reactor.list                      # список активных реакций
salt-run jobs.lookup_jid <jid>            # результаты задания по JID
salt '*' beacons.list                     # текущие beacon'ы на миньоне
salt-call event.send myco/test/event data='{"status": "ok"}'  # эмуляция пользовательского события
salt-run schedule.list                    # запланированные задания мастера
salt-run manage.status                    # статус всех миньонов
```

---

## Версии и совместимость

| Возможность | Версия Salt | Примечание |
| :--- | :--- | :--- |
| `state.orchestrate` | 2015.8.0 | Замена OverState |
| `salt.parallel_runners` | 2018.3.0 | Параллельные runner-задачи |
| `expect_minions` | 2018.3.0 | Ожидание минимального числа миньонов |
| `allow_fail` | 2018.3.0 | Допустимое число неудач |
| `fail_function` | 2018.3.0 | Проверка результата на мастере |
| `retry` | 2019.2.0 | Повторные попытки состояния |
| `subset` | 2017.7.0 | Случайное подмножество миньонов |
| `salt.wait_for_event` | 2015.8.0 | Блокировка до события |
| Reactor SLS | 2015.8.0 | Событийная автоматизация |
| Master Schedule | 2016.3.0 | Планировщик на мастере |

**Важно:** `fail_function` работает только для `salt.function` в оркестрации, но не для `salt.state` или `salt.runner`. Для проверки результата применения состояний используйте `salt.function` с `cmd.run` и парсингом выхода, либо `watch` + `onchanges` на уровне состояний миньонов.

---

## Крайние случаи

### Большой orch SLS

При десятках состояний в одном SLS оркестрации увеличивается время компиляции и сложность отладки. Рекомендация: разбивайте оркестрацию на логические модули (`orch/deploy.sls`, `orch/verify.sls`) и используйте `include` через `runner.state.orchestrate` с несколькими аргументами или отдельные запуски.

### Циклы между SLS оркестрации

Если `orch/A.sls` вызывает `orch/B.sls` через `salt.runner`/`salt.state`, а `orch/B.sls` возвращает управление в `orch/A.sls`, возникает циклическая зависимость. Salt обнаруживает её на этапе компиляции и завершается с ошибкой `A recursive requisite was found`. Решение: выносите общую логику в третий SLS или используйте события через Reactor вместо прямых вызовов.

### Salt-SSH против Master в оркестрации

Salt-SSH не поддерживает классическую оркестрацию через `state.orchestrate` с межминьонными зависимостями. Доступен только `salt-call --local state.orchestrate`, который применяет состояния локально. Нет Reactor, Beacons, Schedule на миньоне, wheel-интерфейса. Для полноценной оркестрации требуется классический Minion.

### Masterless режим ограничения

В masterless-режиме (`salt-call --local`) недоступны:
- `salt.runner`, `salt.wheel`, `salt.parallel_runners`
- `salt.wait_for_event` (нет шины событий мастера)
- `expect_minions`, `allow_fail` (нет группы миньонов)
- Reactor и Beacons

Используйте masterless только для изолированных сценариев: golden images, air-gapped сегменты, edge-устройства.

### Сетевой разрыв во время оркестрации

При обрыве связи с миньоном Salt отмечает задание как `Failed`. Если используется `batch` или `allow_fail`, сбой одного миньона не останавливает весь прогон. Для критичных сценариев комбинируйте `failhard` с `retry` на уровне orchestration runner. Реакторные реакции, зависящие от событий миньона, могут быть потеряны при разрыве — используйте `salt.runner` с polling для подтверждения.

### Гонки при параллелизме

При параллельном выполнении `salt.function` на нескольких миньонахRace condition возможен, если состояния на разных миньонах изменяют общий ресурс (файл на NFS, запись в БД). Решение: использовать `watch`/`onchanges` на уровне состояний миньонов, или `salt.function` с `failhard` для раннего обнаружения конфликтов.

### failhard в оркестрации против per-state

Глобальный `failhard` в конфиге миньона останавливает весь прогон на миньоне. В оркестрации (`state.orchestrate`) доступен параметр `failhard` на уровне runner, который останавливает весь пайплайн оркестрации при сбое на любом миньоне. Не путайте их: `failhard` в SLS-состоянии действует локально, а `failhard` в `state.orchestrate` — глобально для всей инфраструктуры.

---

## Связанные темы:

- [Архитектура SaltStack (Event Bus)](Architecture.md)
- [Highstate и порядок выполнения](Highstate_and_Execution_Order.md)
- [Подходы к безопасности (eAuth и ACL)](Security_Approaches.md)
