# Оркестрация и методы автоматизации в SaltStack

## Определения

- **Оркестрация (Orchestration)**: Процесс координации задач на множестве узлов с учётом их взаимозависимостей. Выполняется на Salt Master через runner `state.orchestrate`, который обобщает систему состояний до уровня всей инфраструктуры: в отличие от [Highstate](Highstate_and_Execution_Order.md), оркестрация управляет порядком применения состояний между разными миньонами и может остановить весь прогон при сбое на одном из узлов. Система пришла на смену механизму OverState (заменена в Salt 2015.8.0).
- **Runner**: Модуль, исполняемый на Salt Master. Раннеры обеспечивают логику управления инфраструктурой (например, `state.orchestrate`, `cloud.profile`, `jobs.lookup_jid`).
- **Beacon (Маяк)**: Лёгкий процесс на Minion, который периодически отслеживает системные события (изменения файлов, нагрузку, статус сервисов, дисковое пространство) и отправляет уведомления на шину событий с тегом `salt/beacon/<minion>/<beacon>`.
- **Reactor (Реактор)**: Компонент на Master, который слушает шину событий и в ответ на совпадение тега запускает действия: применение состояний на миньонах (`local.*`), выполнение раннеров (`runner.*`) или wheel-функций (`wheel.*`) на мастере.
- **Событие (Event)**: Сообщение на шине событий, состоящее из тега (tag) и структуры данных (data). Тег используется для быстрой фильтрации, данные содержат информацию о событии.
- **Salt-Cloud**: Инструмент для автоматизированного создания и уничтожения виртуальных машин в облаках (AWS, Azure, GCP, vSphere, OpenStack) и их последующей привязки к мастеру.
- **Salt-API**: REST-интерфейс (модули `netapi` — `rest_cherrypy`, `rest_tornado`) для интеграции Salt с внешними системами: CI/CD, порталы самообслуживания, вебхуки. Обычно используется с внешней аутентификацией eAuth.
- **eAuth (External Authentication)**: Система делегирования аутентификации внешним провайдерам (LDAP, Active Directory, PAM, OAuth2/JWT) для доступа к Salt-API или CLI с выдачей короткоживущих токенов ([подробнее](Security_Approaches.md)).

---

## Основные концепции

### Модели автоматизации

| Модель | Назначение | Инструмент |
| :--- | :--- | :--- |
| **Push** | Мгновенное управление «сверху вниз» | `salt`, `state.apply` |
| **Pull** | Автоматическая коррекция дрейфа конфигурации | `schedule` на миньонах |
| **Event-Driven** | Реактивная инфраструктура (Self-healing) | `Beacons` + `Reactor` |
| **Orchestration** | Сложные многошаговые пайплайны | `state.orchestrate` |

### Механизмы оркестрации (`state.orchestrate`)

Оркестрация выполняется через Runner `state.orchestrate` и использует SLS-файлы на мастере (каталоги `file_roots`). Для SLS оркестрации и реакций рекомендуется выделять отдельные подкаталоги (`orch/`, `react/` и т.п.), чтобы избежать конфликтов имён с состояниями миньонов.

Запуск оркестрации выполняется на мастере:

```bash
salt-run state.orchestrate orch.web_update            # применить SLS orch/web_update.sls
salt-run state.orch orch.web_update                   # синоним state.orchestrate
salt-run state.orchestrate orch.web_update test=True  # пробный прогон (dry run)
salt-run state.orchestrate orch.web_update pillarenv=prod  # Pillar-окружение
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
- **Реквизиты**: для `salt.*`-состояний работают все реквизиты (включая `require`, `watch`), ссылки на другие блоки — через `- salt: <id>`. Именно они обеспечивают межминьонные зависимости.
- **Управление потоком**: `batch` (выполнение по частям), `subset` (случайное подмножество), `failhard` (остановка при первой ошибке).
- **Контроль выполнения**: `expect_minions` (ошибка, если часть миньонов не ответила), `allow_fail` (допустимое число неудачных миньонов), `fail_function` для `salt.function` (проверка результата на мастере).
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

### Событийная модель: Beacon → Event Bus → Reactor

Ключевое преимущество Salt перед push-only инструментами — реактивная автоматизация. Поток данных строится по цепочке:

1. **Beacon** на миньоне обнаруживает событие (изменение файла, рост нагрузки, падение сервиса).
2. Событие с тегом `salt/beacon/<minion>/<beacon>` попадает на шину событий мастера.
3. **Reactor** на мастере сопоставляет тег с SLS-файлом реакций и выполняет действия (применение состояний, запуск оркестрации, создание ВМ через Salt-Cloud).

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
        - profile: aws_web_node
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

### 4. Ожидание перезагрузки парка (`salt.wait_for_event`)

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

### 5. Периодическая оркестрация (Schedule на мастере)

Оркестрацию можно запускать по расписанию на самом мастере — например, еженочный rollout обновлений или периодическую сверку конфигураций:

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

### Отладка событийной автоматизации

```bash
salt-run state.event pretty=True          # наблюдение за событиями шины в реальном времени
salt-run jobs.lookup_jid <jid>            # результаты задания по JID
salt '*' beacons.list                     # текущие beacon'ы на миньоне
salt-call event.send myco/test/event data='{"status": "ok"}'  # эмуляция пользовательского события
```

**Связанные темы:**
- [Архитектура SaltStack (Event Bus)](Architecture.md)
- [Highstate и порядок выполнения](Highstate_and_Execution_Order.md)
- [Подходы к безопасности (eAuth и ACL)](Security_Approaches.md)
