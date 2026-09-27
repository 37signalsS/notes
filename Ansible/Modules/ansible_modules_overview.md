# Ansible: Обзор модулей

## Определения

**Модули Ansible** — это автономные единицы кода (плагины), предназначенные для выполнения конкретных задач на управляемых хостах. В отличие от плагинов, которые работают непосредственно на контрольном узле, модули копируются на целевой хост, выполняются там и возвращают результат в формате JSON.

**Идемпотентность** — ключевое свойство модулей, гарантирующее достижение целевого состояния без лишних действий при повторных запусках. См. подробный разбор в **[Идемпотентность](../../Concepts/idempotency.md)**.

**FQCN (Fully Qualified Collection Name)** — полное имя модуля, включающее пространство имен и коллекцию (например, `ansible.builtin.copy`). Использование FQCN является обязательным стандартом в современном Ansible (с версии 2.10) для предотвращения конфликтов имен и обеспечения предсказуемости выполнения кода.

**ansible-core** — минимальный пакет, содержащий движок Ansible, основные CLI-утилиты и набор базовых модулей (`ansible.builtin`). Дополнительные возможности расширяются через **Коллекции** (Collections).

### Требования к окружению

Начиная с **ansible-core 2.17**, поддержка Python 2.7 и 3.6 на управляемых узлах прекращена. Для работы современных модулей требуется **Python 3.7+** (ansible-core 2.18+ требует Python 3.8+). Для Windows-хостов требуются соответствующие версии PowerShell и .NET.

## Основные концепции

### Жизненный цикл выполнения модуля
1.  **Подготовка**: Узел управления упаковывает код модуля, его аргументы и зависимости (`module_utils`) в zip-архив.
2.  **Передача**: Архив копируется на управляемый узел через настроенный транспорт (обычно SSH + SFTP/SCP) во временную директорию (по умолчанию `~/.ansible/tmp/`).
3.  **Исполнение**: Код распаковывается и запускается в интерпретаторе Python (или PowerShell для Windows) на целевом узле.
4.  **Ответ**: Модуль выводит JSON-структуру в `stdout`.
5.  **Очистка**: Временные файлы удаляются автоматически, если выполнение завершилось успешно (и не включен режим отладки).

### Общие возвращаемые значения (JSON Response)
Каждый модуль возвращает стандартный набор ключей, которые можно использовать в `register` и `when`:
- `changed`: Булево значение, указывает, были ли внесены изменения в систему.
- `failed`: Булево значение, указывает на ошибку выполнения.
- `msg`: Строка с пояснением результата или ошибки.
- `rc`: Код возврата процесса (для модулей выполнения команд).
- `results`: Список результатов, если задача выполнялась в цикле (`loop`).
- `invocation`: Информация о том, с какими аргументами был вызван модуль (скрывается при `no_log: true`).

### Желаемое состояние (параметр state)
Большинство декларативных модулей используют параметр `state` для описания целевого состояния:
- `present` / `installed`: Ресурс должен существовать.
- `absent` / `removed`: Ресурс должен быть удален.
- `latest`: Установка или обновление до последней доступной версии.
- `started` / `stopped`: Управление состоянием демонов.
- `merged` / `replaced` / `overridden`: Специфичные состояния для сетевых и инфраструктурных модулей.

### Асинхронное выполнение
Для длительных задач (например, миграция БД или установка тяжелого ПО) используется `async` и `poll`:
- `async`: Максимальное время выполнения задачи в секундах.
- `poll`: Частота опроса состояния задачи. Если `poll: 0`, Ansible запускает задачу и сразу переходит к следующей («fire and forget»).

```yaml
- name: "Длительная операция в фоне"
  ansible.builtin.command: /usr/bin/long_running_script.sh
  async: 3600
  poll: 0
  register: job_result
```

### Мониторинг фоновых задач (async_status)
Для отслеживания состояния асинхронных задач используется модуль `ansible.builtin.async_status`. Он позволяет проверять, завершилась ли задача, и получить её результат.

```yaml
- name: "Проверка статуса фоновой задачи"
  ansible.builtin.async_status:
    jid: "{{ job_result.ansible_job_id }}"
  register: job_status
  until: job_status.finished
  retries: 30
  delay: 10
```

### Директивы управления выполнением
- `become`: Повышение привилегий (sudo/doas).
- `no_log`: Скрытие чувствительных данных (пароли, ключи) из вывода и логов.
- `ignore_errors`: Продолжение выполнения плейбука при ошибке конкретного модуля.
- `check_mode`: Возможность запретить выполнение модуля в режиме dry-run (`check_mode: false`).
- `delegate_to`: Выполнение модуля на другом хосте (например, на localhost или балансировщике).

### Поддержка check_mode и diff
Многие модули поддерживают режимы диагностики:
- **check_mode** (`--check`): Показывает, какие изменения были бы внесены, не применяя их на практике.
- **diff** (`--diff`): Показывает разницу между текущим и желаемым состоянием (особенно полезно для текстовых файлов).

```yaml
- name: "Демонстрация check_mode и diff"
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    validate: '/usr/sbin/nginx -t -c %s'
  check_mode: true
  diff: true
```

### Общие параметры модулей
Помимо `state`, большинство модулей поддерживают следующие стандартные параметры:
- **`force`**: Принудительное выполнение операции (перезапись файлов, переустановка пакетов).
- **`backup`**: Создание резервной копии перед изменением (для файлов и конфигураций).
- **`owner` / `group` / `mode`**: Установка владельца, группы и прав доступа (для файловых модулей).
- **`creates` / `removes`**: Обеспечение идемпотентности через проверку существования файлов.
- **`timeout`**: Тайм-аут выполнения операции (для сетевых и долгих операций).

## Практические сценарии

### Использование модулей в циклах
При выполнении в цикле Ansible вызывает модуль для каждого элемента последовательно.

```yaml
- name: "Создание нескольких директорий"
  ansible.builtin.file:
    path: "{{ item }}"
    state: directory
  loop:
    - /var/www/app1
    - /var/www/app2
  register: dir_creation
```

### Глубокая отладка модулей
Если модуль ведет себя непредсказуемо, можно сохранить временные файлы на удаленном узле для ручного анализа.

1.  Установите переменную окружения: `export ANSIBLE_KEEP_REMOTE_FILES=1`.
2.  Запустите плейбук с высокой вербальностью: `ansible-playbook site.yml -vvv`.
3.  Ansible выведет путь к скрипту на удаленном хосте, который можно запустить вручную:
    `python /home/user/.ansible/tmp/ansible-tmp-XXX/AnsiballZ_module_name.py explode`.
4.  В директории `debug_dir` появится исходный код модуля для анализа.

### Категории модулей по назначению

Ниже представлены основные группы модулей и ссылки на их подробное описание в базе знаний:

1.  **[Управление пакетами](ansible_package_management_modules.md)**: `package`, `apt`, `dnf`, `pip`, `npm`.
2.  **[Управление файлами](ansible_file_management_modules.md)**: `copy`, `template`, `file`, `lineinfile`, `blockinfile`.
3.  **[Синхронизация файлов](ansible_file_synchronization_modules.md)**: `synchronize` (на базе rsync), `fetch`.
4.  **[Управление службами и системой](ansible_service_and_system_config_modules.md)**: `systemd`, `service`, `hostname`, `cron`, `reboot`.
5.  **[Пользователи и безопасность](ansible_security_and_user_management_modules.md)**: `user`, `group`, `authorized_key`, `iptables`.
6.  **[Выполнение команд](ansible_command_execution_modules.md)**: `command`, `shell`, `raw`, `script`.
7.  **[PKI и сертификаты](ansible_pki_certificates_modules.md)**: `community.crypto.openssl_privatekey`, `openssl_csr`, `x509_certificate`, `x509_certificate_info`, `openssl_pkcs12`, `certificate_complete_chain`.
8.  **[Управление контейнерами](ansible_container_modules.md)**: `community.docker.docker_container`, `docker_image`, `docker_network`, `docker_volume`, `containers.podman.podman_container`, `podman_image`, `podman_generate_systemd`.
9.  **[Управление базами данных и кэшем](ansible_database_modules.md)**: `community.redis.redis`, `community.postgresql.postgresql_db`, `ansible.mysql.mysql_db`, `community.mongodb.mongodb_user`.
10. **[Управление секретами](ansible_vault_modules.md)**: `community.hashi_vault.hashi_vault`, `hashi_vault_login`, `hashi_vault_secret`.
11. **[Управление сетевым оборудованием](ansible_network_device_modules.md)**: `cisco.ios.ios_vlans`, `juniperdevices.junos.junos_interfaces`, `arista.eos.eos_interfaces`.
12. **[Управление сетевой конфигурацией Linux](ansible_network_configuration_modules.md)**: `community.general.nmcli`, `ansible.posix.sysctl`, Netplan, bonding, VLAN, маршрутизация.
13. **[Управление мониторингом](ansible_monitoring_modules.md)**: `community.zabbix.zabbix_host`, `datadog.dd.datadog_monitor`, `netways.icinga.icinga_host`.
14. **[Управление DNS](ansible_dns_modules.md)**: `community.general.nsupdate`, управление зонами через `template`, PowerDNS API через `uri`.
15. **[Управление выполнением и контролем потока](ansible_control_flow_modules.md)**: `include_tasks`, `import_role`, `add_host`, `group_by`, `meta`, `loop_control`, `until`/`retries`/`delay`.
16. **[Плагины подключения](ansible_connection_plugins.md)**: `ssh`, `winrm`, `network_cli`, `httpapi`, `netconf`, `docker`, `podman`.

### Порядок поиска модулей
Ansible ищет модули в следующих местах (в порядке приоритета):
1.  Директория `library/` в корне текущего плейбука.
2.  Внутри роли: `roles/<role_name>/library/`.
3.  В установленных коллекциях.
4.  Пути из переменной `ANSIBLE_LIBRARY` или параметра `library` в `ansible.cfg`.

## Операции и команды
Утилита `ansible-doc` позволяет получать справку без доступа к интернету.

```bash
# Просмотр полной справки и примеров
ansible-doc ansible.builtin.copy

# Вывод краткого шаблона (snippet) для вставки в плейбук
ansible-doc -s ansible.builtin.file

# Список всех доступных модулей
ansible-doc -l
```

### Управление коллекциями (ansible-galaxy)
```bash
# Установка коллекции
ansible-galaxy collection install community.general

# Просмотр установленных коллекций
ansible-galaxy collection list

# Поиск модуля в установленных коллекциях
ansible-galaxy collection list | grep <module_name>
```

### Общие параметры CLI для выполнения плейбуков
```bash
# Проверка без применения изменений
ansible-playbook site.yml --check

# Просмотр различий
ansible-playbook site.yml --diff

# Ограничение выполнения конкретными хостами
ansible-playbook site.yml --limit webservers

# Продолжение выполнения с определенной задачи
ansible-playbook site.yml --start-at-task "Install packages"
```

## Устранение неполадок

### Типичные ошибки модулей

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `MODULE NOT FOUND` | Модуль не найден или коллекция не установлена | Проверьте FQCN, установите нужную коллекцию через `ansible-galaxy collection install` |
| `Permission denied` | Недостаточно прав на управляемом узле | Используйте `become: yes` или настройте sudo |
| `No such file or directory` | Указанный путь не существует | Проверьте путь или используйте параметр `creates` для идемпотентности |
| `Unexpected failure` | Внутренняя ошибка модуля | Обновите ansible-core и коллекции, проверьте совместимость версий |
| `Timeout` | Операция превысила лимит времени | Увеличьте `timeout` или используйте `async`/`poll` |
| `Python version mismatch` | Неподдерживаемая версия Python | Установите Python 3.7+ (3.8+ для ansible-core 2.18+) |
| `Connection closed` | Разрыв SSH-соединения | Проверьте стабильность сети, увеличьте `timeout` в `ansible.cfg` |
| `Failed to parse module arguments` | Ошибка в синтаксисе параметров | Проверьте YAML-синтаксис и типы данных параметров |

### Диагностика модулей
```bash
# Проверка доступности модуля
ansible-doc ansible.builtin.copy

# Тестирование подключения к хосту
ansible all -m ping

# Проверка фактов хоста
ansible all -m setup -a "filter=ansible_os*"
```

### Режим отладки
```bash
# Максимальная вербальность
ansible-playbook site.yml -vvvv

# Сохранение временных файлов на удаленном узле
export ANSIBLE_KEEP_REMOTE_FILES=1
ansible-playbook site.yml -vvv
```

## Рекомендации

### Выбор правильного модуля
При выборе модуля следуйте принципу «декларативность вместо императивности»:
- **Используйте специализированные модули** (`apt`, `yum`, `copy`, `template`) вместо `command`/`shell`, когда это возможно.
- **Для команд оболочки** (`command`, `shell`) — только когда нет декларативной альтернативы (уникальные операции, миграции, проверки).
- **Для сетевых устройств** — используйте сетевые модули вместо `raw`/`shell`.

### Обработка ошибок в модулях
Стандартные паттерны обработки ошибок:

```yaml
- name: "Пример обработки ошибок"
  ansible.builtin.command: /usr/bin/risky_operation
  register: result
  ignore_errors: true

- name: "Действия при ошибке"
  ansible.builtin.debug:
    msg: "Операция завершилась с ошибкой: {{ result.stderr }}"
  when: result.rc != 0
```

### Тестирование модулей
Для проверки корректности работы модулей используйте:
- **`--check`**: Режим dry-run для проверки без реальных изменений.
- **`--diff`**: Просмотр изменений перед применением.
- **`register`**: Сохранение результатов для последующей обработки.
- **`assert`**: Проверка ожидаемых значений в плейбуках.

```yaml
- name: "Тестирование с assert"
  ansible.builtin.assert:
    that:
      - result.rc == 0
      - result.stdout | length > 0
    fail_msg: "Операция не выполнена"
    success_msg: "Операция выполнена успешно"
```

### Оптимизация производительности
Для ускорения выполнения плейбуков:
- **Параллелизм**: Используйте `forks` в `ansible.cfg` (по умолчанию 5).
- **Факты**: Отключайте сбор фактов (`gather_facts: false`) если они не нужны.
- **Стратегии**: Используйте `strategy: free` для независимого выполнения хостов.
- **Сборщики**: Используйте `ansible.builtin.package_facts` и `service_facts` вместо многократного вызова `setup`.

### Общие принципы
- Всегда используйте FQCN для модулей.
- Проверяйте идемпотентность модулей перед использованием в production.
- Документируйте нестандартные параметры и assumptions в плейбуках.
- Используйте `no_log: true` для задач с чувствительными данными.

## Дополнительная информация

- **[Основные концепции Ansible](../ansible_core_concepts.md)** — архитектура, сравнение модулей и плагинов.
- **[Антипаттерны Ansible](../ansible_bad_practices.md)** — рекомендации по выбору модулей и избеганию частых ошибок.
- **[Собственные модули Ansible](../ansible_custom_modules.md)** — руководство по разработке на Python.
- **[Официальный индекс всех модулей](https://docs.ansible.com/ansible/latest/collections/all_plugins.html#modules)** (англ.)
