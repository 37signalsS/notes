# Ansible: Модули управления службами и системой

## Определения

**Модули управления службами и системой** — это группа специализированных декларативных инструментов Ansible (преимущественно `ansible.builtin` и `ansible.posix`), предназначенных для администрирования жизненного цикла сервисов, тонкой настройки ядра Linux, управления системными ресурсами, лимитами и региональными параметрами.

Эти модули реализуют декларативный подход: пользователь описывает желаемое конечное состояние (например, «служба должна быть запущена»), а Ansible определяет необходимые действия для его достижения, обеспечивая идемпотентность.

**FQCN (Fully Qualified Collection Name)** — полное имя модуля, включающее пространство имен и коллекцию (например, `ansible.builtin.systemd`). Использование FQCN является обязательным стандартом для предотвращения конфликтов имен и обеспечения предсказуемости выполнения во всех современных версиях Ansible.

## Основные концепции

### Управление жизненным циклом служб

1.  **`ansible.builtin.service`**: Модуль-абстракция, работающий через системный менеджер инициализации по умолчанию. Автоматически определяет систему (systemd, SysVinit, OpenRC). Рекомендуется для обеспечения кроссплатформенности ролей.
2.  **`ansible.builtin.systemd`**: Специализированный модуль для систем с systemd. Поддерживает продвинутые функции:
    *   **`daemon_reload`**: Перечитывает конфигурацию systemd с диска. Необходимо вызывать после изменения unit-файлов.
    *   **`daemon_reexec`**: Полный перезапуск самого процесса systemd (актуально при обновлении пакета systemd).
    *   **`scope`**: Позволяет управлять юнитами на уровне системы (`system`) или пользователя (`user`). При использовании `user` задачи обычно выполняются без `become: true`.
    *   **`masked`**: Состояние, полностью блокирующее возможность запуска службы (даже вручную или по зависимости).
3.  **`ansible.builtin.service_facts`**: Сбор состояния всех известных сервисов в переменную `ansible_facts.services`. Позволяет строить сложную логику проверки работоспособности инфраструктуры через условия `when`.

### Возвращаемые данные (Return Values)

Модули управления службами возвращают стандартный набор данных:

| Параметр | Тип | Описание |
|----------|-----|----------|
| `name` | string | Имя управляемого ресурса |
| `state` | string | Текущее состояние ресурса |
| `changed` | boolean | Были ли произведены изменения |
| `enabled` | boolean | Включена ли служба в автозагрузку |
| `status` | dict | Детальная информация о состоянии |

### Настройка ресурсов и ядра Linux

*   **`ansible.posix.sysctl`**: Управление параметрами ядра через интерфейс `/proc/sys`.
    *   **`sysctl_file`**: Позволяет сохранять настройки в отдельные файлы (например, `/etc/sysctl.d/99-performance.conf`).
    *   **`reload`**: Применяет параметры немедленно (`sysctl -p`).
*   **`ansible.builtin.modprobe`**: Управление модулями ядра (загрузка и выгрузка). Позволяет декларативно гарантировать наличие необходимых драйверов или расширений ядра.
*   **`ansible.builtin.pam_limits`**: Настройка лимитов ресурсов (nofile, nproc) в `/etc/security/limits.conf`.
    *   **`limit_type`**: `soft` (предупреждение), `hard` (жесткий запрет) или `-` (оба одновременно).
*   **`ansible.posix.selinux`**: Управление режимами работы SELinux (`enforcing`, `permissive`, `disabled`). Важно помнить, что переход из `disabled` в `enforcing` требует перезагрузки и перемаркировки файловой системы.

### Управление пользователями и группами

*   **`ansible.builtin.user`**: Создание, модификация, блокировка и удаление пользователей. Управление домашними директориями, оболочками (shell), хешированными паролями, сроками их действия и автоматической генерацией SSH-ключей.
*   **`ansible.builtin.group`**: Управление системными группами и их GID.

### Управление хранилищем и сетевой безопасностью

*   **`ansible.builtin.mount`**: Декларативное управление точками монтирования в `/etc/fstab`.
    *   **Состояния (`state`)**:
        *   `mounted`: Добавление в `fstab` и немедленное монтирование.
        *   `unmounted`: Размонтирование, но сохранение записи в `fstab`.
        *   `present`: Только добавление записи в `fstab`.
        *   `absent`: Размонтирование и удаление записи из `fstab`.
*   **`ansible.posix.firewalld` / `community.general.ufw`**: Высокоуровневое управление правилами брандмауэра. Для `firewalld` критично использовать `permanent: true` и `immediate: true` для синхронизации текущего и сохраненного состояний.

### Региональные параметры и время

*   **`ansible.builtin.hostname`**: Установка статического имени хоста.
*   **`ansible.builtin.timezone`**: Настройка системного часового пояса.
*   **`community.general.locale_gen`**: Генерация и настройка системных локалей для поддержки корректной кодировки и региональных стандартов.

### Системное планирование и обслуживание

*   **`ansible.builtin.cron`**: Управление заданиями в планировщике.
    *   **`cron_file`**: Позволяет создавать отдельные файлы в `/etc/cron.d/` вместо редактирования общего `crontab`. Это упрощает управление и предотвращает конфликты при автоматизации.
*   **`ansible.builtin.reboot`**: Модуль для безопасной перезагрузки. Дожидается доступности SSH-порта (или другого условия через `test_command`, например `whoami` или проверку доступности API) перед продолжением плейбука.

### Модули проверки и отладки

*   **`ansible.builtin.ping`**: Проверка доступности управляемых хостов и работоспособности Python на них.
*   **`ansible.builtin.setup`**: Сбор системных фактов (IP-адреса, ОС, архитектура CPU, смонтированные диски). Данные доступны через `ansible_facts`.
*   **`ansible.builtin.assert`**: Прекращает выполнение, если условие не выполняется ("fail-fast" проверки).
*   **`ansible.builtin.fail`**: Принудительное завершение задачи с сообщением об ошибке.
*   **`ansible.builtin.debug`**: Вывод переменных или сообщений для отладки.
*   **`ansible.builtin.set_fact`**: Установка переменных во время выполнения плейбука.
*   **`ansible.builtin.wait_for`**: Ожидание наступления определенного условия (открытие порта, наличие файла, завершение процесса).
*   **`ansible.builtin.meta`**: Управление выполнением плейбука (flush_handlers, end_play, end_host).
*   **`ansible.builtin.get_url`**: Загрузка файлов по HTTP/HTTPS/FTP на управляемый хост.
*   **`ansible.builtin.uri`**: Выполнение HTTP/HTTPS запросов и проверка ответов.

### Оптимизация производительности

**Параметры для ускорения работы:**
- Используйте `ansible.builtin.service` вместо `ansible.builtin.systemd` для кроссплатформенности
- Кэшируйте факты с помощью `ansible.builtin.set_fact` для повторного использования
- Ограничивайте сбор фактов через `gather_facts: no` и `ansible.builtin.setup` only when needed
- Используйте `ansible.builtin.wait_for` вместо циклов ожидания

### Обработка ошибок

**Типичные ошибки и их решение:**

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `Failed to start service` | Нет прав или зависимости | Используйте `become: yes` и проверьте зависимости |
| `Unit not found` | Неправильное имя unit-файла | Проверьте имя через `systemctl list-units` |
| `Access denied` | Нет прав на изменение | Используйте `become: yes` |
| `No such file or directory` | Отсутствует конфигурационный файл | Создайте файл или используйте `ansible.builtin.template` |
| `Invalid parameter` | Неправильный синтаксис | Проверьте документацию модуля |
| `Connection refused` | Сервис не запущен | Запустите сервис перед выполнением задачи |

## Практические сценарии

### Глубокое управление systemd (User Units)
Управление сервисом, запущенным от имени конкретного пользователя.

```yaml
- name: "Запуск пользовательского агента мониторинга"
  ansible.builtin.systemd:
    name: "user-agent.service"
    state: started
    enabled: true
    scope: user
  become: false # Выполняется в контексте сессии пользователя
```

### Настройка базы данных: лимиты и тюнинг ядра
Комплексная подготовка системы для работы высоконагруженной СУБД (например, PostgreSQL).

```yaml
- name: "Тюнинг виртуальной памяти через sysctl"
  ansible.posix.sysctl:
    name: vm.swappiness
    value: '10'
    state: present
    sysctl_file: /etc/sysctl.d/database_tuning.conf

- name: "Установка лимитов открытых файлов"
  ansible.builtin.pam_limits:
    domain: postgres
    limit_type: "-"
    limit_item: nofile
    value: 524288
```

### Управление монтированием дисков
Использование UUID и различных состояний монтирования для обеспечения стабильности при смене имен устройств.

```yaml
- name: "Монтирование диска с данными по UUID"
  ansible.builtin.mount:
    path: /data
    src: UUID=b312a45c-e23f-4a3d-9f1e-1234567890ab
    fstype: xfs
    opts: defaults,noatime
    state: mounted
```

### Планирование через /etc/cron.d
Использование изолированных файлов для системных задач очистки.

```yaml
- name: "Добавление задачи очистки временных файлов"
  ansible.builtin.cron:
    name: "Daily cleanup"
    minute: "0"
    hour: "3"
    job: "/usr/bin/find /tmp -type f -atime +7 -delete"
    cron_file: "system-cleanup"
    user: root
```

### Кроссплатформенное управление фаерволом
Адаптация правил под разные менеджеры в зависимости от дистрибутива.

```yaml
- name: "Открытие HTTP порта через Firewalld (RHEL)"
  ansible.posix.firewalld:
    port: 80/tcp
    permanent: true
    state: enabled
    immediate: true
  when: ansible_os_family == "RedHat"

- name: "Открытие HTTP порта через UFW (Debian)"
  community.general.ufw:
    rule: allow
    port: '80'
    proto: tcp
  when: ansible_os_family == "Debian"
```

### Безопасная перезагрузка после обновления ядра
Ожидание готовности системы и проверка корректности загрузки. Подробные стратегии условной перезагрузки (Debian vs RHEL) описаны в руководстве **[Patch Management: Умная перезагрузка](../ansible_patch_management.md#умная-перезагрузка-conditional-reboot)**.

```yaml
- name: "Перезагрузка после обновления ядра"
  ansible.builtin.reboot:
    reboot_timeout: 600
    pre_reboot_delay: 10
    test_command: "whoami"
```

### Управление модулями ядра
Гарантированная загрузка модуля для поддержки специфичной файловой системы.

```yaml
- name: "Загрузка модуля ядра XFS"
  ansible.builtin.modprobe:
    name: xfs
    state: present
```

### Управление пользователями и группами

```yaml
- name: "Создание системного пользователя для приложения"
  ansible.builtin.user:
    name: appuser
    system: yes
    shell: /bin/bash
    home: /opt/app
    create_home: yes
    groups: appgroup
    append: yes
    state: present

- name: "Создание групп для приложений"
  ansible.builtin.group:
    name: appgroup
    system: yes
    state: present
```

### Загрузка файлов по URL

```yaml
- name: "Загрузка установочного пакета"
  ansible.builtin.get_url:
    url: "https://example.com/app-v1.0.tar.gz"
    dest: "/tmp/app-v1.0.tar.gz"
    mode: '0644'
    checksum: "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
```

### Выполнение HTTP-запросов и проверка API

```yaml
- name: "Проверка доступности API"
  ansible.builtin.uri:
    url: "http://localhost:8080/health"
    method: GET
    return_content: yes
  register: health_check
  until: health_check.status == 200
  retries: 5
  delay: 10
```

### Проверка доступности сервисов

```yaml
- name: "Ожидание готовности PostgreSQL"
  ansible.builtin.wait_for:
    host: localhost
    port: 5432
    timeout: 60
    state: started
```

### Сбор и использование фактов

```yaml
- name: "Сбор информации о системе"
  ansible.builtin.setup:
    filter: ansible_distribution*

- name: "Вывод информации о дистрибутиве"
  ansible.builtin.debug:
    var: ansible_distribution
```

### Условное выполнение задач

```yaml
- name: "Запуск сервиса только на CentOS"
  ansible.builtin.service:
    name: httpd
    state: started
    enabled: yes
  when: ansible_distribution == "CentOS"

- name: "Запуск сервиса только на Ubuntu"
  ansible.builtin.service:
    name: apache2
    state: started
    enabled: yes
  when: ansible_distribution == "Ubuntu"
```

### Обработка ошибок с assert

```yaml
- name: "Проверка минимальной версии Python"
  ansible.builtin.assert:
    that:
      - ansible.python.version.major >= 3
      - ansible.python.version.minor >= 6
    fail_msg: "Требуется Python 3.6 или выше"
    success_msg: "Версия Python подходит"
```

### Установка переменных во время выполнения

```yaml
- name: "Определение конфигурации на основе ОС"
  ansible.builtin.set_fact:
    package_manager: "{{ 'apt' if ansible_os_family == 'Debian' else 'yum' }}"
    service_name: "{{ 'apache2' if ansible_os_family == 'Debian' else 'httpd' }}"
```

### Управление конфигурацией через шаблоны

```yaml
- name: "Генерация конфигурации Nginx"
  ansible.builtin.template:
    src: templates/nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    owner: root
    group: root
    mode: '0644'
    validate: "nginx -t -c %s"
  notify: "restart nginx"

- name: "Перезапуск Nginx после изменений"
  ansible.builtin.systemd:
    name: nginx
    state: restarted
    daemon_reload: yes
  listen: "restart nginx"
```

### Проверка и восстановление сервисов

```yaml
- name: "Проверка работоспособности сервиса"
  ansible.builtin.uri:
    url: "http://localhost:8080/health"
    method: GET
    status_code: 200
  register: health_check
  ignore_errors: yes

- name: "Восстановление сервиса при сбое"
  ansible.builtin.systemd:
    name: myapp
    state: restarted
  when: health_check is failed
```

### Управление сервисами с зависимостями

```yaml
- name: "Остановка зависимых сервисов"
  ansible.builtin.systemd:
    name: "{{ item }}"
    state: stopped
  loop:
    - nginx
    - php-fpm
    - redis

- name: "Обновление приложения"
  ansible.builtin.copy:
    src: "dist/app.jar"
    dest: "/opt/app/app.jar"
    owner: appuser
    group: appgroup
    mode: '0755'

- name: "Запуск сервисов в правильном порядке"
  ansible.builtin.systemd:
    name: "{{ item }}"
    state: started
    enabled: yes
  loop:
    - redis
    - php-fpm
    - nginx
```

### Каталожные задания через cron

```yaml
- name: "Настройка заданий для мониторинга"
  ansible.builtin.cron:
    name: "Health check"
    minute: "*/5"
    job: "/usr/local/bin/health_check.sh >> /var/log/health.log 2>&1"
    cron_file: "monitoring"
    user: monitor

- name: "Настройка заданий для ротации логов"
  ansible.builtin.cron:
    name: "Log rotation"
    minute: "0"
    hour: "0"
    job: "/usr/sbin/logrotate /etc/logrotate.conf"
    cron_file: "maintenance"
    user: root
```

### Управление SELinux

```yaml
- name: "Включение SELinux в режиме enforcing"
  ansible.posix.selinux:
    policy: targeted
    state: enforcing
  when: ansible_distribution in ["CentOS", "RedHat"]

- name: "Установка контекста SELinux для директории"
  ansible.builtin.command:
    cmd: "chcon -R -t httpd_sys_content_t /var/www/html"
  changed_when: false
```

### Настройка временной зоны и локалей

```yaml
- name: "Установка часового пояса"
  ansible.builtin.timezone:
    name: Europe/Moscow

- name: "Генерация русской локали"
  community.general.locale_gen:
    name: ru_RU.UTF-8
    state: present
```

### Управление сервисами с async

```yaml
- name: "Долгая операция с проверкой статуса"
  ansible.builtin.command:
    cmd: "/opt/app/backup.sh"
  async: 3600
  poll: 0
  register: backup_job

- name: "Ожидание завершения бэкапа"
  ansible.builtin.async_status:
    jid: "{{ backup_job.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 60
  delay: 60
```

### Безопасное управление сервисами

```yaml
- name: "Остановка сервиса для обслуживания"
  ansible.builtin.systemd:
    name: myapp
    state: stopped
  become: yes
  become_user: root
  register: service_stopped

- name: "Выполнение обслуживания"
  ansible.builtin.command:
    cmd: "/opt/app/maintenance.sh"
  when: service_stopped.changed

- name: "Запуск сервиса после обслуживания"
  ansible.builtin.systemd:
    name: myapp
    state: started
    enabled: yes
  become: yes
```

### Использование meta для управления выполнением

```yaml
- name: "Flush handlers перед продолжением"
  ansible.builtin.meta: flush_handlers

- name: "Завершение play на текущем хосте"
  ansible.builtin.meta: end_host
  when: ansible_distribution == "Ubuntu"
```

### Проверка файла и его وجودа

```yaml
- name: "Проверка наличия конфигурационного файла"
  ansible.builtin.stat:
    path: /etc/nginx/nginx.conf
  register: nginx_config

- name: "Создание конфигурационного файла если отсутствует"
  ansible.builtin.template:
    src: templates/nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    owner: root
    group: root
    mode: '0644'
  when: not nginx_config.stat.exists
```

### Ожидание файла или порта

```yaml
- name: "Ожидание создания лог-файла"
  ansible.builtin.wait_for:
    path: /var/log/myapp/app.log
    timeout: 30

- name: "Ожидание закрытия порта перед обновлением"
  ansible.builtin.wait_for:
    port: 8080
    state: stopped
    timeout: 30
```

### Комплексное развертывание с обработкой ошибок

```yaml
- name: "Комплексное развертывание приложения"
  block:
    - name: "Проверка свободного места"
      ansible.builtin.assert:
        that:
          - ansible_mounts | selectattr('mount', 'eq', '/opt') | map(attribute='size_available') | first > 1073741824
        fail_msg: "Недостаточно места на диске /opt"

    - name: "Остановка сервиса"
      ansible.builtin.systemd:
        name: myapp
        state: stopped

    - name: "Бэкап текущей версии"
      ansible.builtin.copy:
        src: "/opt/app/"
        dest: "/opt/backup/{{ ansible_date_time.iso8601_basic_short }}/"
        remote_src: yes

    - name: "Развертывание новой версии"
      ansible.builtin.unarchive:
        src: "app-{{ version }}.tar.gz"
        dest: /opt/app/
        remote_src: yes

    - name: "Запуск миграций"
      ansible.builtin.command:
        cmd: "/opt/app/migrate.sh"
      become: yes
      become_user: appuser

    - name: "Запуск сервиса"
      ansible.builtin.systemd:
        name: myapp
        state: started
        daemon_reload: yes

  rescue:
    - name: "Откат к предыдущей версии"
      ansible.builtin.copy:
        src: "/opt/backup/latest/"
        dest: "/opt/app/"
        remote_src: yes

    - name: "Запуск сервиса после отката"
      ansible.builtin.systemd:
        name: myapp
        state: started
```

## Устранение неполадок

- **"Failed to start service"**: Проверьте права доступа и зависимости. Используйте `become: yes`.
- **"Unit not found"**: Убедитесь, что имя unit-файла корректно. Проверьте через `systemctl list-units`.
- **"Access denied"**: Используйте `become: yes` для выполнения от имени root.
- **"No such file or directory"**: Создайте отсутствующие файлы или директории перед настройкой сервиса.
- **"Invalid parameter"**: Проверьте документацию модуля и синтаксис параметров.
- **"Connection refused"**: Убедитесь, что сервис запущен и слушает нужный порт.
- **"Timeout expired"**: Увеличьте таймауты или проверьте сетевую доступность.
- **"SELinux denied"**: Проверьте контексты SELinux или временно отключите для тестирования.

## Дополнительная информация

- **[systemd: управление службами](../../Linux/Core/systemd/service_management.md)** — архитектура systemd и команды диагностики.
- **[Настройка параметров ядра (sysctl)](../../Linux/Core/kernel/sysctl.md)** — справочник производительности Linux.
- **[Планировщик задач cron](../../Linux/SystemAdministration/cron.md)** — нюансы работы и синтаксис.
- **[Обработчики (Handlers)](../ansible_core_concepts.md#обработчики-и-уведомления)** — стандартный способ перезапуска служб в ответ на изменения конфигурации.
- **[SELinux: основы безопасности](../../Linux/Security/Mechanisms/SELinux.md)** — управление контекстами и режимами.
- **[Основные концепции Ansible](../ansible_core_concepts.md)** — архитектура и идемпотентность.
- **[Модули безопасности](ansible_security_and_user_management_modules.md)** — управление пользователями и правами доступа.
- **[Модули управления файлами](ansible_file_management_modules.md)** — копирование, шаблонизация и управление файлами.
- **[Модули управления пакетами](ansible_package_management_modules.md)** — установка и управление программным обеспечением.
- **[Тестирование с Molecule](../ansible_testing_with_molecule.md)** — проверка кода автоматизации.
- **[Безопасность в Ansible](../ansible_security_best_practices.md)** — управление секретами и привилегиями.
