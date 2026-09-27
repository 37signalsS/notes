# Управление выполнением и отладка ролей Ansible

## Определения

**Playbook keyword (ключевое слово уровня плея)** — директива, которая управляет поведением всего Play. Ansible разделяет ключевые слова по четырём уровням: Play, Role, Block, Task. Ключевое слово, допустимое на уровне Play, **не работает** на уровне Role — это principal источник ошибок при попытке задать `serial` или `max_fail_percentage` внутри роли.

**Пакет обработки (batch)** — группа хостов, обрабатываемая одновременно в рамках одного прохода. Размер пакета определяется `serial` (уровень Play) и ограничивается значением `forks` в `ansible.cfg`.

**Порог отказа (`max_fail_percentage`)** — процент хостов в текущем пакете, при превышении которого прерывается весь Play. Работает **только** со стратегиями на базе `linear` и **только** совместно с `serial`.

**Делегирование (`delegate_to`)** — выполнение задачи на хосте, отличном от целевого (`inventory_hostname`). Факты по умолчанию сохраняются для целевого хоста, а не для делегированного.

**Делегирование фактов (`delegate_facts`)** — параметр, переназначающий факты, собранные в делегированной задаче, на текущий (целевой) хост вместо делегированного.

**Однократное выполнение (`run_once`)** — параметр, который обходит цикл по хостам: задача выполняется на первом доступном хосте, а её результат применяется ко всем активным хостам текущего пакета.

**Ограничение конкурентности (`throttle`)** — лимит одновременных выполнений задачи, блока или Play. Независим от `forks` и `serial`, но не может превышать их.

**Task debugger (отладчик задач)** — интерактивный отладчик Ansible, который останавливает выполнение на задаче и позволяет изменить её аргументы, повторить и продолжить работу без перезапуска плейбука. Включается ключевым словом `debugger`, опцией `enable_task_debugger` в `ansible.cfg` или переменной окружения.

**Режим проверки (`check_mode`)** — выполнение задачи без внесения изменений, но с вычислением того, что изменилось бы. Иногда сопровождается `diff` — выводом различий.

**Пошаговое применение (`meta: flush_handlers`)** — задача, принудительно запускающая все уведомленные обработчики до продолжения работы, нарушая обычное правило «обработчики в конце секции».

---

## Предварительные требования

### Системные требования (Ansible 2.21.4)

*   **Control Node:** Требуется **Python 3.12+**.
*   **Target Nodes:** Требуется **Python 3.9+** (для Ansible 2.21.4 рекомендуется Python 3.12+).

### Инструменты

```bash
# Установка ansible-core
pip install ansible-core

# Проверка версии
ansible --version  # → ansible-core 2.21.4

# Список всех модулей, доступных в текущем окружении
ansible-doc -l 2>/dev/null | head -20
# → ansible.builtin.command    Convert the result of running a command on the remote host
# → ansible.builtin.copy      Copy files to a remote host
# → ansible.builtin.debug     Prints a debug message
# → ansible.builtin.setup     Gathers facts about remote hosts

# Подробная документация конкретного модуля с примерами
ansible-doc ansible.builtin.copy
# → COPY    Copy files to a remote host
# → - src: /source/file/on/control/machine
# →   dest: /path/of/file/on/remote/machine

# Генерация полного ansible.cfg с раскомментированными значениями по умолчанию
ansible-config init --disabled > /tmp/ansible-full.cfg
# → файл создан, содержит секции [defaults], [ssh_connection], [privilege_escalation]

# Посмотреть действующие значения конфигурации
ansible-config dump --only-changed
# → forks = 20
# → internal_poll_interval = 0.001
```

**Где смотреть, какие директивы доступны на уровне Role:** официальная таблица уровней ключевых слов — <https://docs.ansible.com/projects/ansible/devel/reference_appendices/playbooks_keywords.html>. Локально проверить конкретную директиву можно через валидацию плейбука — неизвестное на этом уровне ключевое слово даёт ошибку `The field <name> is not allowed` ещё на этапе `--syntax-check`.

### Необходимые знания

Понимание того, чем уровень Role отличается от уровня Play. Без этого невозможно осмысленно проектировать роль, которая безопасна в composition.

---

## Основные концепции / Архитектура / Принципы работы

### Три уровня управления и разделение ответственности

Ansible позволяет задавать поведение на уровнях **Play**, **Role**, **Block** и **Task**. Ключевое различие для проектирования роли: роль может управлять только тем, что попадает в её зону ответственности (свои задачи, обработчики, переменные), а всё, что определяет *темп и границы* работы всего прогона, остаётся в плейбуке.

Это не ограничение, а осознанное разделение: одна и та же роль должна одинаково корректно работать в dev-парке из 5 хостов и в production-парке из 5000, где на каждый хост выставляется свой `serial` и `max_fail_percentage`.

**Для SRE:** это разделение напрямую определяет blast radius роли. Если роль корректно обрабатывает откат на уровне задач и не зависит от `serial`, инженер может безопасно запускать её на любом размере пакета, зная что ошибка затронет не более одного хоста за раз. Для DevOps: та же роль работает в CI (один хост, `serial: 1`) и в production (rolling update) без изменений. Для Sysadmin: это означает, что патч-вторник и разовое исправление используют один и тот же код, протестированный в dev.

### Какие ключевые слова доступны на уровне роли

Полный перечень ключевых слов уровня Role (по официальной документации Ansible):

`any_errors_fatal`, `become`, `become_exe`, `become_flags`, `become_method`, `become_user`, `check_mode`, `collections`, `connection`, `debugger`, `delegate_facts`, `delegate_to`, `diff`, `environment`, `ignore_errors`, `ignore_unreachable`, `module_defaults`, `name`, `no_log`, `port`, `remote_user`, `run_once`, `tags`, `throttle`, `timeout`, `vars`, `when`

Практический вывод: **роль может** ограничивать конкурентность, делегировать задачи, делегировать факты, отключать `check_mode`, указывать `any_errors_fatal`, включать отладчик, скрывать секреты в логах.

### Какие ключевые слова недоступны на уровне роли

| Ключевое слово | Уровень | Почему это важно для роли |
| :--- | :--- | :--- |
| `serial` | Play | Роль не может задать размер пакета. Роль обязана быть безопасна при любом пакете |
| `max_fail_percentage` | Play | Порог отказа задаёт вызывающий плейбук. Роль не должна рассчитывать на него |
| `force_handlers` | Play | Роль не может форсировать обработчики; только вызывающий плейбук |
| `strategy` | Play | Выбор стратегии — прерогатива плейбука и `ansible.cfg` |
| `gather_facts`, `gather_subset`, `gather_timeout` | Play | Роль не управляет сбором фактов. Если нужны факты — документируйте это в README роли |
| `pre_tasks`, `post_tasks`, `tasks`, `handlers`, `hosts`, `roles` | Play | Структура плея неприменима к роли |
| `vars_files`, `vars_prompt`, `fact_path`, `order`, `port` (на уровне Play) | Play | Подключение внешних файлов переменных — решение плейбука |

> **Важно про `collections`:** задачи внутри роли **не наследуют** значение `collections` от Play. Если роль должна искать ресурсы в определённых коллекциях, укажите `collections` в `meta/main.yml` роли — иначе получите `module not found` при вызове из плейбука с нестандартным набором коллекций.

### Порядок выполнения роли внутри плея

Роль не выполняется отдельным «шагом» — её задачи встраиваются в общий список задач плея. Итоговый порядок:

```text
1. pre_tasks        — задачи плейбука до ролей
2. roles            — задачи всех ролей в порядке объявления
                     (зависимости из meta/main.yml выполняются раньше)
3. tasks            — задачи плейбука после ролей
4. post_tasks       — задачи плейбука в конце
5. handlers         — обработчики, уведомленные в секциях 1-4
```

Ключевые следствия для роли:

*   Задачи роли из `roles:` выполняются **до** `tasks:` плейбука. Если роли нужно что-то из `tasks:`, передавайте это через `include_role` в секции `tasks`.
*   `import_role` вставляет задачи роли **на этапе парсинга**, поэтому они попадают в общий список задач и выполняются в позиции вызова. `include_role` выполняется в момент достижения, поэтому внутри цикла или блока ведёт себя как отдельная задача.
*   **Обработчики роли не выполняются в середине роли.** Если роль развертывает конфигурацию и должна тут же перезапустить сервис, нужен `meta: flush_handlers` — см. [Сценарий 9](#сценарий-9-пошаговое-применение-через-flush_handlers).

### Порядок выполнения обработчиков (связанная проблема)

Обработчики запускаются в порядке **объявления**, а не в порядке `notify`. Это источник неочевидных проблем: если `restart nginx` объявлен раньше `reload systemd`, при одновременном уведомлении оба выполнятся в порядке объявления, а не в логическом.

Роль решает эту проблему двумя способами:

*   **Порядок объявления в `handlers/main.yml` роли** — единственный рычаг внутри роли. Выстраивайте обработчики в порядке зависимостей: сначала `daemon_reload`, затем `reload`, затем `restart`.
*   **`meta: flush_handlers`** — принудительный запуск уведомленных обработчиков в нужной точке.

`force_handlers` — ключевое слово уровня Play, недоступное роли. Если нужно гарантировать рестарт сервиса даже при падении соседней задачи, это решение принимает плейбук (`force_handlers: true`) или CLI (`--force-handlers`).

### Вычисление один раз для всего парка: `run_once` + `delegate_to` + `set_fact`

Роль почти всегда должна вычислить что-то один раз (версия из API, значение токена, ID сертификата) и раздать результат всем хостам, а не дёргать источник 5000 раз. Механизм:

1.  `delegate_to` — перенаправляет задачу на конкретный хост (обычно `localhost` или хост из группы `load_balancers`).
2.  `run_once: true` — выполняет задачу на первом доступном хосте **текущего пакета** и применяет результат ко всем хостам этого пакета.
3.  `register` — сохраняет результат в переменную.
4.  `set_fact` — кладёт значение в факт хоста, чтобы оно пережило границу задачи и было доступно всем последующим задачам роли. Важно: `set_fact` выполняется **на каждом хосте без `run_once`**, иначе факт появится только у одного хоста пакета.

Ограничения, которые нужно знать:

*   Без `run_once` задача выполнится на **каждом** хосте, а `delegate_to` лишь изменит адресата — то есть 5000 одинаковых запросов к API.
*   `run_once` без `delegate_to` выполнит задачу на первом хосте пакета — обычно это не то, что нужно, если источник данных находится на отдельной машине.
*   `run_once` в сочетании с `serial` выполняется **один раз на пакет**, а не один раз на весь Play. Это обычно именно то поведение, которое требуется, но при отсутствии `serial` результат вычисляется один раз для всех хостов сразу.

### `delegate_facts` — когда факты остаются не на том хосте

Распространённый сценарий: снять настройки с балансировщика и передать их веб-серверам. Факт, полученный на веб-сервере из `setup` с `delegate_to: lb01`, **не появится** в `hostvars['web01']` — по умолчанию он привяжется к `lb01`.

```yaml
# Неверно: факт сохранится у lb01, а не у текущего хоста
- name: Снять конфигурацию с балансировщика
  ansible.builtin.setup:
  delegate_to: lb01

# Верно: факт привязан к текущему хосту
- name: Снять конфигурацию с балансировщика
  ansible.builtin.setup:
  delegate_to: lb01
  delegate_facts: true
```

### `check_mode` и `diff` на уровне роли

Роль может объявить `check_mode: false` и `diff: true` на уровне своей секции — это отключает режим проверки для всех её задач, что нужно для read-only задач, которые должны выполняться даже в dry-run.

Практические ограничения режима проверки, которые ломают тестирование роли через `--check`:

*   Не все модули поддерживают `check_mode`. Модуль без поддержки либо завершится ошибкой, либо выполнится по-настоящему — поведение зависит от модуля.
*   `ansible.builtin.command` и `ansible.builtin.shell` объявлены как поддерживающие `check_mode`, но **не могут** определить, изменилось ли состояние. В режиме проверки они не выполняют команду и возвращают `skipped: true`. Чтобы задача на чтение реально отработала в dry-run (например, чтобы получить версию для `assert`), добавьте ей `check_mode: false`. Обратная сторона: `shell`, изменяющий состояние, с `check_mode: false` выполнится по-настоящему — поэтому такие задачи обязательно защищайте `when` и не используйте их для изменений.
*   Задачи с `register` в режиме проверки часто получают `skipped: true` вместо реальных данных, что приводит к каскадным ошибкам в Jinja2-шаблонах.
*   `until`/`retries` в режиме проверки выполняют полное число попыток, если условие зависит от изменённого состояния.

### `debugger` — отладка роли без перезапуска плейбука

Ключевое слово `debugger` доступно на уровнях Play, Role, Block и Task. Приоритет: **наиболее гранулярное определение выигрывает** (Task > Block > Role/Play).

| Значение | Поведение |
| :--- | :--- |
| `always` | Отладчик вызывается всегда, независимо от результата задачи |
| `on_failed` | Только при падении задачи |
| `on_unreachable` | Только при недоступности хоста |
| `on_skipped` | Только при пропуске задачи |
| `never` | Отладчик не вызывается |

Глобальное включение — двумя способами:

```ini
# ansible.cfg
[defaults]
enable_task_debugger = True
```

```bash
# Переменная окружения
ANSIBLE_ENABLE_TASK_DEBUGGER=True ansible-playbook -i hosts site.yml
```

Способ `ANSIBLE_STRATEGY=debug` — обратно совместимый механизм для версий до 2.5; Ansible указывает, что он может быть удалён.

Полезные команды в отладчике:

| Команда | Действие |
| :--- | :--- |
| `p task.args` | Показать аргументы задачи |
| `p result._result` | Показать сырой результат модуля |
| `p task_vars` | Показать все переменные задачи, включая переменные роли |
| `p task.get_name()` | Показать полное имя задачи с префиксом роли |
| `task.args['name'] = 'bash'` | Изменить аргумент |
| `task_vars['key'] = value` | Изменить переменную |
| `redo` | Повторить задачу с изменениями |
| `c` / `continue` | Продолжить выполнение |
| `q` / `quit` | Прервать выполнение плейбука |

### Отладка выполнения модуля на удалённом хосте

Когда недостаточно интерактивного отладчика — нужно понять, что именно Ansible отправил на удалённый узел и как это выполнялось:

```bash
# Сохранить временные файлы модуля на удалённом хосте (по умолчанию удаляются)
export ANSIBLE_KEEP_REMOTE_FILES=1

# Запустить с подробным логом: покажет путь к временному файлу модуля
ansible-playbook site.yml -vvvv --limit web01
# → TEMP REMOTE MODULE FILE: /home/deploy/.ansible/tmp/ansible-tmp-1461434734.35-...

# Подключиться к хосту и посмотреть содержимое
ssh deploy@web01
ls -la /home/deploy/.ansible/tmp/ansible-tmp-*
```

Для Windows-хостов `ANSIBLE_KEEP_REMOTE_FILES=1` сохраняет сгенерированные `.ps1`-скрипты во временном каталоге пользователя — по ним можно воспроизвести выполнение вручную.

> **Сброс:** временные файлы накапливаются в `~/.ansible/tmp` на управляемых хостах. Удаляйте их принудительно (`rm -rf ~/.ansible/tmp/*`) или отключайте `ANSIBLE_KEEP_REMOTE_FILES` в продакшене, иначе на хостах со слабым диском закончится место.

---

## Практические сценарии

### Сценарий 1: Роль, совместимая с rolling-деплой

Роль не может задать `serial` и `max_fail_percentage`. Единственный способ сделать её безопасной — проектировать так, чтобы она корректно отрабатывала при любом размере пакета и не зависела от порога отказа.

```yaml
# playbooks/site.yml — порог отказа задаёт вызывающий плейбук
- name: Rolling update веб-серверов
  hosts: webservers
  serial: "20%"
  max_fail_percentage: 10
  any_errors_fatal: false
  roles:
    - role: web_server
```

```yaml
# roles/web_server/tasks/main.yml — роль ничего не знает про serial,
# но подготовлена к пошаговой обработке
- name: Зафиксировать текущее состояние для отката
  ansible.builtin.stat:
    path: /etc/nginx/nginx.conf
  register: config_before

- name: Развернуть конфигурацию
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
  notify: restart nginx

- name: Проверить конфигурацию до перезапуска
  ansible.builtin.command:
    cmd: nginx -t
  register: nginx_syntax
  changed_when: false
  failed_when: nginx_syntax.rc != 0

- name: Откатить конфигурацию при ошибке валидации
  ansible.builtin.copy:
    content: "{{ config_before.stat.content | b64decode }}"
    dest: /etc/nginx/nginx.conf
  when: nginx_syntax.rc != 0
  notify: restart nginx
```

Ключевая идея: роль делает каждый шаг самодостаточным (валидация до рестарта, автооткат при провале), а плейбук управляет только темпом. Тогда один и тот же код корректен и при `serial: 1`, и при `serial: 50%`.

### Сценарий 2: Вычисление один раз для всего парка

```yaml
# roles/app_deploy/tasks/main.yml
- name: Получить список образов из реестра
  ansible.builtin.uri:
    url: "https://registry.internal/v2/app/tags/list"
    headers:
      Authorization: "Bearer {{ registry_token }}"
    return_content: true
  delegate_to: "{{ groups['registry'][0] }}"
  run_once: true
  register: registry_tags
  no_log: true

- name: Сохранить вычисленное значение в факт каждого хоста
  ansible.builtin.set_fact:
    app_available_versions: "{{ registry_tags.json.tags | sort }}"
  # Без run_once и без when: результат run_once доступен всем хостам пакета,
  # а set_fact должен создать факт у каждого из них
```

**Почему нельзя проще:** если убрать `run_once`, задача выполнится на каждом хосте и сделает 5000 одинаковых HTTP-запросов к реестру. Если заменить `delegate_to` на `localhost`, а inventory не содержит `localhost` — задача упадёт.

**Нюанс с `serial`:** `run_once` срабатывает **один раз на пакет**, а не на весь плейбук. При `serial: 5` и 5000 хостах это 1000 пакетов и, соответственно, 1000 запросов к реестру. Если реестр ограничивает частоту запросов, добавьте `throttle: 1` — это ограничит скорость, но не число запросов; радикальное решение — вынести вызов в отдельный play с `serial: 1` на одном хосте и передать результат через `set_fact` хостам.

### Сценарий 3: Передача конфигурации с балансировщика на веб-серверы

```yaml
# roles/frontend_sync/tasks/main.yml
- name: Считать состав upstream с балансировщика
  ansible.builtin.slurp:
    src: /etc/haproxy/haproxy.cfg
  delegate_to: "{{ groups['load_balancers'][0] }}"
  register: lb_config

- name: Применить конфигурацию на текущем хосте
  ansible.builtin.template:
    src: upstream.conf.j2
    dest: /etc/myapp/upstream.conf
  vars:
    upstreams: "{{ lb_config.content | b64decode | regex_findall('server ([\\w.-]+):([0-9]+)') }}"
  notify: reload app
```

Здесь `register` достаточно — `slurp` не собирает факты, поэтому `delegate_facts` не требуется. `delegate_facts` нужен именно для модуля `ansible.builtin.setup` и других, создающих факты.

### Сценарий 4: Читаемый вывод цикла на большом парке

Без `loop_control` на 500 хостах вывод роли превращается в 500 одинаковых строк, из которых невозможно понять, где сбой.

```yaml
# Плохо: 500 безымянных строк
- name: Настроить пользователей
  ansible.builtin.user:
    name: "{{ item }}"
    groups: deploy
  loop: "{{ deploy_users }}"

# Хорошо: каждая итерация идентифицируется
- name: Настроить пользователей
  ansible.builtin.user:
    name: "{{ item.name }}"
    groups: "{{ item.groups }}"
    state: present
  loop: "{{ deploy_users }}"
  loop_control:
    label: "{{ item.name }} (uid={{ item.uid | default('auto') }})"
    loop_var: current_user
  vars:
    deploy_users:
      - { name: deploy1, uid: 1001, groups: [deploy, docker] }
      - { name: deploy2, uid: 1002, groups: [deploy] }
```

`loop_var` обязателен, когда в теле цикла используется вложенный `include_tasks` с собственным циклом: без переименования переменной внутренний цикл перезапишет `item` внешнего.

### Сценарий 5: Роль, безопасная для `--check --diff`

```yaml
# roles/nginx/tasks/main.yml
- name: Собрать версию nginx (read-only, работает в check mode)
  ansible.builtin.command:
    cmd: nginx -v
  register: nginx_version_raw
  changed_when: false
  check_mode: false   # без этого задача будет пропущена в dry-run

- name: Вывести версию
  ansible.builtin.debug:
    msg: "nginx {{ nginx_version_raw.stderr.split()[-1] }}"
  check_mode: false

- name: Развернуть конфигурацию
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
  notify: reload nginx
  diff: true          # показывать diff при --diff
```

```bash
# Проверка роли без применения изменений
ansible-playbook site.yml --check --diff --limit web01
# → changed: [web01] (item=...)
# → --- before
# → +++ after
# → @@ -1,3 +1,3 @@
```

Задача-валидатор (`nginx -t`, `curl /health`) обязана иметь `changed_when: false` и `check_mode: false` — иначе в dry-run она будет пропущена, и шаблоны, зависящие от её `register`, получат неопределённую переменную.

### Сценарий 6: Отладка роли интерактивно

```yaml
# Включить отладчик для всей роли — удобно при разработке
- name: Отладка роли
  ansible.builtin.include_role:
    name: app_deploy
  debugger: on_failed
  vars:
    debugger_enabled: true
```

```yaml
# roles/app_deploy/tasks/main.yml
- name: Проверить конфигурацию
  ansible.builtin.command:
    cmd: /opt/app/bin/app --check-config
  register: app_check
  changed_when: false
  debugger: on_failed   # отладчик сработает только на этой задаче
  failed_when: app_check.rc != 0
```

При срабатывании отладчика:

```text
fatal: [web01]: FAILED! => {"changed": false, "cmd": "/opt/app/bin/app --check-config", "rc": 2}
Debugger invoked
[web01] TASK: app_deploy : Проверить конфигурацию (debug)>
(debug)> p result._result
{'changed': False, 'cmd': '/opt/app/bin/app --check-config', 'rc': 2, 'stderr': 'missing APP_DB_HOST'}
(debug)> p task_vars['app_db_host']
'10.0.0.5'
(debug)> redo
(debug)> c
```

Отладчик показывает переменные роли вместе с переменными задачи, что позволяет проверить, правильно ли `defaults/main.yml` и `argument_specs.yml` связаны с фактическими значениями.

### Сценарий 7: Ожидание готовности сервиса внутри роли

```yaml
# roles/web_server/tasks/main.yml
- name: Дождаться готовности порта
  ansible.builtin.wait_for:
    port: 80
    host: 127.0.0.1
    state: started
    timeout: 30

- name: Дождаться успешного ответа health-эндпоинта
  ansible.builtin.uri:
    url: "http://127.0.0.1/health"
    status_code: 200
    return_content: true
  register: health
  until: health.status == 200
  retries: 12        # 12 попыток
  delay: 5           # с интервалом 5 секунд = до 60 секунд ожидания
  changed_when: false
```

`delay` используется только вместе с `until`. Максимальное время ожидания равно `retries × delay`. Проверка `health` в конце роли — обязательный элемент: без неё роль сообщит об успехе, даже если сервис не поднялся, а обработчик молча не сработает.

### Сценарий 8: Локальная изоляция критичных шагов

`any_errors_fatal` доступен на уровне роли. Для шага, падение которого означает потерю кворума или неконсистентный кластер, его следует выделить в отдельную роль с `any_errors_fatal: true` — это заставит Play остановиться на всех хостах, а не продолжать работу.

```yaml
# roles/cluster_critical/tasks/main.yml
- name: Критичные операции с кластером
  any_errors_fatal: true
  block:
    - name: Вывести узел из кластера
      ansible.builtin.command:
        cmd: /usr/sbin/node_etcd leave
      register: etcd_leave
      changed_when: "'left' in etcd_leave.stdout"

    - name: Обновить конфигурацию кластера
      ansible.builtin.template:
        src: etcd.conf.j2
        dest: /etc/etcd/etcd.conf
      notify: restart etcd

  rescue:
    - name: Вернуть узел в кластер
      ansible.builtin.command:
        cmd: /usr/sbin/node_etcd join
      changed_when: true

  always:
    - name: Дождаться восстановления кластера
      ansible.builtin.uri:
        url: "http://127.0.0.1:2379/health"
        status_code: 200
      register: etcd_health
      until: etcd_health.status == 200
      retries: 6
      delay: 10
      changed_when: false
```

Разделение на «критичную» роль с `any_errors_fatal: true` и обычные роли для массовых операций — стандартный приём для ролей, обновляющих состояние кластера.

### Сценарий 9: Пошаговое применение через `flush_handlers`

Обработчики по умолчанию выполняются в конце секции. Если роль должна применить промежуточный рестарт и только потом продолжить, нужен `meta: flush_handlers`.

```yaml
# roles/app_deploy/tasks/main.yml
- name: Установить новую версию
  ansible.builtin.unarchive:
    src: app-{{ app_version }}.tar.gz
    dest: /opt/app
  notify: restart app

- name: Применить рестарт до миграции схемы
  ansible.builtin.meta: flush_handlers
  # → now the handler "restart app" has been executed

- name: Выполнить миграцию базы данных
  ansible.builtin.command:
    cmd: /opt/app/bin/migrate
  environment:
    DATABASE_URL: "{{ vault_database_url }}"
  changed_when: true
  no_log: true
```

**Ограничение:** `flush_handlers` вызывает *все* уведомленные на данный момент обработчики, а не только указанный. Если к этому моменту уведомлены обработчики нескольких ролей, они все выполнятся. Это нужно учитывать при компоновке ролей.

### Сценарий 10: `end_role` и `end_play` — корректное досрочное завершение

```yaml
# roles/validator/tasks/main.yml
- name: Проверить, что роль применима к хосту
  ansible.builtin.assert:
    that:
      - ansible_facts['os_family'] in supported_os_families
    fail_msg: "Роль не поддерживает {{ ansible_facts['distribution'] }}"

- name: Досрочно завершить роль, если сервис не требуется
  ansible.builtin.meta: end_role
  when: not service_required
  # → роль завершается для этого хоста, остальные роли продолжают выполняться

- name: Остальная логика роли
  ansible.builtin.debug:
    msg: "Роль применима к {{ inventory_hostname }}"
```

`meta: end_role` прерывает выполнение текущей роли на конкретном хосте; последующие роли и `post_tasks` выполняются. `meta: end_play` прерывает весь Play на этом хосте. Разница критична: `end_play` внутри роли остановит и остальные роли, что трудно заметить при чтении кода.

### Сценарий 11: Игнорирование недоступных хостов в роли

`ignore_unreachable` не затрагивает обычные ошибки задач (в отличие от `ignore_errors`) — это делает его безопасным для парков с эфемерными узлами.

```yaml
# roles/service_mesh_agent/tasks/main.yml
- name: Установить агента
  any_errors_fatal: false
  ignore_unreachable: true
  block:
    - name: Скачать пакет агента
      ansible.builtin.get_url:
        url: "{{ agent_url }}"
        dest: /tmp/agent.deb
      register: agent_download

    - name: Установить пакет агента
      ansible.builtin.apt:
        deb: /tmp/agent.deb
        state: present
      when: agent_download is succeeded

- name: Очистить временный файл
  ansible.builtin.file:
    path: /tmp/agent.deb
    state: absent
  ignore_unreachable: true
```

### Сценарий 12: Отсутствие изменений при повторном запуске (идемпотентность роли)

Задача, которая всегда сообщает `changed`, ломает обработчики: рестарт будет выполняться при каждом запуске. Проверка на идемпотентность обязательна для любой продакшен-роли.

```yaml
# roles/app_deploy/tasks/main.yml
- name: Записать строку в файл, только если её нет
  ansible.builtin.lineinfile:
    path: /etc/app/config.yml
    line: "listen_port: {{ app_port }}"
    regexp: '^listen_port:'
    state: present
  register: config_edit
  changed_when: "'listen_port' in config_edit.changed"

- name: Выполнить команду, не меняющую состояние
  ansible.builtin.command:
    cmd: /usr/bin/systemctl is-active app
  register: service_state
  changed_when: false   # команда только читает состояние

- name: Проверка результата без внесения изменений
  ansible.builtin.assert:
    that:
      - service_state.rc == 0
    fail_msg: "Сервис app не запущен"
  changed_when: false
```

```bash
# Контрольный прогон: должен быть changed=0
ansible-playbook site.yml --limit web01
# → PLAY RECAP: web01 : ok=12 changed=0 unreachable=0 failed=0
```

`changed=0` при повторном запуске — критерий готовности роли к продакшену. Теория идемпотентности разобрана в [Идемпотентность](../../Concepts/idempotency.md).

---

## Операции и команды

### Диагностика порядка выполнения

```bash
# Полный список задач в порядке выполнения (без запуска)
ansible-playbook site.yml --list-tasks
# → play #1 (web_server) (web-01)
# →   TASK [web_server : Собрать версию nginx] ***

# Только задачи с указанным тегом
ansible-playbook site.yml --list-tasks --tags deploy
```

```bash
# Показать, что реально попадёт в выполнение, с тегами и условиями
ansible-playbook site.yml --list-hosts
# → hosts (2):
# →   web-01
# →   web-02
```

### Проверка без применения

```bash
# Полный dry-run с различиями
ansible-playbook site.yml --check --diff
# → TASK [web_server : Развернуть конфигурацию] *** ok=1 changed=1
# → --- before
# → +++ after
# → @@ -3,1 +3,1 @@
# → -listen 80;
# → +listen 8080;

# Dry-run с подробным выводом (чтобы понять, почему задача пропущена)
ansible-playbook site.yml --check -vv
# → TASK [web_server : Установить пакет] *** skipping: [web-01] => (item == 'nginx') is false
```

### Отладка

```bash
# Подробный вывод: имена задач, значения переменных, результаты
ansible-playbook site.yml -vvv

# Максимальный вывод: показывает пути к временным файлам модулей на хостах
ansible-playbook site.yml -vvvv

# Только уведомлённые обработчики (список, без выполнения)
ansible-playbook site.yml --list-handlers
```

```bash
# Интерактивный отладчик на упавшей задаче
ANSIBLE_ENABLE_TASK_DEBUGGER=True ansible-playbook site.yml --limit web01
# → fatal: [web01]: FAILED! => {"msg": "..."}
# → Debugger invoked
# → [web01] TASK: app_deploy : Проверить конфигурацию (debug)>

# Отладчик только на указанной роли
ansible-playbook site.yml -e "debugger_enabled=true"
```

```bash
# Сохранить временные файлы модулей на удалённых хостах
ANSIBLE_KEEP_REMOTE_FILES=1 ansible-playbook site.yml -vvvv
# → TEMP REMOTE MODULE FILE: /home/deploy/.ansible/tmp/ansible-tmp-...
```

### Переменные и факты

```bash
# Все переменные, доступные внутри роли
ansible-playbook site.yml --list-variables | grep web_server
# → web_server_port             | 80      | показать эту переменную
# → web_server_workers          | 4       | показать эту переменную

# Значение одной переменной
ansible-playbook site.yml -e "debug=true" -l web01
```

```bash
# Проверить, что задано в meta/argument_specs.yml
# Валидация типов происходит при разборе роли, поэтому её видит только плейбук
ansible-playbook site.yml --syntax-check
# → playbook: site.yml
# → Нет ошибок разбора → спецификация роли принята

# Убедиться, что обязательные аргументы переданы, до применения изменений
ansible-playbook site.yml --check --diff -l web01
# → если обязательный аргумент не передан — ошибка валидации ДО выполнения задач
```

### Пакетное выполнение и параллелизм

`serial` и `max_fail_percentage` — ключевые слова уровня Play, из CLI они не задаются. Управление ими — только в плейбуке или через переменную `ansible_play_batch_size` при `serial: 1`.

```yaml
# playbooks/site.yml — единственное место, где задаётся темп выполнения
- name: Rolling update
  hosts: webservers
  serial: 5
  max_fail_percentage: 20
  roles:
    - role: web_server
```

```bash
# Общий параллелизм — единственный параметр пакетной обработки из CLI
ansible-playbook site.yml --forks 20
# → скорость выполнения роли выросла вдвое (было 5 хостов одновременно)

# Посмотреть, какие значения конфигурации переопределены
ansible-config dump --only-changed
# → DEFAULT_FORKS (env: ANSIBLE_FORKS) set for config: default (20)
# → DEFAULT_KEEP_REMOTE_FILES (env: ANSIBLE_KEEP_REMOTE_FILES) set for config: default (False)
```

**Что чем управляется:**

| Параметр | Уровень | Как задать |
| :--- | :--- | :--- |
| `serial` | Play | Только в плейбуке (`serial: 5`, `serial: 10%`, `serial: 1`) |
| `max_fail_percentage` | Play | Только в плейбуке |
| `forks` | CLI/config | `--forks 20` или `ANSIBLE_FORKS=20` |
| `throttle` | Play / Role / Block / Task | Только в YAML |
| `strategy` | Play | Только в плейбуке (`strategy: free`) |

---

## Устранение неполадок

### Ошибка: "The field serial is not allowed" при попытке задать в роли

**Причина:** `serial` — ключевое слово уровня Play. Роль не может им управлять.

**Решение:** перенести `serial` в плейбук, а роль проектировать так, чтобы она была безопасна при любом размере пакета:

```yaml
# playbooks/site.yml
- hosts: webservers
  serial: "25%"
  max_fail_percentage: 10
  roles:
    - role: web_server
```

### Ошибка: max_fail_percentage не останавливает выполнение

**Причина:** `max_fail_percentage` работает только совместно с `serial` и только со стратегиями на базе `linear`. При `strategy: free` порог игнорируется.

**Решение:** задать `serial` и использовать линейную стратегию; для `free` контроль предела задавать через `any_errors_fatal` на уровне роли или блока.

### Ошибка: обработчик не выполняется после изменения конфигурации

**Причины и решения:**

```bash
# 1. Задача не сообщила об изменении — проверьте через register
ansible-playbook site.yml --list-handlers
```

| Причина | Проверка | Решение |
| :--- | :--- | :--- |
| Задача вернула `changed: false` | Добавить `debug: var=result` | Добавить `changed_when` по фактическому признаку изменения |
| Обработчик объявлен после `import_role` | `--list-tasks` | `import_role` разворачивает задачи на парсинге, но обработчики роли встают в очередь; проверьте, что имя в `notify` совпадает с `name` |
| `notify` указывает несуществующее имя | `grep -r "notify:" roles/` | Сверить `notify` с `- name:` в `handlers/main.yml` |
| Роль завершилась раньше секции | Лог выполнения | Обработчики выполняются в конце секции; если нужен немедленный запуск — `meta: flush_handlers` |
| Задача в `rescue` | Лог выполнения | `notify` в `rescue` не вызывает обработчик, если handler не был уведомлён до ошибки |
| Совпадение имён обработчиков в двух ролях | `grep -rn "^- name: restart" roles/` | Используйте уникальные имена или `listen` |

### Ошибка: конфигурация применена, но сервис не перезапущен из-за падения соседней задачи

**Причина:** по умолчанию обработчики не выполняются для хоста, у которого упала задача. `force_handlers` — ключевое слово уровня Play, недоступное роли.

**Решение (выбирает вызывающий плейбук):**

```yaml
# playbooks/site.yml
- hosts: webservers
  force_handlers: true
  roles:
    - role: web_server
```

```bash
# Или через CLI
ansible-playbook site.yml --force-handlers
```

**Решение на стороне роли** — сделать рестарт немедленным, чтобы падение соседней задачи не помешало:

```yaml
- name: Развернуть конфигурацию
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf

- name: Перезапустить сервис немедленно, не дожидаясь конца секции
  ansible.builtin.meta: flush_handlers
```

### Ошибка: факт не виден на целевом хосте после delegate_to

**Причина:** факты, собранные в делегированной задаче, привязываются к делегированному хосту.

**Решение:** добавить `delegate_facts: true` к задаче с модулем `ansible.builtin.setup`:

```yaml
- name: Считать настройки балансировщика
  ansible.builtin.setup:
  delegate_to: lb01
  delegate_facts: true
  # → факт доступен как ansible_facts[...] и в hostvars[текущий хост]
```

### Ошибка: цикл из 500 элементов даёт нечитаемый вывод

**Решение:** добавить `loop_control` с `label` (и `loop_var`, если внутри есть вложенный цикл). Подробнее — [Сценарий 4](#сценарий-4-читаемый-вывод-цикла-на-большом-парке).

### Ошибка: "The task includes an option with an undefined variable" в dry-run

**Причина:** задача-валидатор с `register` была пропущена в режиме проверки, и последующий шаблон получил неопределённую переменную.

**Решение:** добавить `check_mode: false` к read-only задачам, от которых зависит логика, либо обработать случай `skipped`:

```yaml
- name: Проверить состояние сервиса
  ansible.builtin.command:
    cmd: systemctl is-active app
  register: svc
  changed_when: false
  check_mode: false
```

```yaml
- name: Использовать результат с учётом пропуска
  ansible.builtin.debug:
    msg: "Сервис: {{ svc.stdout | default('не проверялся в check mode') }}"
```

### Ошибка: роль работает в тестах, но падает в CI

**Типичные причины:**

| Причина | Диагностика | Решение |
| :--- | :--- | :--- |
| `run_once` без `delegate_to` попадает на хост, которого нет в тестовом инвентаре | Лог CI: задача выполнена не на ожидаемом хосте | Добавить `delegate_to: localhost` |
| Путь к секрету (`lookup('file', '~vault_pass')`) различается локально и в CI | `ANSIBLE_DEBUG=1` | Передавать путь через переменную окружения |
| Роль полагается на факт, отсутствующий в тестовом окружении | Добавить `assert` на наличие факта | Задать факт в `group_vars` тестового инвентаря |
| Зависимость от `forks`/`throttle` из локального `ansible.cfg` | `ansible-config dump --only-changed` | Зафиксировать конфигурацию в репозитории и указать `ANSIBLE_CONFIG` в CI |

### Ошибка: "Unsupported parameters" при попытке задать `serial` в роли или блоке

**Причина:** попытка применить ключевое слово уровня Play к объекту более низкого уровня.

**Решение:** использовать `throttle` (допустим на уровне Role) для ограничения конкурентности либо `serial` в плейбуке для пакетной обработки. Это разные механизмы: `throttle` ограничивает одновременные выполнения внутри пакета, `serial` — размер пакета.

### Отладка не срабатывает

| Причина | Решение |
| :--- | :--- |
| Отладчик не включён ни в одном уровне | Задать `debugger: on_failed` на роли, блоке или задаче, либо `enable_task_debugger = True` в `ansible.cfg` |
| `debugger: never` на более гранулярном уровне перекрыл `on_failed` | Проверить все уровни: побеждает наиболее гранулярное определение |
| Задача пропущена (`skipped`), а стоит `on_failed` | Заменить на `on_skipped` или `always` |
| Используется `ANSIBLE_STRATEGY=debug` | Устаревший способ; перейти на `enable_task_debugger` или ключевое слово `debugger` |

---

## Лучшие практики

1.  **Разделяйте ответственность:** темп и границы прогона (`serial`, `max_fail_percentage`, `force_handlers`, `strategy`) — зона плейбука. Внутренняя корректность, конкурентность, делегирование и режим проверки — зона роли.
2.  **Делайте роль безопасной при любом пакете:** проверяйте конфигурацию до рестарта, откатывайте при провале, завершайте задачи ожиданием готовности. Тогда `serial: 1` и `serial: 50%` используют один и тот же код.
3.  **Вычисляйте один раз:** `delegate_to` + `run_once` + `register` + `set_fact` вместо тысяч одинаковых вызовов внешнего API. Помните: с `serial` это будет один вызов на пакет.
4.  **Добавляйте `loop_control` в любой цикл, который виден пользователю.** `label` превращает нечитаемый вывод в диагностический инструмент.
5.  **Помечайте все read-only задачи `changed_when: false` и `check_mode: false`** — иначе роль нельзя проверить через `--check` и она бездумно рестартует сервисы.
6.  **Проверяйте `changed=0` на повторном запуске.** Это минимальный критерий готовности роли к продакшену.
7.  **Включайте `debugger` в роль при разработке и убирайте перед коммитом** — `debugger: on_failed` на уровне роли экономит часы на цикле разработки.
8.  **Используйте `meta: flush_handlers` осознанно** — помните, что он запускает *все* уведомленные обработчики, а не только нужный.
9.  **Выносите критичные операции в отдельную роль с `any_errors_fatal: true`**, чтобы потеря кворума останавливала весь прогон.
10. **Сбрасывайте `ANSIBLE_KEEP_REMOTE_FILES` в продакшене** — иначе временные файлы модулей накапливаются на управляемых хостах.
11. **Документируйте в README роли факты, которые она использует**, и то, что она ожидает от вызывающего плейбука (например, наличие определённой группы инвентаря для `delegate_to`).
12. **Проверяйте роль в двух режимах:** обычный запуск (корректность изменений) и `--check --diff` (безопасность dry-run). Роль, работающая только в одном из них, не готова к продакшену.

---

## Граничные случаи

### Роль вызывается из `roles:` и не может получить `tasks:`-переменные

Роль, объявленная в директиве `roles:`, выполняется до `tasks:` плейбука. Если ей нужны значения, вычисленные в `tasks:`, передавайте их явно через `vars:` при вызове — либо переносите вызов в секцию `tasks:` через `include_role`.

### `import_role` внутри цикла вызывает ошибку парсинга

`import_role` разворачивается на этапе парсинга и не поддерживает циклы. Для вызова роли в цикле используйте `include_role`, понимая, что он выполняется в момент достижения и не подходит для задач, которым нужна статическая позиция в списке.

### `run_once` внутри цикла или `block`

`run_once` действует на весь цикл по хостам в пределах текущего пакета. Внутри `block` без `rescue` падение на хосте прерывает и `run_once`-задачу, и остальные задачи блока. Для гарантированного выполнения оберните `run_once`-задачу в `block`/`always`.

### `delegate_to` на хост, отсутствующий в инвентаре

Если `delegate_to` указывает на имя, которого нет в инвентаре, Ansible подставляет inventory-переменные целевого хоста и часто падает с `UNREACHABLE`. Проверяйте наличие группы в инвентаре и используйте `delegate_to: localhost` с `connection: local` для гарантированно существующей цели.

### Обработчик в `always` не выполняется

Обработчики, уведомлённые в секции `always`, попадают в очередь и выполняются в конце секции — но если после этого хост завершился с ошибкой, очередь может быть не обработана. Критичные рестарты выполняйте явно через `meta: flush_handlers`, а не полагайтесь на очередь.

### `throttle` внутри роли не решает задачу, если `forks` меньше

`throttle` не может превышать `forks` и `serial`. Если `throttle: 10` при `forks: 5`, фактически одновременно выполнятся 5 задач. Проверяйте итоговую конфигурацию через `ansible-config dump --only-changed`.

### Роль меняет поведение при `--check`

Некоторые задачи в dry-run пропускаются, и это меняет логику роли. Всегда проверяйте, что путь исполнения в `--check` не приводит к каскадным ошибкам в шаблонах, и защищайте такие места через `default()` либо `check_mode: false` на источнике данных.

### Роль вызывается несколько раз в одном плее

Если одна и та же роль включена дважды (через зависимость в `meta/main.yml` и явно в плейбуке), задачи выполняются дважды, а обработчики дублируются. Управляйте этим через `allow_duplicates` в `meta/main.yml` вызывающей роли.

---

## Дополнительная информация

Теоретические основы без привязки к ролям разобраны в профильных файлах:

*   **[Управление ходом выполнения](../PlaybookStructure/flow_control.md)** — `serial`, `max_fail_percentage`, `any_errors_fatal`, `throttle`, `loop_control`, `changed_when`/`failed_when`, `until`, `block`/`rescue`/`always`, `check_mode`.
*   **[Переменные и факты](../PlaybookStructure/variables.md)** — `set_fact`, `register`, `cacheable`, `delegate_facts`, `hostvars`, `include_vars`, `no_log`.
*   **[Основы структуры плейбуков](../PlaybookStructure/basics.md)** — порядок выполнения секций, `pre_tasks`/`post_tasks`, поведение обработчиков.
*   **[Продвинутые возможности плейбуков](../PlaybookStructure/advanced.md)** — `force_handlers`, `ignore_unreachable`, `debugger`, тонкости обработчиков.
*   **[Отладка и диагностика](../examples/debugging_examples.md)** — методы поиска причин сбоев, `--check --diff`, `ANSIBLE_KEEP_REMOTE_FILES`.
*   **[Антипаттерны Ansible](../ansible_bad_practices.md)** — ошибки проектирования, в том числе неверная обработка ошибок в блоках.
*   **[Оптимизация производительности](../ansible_performance_tuning.md)** — `forks`, `pipelining`, стратегии выполнения, кеширование фактов.
*   **[Дрейф конфигурации](../examples/ansible_configuration_drift.md)** — обнаружение расхождений между ролью и реальным состоянием хоста.
*   **[Создание и использование ролей](usage.md)** — способы подключения роли, `import_role` vs `include_role`, `public`, `apply`.
*   **[Структура роли](structure.md)** — каталоги, метаданные, спецификация аргументов.
*   **[Тестирование ролей через ansible-test](../ansible-test.md)** — санити-тесты коллекций и модулей.
