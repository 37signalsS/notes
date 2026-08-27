# Ansible: Модули синхронизации файлов

## Определения

**Модули синхронизации файлов** — это группа специализированных инструментов Ansible (преимущественно из коллекции `ansible.posix`), предназначенных для эффективной передачи больших объемов данных и зеркалирования директорий между узлами.

**ansible.posix.synchronize** — основной модуль синхронизации, представляющий собой высокоуровневую обертку над системной утилитой **rsync**. Он оптимизирует передачу, отправляя только измененные части файлов (дельта-алгоритм), что делает его значительно быстрее стандартных средств копирования при работе с большими структурами данных.

**rsync (Remote Sync)** — протокол и утилита для минимизации сетевого трафика путем передачи только дифференциальных изменений (диффов) файлов.

**FQCN (Fully Qualified Collection Name)** — полное имя модуля (`ansible.posix.synchronize`). Использование FQCN обязательно, так как модуль поставляется в составе коллекции `ansible.posix`, а не в ядре `ansible-core`.

### Возвращаемые данные (Return Values)

Все модули синхронизации возвращают стандартный набор данных:

| Параметр | Тип | Описание |
|----------|-----|----------|
| `stdout` | string | Стандартный вывод команды rsync |
| `stderr` | string | Стандартный поток ошибок |
| `rc` | integer | Код возврата команды (0 = успех) |
| `changed` | boolean | Были ли произведены изменения |
| `cmd` | string | Выполненная команда rsync |
| `delta` | string | Время выполнения |
| `invocation` | dict | Параметры вызова модуля |

## Основные концепции

### Сравнение инструментов передачи данных

| Характеристика | `ansible.builtin.copy` | `ansible.builtin.fetch` | `ansible.posix.synchronize` |
| :--- | :--- | :--- | :--- |
| **Механизм** | SFTP / SCP (Ansible транспорт) | SFTP / SCP (Ansible транспорт) | **rsync** (прямое SSH-соединение) |
| **Направление** | Push (на хост) | Pull (с хоста) | Push и Pull |
| **Директории** | Поддерживает (медленно) | **Не поддерживает** (только файлы) | Поддерживает (очень быстро) |
| **Эффективность** | Передает файлы целиком | Передает файлы целиком | Дельта-копирование (только диффы) |
| **Зависимости** | Python на хосте | Python на хосте | **rsync** на обоих узлах |
| **Сохранение прав** | Да | Нет | Да (полное) |
| **Симлинки** | Копирует как файлы | Копирует как файлы | Сохраняет симлинки |
| **Хардлинки** | Копирует как файлы | Копирует как файлы | Сохраняет хардлинки |
| **Контрольные суммы** | Проверяет | Проверяет | Опциональная проверка |

### Механизм работы и транспорта

В отличие от стандартных модулей Ansible, которые выполняются через `ansible-connection`, `synchronize` запускает локальный процесс `rsync`, который устанавливает **собственное SSH-соединение** с удаленным хостом.

**Ключевые особенности:**
- **Эффективность**: Использование дельта-алгоритмов rsync.
- **SSH Agent Forwarding**: При синхронизации между двумя удаленными серверами (`delegate_to`) требуется проброс SSH-агента, чтобы первый сервер мог авторизоваться на втором.
- **Транспорт**: Модуль открывает отдельное SSH-соединение от имени пользователя, запустившего Ansible плейбук. Это может вызвать проблемы с аутентификацией, если не настроен беспарольный доступ или не используется `use_ssh_args`.
- **Зависимости**: Утилита `rsync` должна быть установлена как на контрольном узле, так и на всех целевых хостах.
- **Делегирование**: По умолчанию синхронизация идет между контрольным узлом и управляемым хостом. С помощью `delegate_to` можно настроить синхронизацию между двумя удаленными серверами (например, с Master на Replica).

### Идемпотентность в synchronize

Модуль `synchronize` поддерживает идемпотентность через:
- **Сравнение контрольных сумм** (параметр `checksum=yes`)
- **Сравнение времени модификации и размера** (по умолчанию)
- **Удаление лишних файлов** (параметр `delete=yes`)
- **Архивный режим** (параметр `archive=yes`) — сохраняет права, владельцев, временные метки

### Критически важные параметры

- **`mode`**: Направление синхронизации.
  - `push` (по умолчанию): С контрольного узла на удаленный хост.
  - `pull`: С удаленного хоста на контрольный узел (удобно для сбора бэкапов).
- **`delete`**: Если `yes`, удаляет в целевой директории файлы, которых нет в источнике. Позволяет поддерживать идентичное зеркало.
- **`archive`**: (по умолчанию `yes`) Включает флаг `-a` в rsync (рекурсия, сохранение прав, владельцев, ссылок и временных меток).
- **`checksum`**: Если `yes`, rsync сравнивает файлы по контрольным суммам, а не по времени модификации и размеру. Надежнее, но нагружает CPU.
- **`rsync_opts`**: Список дополнительных флагов rsync (например, `--exclude`, `--bwlimit`, `--partial`).
- **`rsync_path`**: Позволяет указать путь к бинарному файлу rsync на удаленном хосте или команду для запуска через `sudo` (например, `sudo rsync`).
- **`use_ssh_args`**: Если `yes`, заставляет модуль использовать SSH-настройки из `ansible.cfg` (включая ProxyJump/Bastion и SSH-ключи).
- **`recursive`**: Если `yes`, рекурсивно копирует директории.
- **`compress`**: Если `yes`, включает сжатие данных при передаче.
- **`partial`**: Если `yes`, сохраняет частично переданные файлы для последующей дозагрузки.
- **`whole_file`**: Если `yes`, отключает дельта-алгоритм и передает файлы целиком (полезно для маленьких файлов).
- **`dirs`**: Если `yes`, передает только метаданные директорий (без файлов).
- **`links`**: Если `yes`, копирует симлинки как симлинки.
- **`hard_links`**: Если `yes`, воспроизводит хардлинки.
- **`times`**: Если `yes`, сохраняет временные метки файлов.
- **`owner`**: Если `yes`, сохраняет владельца файла.
- **`group`**: Если `yes`, сохраняет группу файла.
- **`perms`**: Если `yes`, сохраняет права доступа.
- **`executability`**: Если `yes`, сохраняет флаг исполняемости.

### Оптимизация производительности

**Параметры для ускорения передачи:**
- `--bwlimit=KBPS`: Ограничение скорости передачи в КБ/с
- `--partial`: Сохранение частично переданных файлов
- `--progress`: Вывод прогресса передачи
- `--compress`: Сжатие данных при передаче
- `--whole-file`: Отключение дельта-алгоритма для маленьких файлов
- `--append-verify`: Дозагрузка файлов с проверкой контрольной суммы

### Обработка ошибок

**Типичные ошибки и их решение:**

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `rsync: command not found` | rsync не установлен | Установите rsync на обоих узлах |
| `Permission denied (publickey)` | Проблемы с SSH-ключами | Настройте SSH-ключи или ssh-agent |
| `Host key verification failed` | Хост не в known_hosts | Добавьте хост или отключите проверку |
| `rsync error: some files could not be transferred` | Проблемы с правами | Используйте `rsync_path: "sudo rsync"` |
| `Connection refused` | SSH-сервер не запущен | Запустите sshd на целевом хосте |
| `No route to host` | Проблемы с сетью | Проверьте маршрут и файрвол |
| `Broken pipe` | Разрыв соединения | Увеличьте таймауты SSH |
| `Permission denied (MOUNT)` | Проблемы с точкой монтирования | Проверьте права на точку монтирования |

## Практические сценарии

### Зеркалирование статического контента (Push)
Передача дистрибутива с очисткой устаревших файлов и ограничением скорости.

```yaml
- name: "Синхронизация статики веб-сайта"
  ansible.posix.synchronize:
    src: "dist/"
    dest: "/var/www/html/app/"
    delete: yes
    recursive: yes
    rsync_opts:
      - "--exclude=.git"
      - "--exclude=*.log"
      - "--bwlimit=5000" # Ограничение скорости 5 МБ/с
```

### Сбор бэкапов с удаленных хостов (Pull)
Модуль `ansible.builtin.fetch` не умеет скачивать директории. Для этого используется `synchronize` в режиме `pull`.

```yaml
- name: "Выгрузка бэкапов на контрольный узел"
  ansible.posix.synchronize:
    mode: pull
    src: "/var/backups/db/"
    dest: "./storage/backups/{{ inventory_hostname }}/"
    checksum: yes
```

### Синхронизация через Bastion-хост
Использование настроек транспорта Ansible для работы в изолированных сетях.

```yaml
- name: "Передача файлов через SSH Jump"
  ansible.posix.synchronize:
    src: "configs/"
    dest: "/etc/myapp/"
    use_ssh_args: yes
```

### Синхронизация между двумя удаленными серверами
Копирование данных напрямую с Master на Slave с использованием делегирования.

```yaml
- name: "Копирование данных между серверами"
  ansible.posix.synchronize:
    src: "/data/shared/"
    dest: "/data/shared/"
  delegate_to: "master_server"
```
*Примечание: Master должен иметь SSH-доступ к Slave.*

### Работа с правами root через sudo rsync
Используется, когда целевая директория защищена и требует прав суперпользователя.

```yaml
- name: "Синхронизация в защищенную директорию"
  ansible.posix.synchronize:
    src: "secure_data/"
    dest: "/root/data/"
    rsync_path: "sudo rsync"
```

### Восстановление из бэкапа

```yaml
- name: "Восстановление данных из бэкапа"
  ansible.posix.synchronize:
    mode: push
    src: "./backups/{{ inventory_hostname }}/"
    dest: "/var/lib/mysql/"
    delete: no
    rsync_opts:
      - "--exclude=*.sock"
      - "--exclude=*.pid"
  become: yes
  become_user: mysql
```

### Синхронизация лог-файлов

```yaml
- name: "Сбор логов с удаленных серверов"
  ansible.posix.synchronize:
    mode: pull
    src: "/var/log/nginx/"
    dest: "./logs/nginx/{{ inventory_hostname }}/"
    rsync_opts:
      - "--include=access.log"
      - "--include=error.log"
      - "--exclude=*"
    checksum: yes
```

### Синхронизация конфигурационных файлов

```yaml
- name: "Синхронизация конфигурации Nginx"
  ansible.posix.synchronize:
    src: "configs/nginx/"
    dest: "/etc/nginx/"
    delete: yes
    rsync_opts:
      - "--exclude=*.bak"
      - "--exclude=*.swp"
    perms: yes
    owner: yes
    group: yes
  become: yes
  notify: "restart nginx"
```

### Синхронизация с сжатием

```yaml
- name: "Синхронизация с сжатием данных"
  ansible.posix.synchronize:
    src: "large_files/"
    dest: "/data/transfer/"
    compress: yes
    rsync_opts:
      - "--progress"
      - "--partial"
      - "--bwlimit=10000" # 10 МБ/с
```

### Синхронизация с дозагрузкой прерванных файлов

```yaml
- name: "Дозагрузка прерванных файлов"
  ansible.posix.synchronize:
    src: "big_files/"
    dest: "/data/transfer/"
    partial: yes
    rsync_opts:
      - "--append-verify"
      - "--progress"
```

### Синхронизация с исключением по шаблонам

```yaml
- name: "Синхронизация с исключением временных файлов"
  ansible.posix.synchronize:
    src: "project/"
    dest: "/opt/project/"
    rsync_opts:
      - "--exclude=*.tmp"
      - "--exclude=*.temp"
      - "--exclude=__pycache__"
      - "--exclude=.pytest_cache"
      - "--exclude=node_modules"
      - "--exclude=.git"
```

### Синхронизация с включением только определенных файлов

```yaml
- name: "Синхронизация только конфигурационных файлов"
  ansible.posix.synchronize:
    src: "configs/"
    dest: "/etc/myapp/"
    rsync_opts:
      - "--include=*.conf"
      - "--include=*/"
      - "--exclude=*"
```

### Синхронизация с сохранением хардлинков

```yaml
- name: "Синхронизация с хардлинками"
  ansible.posix.synchronize:
    src: "/data/shared/"
    dest: "/backup/shared/"
    hard_links: yes
    archive: yes
```

### Синхронизация с сохранением симлинков

```yaml
- name: "Синхронизация с симлинками"
  ansible.posix.synchronize:
    src: "/var/www/"
    dest: "/backup/www/"
    links: yes
    archive: yes
    rsync_opts:
      - "--copy-links" # Разворачивает симлинки (копирует файлы)
```

### Синхронизация только метаданных директорий

```yaml
- name: "Создание структуры директорий"
  ansible.posix.synchronize:
    src: "structure/"
    dest: "/opt/structure/"
    dirs: yes
    recursive: yes
```

### Синхронизация с ограничением скорости по расписанию

```yaml
- name: "Ночная синхронизация с ограничением скорости"
  ansible.posix.synchronize:
    src: "/var/log/"
    dest: "./logs/{{ inventory_hostname }}/"
    rsync_opts:
      - "--bwlimit=2000" # 2 МБ/с
      - "--compress"
      - "--delete"
  when: "ansible_date_time.hour | int < 6"
```

### Синхронизация с проверкой после передачи

```yaml
- name: "Синхронизация с проверкой"
  ansible.posix.synchronize:
    src: "dist/"
    dest: "/var/www/html/"
    checksum: yes
    delete: yes
  register: sync_result

- name: "Проверка результатов синхронизации"
  ansible.builtin.debug:
    msg: "Синхронизировано файлов: {{ sync_result.cmd }}"
```

### Синхронизация с логированием

```yaml
- name: "Синхронизация с логированием"
  ansible.posix.synchronize:
    src: "data/"
    dest: "/backup/data/"
    rsync_opts:
      - "--stats"
      - "--itemize-changes"
  register: sync_log

- name: "Вывод статистики синхронизации"
  ansible.builtin.debug:
    var: sync_log.stdout_lines
```

### Синхронизация Docker-томов

```yaml
- name: "Синхронизация Docker-данных"
  ansible.posix.synchronize:
    src: "/var/lib/docker/volumes/{{ item }}/_data/"
    dest: "./docker-backups/{{ item }}/"
    mode: pull
    rsync_opts:
      - "--exclude=*.sock"
      - "--exclude=*.pid"
  loop:
    - postgres_data
    - redis_data
    - app_data
```

### Синхронизация Kubernetes-манифестов

```yaml
- name: "Синхронизация манифестов Kubernetes"
  ansible.posix.synchronize:
    src: "k8s/"
    dest: "/etc/kubernetes/manifests/"
    delete: yes
    rsync_opts:
      - "--exclude=*.bak"
      - "--exclude=*.tmp"
  notify: "restart kubelet"
```

### Синхронизация с делегированием через промежуточный хост

```yaml
- name: "Синхронизация через промежуточный хост"
  ansible.posix.synchronize:
    src: "/data/shared/"
    dest: "/data/shared/"
  delegate_to: "{{ item }}"
  loop:
    - proxy_server
    - backup_server
```

### Синхронизация с условием по хосту

```yaml
- name: "Синхронизация только для веб-серверов"
  ansible.posix.synchronize:
    src: "web_content/"
    dest: "/var/www/html/"
    delete: yes
  when: "'webservers' in group_names"

- name: "Синхронизация только для серверов БД"
  ansible.posix.synchronize:
    src: "db_backups/"
    dest: "/var/backups/mysql/"
    mode: pull
  when: "'dbservers' in group_names"
```

### Синхронизация с параллельной обработкой

```yaml
- name: "Параллельная синхронизация на несколько хостов"
  ansible.posix.synchronize:
    src: "app/"
    dest: "/opt/app/"
    delete: yes
  async: 300
  poll: 0
  register: sync_jobs

- name: "Ожидание завершения синхронизации"
  ansible.builtin.async_status:
    jid: "{{ item.ansible_job_id }}"
  loop: "{{ sync_jobs.results }}"
  register: async_final
  until: async_final.finished
  retries: 60
  delay: 10
```

### Синхронизация с откатом при ошибке

```yaml
- name: "Синхронизация с бэкапом перед обновлением"
  block:
    - name: "Создание бэкапа текущей версии"
      ansible.posix.synchronize:
        mode: pull
        src: "/var/www/html/"
        dest: "./backups/pre_update/{{ ansible_date_time.iso8601_basic_short }}/"
        rsync_opts:
          - "--exclude=*.log"

    - name: "Синхронизация новой версии"
      ansible.posix.synchronize:
        src: "dist/"
        dest: "/var/www/html/"
        delete: yes
        rsync_opts:
          - "--exclude=*.log"

  rescue:
    - name: "Откат к предыдущей версии"
      ansible.posix.synchronize:
        src: "./backups/pre_update/latest/"
        dest: "/var/www/html/"
        delete: yes
```

## Устранение неполадок

- **"rsync command not found"**: Проверьте наличие пакета `rsync` на ОБОИХ узлах.
- **"Permission denied (publickey)"**: `synchronize` не использует пароли из `ansible_ssh_pass`. Требуется настройка SSH-ключей или `ssh-agent`.
- **"Host key verification failed"**: Возникает при первом подключении. Добавьте хост в `known_hosts` или установите `host_key_checking = False` в `ansible.cfg`.
- **Проблемы с sudo**: Если используется `rsync_path: "sudo rsync"`, убедитесь, что в `/etc/sudoers` на хосте отключена опция `requiretty`.
- **"rsync: connection unexpectedly closed"**: Увеличьте таймаут SSH через `ansible_ssh_common_args`.
- **"rsync: error: some files could not be transferred"**: Проверьте права доступа к файлам и директориям.
- **Медленная синхронизация**: Используйте `--compress`, `--bwlimit` и `--whole-file` для оптимизации.
- **Потеря данных при синхронизации**: Всегда тестируйте с `--dry-run` перед реальной синхронизацией.

## Оптимизация производительности

### Рекомендации для больших объемов данных

1. **Используйте `--whole-file`** для маленьких файлов (< 1 МБ)
2. **Включайте сжатие** (`compress: yes`) для текстовых файлов
3. **Ограничивайте скорость** (`--bwlimit`) в生产 средах
4. **Используйте `--partial`** для ненадежных соединений
5. **Настраивайте SSH-опции** для увеличения таймаутов

### Мониторинг синхронизации

```yaml
- name: "Синхронизация с мониторингом"
  ansible.posix.synchronize:
    src: "data/"
    dest: "/backup/data/"
    rsync_opts:
      - "--stats"
      - "--itemize-changes"
      - "--progress"
  register: sync_result

- name: "Логирование результатов"
  ansible.builtin.lineinfile:
    path: "/var/log/sync.log"
    line: "{{ ansible_date_time.iso8601 }}: {{ sync_result.stdout_lines }}"
    create: yes
```

## Дополнительная информация

- **[rsync — справочник алгоритмов](../../Linux/SystemAdministration/rsync.md)** — подробное описание флагов утилиты.
- **[Обзор модулей Ansible](ansible_modules_overview.md)** — выбор правильного инструмента управления файлами.
- **[Оптимизация производительности](../ansible_performance_tuning.md)** — ускорение передачи в крупных инфраструктурах.
- **[Основные концепции Ansible](../ansible_core_concepts.md)** — архитектура и идемпотентность.
- **[Модули управления файлами](ansible_file_management_modules.md)** — `copy`, `template`, `file`, `stat`.
- **[Безопасность в Ansible](../ansible_security_best_practices.md)** — управление SSH-ключами и секретами.
- **[Тестирование с Molecule](../ansible_testing_with_molecule.md)** — проверка кода автоматизации.
