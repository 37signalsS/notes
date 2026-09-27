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
- **Ansible Navigator** — современная утилита CLI для запуска плейбуков и работы с Execution Environments (EE) через TUI или stdout.
- **Fact Gathering** — этап сбора системной информации (ansible_facts) модулем `setup` перед выполнением задач плейбука.

## Предварительные требования

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **ansible-core** | 2.21+ | Ядро Ansible |
| **Python** | 3.12+ | Совместимость с ansible-core |
| **OpenSSH** (целевые хосты) | 7.0+ | Доступ по SSH для Ansible |
| **sudo** (целевые хосты) | 1.8+ | Права root для установки пакетов |
| **WinRM** (Windows) | 5.0+ | Удалённое управление Windows-хостами |

**Проверка окружения:**
```bash
# Версия Ansible
ansible --version | head -1
# → ansible [core 2.21.4]

# Доступность целевых хостов
ansible all -m ping

# Конфигурация по умолчанию
ansible-config dump | head -20
```

## Основные концепции

### Жизненный цикл выполнения Playbook

Выполнение Playbook проходит через последовательные фазы:

#### Фаза 1: Подготовка (Pre-execution)

Перед запуском Ansible выполняет статические проверки:
```bash
# Проверка синтаксиса YAML и структуры плейбука
ansible-playbook site.yml --syntax-check
# → PLAY [site.yml] 0 ok

# Список затронутых хостов
ansible-playbook site.yml --list-hosts
# → host #1) web01.example.com
# → host #2) web02.example.com

# Список задач
ansible-playbook site.yml --list-tasks
```

**Важно:** `--syntax-check` не проверяет логику задач, только синтаксис YAML и структуру плейбука.

#### Фаза 2: Сбор фактов (Fact Gathering)

По умолчанию модуль `setup` запускается на каждом хосте для сбора ansible_facts:
```yaml
# Отключение сбора фактов для ускорения
- name: Быстрое обновление пакетов
  hosts: all
  gather_facts: false
  tasks:
    - name: Обновление пакетов
      ansible.builtin.package:
        name: "*"
        state: latest
```

**Параметры управления сбором фактов:**

| Параметр | Описание | Пример |
| :--- | :--- | :--- |
| `gather_facts` | Включение/отключение сбора | `gather_facts: false` |
| `gather_subset` | Категории данных | `gather_subset: ['!all', 'network']` |
| `gather_timeout` | Таймаут сбора (секунды) | `gather_timeout: 30` |

**Fact Caching** — сохранение фактов между запусками:
```ini
# ansible.cfg
[defaults]
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_facts_cache
fact_caching_timeout = 86400  # 24 часа
```

#### Фаза 3: Выполнение задач (Execution)

Ansible проходит по каждой задаче в соответствии с выбранной стратегией:

- **linear** (по умолчанию): все хосты выполняют одну задачу, затем переходят к следующей
- **free**: каждый хост проходит задачи максимально быстро, не дожидаясь остальных
- **host_pinned**: фиксированное число хостов вместо forks

```yaml
# Strategy: free — максимальная скорость
- name: Независимые задачи
  hosts: all
  strategy: free
  tasks:
    - name: Длительная задача
      ansible.builtin.command: sleep 10
```

#### Фаза 4: Анализ результатов (Post-execution)

После выполнения Ansible формирует `PLAY RECAP`:
```
PLAY RECAP *********************************************************************
web01.example.com    : ok=120  changed=45  unreachable=0  failed=0  skipped=10
web02.example.com    : ok=120  changed=42  unreachable=1  failed=0  skipped=10
```

**Цветокодирование вывода:**

| Цвет | Статус | Значение |
| :--- | :--- | :--- |
| Зелёный | `ok` | Задача выполнена, изменений нет (целевое состояние уже достигнуто) |
| Жёлтый | `changed` | Задача выполнена, система изменена |
| Красный | `failed` | Ошибка выполнения задачи |
| Красный | `unreachable` | Невозможность подключиться к хосту |
| Голубой | `skipped` | Задача пропущена из-за `when` или тегов |

### Запуск Playbook

```bash
ansible-playbook -i inventory.ini site.yml
# → Стандартный запуск site.yml на хостах из inventory.ini
```

**Проверка синтаксиса:**
```bash
ansible-playbook site.yml --syntax-check
# → Проверка YAML и структуры плейбука
```

**Полезные варианты запуска:**
```bash
# Проверка синтаксиса + список задач
ansible-playbook site.yml --syntax-check --list-tasks

# Проверка синтаксиса + список тегов
ansible-playbook site.yml --syntax-check --list-tags

# Проверка затронутых хостов
ansible-playbook site.yml --list-hosts
```

### Анализ вывода выполнения

**Callback Plugins:**
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

### Уровни детализации (Verbosity)

| Флаг | Что показывает | Когда использовать |
| :--- | :--- | :--- |
| (без флага) | Краткий вывод: ok/changed/failed | Штатное выполнение |
| `-v` | Задачи + имена хостов | Базовый мониторинг |
| `-vv` | Подробности модулей | Отладка конкретных задач |
| `-vvv` | SSH-соединения + переменные | Отладка SSH и передаваемых значений |
| `-vvvv` | Сбор фактов + окружение | Глубокая отладка проблем подключения |

**Пример отладки SSH:**
```bash
ansible-playbook site.yml -vvv
# <192.168.1.10> SSH state: is_connection_persistent
# <192.168.1.10> EXEC ssh -C ... 192.168.1.10
```

## Ключевые опции командной строки

### Управление охватом (Scope)

```bash
# Ограничение конкретными хостами
ansible-playbook site.yml --limit web01.example.com

# Ограничение группой
ansible-playbook site.yml --limit webservers

# Исключение хоста
ansible-playbook site.yml --limit "all:!db01.example.com"

# Комбинация групп
ansible-playbook site.yml --limit "webservers:&production"
```

**Теги:**
```bash
# Только задачи с тегом "deploy"
ansible-playbook site.yml --tags deploy

# Несколько тегов
ansible-playbook site.yml --tags "deploy,config"

# Исключение тегов
ansible-playbook site.yml --skip-tags "test,debug"
```

### Переменные и аутентификация

```bash
# Extra-vars (наивысший приоритет)
ansible-playbook site.yml -e "version=2.1.0 environment=staging"

# JSON-формат
ansible-playbook site.yml -e '{"packages": ["nginx", "postgresql"], "state": "latest"}'

# Файл переменных
ansible-playbook site.yml -e "@vars/production.yml"
```

**Приоритет переменных (от наивысшего к наименьшему):**
1. `-e` (extra-vars в командной строке)
2. Task-level variables
3. Inventory host_vars / group_vars
4. Playbook group_vars / host_vars
5. Inventory facts / registered variables
6. Role facts / default variables
7. `ansible.cfg` / environment variables

### Параметры выполнения

```yaml
# Strategy: free — максимальная скорость
- name: Независимые задачи
  hosts: all
  strategy: free
  tasks:
    - name: Длительная задача
      ansible.builtin.command: sleep 10
```

**Параметры CLI:**

| Параметр | Описание |
| :--- | :--- |
| `-f`, `--forks` | Количество параллельных потоков (по умолчанию 5) |
| `--strategy` | Стратегия выполнения (`linear`, `free`, `host_pinned`) |
| `--start-at-task` | Начать с конкретной задачи по имени |
| `--step` | Пошаговое выполнение с подтверждением |
| `--force-handlers` | Выполнять Handlers даже при ошибке |

**Приоритет tuning параметров:** за детальной настройкой `forks`, `fact_caching`, `serial` и `async` обратитесь к [Оптимизация производительности](./ansible_performance_tuning.md).

### Отладка и проверка

```bash
# Check Mode — что будет изменено?
ansible-playbook -i inventories/prod site.yml --check

# Diff — конкретные изменения
ansible-playbook -i inventories/prod site.yml --check --diff

# Запуск с конкретной задачи
ansible-playbook site.yml --start-at-task "Deploy Application"

# Пошаговое выполнение
ansible-playbook site.yml --step

# Выполнить handlers при ошибке
ansible-playbook site.yml --force-handlers
```

## Переменные окружения (Environment Variables)

| Переменная | Описание |
| :--- | :--- |
| `ANSIBLE_FORCE_COLOR` | Принудительная раскраска вывода |
| `ANSIBLE_HOST_KEY_CHECKING` | Отключение проверки SSH Host Key (небезопасно, но в CI) |
| `ANSIBLE_STDOUT_CALLBACK` | Выбор плагина отображения вывода (`yaml`, `debug`, `minimal`) |
| `ANSIBLE_LOG_PATH` | Путь к файлу лога выполнения |
| `ANSIBLE_TIMEOUT` | Таймаут подключения к хосту (секунды) |
| `ANSIBLE_FORKS` | Количество параллельных потоков |
| `ANSIBLE_PRIVATE_KEY_FILE` | Путь к приватному ключу SSH |
| `ANSIBLE_REMOTE_USER` | Пользователь по умолчанию для SSH |
| `ANSIBLE_BECOME_METHOD` | Метод повышения привилегий (`sudo`, `su`, `pbrun`) |
| `ANSIBLE_BECOME_USER` | Пользователь для become (по умолчанию `root`) |
| `ANSIBLE_VAULT_PASSWORD_FILE` | Путь к файлу с паролем Vault |
| `ANSIBLE_CACHE_PLUGIN` | Плагин кэширования (`jsonfile`, `redis`, `mongodb`) |
| `ANSIBLE_PIPELINING` | Включение SSH Pipelining (ускоряет выполнение) |

**Примеры:**
```bash
export ANSIBLE_LOG_PATH=./logs/ansible_$(date +%Y%m%d_%H%M%S).log
export ANSIBLE_HOST_KEY_CHECKING=False
export ANSIBLE_STDOUT_CALLBACK=yaml
ansible-playbook site.yml

export ANSIBLE_FORKS=20
export ANSIBLE_TIMEOUT=30
ansible-playbook -i production.ini site.yml
```

## Запуск через Ansible Navigator (Современный стандарт)

С появлением **Execution Environments (EE)** рекомендуется использовать `ansible-navigator`. Она обеспечивает изоляцию и идентичность сред выполнения.

```bash
ansible-navigator run site.yml -i inventory.ini --mode stdout
# → Запуск внутри изолированного контейнера EE
```

**Основные опции:**
```bash
# Интерактивный режим (TUI)
ansible-navigator run site.yml

# Stdout (как ansible-playbook)
ansible-navigator run site.yml --mode stdout

# Указание образа EE
ansible-navigator run site.yml --execution-environment-image my-ee:latest

# Просмотр коллекций в EE
ansible-navigator collection list

# Просмотр документации модуля
ansible-navigator doc ansible.builtin.package
```

## Практические сценарии

### Безопасное обновление (Check Mode + Diff)

```bash
ansible-playbook -i inventories/prod site.yml --check --diff
```

### Интерактивная отладка (Debugger)

```yaml
- name: Задача с отладчиком
  ansible.builtin.command: /usr/bin/false
  debugger: on_failed
```

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
(v)ar varname — показать значение переменной
(a)rgs        — показать аргументы задачи
(l)ist        — показать текущую задачу
(s)kip        — пропустить текущую задачу
```

### Неинтерактивный запуск в CI/CD

```bash
ansible-playbook -i inventory/prod deploy.yml \
  --vault-password-file .vault_pass \
  --check --diff
```

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
```

### Запуск нескольких плейбуков последовательно

```bash
# Последовательный запуск
ansible-playbook site.yml && ansible-playbook deploy.yml && ansible-playbook verify.yml

# Параллельный запуск (могут конфликтовать!)
ansible-playbook site.yml &
ansible-playbook deploy.yml &
wait
```

### Контроль узлов через limit + теги

```bash
ansible-playbook site.yml \
  --limit webservers \
  --tags config \
  --check --diff
```

### Использование --start-at-task для длинных плейбуков

```bash
# Если плейбук из 200 задач упал на задаче 150
ansible-playbook site.yml --start-at-task "Deploy Application"
```

### Запуск задачи от конкретного пользователя

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

## Диагностика

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `SSH: connect to port 22: Connection refused` | Хост недоступен или SSH не запущен | Проверьте `systemctl status sshd` и сеть |
| `Permission denied (publickey,password)` | Неверный ключ или пароль | Проверьте `ANSIBLE_PRIVATE_KEY_FILE` и права на ключ |
| `FAIL! => {"msg": "Incorrect sudo password"}` | Неверный пароль sudo | Используйте `--ask-become-pass` или `--vault-password-file` |
| `Skipped: [Errno 2] No such file or directory` | Модуль отсутствует на Control Node | Установите недостающую коллекцию: `ansible-galaxy collection install` |
| `UNREACHABLE! => [WinRM]` | WinRM не настроен на Windows | Проверьте `[winrm]` в `ansible.cfg` |
| `The task includes an option with an undefined variable` | Переменная не определена | Проверьте `gather_facts` и переменные inventory |

### Диагностические команды

```bash
# Проверка версии и окружения
ansible --version
# → ansible [core 2.21.4]

# Проверка конфигурации
ansible-config dump | grep -E "forks|timeout|strategy"

# Проверка доступности хостов
ansible all -m ping

# Детальная отладка SSH
ansible-playbook site.yml -vvv
```

## Retry-файлы

**Retry file** — файл, в котором Ansible сохраняет список хостов, завершивших выполнение с ошибкой (`UNREACHABLE` или `FAILED`). При повторном запуске плейбука с флагом `--retry-files` Ansible автоматически ограничивает выполнение только этими хостами.

### Определения

- **Retry file** — JSON-файл, содержащий список хостов с ошибками и детали последнего отказа.
- **`retry_files_enabled`** — параметр `ansible.cfg`, включающий или отключающий создание retry-файлов.
- **`retry_files_save_path`** — параметр `ansible.cfg`, задающий каталог для хранения retry-файлов.

### Как работает

1. При выполнении плейбука Ansible записывает в retry-файл каждый хост, завершившийся с ошибкой.
2. При повторном запуске с `--limit @retry` Ansible читает этот файл и ограничивает выполнение только проблемными хостами.
3. После успешного завершения на всех хостах retry-файл автоматически удаляется.

### Где хранятся

По умолчанию retry-файлы создаются в каталоге плейбука с именем `<playbook_name>.retry`. Путь можно изменить через `retry_files_save_path` в `ansible.cfg`.

```ini
[defaults]
retry_files_enabled = True
retry_files_save_path = ~/.ansible/retry
```

### Включение и отключение

```bash
# Отключить retry-файлы глобально
ansible.cfg:
  [defaults]
  retry_files_enabled = False

# Отключить для одного запуска
ANSIBLE_RETRY_FILES_ENABLED=false ansible-playbook site.yml

# Включить только для конкретного запуска
ansible-playbook site.yml --retry-files
```

### Практический сценарий

```bash
# Запуск плейбука
ansible-playbook site.yml

# При ошибке Ansible создаёт site.yml.retry:
# {"hosts": ["web01", "db01"], "task": "Deploy application"}

# Повторный запуск только на failed-хостах
ansible-playbook site.yml --limit @site.yml.retry

# Или с отладкой
ansible-playbook site.yml --limit @site.yml.retry -vvv
```

### Retry-файл в CI/CD

```yaml
# .gitlab-ci.yml
deploy:
  script:
    - ansible-playbook site.yml || true
    - |
      if [ -f site.yml.retry ]; then
        echo "Обнаружены ошибки, повторный запуск..."
        ansible-playbook site.yml --limit @site.yml.retry
        rm -f site.yml.retry
      fi
```

### Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Retry-файл не создаётся | `retry_files_enabled = False` | Включите параметр в `ansible.cfg` |
| Retry-файл не удаляется | Хост всё ещё в `failed` | Исправьте ошибку и перезапустите |
| `--limit @file` не работает | Файл не найден | Укажите полный путь: `--limit @/path/to/file.retry` |

### Лучшие практики

- [ ] **CI/CD:** Используйте retry-файлы для автоматического повторного запуска на failed-хостах.
- [ ] **Очистка:** Удаляйте retry-файлы после успешного завершения, чтобы не накапливать мусор.
- [ ] **Безопасность:** Не коммитьте retry-файлы в Git — они могут содержать конфиденциальные данные хостов.
- [ ] **Ограничение:** Используйте `--limit @retry` только для целевых хостов, а не для всего парка.

## Лучшие практики

- [ ] **Idempotency:** Все модули должны быть идемпотентными — повторный запуск не меняет систему
- [ ] **gather_facts: false:** Отключайте сбор фактов, если они не используются для ускорения
- [ ] **Check Mode:** Всегда проверяйте изменения в `--check --diff` перед production-запуском
- [ ] **Serial updates:** Используйте `serial` или `strategy: free` для rolling updates вместо массового обновления
- [ ] **Limit scope:** Ограничивайте `--limit` и `--tags` для снижения рисков
- [ ] **SSH Pipelining:** Включите `pipelining = True` и `ControlPersist` для ускорения SSH
- [ ] **Fact Caching:** Используйте кэширование фактов для крупных инвентарей (>50 хостов)
- [ ] **CI/CD non-interactive:** Используйте `--vault-password-file` и SSH-ключи в CI
- [ ] **Logging:** Настройте `ANSIBLE_LOG_PATH` для аудита всех запусков
- [ ] **Tags:** Размечайте задачи тегами (`deploy`, `config`, `test`) для гибкого запуска
- [ ] **Handlers:** Используйте `--force-handlers` для гарантированного выполнения cleanup
- [ ] **Debugger:** Добавляйте `debugger: on_failed` в критические задачи для оперативной диагностики
- [ ] **Ansible Navigator:** Используйте EE для воспроизводимости сред выполнения
- [ ] **Throttle:** Ограничивайте `throttle` для API-запросов и задач с внешними ограничениями

## Дополнительная информация

- [Управление потоком выполнения](./PlaybookStructure/flow_control.md) — работа с `when`, `loop`, `block` и тегами.
- [Оптимизация производительности](./ansible_performance_tuning.md) — настройка `forks`, `fact_caching`, `serial` и `async`.
- [Управление обновлениями (Patch Management)](./ansible_patch_management.md) — стратегии массового патчинга ОС.
- [Безопасность (Vault)](./Vault/basics.md) — работа с зашифрованными данными.
- [Настройка ansible.cfg](./ansible_setup_and_config.md) — установка параметров по умолчанию.
- [Ansible Execution Environments](./ansible-execution-environments.md) — контейнерные среды выполнения.
