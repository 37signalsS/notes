# Ansible: Оптимизация производительности

## Определения

* **SSH Pipelining**: Метод, сокращающий количество SSH-операций за счет передачи скриптов модулей через стандартный ввод (STDIN) существующего соединения, вместо создания второго для их выполнения.
* **SSH Multiplexing**: Функция OpenSSH, позволяющая переиспользовать одно TCP-соединение для нескольких последовательных SSH-сессий, устраняя задержки на аутентификацию.
* **Forks**: Параметр, определяющий количество хостов, которые Ansible обрабатывает параллельно.
* **Execution Strategy**: Плагин, управляющий потоком выполнения задач на группе хостов. Основные стратегии — `linear` (синхронная) и `free` (асинхронная).
* **Facts (Факты)**: Переменные, содержащие информацию о системе (например, IP-адрес, версия ОС), которые Ansible собирает (`gathers`) на удаленных хостах в начале выполнения.
* **Асинхронные задачи (Async Tasks)**: Задачи, которые Ansible запускает в фоновом режиме, не дожидаясь их завершения.
* **Mitogen**: Сторонний плагин, заменяющий транспортный уровень Ansible (ускорение 1.5–8 раз). **Важно:** В Ansible 12+ (ansible-core 2.19+) strategy plugins объявлены устаревшими — следите за обновлениями проекта.
* **Callback-плагины**: Расширения, которые реагируют на события в Ansible (например, завершение задачи) и позволяют изменять вывод, собирать статистику или выполнять другие действия.

## Основные концепции

### 1. Оптимизация SSH-соединений

#### SSH Pipelining

По умолчанию Ansible для каждой задачи устанавливает два SSH-соединения: одно для копирования Python-скрипта модуля, второе — для его запуска. **Pipelining** устраняет второе соединение, передавая скрипт через STDIN.

**Требование**: На удаленных хостах в конфигурации `sudoers` должна быть отключена опция `requiretty`.

**Включение в `ansible.cfg`**:

```ini
[ssh_connection]
pipelining = True
```

#### SSH Multiplexing (ControlPersist)

Эта функция OpenSSH позволяет переиспользовать одно TCP-соединение для множества SSH-сессий к одному хосту, что кардинально снижает задержки на повторную аутентификацию. **Рекомендуется всегда держать включенным.**

**Включение в `ansible.cfg`**:

```ini
[ssh_connection]
ssh_args = -o ControlMaster=auto -o ControlPersist=60s
```

* `ControlPersist=60s`: Мастер-соединение остается активным 60 секунд после завершения последней сессии.

### 2. Параллелизм (Forks)

Параметр `forks` определяет, сколько хостов Ansible обрабатывает параллельно. Значение по умолчанию (5) слишком мало для больших инвентарей.

**Настройка**:

* **В `ansible.cfg`**:

    ```ini
    [defaults]
    forks = 50
    ```

* **В командной строке**:

    ```bash
    ansible-playbook my_playbook.yml --forks=50
    ```

> **Потребление памяти**: Большее количество форков требует больше оперативной памяти на управляющем узле. Подбирайте значение экспериментально, начиная с 20-30.

### 3. Стратегии выполнения (Execution Strategies)

* **`linear` (по умолчанию)**: Ansible ждет, пока **все** хосты завершат текущую задачу, прежде чем перейти к следующей. Это медленно.
* **`free`**: Как только хост завершает задачу, он немедленно приступает к следующей, не ожидая остальных. Идеально для разнородных систем.

**Настройка в плейбуке**:

```yaml
- hosts: all
  strategy: free
  tasks:
    # ...
```

### 4. Оптимизация сбора фактов

Сбор фактов (`gather_facts`) может быть длительной операцией.

* **Полное отключение**: Если факты не нужны.

    ```yaml
    - hosts: all
      gather_facts: false
    ```

* **Частичный сбор (`gather_subset`)**: Собирайте только необходимые данные.

    ```yaml
    - hosts: all
      gather_subset: min # Минимальный набор: архитектура, дистрибутив
    ```

    Доступные подмножества: `min`, `network`, `hardware`, `virtual`. Можно комбинировать (`min,network`) или исключать (`!hardware`).

### 5. Измерение производительности (Callback-плагины)

Для поиска узких мест и оценки эффекта от оптимизаций используйте callback-плагины.

**Доступные плагины:**

* `timer` — показывает время выполнения каждой задачи
* `profile_tasks` — выводит отсортированный список задач по времени выполнения (в конце)
* `profile_roles` — агрегирует время по ролям

**Включение (ansible-core < 2.13):**

```ini
[defaults]
callback_whitelist = timer, profile_tasks, profile_roles
```

**Включение (ansible-core >= 2.13):**

```ini
[defaults]
callback_plugins = ~/.ansible/plugins/callback:/usr/share/ansible/plugins/callback
```

**Альтернатива через переменную окружения:**

```bash
export ANSIBLE_CALLBACK_PLUGINS="~/.ansible/plugins/callback:/usr/share/ansible/plugins/callback"
ansible-playbook playbook.yml -e "callback_whitelist=timer,profile_tasks"
```

> **Примечание:** В ansible-core 2.13+ `callback_whitelist` заменён на `callback_plugins`. Для временного использования старых плагинов также можно указать `ANSIBLE_CALLBACK_WHITELIST`.

### 6. Оптимизация копирования файлов (`copy` vs `synchronize`)

* **`ansible.builtin.copy`**: Медленный для большого количества файлов.
* **`ansible.builtin.synchronize`**: Обертка над `rsync`, значительно быстрее, так как передает только изменения.

**Когда что использовать**:

* Для копирования большого дерева каталогов без `mitogen` — `synchronize`.
* При использовании `mitogen` — начните с `copy`, так как общая скорость и так будет высокой. Переходите к `synchronize`, только если копирование остается узким местом.

## Практические сценарии

### 1. Последовательное обновление (Rolling Updates)

Для управления порядком выполнения задач на хостах используются `serial` и `throttle`.

* **`serial: <N>`**: Ограничивает выполнение **всего плея** N хостами за раз.

    ```yaml
    - hosts: webservers
      serial: 1 # Выполнять плей по одному хосту за раз
      tasks:
        # ...
    ```

* **`throttle: <N>`**: Ограничивает параллелизм для **одной конкретной задачи**.

    ```yaml
    - name: Restart web server
      ansible.builtin.service:
        name: nginx
        state: restarted
      throttle: 1 # Перезапускать сервис строго по одному
    ```

### 2. Запуск долгих операций (Асинхронные задачи)

Метод позволяет плейбуку не ждать завершения длительных операций, таких как компиляция или бэкап.

* `async: <seconds>`: Максимальное время выполнения задачи в фоне.
* `poll: 0`: "Fire and forget" — запустить и не ждать.

**Пример**:

```yaml
- name: Run long background process
  ansible.builtin.command: /usr/bin/long_running_script.sh
  async: 3600 # Максимум 1 час на выполнение
  poll: 0     # Не ждать завершения
  register: long_task_result

- name: Check status of the long task later
  ansible.builtin.async_status:
    jid: "{{ long_task_result.ansible_job_id }}"
  register: job_status
  until: job_status.finished
  retries: 30 # Проверять 30 раз
  delay: 60   # Каждые 60 секунд
```

## Дополнительная информация

### Плагин Mitogen

**Mitogen** — сторонний плагин, заменяющий транспортный уровень Ansible для ускорения выполнения плейбуков (прирост 1.5–8 раз). Использует одно оптимизированное соединение, передаёт код модулей через STDIN, выполняет задачи в одном долгоживущем Python-процессе.

**Важно (Ansible 12+ / ansible-core 2.19+):** В Ansible 12+ сторонние плагины стратегий объявлены устаревшими. Текущий механизм интеграции Mitogen через strategy plugins может стать неработоспособным. Следите за обновлениями проекта Mitogen.

**Использование:**

1. Установите Mitogen:
   * Через Ansible Galaxy: `ansible-galaxy collection install serverscom.mitogen`
   * Или из репозитория: `pip install mitogen`

2. Настройте `ansible.cfg`:

    ```ini
    [defaults]
    strategy_plugins = ~/.ansible/collections/ansible_collections/serverscom/mitogen/plugins/strategy
    ```

3. Задайте стратегию в плейбуке:

    ```yaml
    - hosts: all
      strategy: mitogen_linear  # или mitogen_free
    ```

### Callback-плагины для профилирования

Для измерения производительности и поиска узких мест используйте callback-плагины:

| Плагин | Описание |
| :--- | :--- |
| `timer` | Время выполнения каждой задачи |
| `profile_tasks` | Отсортированный список задач по времени (в конце выполнения) |
| `profile_roles` | Агрегация времени по ролям |
| `ansible.builtin.default` (с `result_format=yaml`) | YAML-вывод (заменяет устаревший `community.general.yaml`) |

**Включение в `ansible.cfg`** (ansible-core < 2.13):

```ini
[defaults]
callback_whitelist = timer, profile_tasks, profile_roles
```

**Включение в `ansible.cfg`** (ansible-core >= 2.13):

```ini
[defaults]
callback_plugins = ~/.ansible/plugins/callback:/usr/share/ansible/plugins/callback
```

**Включение через переменную окружения:**

```bash
export ANSIBLE_CALLBACK_PLUGINS="~/.ansible/plugins/callback:/usr/share/ansible/plugins/callback"
ansible-playbook playbook.yml -e "callback_whitelist=timer,profile_tasks"
```

### Связанные документы

* [Тестирование ролей с Molecule](ansible_testing_with_molecule.md) — автоматизированное тестирование
* [Сборка контейнеров через Ansible](ansible_buildah_image_building.md) — Ansible-bender
* [Pull-режим](ansible_pull.md) — альтернативный способ управления
* [SSH-клиент: мультиплексирование](../Linux/Security/ssh/ssh_client_config.md) — подробная настройка SSH
