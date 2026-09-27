# Ansible — оптимизация производительности

## Определения

**SSH Pipelining** — метод ускорения, при котором скрипты модулей передаются через стандартный ввод (STDIN) существующего SSH-соединения. Это исключает необходимость создания и копирования временного Python-файла на диск управляемого узла для каждой задачи, что снижает нагрузку на I/O и сеть.

**SSH Multiplexing (ControlPersist)** — механизм OpenSSH, позволяющий переиспользовать одно TCP-соединение для нескольких последовательных SSH-сессий. Это избавляет от накладных расходов на повторное рукопожатие (handshake) и аутентификацию.

**Параллелизм (Forks)** — параметр, определяющий количество параллельных процессов, которые Ansible может порождать для одновременного выполнения задач на разных хостах.

**Кэширование фактов (Fact Caching)** — сохранение собранных системных данных (facts) во внешнее хранилище, что позволяет избежать повторного выполнения `gather_facts` при каждом запуске плейбука.

**Стратегия выполнения (Execution Strategy)** — плагин, определяющий порядок прохождения задач через группу хостов (например, синхронно или независимо).

**jinja2_native** — режим работы движка шаблонизации, позволяющий Jinja2 возвращать нативные типы Python (списки, словари) вместо их строковых представлений, что экономит ресурсы на преобразовании типов.

**gather_facts** — этап сбора системной информации (ansible_facts) перед выполнением задач плейбука. Включает информацию о сети, дисках, пакетах, пользователях и т.д.

**throttle** — параметр задачи, ограничивающий количество параллельных выполнений этой задачи в пределах текущего батча хостов.

**serial** — параметр плейбука, определяющий размер батча хостов, обрабатываемых одновременно в рамках rolling updates.

---

## Основные концепции

### 1. Оптимизация сетевых соединений

#### Настройка SSH в ansible.cfg
Для максимальной скорости работы через SSH необходимо включить конвейеризацию и мультиплексирование в блоке `[ssh_connection]`. Настройка `ControlPersist` на длительное время (например, 1 час) полезна для частых запусков.

```ini
[ssh_connection]
# Включение Pipelining (требует отключения requiretty в sudoers на хостах)
pipelining = True

# Настройка ControlPersist для переиспользования соединений
ssh_args = -o ControlMaster=auto -o ControlPersist=3600s
# Короткий путь к сокетам (помогает избежать ошибок длины пути в UNIX)
control_path = %(directory)s/ansible-ssh-%%h-%%p-%%r
```

#### Таблица параметров SSH-соединения

| Параметр | Описание | Рекомендуемое значение |
| :--- | :--- | :--- |
| `pipelining` | Передача модулей через STDIN | `True` |
| `ControlMaster` | Мультиплексирование соединений | `auto` |
| `ControlPersist` | Время жизни соединения | `3600s` (1 час) |
| `ControlPath` | Путь к сокету | `%(directory)s/ansible-ssh-%%h-%%p-%%r` |
| `retries` | Количество повторных попыток | `3` |
| `timeout` | Таймаут подключения | `10` (секунды) |
| `ssh_args` | Дополнительные аргументы SSH | `-o ControlMaster=auto -o ControlPersist=3600s` |

#### Проблема: блокировка SSH-сессиями при большом парке

При парке более 100 хостов может возникнуть проблема, когда Ansible открывает слишком много параллельных SSH-сессий, что приводит к таймаутам и недоступности узлов. В некоторых конфигурациях по умолчанию Ansible может использовать одну SSH-сессию для всех задач, полностью блокируя выполнение.  
**Решение:**  
1. Увеличить `forks` в `ansible.cfg` (рекомендуется 50–100 для парков 100–200 хостов).  
2. При необходимости снизить `serial` для батч-обработки.  
3. Для передачи большого количества файлов использовать `synchronize` (rsync) или упаковку в архив, чтобы минимизировать количество операций копирования.

### 2. Управление параллелизмом

Параметр `forks` по умолчанию равен 5, что крайне мало для сред более чем с 10–20 хостами. Увеличение этого параметра повышает потребление памяти и CPU на Control Node.

*   **В ansible.cfg:** `forks = 50`
*   **В CLI:** 
    ```bash
    ansible-playbook site.yml --forks 50
    # → Выполнение пойдет батчами по 50 хостов одновременно
    ```

#### Соотношение forks и ресурсов Control Node

| Количество хостов | Рекомендуемое forks | Потребление RAM (примерное) |
| :--- | :--- | :--- |
| 10–50 | 20–50 | 512 МБ – 1 ГБ |
| 50–200 | 50–100 | 1–4 ГБ |
| 200–1000 | 100–200 | 4–16 ГБ |
| 1000+ | 200+ (с осторожностью) | 16+ ГБ |

#### Ограничение параллелизма (throttle)

Параметр `throttle` позволяет ограничить количество параллельных выполнений конкретной задачи:

```yaml
- name: Ограничение API-запросов
  ansible.builtin.uri:
    url: "https://api.example.com/endpoint"
    method: POST
  throttle: 5  # Не более 5 параллельных запросов
```

### 3. Кэширование фактов (Fact Caching)

Сбор фактов (`gather_facts`) — одна из самых долгих операций. Кэширование позволяет ускорить запуск на 30–50% в крупных инвентарях.

**Пример 1: JSON-файлы (для локальной работы):**
```ini
[defaults]
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_cache
fact_caching_timeout = 86400
```

**Пример 2: Redis (для распределенных сред и [AWX/AAP](./ansible-automation-platform.md)):**
```ini
[defaults]
fact_caching = redis
fact_caching_connection = 127.0.0.1:6379:0
fact_caching_timeout = 86400
```

**Пример 3: Memcached (высокая производительность при чтении):**
```ini
[defaults]
fact_caching = memcached
fact_caching_connection = 127.0.0.1:11211
fact_caching_timeout = 86400
```

#### Оптимизация сбора фактов

```yaml
# Отключение сбора фактов для плейбука
- hosts: all
  gather_facts: false
  tasks:
    - name: Задача без фактов
      ansible.builtin.debug:
        msg: "Факты не собираются"

# Сбор только необходимых фактов
- hosts: all
  gather_facts: true
  gather_subset:
    - network
    - hardware
  gather_timeout: 30

# Использование кэшированных фактов
- hosts: all
  vars:
    ansible_facts: "{{ hostvars[inventory_hostname] }}"
```

### 4. Стратегии выполнения

*   **Linear (по умолчанию):** Ansible ждет завершения текущей задачи на всех хостах перед переходом к следующей.
*   **Free:** Каждый хост проходит по задачам плейбука с максимально возможной скоростью, не дожидаясь остальных.
*   **Host Pinned:** Хост остается в своем слоте (fork) до завершения всего плейбука, что оптимизирует использование соединений.

```yaml
- hosts: all
  strategy: free
  tasks:
    - name: Длительная задача установки
      ansible.builtin.package:
        name: "*"
        state: latest
```

#### Таблица сравнения стратегий

| Стратегия | Поведение | Использование соединений | Подходит для |
| :--- | :--- | :--- | :--- |
| `linear` | Синхронное выполнение | Среднее | Зависимые задачи |
| `free` | Независимое выполнение | Высокое | Независимые задачи |
| `host_pinned` | Фиксированное число хостов | Низкое | Длительные плейбуки |

### 5. Внутренняя оптимизация Python

*   **`jinja2_native = True`**: Включите в `[defaults]`, чтобы избежать лишних преобразований типов в сложных шаблонах.
*   **FQCN (Fully Qualified Collection Name)**: Использование полных имен модулей (`ansible.builtin.copy`) ускоряет их поиск движком Ansible.

### 6. Оптимизация переменных и условий

```yaml
# Использование простых переменных вместо сложных вычислений
- name: Использование переменной
  ansible.builtin.debug:
    msg: "{{ simple_var }}"

# Кэширование результатов вычислений
- name: Вычисление с кэшированием
  ansible.builtin.set_fact:
    computed_value: "{{ complex_calculation | cache }}"

# Использование when вместо блоков с conditional
- name: Условное выполнение
  ansible.builtin.debug:
    msg: "Условие выполнено"
  when: condition_var | bool
```

---

## Практические сценарии

## Практические сценарии

### Последовательное обновление (Rolling Updates)

Использование `serial` и `throttle` позволяет безопасно обновлять высоконагруженные кластеры без простоя. Системное описание стратегий обновления приведено в разделе **[Управление обновлениями (Patch Management)](./ansible_patch_management.md)**.

```yaml
- hosts: web_servers
  serial: "25%" # Обновлять по четверти серверов за раз
  tasks:
    - name: Перезапуск балансировщика
      ansible.builtin.service:
        name: haproxy
        state: restarted
      throttle: 1 # Перезапускать строго по одному внутри текущего батча
```

### Асинхронные задачи (async / poll)

Идеально для операций, занимающих более 10–15 минут (например, пересборка RAID, долгие скрипты БД, выгрузка дампов). Подробнее о применении асинхронности — [Управление потоком выполнения](./PlaybookStructure/flow_control.md).

```yaml
- name: Запуск длительной операции в фоне
  ansible.builtin.command: /usr/local/bin/heavy_task.sh
  async: 3600 # Максимальное время выполнения (в секундах)
  poll: 0    # Не ждать завершения, немедленно перейти к следующей задаче
  register: job_result

- name: Проверка статуса позже (через модуль async_status)
  ansible.builtin.async_status:
    jid: "{{ job_result.ansible_job_id }}"
  register: job_status
  until: job_status.finished
  retries: 30
  delay: 60
```

### Выборочный запуск задач (tags и skip-tags)

Использование тегов позволяет запускать только необходимые задачи, что значительно ускоряет отладку и повторные запуски. Подробнее о работе с тегами и лимитом — [Выполнение Playbook: ключевые опции CLI](./ansible_playbook_execution.md).

```yaml
# Управление стратегией выполнения в плейбуке
- hosts: web_servers
  strategy: free
  serial: "25%"
  tasks:
    - name: Длительная задача
      ansible.builtin.command: sleep 10
      throttle: 5  # Не более 5 параллельных запросов
```

### Оптимизация для CI/CD

```ini
[defaults]
# Быстрый запуск в CI/CD
host_key_checking = False
timeout = 30
forks = 20

# Кэширование для повторных запусков
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_cache
fact_caching_timeout = 3600

# Минимальный вывод
nocows = 1
verbosity = 0
```

### Оптимизация для CI/CD

Настройка `ansible.cfg` для CI/CD должна включать `forks`, `timeout` и отключение `host_key_checking`. Детали CI/CD-запусков и переменных окружения — [Выполнение Playbook: неинтерактивный запуск в CI/CD](./ansible_playbook_execution.md).

```bash
# Запуск в CI/CD с оптимизацией
ANSIBLE_HOST_KEY_CHECKING=False \
ANSIBLE_TIMEOUT=30 \
ansible-playbook site.yml \
  --forks 20 \
  --syntax-check \
  --check \
  --diff
```

---

## Дополнительная информация

### Профилирование производительности

Для поиска "медленных" задач используйте встроенные callback-плагины. Это поможет выявить, на каких шагах теряется больше всего времени. Подробнее о работе этих плагинов и создании собственных см. в руководстве **[Разработка Callback-плагинов](./ansible-callback-plugins.md)**.

**Включение в ansible.cfg:**
```ini
[defaults]
callbacks_enabled = ansible.posix.timer, ansible.posix.profile_tasks, ansible.posix.profile_roles
```

### Mitogen: Strategy Plugin для производительности

**Mitogen** — сторонний плагин стратегии, который радикально ускоряет Ansible за счёт замены SSH-транспорта на собственный Python-протокол, минуя накладные расходы на создание нового SSH-соединения и Python-процесса для каждой задачи.

#### Как Mitogen ускоряет Ansible

| Компонент | Стандартный SSH | Mitogen | Ускорение |
| :--- | :--- | :--- | :--- |
| SSH handshake | 50-200ms на хост | Отсутствует (постоянное соединение) | ~100x |
| Копирование модуля | 10-50ms (SCP) | 0ms (через STDIN) | ~50x |
| Запуск Python | 100-500ms (interpreter startup) | 0ms (интерпретатор уже запущен) | ~200x |
| **Итого на задачу** | **200-800ms** | **5-20ms** | **10-40x** |

#### Установка и настройка

```bash
# Установка Mitogen
pip install mitogen

# Проверка версии
python -c "import mitogen; print(mitogen.__version__)"
```

```ini
# ansible.cfg
[defaults]
strategy_plugins = /path/to/mitogen/ansible_mitogen/plugins/strategy
strategy = mitogen_linear
```

#### Ограничения и статус на 2026 год

- **Поддержка ansible-core:** Официально поддерживается до ansible-core 2.16. Новые версии (2.17+) могут работать, но без гарантий.
- **Совместимость с коллекциями:** Конфликтует с некоторыми коллекциями, использующими кастомные connection-плагины.
- **Execution Environments:** Не поддерживается в EE (контейнеризированные среды).
- **Подключение Windows:** Не поддерживается — только SSH на Linux/Unix.

#### Когда использовать Mitogen

```
Использовать Mitogen когда:
  - Нет Execution Environments (standalone Control Node)
  - ansible-core <= 2.16
  - 100+ хостов, много коротких задач
  - Нет кастомных connection-плагинов в ролях

НЕ использовать Mitogen когда:
  - Используются Execution Environments (AAP/AWX)
  - ansible-core >= 2.17
  - Есть Windows-хосты
  - Используются кастомные connection-плагины
```

#### Альтернативы Mitogen (нативный тюнинг)

В современных средах (2026+) рекомендуется нативный тюнинг вместо Mitogen:

```ini
# ansible.cfg — максимальная производительность без Mitogen
[defaults]
fact_caching = redis
fact_caching_connection = 127.0.0.1:6379:0
fact_caching_timeout = 86400
jinja2_native = True
forks = 100

[ssh_connection]
pipelining = True
ssh_args = -o ControlMaster=auto -o ControlPersist=3600s -o ControlPath=/tmp/ansible-ssh-%h-%p-%r
retries = 3
```

#### Бенчмарк: Mitogen vs нативный SSH

```
Сценарий: 200 хостов, 50 задач (установка пакетов, копирование конфигов, перезапуск сервисов)

| Режим | Время выполнения | Потребление RAM |
| :--- | :--- | :--- |
| SSH (forks=5) | 45 мин | 512 МБ |
| SSH (forks=50) + pipelining | 12 мин | 4 ГБ |
| SSH (forks=100) + pipelining + Redis cache | 8 мин | 8 ГБ |
| Mitogen (forks=50) | 3 мин | 2 ГБ |
| Mitogen (forks=100) | 2 мин | 4 ГБ |
```

**Вывод:** Mitogen всё ещё даёт 3-4x ускорение поверх оптимизированного SSH, но ценой совместимости. Для новых проектов с AAP/AWX используйте нативный тюнинг.

### Оптимизация Execution Environments (EE)

При использовании контейнеризированных сред выполнения (EE) убедитесь, что:
1.  **Образы EE прогреты**: Используйте локальный кэш образов на узлах выполнения.
2.  **Минимальный объем**: Не включайте лишние коллекции и пакеты в образ, так как это увеличивает время загрузки и анализа зависимостей.
3.  **Кэширование слоев**: Используйте `--cache` при сборке для ускорения повторных сборок.

### Диагностические команды

```bash
# Просмотр текущих настроек
ansible-config dump --only-changed

# Просмотр всех параметров производительности
ansible-config dump | grep -E "forks|pipelining|fact_caching|timeout"

# Проверка времени выполнения плейбука
time ansible-playbook site.yml

# Просмотр использованных_factов
ansible-playbook site.yml --diff

# Проверка соединения с хостами
ansible all -m ping

# Просмотр фактов хоста
ansible web01 -m setup

# Просмотр фактов с фильтром
ansible web01 -m setup -a "filter=ansible_distribution*"
```

### Таблица типовых ошибок

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `Timeout expired` | Медленное соединение или хост | Увеличьте `timeout` или проверьте сеть |
| `Too many open files` | Слишком много forks | Уменьшите `forks` или увеличьте `ulimit` |
| `Permission denied` | Pipelining требует отключения `requiretty` | Обновите sudoers на хостах |
| `Connection refused` | Хост недоступен | Проверьте SSH-доступ и firewall |
| `Module timeout` | Длительная операция | Используйте `async` для длительных задач |
| `Fact cache error` | Проблемы с хранилищем фактов | Проверьте Redis/Memcached/jsonfile |
| `Strategy error` | Некорректная стратегия | Проверьте `strategy` в плейбуке |
| `Forks limit` | Мало памяти на Control Node | Увеличьте RAM или уменьшите `forks` |

### Capacity Planning для Ansible Control Node

#### Формула расчёта ресурсов

```
RAM (GB) = forks × memory_per_task(MB) / 1024
CPU cores = forks / 2 (для SSH) или forks / 5 (для Mitogen)
```

| Параметр | Значение по умолчанию | Рекомендация для 2000 хостов |
| :--- | :--- | :--- |
| `forks` | 5 | 100-200 |
| `pipelining` | False | True |
| `timeout` | 10 | 30 |
| `fact_caching` | memory | Redis/Memcached |
| RAM | 1 ГБ | 16-32 ГБ |
| CPU | 2 cores | 8-16 cores |

#### Масштабирование: от 100 до 10 000 хостов

**Уровень 1: 100-500 хостов (один Control Node)**
```ini
[defaults]
forks = 50
fact_caching = redis
fact_caching_connection = 127.0.0.1:6379:0
fact_caching_timeout = 86400

[ssh_connection]
pipelining = True
ssh_args = -o ControlMaster=auto -o ControlPersist=3600s
```

**Уровень 2: 500-2000 хостов (оптимизированный Control Node)**
```ini
[defaults]
forks = 100
fact_caching = redis
fact_caching_connection = redis-cluster.internal:6379:0
fact_caching_timeout = 86400
jinja2_native = True
gathering = smart
fact_caching_connection = /tmp/ansible_facts_cache

[ssh_connection]
pipelining = True
ssh_args = -o ControlMaster=auto -o ControlPersist=3600s -o ServerAliveInterval=30
retries = 3
```

**Уровень 3: 2000-10000 хостов (распределённая архитектура)**

```
                          ┌─────────────────┐
                          │   AAP/AWX Tower  │
                          │  (Оркестратор)   │
                          └────────┬────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
    ┌─────────▼─────────┐ ┌───────▼───────┐ ┌─────────▼─────────┐
    │  Execution Node 1 │ │ Execution Node 2│ │  Execution Node 3 │
    │  (500 хостов)     │ │  (500 хостов)  │ │  (500 хостов)     │
    │  forks=100        │ │  forks=100     │ │  forks=100         │
    │  pipelining=True  │ │  pipelining    │ │  pipelining=True   │
    └───────────────────┘ └───────────────┘ └───────────────────┘
```

#### Execution Environments для масштабирования

```yaml
# inventory/execution_nodes.yml
all:
  children:
    execution_nodes:
      hosts:
        ee-node-01:
          ansible_host: 10.0.0.10
          ee_capacity: 500
          ee_concurrent_jobs: 25
        ee-node-02:
          ansible_host: 10.0.0.11
          ee_capacity: 500
          ee_concurrent_jobs: 25
        ee-node-03:
          ansible_host: 10.0.0.12
          ee_capacity: 500
          ee_concurrent_jobs: 25
```

#### Параллельные запуски: forks + serial + throttle

```yaml
# Стратегия для 2000 хостов с контролем нагрузки
- name: Mass configuration update
  hosts: all
  serial: "10%"          # 200 хостов за батч
  throttle: 50           # Не более 50 параллельных SSH
  tasks:
    - name: Update packages
      ansible.builtin.apt:
        upgrade: dist
        state: present

    - name: Apply configuration
      ansible.builtin.template:
        src: templates/app.conf.j2
        dest: /etc/app/config.conf
      notify: Restart app

  handlers:
    - name: Restart app
      ansible.builtin.systemd:
        name: app
        state: restarted
```

#### Мониторинг производительности Control Node

```bash
# Мониторинг потребления памяти
watch -n 5 'ps aux | grep ansible | awk "{sum += \$6} END {print sum/1024 \" MB\"}"'

# Мониторинг соединений
ss -tnp | grep ssh | wc -l

# Профилирование плейбука
ANSIBLE_CALLBACK_WHITELIST=ansible.posix.timer,ansible.posix.profile_tasks \
ansible-playbook site.yml --forks 100
```

#### Таблица рекомендаций по масштабу

| Инфраструктура | Control Node RAM | forks | fact_caching | Архитектура |
| :--- | :--- | :--- | :--- | :--- |
| 10-100 хостов | 2 ГБ | 20-50 | jsonfile | Один CN |
| 100-500 хостов | 4-8 ГБ | 50-100 | Redis | Один CN |
| 500-2000 хостов | 16-32 ГБ | 100-200 | Redis Cluster | AAP + EE Nodes |
| 2000-10000 хостов | 32+ ГБ | 200+ | Redis Cluster | AAP + 3-5 EE Nodes |
| 10000+ хостов | Масштабируемый | 200+ | External DB | Distributed AAP |

### Смотрите также

*   **[Управление обновлениями (Patch Management)](./ansible_patch_management.md)** — стратегии массового обновления ОС в гетерогенных средах.
*   **[Настройка и конфигурация Ansible](./ansible_setup_and_config.md)** — базовые параметры `ansible.cfg`.
*   **[Синхронизация файлов (synchronize)](./Modules/ansible_file_synchronization_modules.md)** — ускорение передачи данных через rsync.
*   **[Переменные и факты](./PlaybookStructure/variables.md)** — работа с системными данными и ограничение сбора фактов (`gather_subset`).
