# Ansible: Модули синхронизации файлов

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **ansible-core** | 2.15+ | 2.21+ |
| **Python** (control node) | 3.12+ | 3.14 |
| **Python** (managed node) | 3.9+ | 3.12+ |
| **rsync** (control + managed) | 3.1+ | 3.2+ |
| **openssh-server** (целевые хосты) | 7.0+ | Актуальная LTS |
| **sudo** (целевые хосты) | 1.8+ | Актуальная LTS |

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.x]

rsync --version | head -1
# → rsync  version 3.2.x ...

ansible all -m ping
```

## Определения

**Модули синхронизации файлов** — группа специализированных инструментов Ansible, предназначенных для эффективной передачи больших объемов данных и зеркалирования директорий между узлами.

**ansible.posix.synchronize** — основной модуль синхронизации, представляющий собой высокоуровневую обертку над системной утилитой **rsync**. Он оптимизирует передачу, отправляя только измененные части файлов (дельта-алгоритм), что делает его значительно быстрее стандартных средств копирования при работе с большими структурами данных.

**rsync (Remote Sync)** — протокол и утилита для минимизации сетевого трафика путем передачи только дифференциальных изменений (диффов) файлов.

**FQCN (Fully Qualified Collection Name)** — полное имя модуля (`ansible.posix.synchronize`). Использование FQCN обязательно, так как модуль поставляется в составе коллекции `ansible.posix`, а не в ядре `ansible-core`.

**Дельта-алгоритм** — механизм rsync, разбивающий файлы на блоки, вычисляющий контрольные суммы и передающий только измененные блоки, а не файлы целиком.

**rsyncd** — демон rsync, слушающий TCP/873 и обслуживающий запросы синхронизации без SSH.

**rrsync (Restricted rsync)** — ограниченная версия rsync, запускаемая через forced command в SSH, которая разрешает только операции синхронизации в рамках заданной директории.

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

### Принцип работы и транспорта

В отличие от стандартных модулей Ansible, которые выполняются через `ansible-connection`, `synchronize` запускает локальный процесс `rsync`, который устанавливает **собственное SSH-соединение** с удаленным хостом.

**Жизненный цикл выполнения:**
```
Задача (Task) → Модуль (Module) → Формирование команды rsync →
Установка SSH-соединения → Дельта-передача → Обработка возвращаемых данных →
Применение идемпотентности → Результат (changed/failed)
```

**Ключевые особенности транспорта:**
- **Эффективность**: Использование дельта-алгоритмов rsync (rolling checksum + xxHash в версии 3.2+).
- **SSH Agent Forwarding**: При синхронизации между двумя удаленными серверами (`delegate_to`) требуется проброс SSH-агента, чтобы первый сервер мог авторизоваться на втором.
- **Транспорт**: Модуль открывает отдельное SSH-соединение от имени пользователя, запустившего Ansible плейбук. Это может вызвать проблемы с аутентификацией, если не настроен беспарольный доступ или не используется `use_ssh_args`.
- **Зависимости**: Утилита `rsync` должна быть установлена как на контрольном узле, так и на всех целевых хостах.
- **Делегирование**: По умолчанию синхронизация идет между контрольным узлом и управляемым хостом. С помощью `delegate_to` можно настроить синхронизацию между двумя удаленными серверами (например, с Primary на Standby).

### Транспортные режимы rsync

**1. Локальный (Local):**
Источник и приемник на одной машине. Дельта-алгоритм работает локально.

```bash
rsync -a /src/ /dst/
```

**2. Удалённая оболочка (Remote Shell):**
Использует SSH или RSH для создания канала. Режим по умолчанию при указании `user@host:`.

```bash
rsync -avz -e ssh /src/ user@host:/dst/
# → Ожидаемый вывод:
# sending incremental file list
# ./
# file1.txt
# sent 1,024 bytes  received 42 bytes  2,132.00 bytes/sec
# total size is 2,048  speedup is 1.92
```

**3. Демон (Daemon):**
Подключение к rsyncd через собственный протокол (TCP/873). Не требует SSH, но требует отдельной настройки демона.

```bash
rsync -av /src/ backup_user@host::backup
```

### Идемпотентность в synchronize

Модуль `synchronize` поддерживает идемпотентность через:
- **Сравнение контрольных сумм** (параметр `checksum=yes`) — надежнее, но нагружает CPU.
- **Сравнение времени модификации и размера** (по умолчанию) — быстро, но может пропустить изменения при некорректных метках времени.
- **Удаление лишних файлов** (параметр `delete=yes`) — поддерживает идентичное зеркало.
- **Архивный режим** (параметр `archive=yes`) — сохраняет права, владельцев, временные метки, симлинки, хардлинки.

**Важно:** Идемпотентность обеспечивается на уровне rsync, а не Ansible. Модуль всегда возвращает `changed: true`, если rsync передал хотя бы один файл. Для детального контроля используйте `--dry-run` в `rsync_opts`.

### Привилегированный доступ (become)

Для синхронизации в защищенные директории (например, `/root/`, `/etc/`, `/var/lib/`) требуется root-доступ. Используйте `become: yes` или `rsync_path: "sudo rsync"`.

```yaml
- name: "Синхронизация в защищенную директорию"
  ansible.posix.synchronize:
    src: "secure_data/"
    dest: "/root/data/"
    rsync_path: "sudo rsync"
```

## Установка и настройка

### Установка rsync

**Debian/Ubuntu:**
```bash
ansible all -m ansible.builtin.apt -a "name=rsync state=present" --become
# → changed: [web01] => (item=rsync)
# → changed: [web02] => (item=rsync)
```

**RHEL/CentOS/AlmaLinux:**
```bash
ansible all -m ansible.builtin.dnf -a "name=rsync state=present" --become
# → changed: [db01] => (item=rsync)
```

**SUSE/openSUSE:**
```bash
ansible all -m ansible.builtin.zypper -a "name=rsync state=present" --become
```

**Alpine Linux:**
```bash
ansible all -m ansible.builtin.apk -a "name=rsync state=present" --become
```

### Настройка SSH для синхронизации

**Проверка SSH-доступа:**
```bash
ansible all -m ansible.builtin.shell -a "ssh -o BatchMode=yes -o ConnectTimeout=5 {{ inventory_hostname }} echo OK"
# → ok: [web01] => {
# →     "changed": false,
# →     "stdout": "OK"
# → }
```

**Настройка SSH-агента для делегирования:**
```yaml
- name: "Проверка SSH-ключа между серверами"
  ansible.builtin.shell: ssh -o BatchMode=yes -o ConnectTimeout=5 {{ slave_host }} echo OK
  delegate_to: "{{ master_host }}"
  register: ssh_check
  ignore_errors: yes

- name: "Копирование SSH-ключа на Slave"
  ansible.builtin.copy:
    src: "{{ lookup('env', 'HOME') }}/.ssh/id_rsa.pub"
    dest: "/root/.ssh/authorized_keys"
    mode: '0600'
  delegate_to: "{{ slave_host }}"
  when: ssh_check is failed
```

### Настройка rsyncd (демон режим)

Для синхронизации через демон (полезно в air-gapped средах без SSH):

**Файл `/etc/rsyncd.conf` на сервере-приемнике:**
```bash
# /etc/rsyncd.conf
uid = root
gid = root
use chroot = yes
max connections = 4
log file = /var/log/rsyncd.log
pid file = /var/run/rsyncd.pid
lock file = /var/run/rsyncd.lock
[backup]
    path = /backup
    comment = Backup directory
    read only = no
    auth users = backup_user
    secrets file = /etc/rsyncd.secrets
```

**Запуск демона:**
```bash
# systemctl enable --now rsyncd
# → Created symlink /etc/systemd/system/multi-user.target.wants/rsyncd.service.
# → Started rsyncd.service - fast remote file copy program daemon.
```

## Операции и команды

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
- **`compress`**: Если `yes`, включает сжатие данных при передаче (алгоритмы zstd/lz4 в rsync 3.2+).
- **`partial`**: Если `yes`, сохраняет частично переданные файлы для последующей дозагрузки.
- **`whole_file`**: Если `yes`, отключает дельта-алгоритм и передает файлы целиком (полезно для маленьких файлов < 1 МБ).
- **`dirs`**: Если `yes`, передает только метаданные директорий (без файлов).
- **`links`**: Если `yes`, копирует симлинки как симлинки.
- **`hard_links`**: Если `yes`, воспроизводит хардлинки.
- **`times`**: Если `yes`, сохраняет временные метки файлов.
- **`owner`**: Если `yes`, сохраняет владельца файла.
- **`group`**: Если `yes`, сохраняет группу файла.
- **`perms`**: Если `yes`, сохраняет права доступа.
- **`executability`**: Если `yes`, сохраняет флаг исполняемости.

### Универсальные операции

| Операция | Модуль | Ключевые параметры |
|----------|--------|-------------------|
| Push-синхронизация | `ansible.posix.synchronize` | `mode: push`, `src`, `dest` |
| Pull-синхронизация | `ansible.posix.synchronize` | `mode: pull`, `src`, `dest` |
| Синхронизация через rsyncd | `ansible.posix.synchronize` | `src`, `dest`, `rsync_path` |
| Синхронизация с rrsync | `ansible.posix.synchronize` | `mode: pull`, `rsync_path` |

### Операции для модуля synchronize

| Операция | Пример |
|----------|--------|
| Push с очисткой | `ansible.posix.synchronize: src=dist/ dest=/var/www/html/ delete=yes` |
| Pull с контрольными суммами | `ansible.posix.synchronize: mode=pull src=/var/backups/ dest=./backups/ checksum=yes` |
| Синхронизация через Bastion | `ansible.posix.synchronize: src=configs/ dest=/etc/app/ use_ssh_args=yes` |
| Синхронизация с sudo | `ansible.posix.synchronize: src=data/ dest=/root/data/ rsync_path="sudo rsync"` |
| Ограничение скорости | `ansible.posix.synchronize: src=/var/log/ dest=./logs/ rsync_opts=["--bwlimit=2000"]` |
| Dry-run (проверка) | `ansible.posix.synchronize: src=dist/ dest=/var/www/ rsync_opts=["--dry-run"]` |
| Только метаданные директорий | `ansible.posix.synchronize: src=structure/ dest=/opt/structure/ dirs=yes` |

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
  register: sync_result
  # → changed: [web01] => (item=None)
  # → stdout: sending incremental file list
  # → delta: 2.34 seconds
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
  register: backup_result
  # → changed: [db01] => (item=None)
  # → stdout: sending incremental file list
  # → delta: 15.67 seconds
```

### Синхронизация через Bastion-хост

Использование настроек транспорта Ansible для работы в изолированных сетях.

```yaml
- name: "Передача файлов через SSH Jump"
  ansible.posix.synchronize:
    src: "configs/"
    dest: "/etc/myapp/"
    use_ssh_args: yes
  # → changed: [internal-server] => (item=None)
```

### Синхронизация между двумя удаленными серверами

Копирование данных напрямую с Primary на Standby с использованием делегирования.

```yaml
- name: "Копирование данных между серверами"
  ansible.posix.synchronize:
    src: "/data/shared/"
    dest: "/data/shared/"
  delegate_to: "primary_server"
  # → changed: [standby_server] => (item=None)
  # → Примечание: Primary должен иметь SSH-доступ к Standby.
```

### Работа с правами root через sudo rsync

Используется, когда целевая директория защищена и требует прав суперпользователя.

```yaml
- name: "Синхронизация в защищенную директорию"
  ansible.posix.synchronize:
    src: "secure_data/"
    dest: "/root/data/"
    rsync_path: "sudo rsync"
  # → changed: [web01] => (item=None)
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
  register: restore_result
  # → changed: [db01] => (item=None)
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
  register: log_result
  # → changed: [web01] => (item=None)
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
  # → changed: [web01] => (item=None)
```

### Синхронизация с сжатием данных

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
  register: compress_result
  # → changed: [web01] => (item=None)
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
  # → changed: [web01] => (item=None)
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
  # → changed: [web01] => (item=None)
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
  # → changed: [web01] => (item=None)
```

### Синхронизация с сохранением хардлинков

```yaml
- name: "Синхронизация с хардлинками"
  ansible.posix.synchronize:
    src: "/data/shared/"
    dest: "/backup/shared/"
    hard_links: yes
    archive: yes
  # → changed: [backup01] => (item=None)
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
  # → changed: [backup01] => (item=None)
```

### Синхронизация только метаданных директорий

```yaml
- name: "Создание структуры директорий"
  ansible.posix.synchronize:
    src: "structure/"
    dest: "/opt/structure/"
    dirs: yes
    recursive: yes
  # → changed: [web01] => (item=None)
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
  # → changed: [log-server] => (item=None)
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
  # → changed: [web01] => (item=None)

- name: "Проверка результатов синхронизации"
  ansible.builtin.debug:
    msg: "Синхронизировано: {{ sync_result.cmd }}"
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
  # → changed: [backup01] => (item=None)

- name: "Вывод статистики синхронизации"
  ansible.builtin.debug:
    var: sync_log.stdout_lines
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
  # → changed: [proxy_server] => (item=None)
```

### Синхронизация с условием по хосту

```yaml
- name: "Синхронизация только для веб-серверов"
  ansible.posix.synchronize:
    src: "web_content/"
    dest: "/var/www/html/"
    delete: yes
  when: "'webservers' in group_names"
  # → changed: [web01] => (item=None)

- name: "Синхронизация только для серверов БД"
  ansible.posix.synchronize:
    src: "db_backups/"
    dest: "/var/backups/mysql/"
    mode: pull
  when: "'dbservers' in group_names"
  # → changed: [db01] => (item=None)
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
  # → changed: [web01] => (item=None)

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

### Массовое развертывание с контролем скорости

```yaml
- name: "Развертывание на кластер с batch-стратегией"
  ansible.posix.synchronize:
    src: "release/"
    dest: "/opt/app/"
    delete: yes
  serial: "25%"
  throttle: 10
  # → changed: [web01] => (item=None)
  # → changed: [web02] => (item=None)
```

### Работа в air-gapped средах (без доступа к интернету)

В air-gapped средах rsync работает через прямое SSH-соединение или через rsyncd, что делает его идеальным для изолированных сетей.

```yaml
- name: "Синхронизация в air-gapped среде"
  ansible.posix.synchronize:
    src: "/opt/releases/app-v1.2.3/"
    dest: "/opt/app/"
    delete: yes
    checksum: yes
  delegate_to: "bastion_host"
  # → changed: [internal-app01] => (item=None)
```

### Синхронизация через rsyncd (демон режим)

```yaml
- name: "Синхронизация через демон rsync"
  ansible.posix.synchronize:
    src: "/data/export/"
    dest: "backup_user@backup-server::backup"
    rsync_path: "rsync --config=/etc/rsyncd.conf"
  # → changed: [backup-server] => (item=None)
```

### Синхронизация с rrsync (ограниченный доступ)

```yaml
- name: "Синхронизация через rrsync"
  ansible.posix.synchronize:
    mode: pull
    src: "/var/www/"
    dest: "./backups/{{ inventory_hostname }}/"
    rsync_path: "rrsync /var/www"
  # → changed: [backup-server] => (item=None)
  # → Примечание: rrsync ограничивает доступ только директорией /var/www.
```

### Синхронизация с dry-run для compliance-проверки

```yaml
- name: "Проверка расхождений без изменений"
  ansible.posix.synchronize:
    src: "configs/"
    dest: "/etc/myapp/"
    rsync_opts:
      - "--dry-run"
      - "--itemize-changes"
  register: dry_run_result
  # → changed: [web01] => (item=None)
  # → stdout: >f+++++++++ configs/app.conf
  # → stdout: >f.st...... configs/nginx.conf

- name: "Прерывание при обнаружении расхождений"
  ansible.builtin.assert:
    that:
      - "dry_run_result.stdout == ''"
    fail_msg: "Обнаружены расхождения в конфигурации!"
  when: dry_run_result is success
```

## Диагностика и устранение неисправностей

### Типичные ошибки и их решение

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
| `rsync: connection unexpectedly closed` | Таймаут SSH | Увеличьте таймаут через `ansible_ssh_common_args` |
| `@ERROR: auth failed on module` | Неверные учетные данные rsyncd | Проверьте `secrets file` в `rsyncd.conf` |
| `rsync error: error in rsync protocol data stream` | Несовместимые версии rsync | Обновите rsync на обоих узлах |
| `Partial transfer due to error` | Файлы исчезли во время передачи | Используйте `--partial` и `--ignore-errors` |
| `Mонтаж смонтирован без опции noexec` | Ограничения на точку монтирования | Перемонтируйте с `exec` или используйте другую директорию |

### Паттерны обработки ошибок

```yaml
- name: "Установка rsync на хосты"
  ansible.builtin.package:
    name: rsync
    state: present
  become: yes

- name: "Синхронизация с обработкой ошибок"
  ansible.posix.synchronize:
    src: "data/"
    dest: "/backup/data/"
    delete: yes
  register: sync_result
  until: sync_result is success
  retries: 3
  delay: 10
  become: yes
  # → changed: [web01] => (item=None)
  # → В случае ошибки: повторится 3 раза с задержкой 10 секунд
```

### Диагностика rsync

```bash
# Проверка установленной версии
rsync --version
# → rsync  version 3.2.7  protocol version 31

# Проверка доступности rsyncd
nc -zv backup-server 873
# → Connection to backup-server 873 port [tcp/rsync] succeeded!

# Тестовая синхронизация вручную
rsync -avz --dry-run /src/ user@host:/dst/
# → sending incremental file list
# → ./
# → file1.txt
# → total size is 2,048  speedup is 1.92

# Проверка SSH-соединения
ssh -o BatchMode=yes -o ConnectTimeout=5 user@host "rsync --version"
```

## Рекомендации и оптимизация

### Оптимизация для больших объемов

```yaml
- name: "Оптимизированная синхронизация больших данных"
  ansible.posix.synchronize:
    src: "/data/large_dataset/"
    dest: "/backup/large_dataset/"
    delete: yes
    compress: yes
    whole_file: no
    partial: yes
    rsync_opts:
      - "--bwlimit=10000" # 10 МБ/с
      - "--progress"
      - "--stats"
  register: large_sync
  # → changed: [backup01] => (item=None)
  # → delta: 45.23 seconds
```

### Ограничение bandwidth в production

```yaml
- name: "Синхронизация с ограничением скорости"
  ansible.posix.synchronize:
    src: "/var/log/"
    dest: "./logs/{{ inventory_hostname }}/"
    rsync_opts:
      - "--bwlimit=2000" # 2 МБ/с
      - "--compress"
      - "--delete"
  throttle: 5 # Максимум 5 хостов одновременно
  # → changed: [log01] => (item=None)
```

### Dry-run перед реальной синхронизацией

```yaml
- name: "Проверка расхождений"
  ansible.posix.synchronize:
    src: "configs/"
    dest: "/etc/myapp/"
    rsync_opts:
      - "--dry-run"
      - "--itemize-changes"
  register: dry_run

- name: "Синхронизация только если нет расхождений"
  ansible.posix.synchronize:
    src: "configs/"
    dest: "/etc/myapp/"
    delete: yes
  when: dry_run.stdout == ''
```

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
    line: "{{ ansible_date_time.iso8601 }}: {{ sync_result.stdout }}"
    create: yes
```

### Работа с секретами и безопасность

```yaml
- name: "Синхронизация без логирования чувствительных данных"
  ansible.posix.synchronize:
    src: "secrets/"
    dest: "/etc/app/secrets/"
    delete: yes
  no_log: true
  # → changed: [web01] => (item=None)
  # → Защищает от утечки имен файлов и путей
```

### Использование rrsync для ограничения доступа

```bash
# На сервере-источнике: /root/.ssh/authorized_keys
command="rrsync /var/www/backups",no-agent-forwarding,no-port-forwarding,no-pty,no-user-rc ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQ...
```

```yaml
- name: "Синхронизация через ограниченный доступ"
  ansible.posix.synchronize:
    mode: pull
    src: "/var/www/backups/"
    dest: "./backups/{{ inventory_hostname }}/"
    checksum: yes
  # → rrsync разрешает только чтение директории /var/www/backups
```

## Общие рекомендации

- **Используйте FQCN** для всех модулей (`ansible.posix.synchronize` вместо `synchronize`), чтобы избежать конфликтов с модулями из сторонних коллекций.
- **Предпочитайте `synchronize` вместо `copy`/`fetch`** для директорий и больших объемов данных — дельта-алгоритм rsync значительно быстрее.
- **Используйте `checksum: yes`** для критически важных данных, где время модификации может отличаться от фактического содержимого.
- **Используйте `delete: yes`** только при необходимости точного зеркалирования — это удаляет файлы в целевой директории.
- **Используйте `rsync_opts: ["--dry-run"]`** перед реальной синхронизацией для проверки расхождений.
- **Используйте `retries` и `delay`** для задач синхронизации в средах с нестабильным сетевым соединением.
- **Используйте `compress: yes`** для текстовых файлов через медленные каналы связи.
- **Используйте `whole_file: yes`** для маленьких файлов (< 1 МБ) в локальных сетях — это быстрее, чем дельта-алгоритм.
- **Используйте `rsync_path: "sudo rsync"`** вместо `become: yes` для синхронизации в защищенные директории — это более надежно.
- **Используйте `use_ssh_args: yes`** при работе через Bastion-хост или с нестандартными SSH-настройками.
- **Используйте `rrsync`** для ограничения доступа к директориям через SSH.
- **Используйте `rsyncd`** для высоконагруженных сред или air-gapped сетей без SSH.
- **Никогда не храните секреты в открытом виде** — используйте `no_log: true` и Ansible Vault.
- **Тестируйте с `--dry-run`** перед реальной синхронизацией в production.
- **Используйте `async`/`poll`** для длительных синхронизаций на большом количестве хостов.
- **Настраивайте SSH-ключи** для беспарольного доступа между серверами при использовании `delegate_to`.

## Дополнительная информация

- **[rsync — справочник алгоритмов](../../Linux/SystemAdministration/rsync.md)** — подробное описание флагов утилиты.
- **[Обзор модулей Ansible](ansible_modules_overview.md)** — выбор правильного инструмента управления файлами.
- **[Основные концепции Ansible](../ansible_core_concepts.md)** — архитектура и идемпотентность.
- **[Модули управления файлами](ansible_file_management_modules.md)** — `copy`, `template`, `file`, `stat`.
- **[Безопасность в Ansible](../ansible_security_best_practices.md)** — управление SSH-ключами и секретами.
- **[Тестирование с Molecule](../ansible_testing_with_molecule.md)** — проверка кода автоматизации.
