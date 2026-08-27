# Ansible: Выполнение Playbook

## Определения

- **ansible-playbook** — утилита командной строки для запуска и выполнения Playbook Ansible на управляемых узлах (Managed Nodes). Принимает YAML-файл плейбука и опциональный Inventory.
- **Play (Плей / Сценарий)** — логически сгруппированный набор задач (Tasks), применяемый к определенной группе хостов из Inventory. Каждый Playbook может содержать один или несколько Play'ов.
- **Task (Задача)** — атомарная операция в Playbook, вызывающая конкретный Ansible Module для достижения желаемого состояния системы.
- **Idempotency (Идемпотентность)** — свойство Ansible, гарантирующее, что повторный запуск Playbook не изменит систему, если она уже находится в целевом состоянии. Ключевой принцип Infrastructure as Code.
- **PLAY RECAP** — итоговая сводка выполнения Playbook, отображающая статистику по каждому хосту (`ok`, `changed`, `unreachable`, `failed`, `skipped`, `rescued`, `ignored`).
- **Check Mode (Dry Run)** — режим проверки без фактического внесения изменений. Модули сообщают, что *было бы* изменено, но систему не трогают. Аналог `--dry-run` в других инструментах.
- **Verbosity (Детализация вывода)** — уровень подробности логов ansible-playbook (от `-v` до `-vvvv`). Уровень `-vvvv` показывает SSH-соединения и переменные окружения.
- **Fact Caching** — механизм сохранения Facts между запусками плейбуков (в файле, Redis, MongoDB). Позволяет ускорять повторные запуски и использовать Facts из предыдущих выполнений.
- **Callback Plugin** — плагин, определяющий формат вывода в консоли и позволяющий перехватывать события для логирования или уведомлений. Современный стандарт — плагин `yaml`.
- **Execution Environment (EE)** — изолированный контейнерный образ с Ansible, коллекциями и зависимостями. Обеспечивает воспроизводимость и идентичность среды выполнения.
- **Extra-vars** — переменные, передаваемые через командную строку (`-e`). Имеют наивысший приоритет среди всех источников переменных Ansible.
- **Tags (Теги)** — метки, накладываемые на задачи для фильтрации выполнения. Позволяют запускать только определённые группы задач.
- **Strategy** — алгоритм управления порядком выполнения задач на хостах. Основные: `linear` (синхронный), `free` (независимый), `host_pinned` (фиксированный пул).
- **Debugger** — встроенный интерактивный отладчик Ansible, останавливающий выполнение при ошибке и предоставляющий доступ к переменным и командной строке.

## Основные концепции

### Запуск Playbook

Стандартный запуск требует указания файла плейбука и, как правило, файла [Inventory](./ansible_setup_and_config.md).

```bash
ansible-playbook -i inventory.ini site.yml
# → Запуск сценария site.yml на хостах из inventory.ini
```

Перед выполнением рекомендуется провести **статический анализ** кода:
```bash
ansible-playbook site.yml --syntax-check
# → Проверка синтаксиса YAML и структуры плейбука
```

**Полезные варианты запуска:**
```bash
# Проверка синтаксиса + список задач
ansible-playbook site.yml --syntax-check --list-tasks

# Проверка синтаксика + список тегов
ansible-playbook site.yml --syntax-check --list-tags

# Проверка какие хосты будут затронуты
ansible-playbook site.yml --list-hosts

# Комбинация: синтаксис + задачи + теги + хосты
ansible-playbook site.yml --syntax-check --list-tasks --list-tags --list-hosts
```

### Сбор системной информации (Fact Gathering)

По умолчанию Ansible запускает модуль `setup` в начале каждого сценария для сбора фактов о хостах (IP-адреса, ОС, диски и т.д.).

*   **gather_facts: false**: Отключение сбора фактов для ускорения выполнения (если факты не используются).
*   **gather_subset**: Ограничение категорий собираемых данных (например, `!all,min`) для оптимизации.
*   **gather_timeout**: Время ожидания сбора фактов (по умолчанию 10с).
*   **Fact Caching**: Возможность сохранять факты между запусками плейбуков (настраивается в `ansible.cfg`).

**Пример отключения сбора фактов:**
```yaml
- name: Быстрое обновление пакетов
  hosts: all
  gather_facts: false  # Facts не нужны — ускоряем выполнение
  tasks:
    - name: Обновление пакетов
      ansible.builtin.package:
        name: "*"
        state: latest
```

**Пример использования Fact Caching:**
```ini
# ansible.cfg
[defaults]
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_facts_cache
fact_caching_timeout = 86400  # 24 часа
```

**Пример ограничения сбора Facts:**
```yaml
- name: Задача с минимальными фактами
  hosts: all
  gather_facts: true
  gather_subset:
    - "!all"
    - "!min"
    - network  # Только сетевые интерфейсы
  gather_timeout: 30
```

### Анализ вывода выполнения

Вывод в консоль цветокодирован для быстрого анализа состояния:

*   **Зеленый (ok)**: Задача выполнена успешно, изменений в системе не потребовалось (состояние уже соответствует целевому).
*   **Желтый (changed)**: Задача выполнена успешно, в систему внесены изменения.
*   **Красный (failed / unreachable)**: Ошибка выполнения задачи или невозможность подключиться к хосту. Выполнение для данного хоста прерывается.
*   **Голубой (cyan / skipped)**: Задача пропущена из-за условий `when` или несовпадения тегов.

**Плагины вывода (Callback Plugins):**
Callback-плагины определяют формат вывода в консоли и позволяют перехватывать события для логирования или уведомлений. Подробнее о типах и создании собственных плагинов см. в руководстве **[Разработка Callback-плагинов](./ansible-callback-plugins.md)**.

Современным стандартом является плагин `yaml`.
Настройка через переменную окружения:
```bash
export ANSIBLE_STDOUT_CALLBACK=yaml
ansible-playbook site.yml
```

**Доступные плагины вывода:**

| Плагин | Формат | Когда использовать |
| :--- | :--- | :--- |
| `yaml` | YAML-подобный, структурированный | Стандарт для ручных запусков и CI |
| `debug` | Подробный с переменными | Глубокая отладка |
| `minimal` | Однострочный | Сжатые логи, cron-задачи |
| `json` | JSON-поток | Машинная обработка логов |
| `tree` | Дерево по хостам | Детальный отчёт по хостам |

**Пример с tree:**
```bash
ansible-playbook site.yml -e "output_dir=./logs"
ANSIBLE_STDOUT_CALLBACK=tree ANSIBLE_TREE_DIR=./logs ansible-playbook site.yml
```

### Уровни детализации (Verbosity)

Уровни `-v` ... `-vvvv` влияют на количество информации в выводе:

| Флаг | Что показывает | Когда использовать |
| :--- | :--- | :--- |
| (без флага) | Краткий вывод: ok/changed/failed | Штатное выполнение |
| `-v` | Задачи + имена хостов | Базовый мониторинг |
| `-vv` | Подробности модулей | Отладка конкретных задач |
| `-vvv` | SSH-соединения + переменные | Отладка SSH и передаваемых значений |
| `-vvvv` | Сбор фактов + окружение | Глубокая отладка проблем подключения |

**Пример отладки SSH:**
```bash
# Показать подробности SSH-соединения
ansible-playbook site.yml -vvv

# Пример вывода (фрагмент):
# <192.168.1.10> SSH state: is_connection_persistent
# <192.168.1.10> EXEC ssh -C ... 192.168.1.10
# <192.168.1.10> EXEC /bin/sh -c 'echo ~ && umask 22 && ...'
```

### Ключевые опции командной строки

#### Управление охватом (Scope)
*   `-i`, `--inventory`: Путь к файлу или директории Inventory. Можно указывать несколько раз.
*   `-l`, `--limit`: Ограничение выполнения конкретными хостами или группами (например, `--limit webservers`).
*   `-t`, `--tags`: Выполнение только задач с указанными тегами. Подробнее: [Теги и управление потоком](./PlaybookStructure/flow_control.md#теги-tags).
*   `--skip-tags`: Пропуск задач с указанными тегами.

**Примеры использования `--limit`:**
```bash
# Только один хост
ansible-playbook site.yml --limit web1.example.com

# Только группа хостов
ansible-playbook site.yml --limit webservers

# Исключение хоста (используйте !)
ansible-playbook site.yml --limit "all:!db1.example.com"

# Комбинация групп
ansible-playbook site.yml --limit "webservers:&production"
```

**Примеры использования тегов:**
```bash
# Только задачи с тегом "deploy"
ansible-playbook site.yml --tags deploy

# Несколько тегов через запятую
ansible-playbook site.yml --tags "deploy,config"

# Исключение тегов
ansible-playbook site.yml --skip-tags "test,debug"

# Только特定的 тег + исключение
ansible-playbook site.yml --tags "deploy" --skip-tags "rollback"
```

#### Отладка и проверка
*   `-v`, `-vv`, `-vvv`, `-vvvv`: Уровень детализации вывода (Verbosity). Флаг `-vvv` оптимален для отладки SSH-соединений и проверки передаваемых переменных.
*   `-C`, `--check`: Режим проверки (**Check Mode** / Dry Run). Изменения не вносятся; модули сообщают, что *было бы* изменено.
*   `-D`, `--diff`: Показ изменений в файлах в формате `diff` (что было удалено/добавлено). Часто комбинируется с `--check`.
*   `--list-hosts` / `--list-tasks` / `--list-tags`: Вывод списка затрагиваемых хостов, задач или доступных тегов без запуска.

**Практические примеры Check Mode:**
```bash
# Базовая проверка: что будет изменено?
ansible-playbook -i inventories/prod site.yml --check

# Проверка с diff: показать конкретные изменения в файлах
ansible-playbook -i inventories/prod site.yml --check --diff

# Проверка только определённых хостов
ansible-playbook -i inventories/prod site.yml --check --limit webservers

# Проверка только определённых задач по тегам
ansible-playbook -i inventories/prod site.yml --check --diff --tags config

# Проверка с увеличенной детализацией
ansible-playbook -i inventories/prod site.yml --check --diff -v
```

**Проверка что запланировано (dry run без модулей):**
```bash
# Список задач, которые будут выполнены
ansible-playbook site.yml --list-tasks

# Список хостов, которые будут затронуты
ansible-playbook site.yml --list-hosts

# Только特定的 задачи
ansible-playbook site.yml --list-tasks | grep -i "update"
```

#### Переменные и аутентификация
*   `-e`, `--extra-vars`: Передача переменных напрямую в командную строку. Имеют наивысший приоритет.
    ```bash
    ansible-playbook site.yml -e "app_version=1.2.3 env=prod"
    ```
*   `-b`, `--become`: Выполнение задач с повышением привилегий (`sudo`).
*   `--become-user`: Указание пользователя, от имени которого выполнять задачу (по умолчанию `root`). Пример: `--become-user postgres`.
*   `-K`, `--ask-become-pass`: Запрос пароля для `sudo`.
*   `-k`, `--ask-pass`: Запрос пароля для SSH.
*   `--ask-vault-pass`: Запрос пароля для расшифровки [Ansible Vault](./Vault/basics.md).

**Приоритет переменных (от наивысшего к наименьшему):**
1.  `-e` (extra-vars в командной строке)
2.  Task-level variables (переменные задачи)
3.  Inventory host_vars / group_vars
4.  playbook group_vars / host_vars
5.  Inventory facts / registered variables
6.  Role facts / default variables
7.  `ansible.cfg` / environment variables

**Примеры extra-vars:**
```bash
# Простые значения
ansible-playbook site.yml -e "version=2.1.0 environment=staging"

# JSON-формат (для сложных структур)
ansible-playbook site.yml -e '{"packages": ["nginx", "postgresql"], "state": "latest"}'

# Файл переменных
ansible-playbook site.yml -e "@vars/production.yml"

# Комбинация: файл + командная строка (команда перезаписывает файл)
ansible-playbook site.yml -e "@vars/production.yml" -e "version=2.2.0"
```

#### Параметры выполнения
*   `-f`, `--forks`: Количество параллельных потоков (по умолчанию 5). Подробнее: [Оптимизация производительности](./ansible_performance_tuning.md).
*   `--strategy`: Выбор стратегии выполнения (`linear`, `free`, `host_pinned`).
*   `--start-at-task`: Начать выполнение с конкретной задачи по её имени.
*   `--step`: Пошаговое выполнение с интерактивным подтверждением каждой задачи.
*   `--force-handlers`: Выполнять обработчики (Handlers) даже если Playbook завершился с ошибкой.

**Стратегии выполнения (Strategy):**

| Стратегия | Поведение | Когда использовать |
| :--- | :--- | :--- |
| `linear` | Все хосты выполняют одну задачу, затем переходят к следующей | Зависимые задачи, стандартный плейбук |
| `free` | Каждый хост проходит задачи максимально быстро, не дожидаясь остальных | Независимые задачи, максимальная скорость |
| `host_pinned` | Фиксированное число хостов (вместо forks) | Длительные плейбуки, чтобы не перегружать контроллер |

**Примеры стратегий:**
```yaml
# Стандартная стратегия (linear по умолчанию)
- name: Пример
  hosts: all
  strategy: linear
  tasks:
    - name: Задача 1
      ansible.builtin.command: echo "Task 1 on {{ inventory_hostname }}"

# Стратегия free (максимальная скорость)
- name: Независимые задачи
  hosts: all
  strategy: free
  tasks:
    - name: Длительная задача
      ansible.builtin.command: sleep 10
      # Каждый хост выполнит быстро, не дожидаясь остальных

# Стратегия host_pinned (фиксированный пул)
- name: Длительное обновление
  hosts: all
  strategy: host_pinned
  serial: 1  # Один хост за раз
  tasks:
    - name: Обновление пакетов
      ansible.builtin.package:
        name: "*"
        state: latest
```

**start-at-task:**
```bash
# Начать с конкретной задачи ( полезно при длинных плейбуках)
ansible-playbook site.yml --start-at-task "Deploy application"
```

**--step (интерактивный режим):**
```bash
# Пошаговое выполнение с подтверждением
ansible-playbook site.yml --step
# Ansible будет спрашивать "Perform task: [N/y]" перед каждой задачей
```

**--force-handlers:**
```bash
# Выполнить handlers даже при ошибке (полезно для очистки)
ansible-playbook site.yml --force-handlers
```

## Переменные окружения (Environment Variables)

| Переменная | Описание |
| :--- | :--- |
| `ANSIBLE_FORCE_COLOR` | Принудительная раскраска вывода (полезно для логов CI). |
| `ANSIBLE_HOST_KEY_CHECKING` | Отключение проверки SSH Host Key (небезопасно, но часто нужно в CI). |
| `ANSIBLE_STDOUT_CALLBACK` | Выбор плагина отображения вывода (`yaml`, `debug`, `minimal`). |
| `ANSIBLE_LOG_PATH` | Путь к файлу лога выполнения. |
| `ANSIBLE_TIMEOUT` | Таймаут подключения к хосту (в секундах). |
| `ANSIBLE_FORKS` | Количество параллельных потоков (переопределяет `ansible.cfg`). |
| `ANSIBLE_PRIVATE_KEY_FILE` | Путь к приватному ключу SSH по умолчанию. |
| `ANSIBLE_REMOTE_USER` | Пользователь по умолчанию для SSH-подключения. |
| `ANSIBLE_BECOME_METHOD` | Метод повышения привилегий (`sudo`, `su`, `pbrun`). |
| `ANSIBLE_BECOME_USER` | Пользователь для become (по умолчанию `root`). |
| `ANSIBLE_VAULT_PASSWORD_FILE` | Путь к файлу с паролем Vault. |
| `ANSIBLE_CACHE_PLUGIN` | Плагин кэширования (`jsonfile`, `redis`, `mongodb`). |
| `ANSIBLE_GATHERING` | Режим сбора Facts (`implicit`, `explicit`, `smart`). |
| `ANSIBLE_ssh_common_args` | Дополнительные SSH-аргументы для всех хостов. |
| `ANSIBLE_PIPELINING` | Включение SSH Pipelining (ускоряет выполнение). |

**Примеры использования:**
```bash
# Логирование в файл + отключение проверки ключей + YAML-вывод
export ANSIBLE_LOG_PATH=./logs/ansible_$(date +%Y%m%d_%H%M%S).log
export ANSIBLE_HOST_KEY_CHECKING=False
export ANSIBLE_STDOUT_CALLBACK=yaml
ansible-playbook site.yml

# Увеличение forks и таймаута для больших кластеров
export ANSIBLE_FORKS=20
export ANSIBLE_TIMEOUT=30
ansible-playbook -i production.ini site.yml

# Использование приватного ключа
export ANSIBLE_PRIVATE_KEY_FILE=~/.ssh/id_rsa_ansible
ansible-playbook site.yml
```

## Запуск через Ansible Navigator (Современный стандарт)

С появлением **Execution Environments (EE)** рекомендуется использовать утилиту `ansible-navigator`. Она обеспечивает полную изоляцию и идентичность сред выполнения.

```bash
ansible-navigator run site.yml -i inventory.ini --mode stdout
# → Запуск внутри изолированного контейнера EE
```
Подробнее: [Ansible Execution Environments](./ansible-execution-environments.md).

**Основные опции navigator:**
```bash
# Запуск в интерактивном режиме (TUI)
ansible-navigator run site.yml

# Запуск в stdout (как ansible-playbook)
ansible-navigator run site.yml --mode stdout

# Указание образа EE
ansible-navigator run site.yml --execution-environment-image my-ee:latest

# Просмотр доступных коллекций в EE
ansible-navigator collection list

# Просмотр документации модуля
ansible-navigator doc ansible.builtin.package
```

## Практические сценарии

### Безопасное обновление (Check Mode + Diff)

Перед применением изменений в production-среде критически важно проверить, что именно будет изменено.
```bash
ansible-playbook -i inventories/prod site.yml --check --diff
```

### Интерактивная отладка (Debugger)

Использование встроенного отладчика при сбоях задач:
```yaml
- name: Задача с отладчиком
  ansible.builtin.command: /usr/bin/false
  debugger: on_failed
```
При ошибке Ansible откроет консоль для инспекции переменных и повторного запуска задачи (`r`).

**Все режимы отладчика:**

| Режим | Срабатывает когда | Когда использовать |
| :--- | :--- | :--- |
| `on_failed` | Задача завершилась ошибкой | Стандартная отладка |
| `on_unreachable` | Хост недоступен | Проблемы с SSH/сетью |
| `on_skipped` | Задача пропущена | Отладка условий `when` |
| `on_ok` | Задача выполнена успешно | Отладка переменных после выполнения |

**Команды отладчика:**
```
(c)ontinue    — продолжить выполнение
(r)etry       — повторить текущую задачу
(e)xit        — выйти из отладчика
(p)rint stats — показать статистику выполнения
(q)uit        — выйти с ошибкой
(v)ar varname — показать значение переменной
(a)rgs        — показать аргументы задачи
(b)reakpoint  — установить точку останова
(l)ist        — показать текущую задачу
(s)kip        — пропустить текущую задачу
```

**Пример отладчика с different modes:**
```yaml
---
- name: Пример отладчика
  hosts: all
  tasks:
    - name: Задача с отладчиком на ошибку
      ansible.builtin.command: /bin/false
      debugger: on_failed

    - name: Задача с отладчиком на пропуск
      ansible.builtin.debug:
        msg: "Эта задача пропущена"
      when: false
      debugger: on_skipped

    - name: Задача с отладчиком на успех
      ansible.builtin.debug:
        msg: "Задача выполнена"
      debugger: on_ok
```

### Интеграция с Vagrant

При использовании Ansible в качестве провизионера для Vagrant:
```ruby
config.vm.provision "ansible" do |ansible|
  ansible.playbook = "playbook.yml"
  ansible.inventory_path = "path/to/your/inventory.ini"
  # ansible.extra_vars = { version: "1.0.1" }
end
```

### Запуск задачи от конкретного пользователя

Если все плейбуки по умолчанию выполняются от одного пользователя (например, `deploy`), но отдельную задачу нужно запустить от другого (например, `postgres`), используйте директиву `become_user` на уровне задачи:

```yaml
- name: Выполнить миграции базы данных
  ansible.builtin.command: /opt/app/scripts/migrate.sh
  become: true
  become_user: postgres
  register: migration_result

- name: Проверить результат миграции
  ansible.builtin.assert:
    that:
      - migration_result.rc == 0
    fail_msg: "Миграция завершилась с ошибкой"
```

Это соответствует принципу наименьших привилегий: только конкретная задача работает от имени сервисного пользователя, а не весь плейбук.

### Неинтерактивный запуск в CI/CD

1.  Используйте SSH-ключи (через `ssh-agent`).
2.  Используйте файлы паролей для Vault: `--vault-password-file .vault_pass`.
3.  Установите `ANSIBLE_FORCE_COLOR=true` для читаемости логов.

**Пример GitLab CI:**
```yaml
deploy:
  stage: deploy
  image: cytopia/ansible
  script:
    - ansible-playbook -i inventory/prod deploy.yml
      --vault-password-file <(echo "$VAULT_PASS")
      --check --diff
  variables:
    ANSIBLE_FORCE_COLOR: "true"
    ANSIBLE_HOST_KEY_CHECKING: "False"
    ANSIBLE_LOG_PATH: "./ansible.log"
  artifacts:
    paths:
      - ansible.log
    when: always
```

**Пример GitHub Actions:**
```yaml
- name: Run Ansible Playbook
  uses: dawidd6/action-ansible-playbook@v2
  with:
    playbook: deploy.yml
    inventory: inventory/prod
    vault_password: ${{ secrets.VAULT_PASS }}
    options: |
      --check --diff
      --extra-vars "version=${{ github.sha }}"
```

### Запуск нескольких плейбуков последовательно

```bash
# Последовательный запуск
ansible-playbook site.yml && ansible-playbook deploy.yml && ansible-playbook verify.yml

# Параллельный запуск (важно: они могут конфликтовать!)
ansible-playbook site.yml &
ansible-playbook deploy.yml &
wait
```

### Использование --start-at-task для длинных плейбуков

```bash
# Если плейбук из 200 задач упал на задаче 150
# Не нужно запускать все 149 задач заново!
ansible-playbook site.yml --start-at-task "Deploy Application"
```

### Контроль узлов через limit + теги

```bash
# Обновить только веб-серверы в production, только конфигурационные задачи
ansible-playbook site.yml \
  --limit webservers \
  --tags config \
  --check --diff
```

## Дополнительная информация

### Смотрите также

*   **[Управление обновлениями (Patch Management)](./ansible_patch_management.md)** — стратегии массового обновления ОС в гетерогенных средах.
*   [Оптимизация производительности](./ansible_performance_tuning.md) — стратегии `linear`, `free`, использование `serial` и `async`.
* [Управление потоком выполнения](./PlaybookStructure/flow_control.md) — работа с `when`, `loop` и тегами.
* [Безопасность (Vault)](./Vault/basics.md) — работа с зашифрованными данными.
* [Настройка ansible.cfg](./ansible_setup_and_config.md) — установка параметров по умолчанию.
* [Отладка Ansible](./examples/debugging_examples.md) — подробные примеры отладки и использования debugger.
* [Callback-плагины](./ansible-callback-plugins.md) — кастомизация вывода и интеграция с внешними системами.
* [Execution Environments](./ansible-execution-environments.md) — контейнерные среды выполнения.
