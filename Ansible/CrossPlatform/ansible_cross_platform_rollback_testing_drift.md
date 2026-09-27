# Кроссплатформенный откат, тестирование и drift detection

## Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия | Примечание |
| :--- | :--- | :--- | :--- |
| **ansible-core** | 2.20+ | 2.21.4+ | 2.22.0 GA в ноябре 2026 |
| **Python** (control node) | 3.11+ | 3.12–3.14 | Для ansible-core 2.21; 2.22 поддерживает 3.13–3.15 |
| **Python** (managed node, POSIX) | 3.9+ | 3.12+ | Для ansible-core 2.21 |
| **PowerShell** (Windows) | 5.1+ | 7.6 LTS | 7.6 LTS — стандарт для 2.21/2.22 (поддержка до Nov 2028) |
| **OpenSSH** | 8.0+ | 10.5+ | 10.5 — актуальный релиз (август 2026) |
| **Molecule** | 24.0+ | 26.8.0+ | Поддерживает только последние 2 мажорные версии Ansible |
| **Docker/Podman** | 20.10+/4.0+ | 24.0+/4.9+ | Драйверы для изолированного тестирования |
| **PyWinRM** | 0.4.0+ | 0.5.0+ | Для WinRM транспорта к Windows |

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.4]

molecule --version
# → molecule 26.8.0 using python 3.12.x

ssh -V
# → OpenSSH_10.5, OpenSSL 3.x

ansible all -m ansible.builtin.setup -a "filter=ansible_os_family*" | head -20
# → "ansible_facts": {"os_family": "Debian"} ...
```

## Определения

- **Rollback (откат)** — возврат системы к предыдущему стабильному состоянию после неудачного деплоя.
- **Configuration snapshot** — сохранение конфигурации перед изменением для возможности отката.
- **Drift detection** — обнаружение несанкционированных изменений конфигурации путем сравнения желаемого и фактического состояния.
- **`block/rescue/always`** — механизм атомарных изменений с откатом внутри плейбука.
- **`delegate_facts`** — привязка фактов, собранных в делегированной задаче, к целевому хосту вместо делегированного.
- **`gather_facts`** — сбор фактов через модуль `ansible.builtin.setup`. По умолчанию `true` в начале каждого плея.
- **`changed_when` / `failed_when`** — переопределение статусов задач для корректной отчетности об изменениях.
- **`meta: clear_host_errors`** — сброс ошибок хоста для повторной попытки.
- **`serial`** — размер батча хостов при поэтапном деплое. Целое число, процентная строка или список.
- **`max_fail_percentage`** — максимальный допустимый процент ошибок в батче перед прерыванием.
- **Blast Radius** — масштаб последствий при сбое деплоя; ограничивается `serial` и `max_fail_percentage`.
- **MTTR (Mean Time To Repair)** — среднее время восстановления после сбоя. Автоматизированный откат снижает MTTR.
- **RTO (Recovery Time Objective)** — максимально допустимое время восстановления после сбоя.
- **RPO (Recovery Point Objective)** — максимально допустимый интервал потери данных, определяющий частоту создания бэкапов.
- **Idempotency** — свойство операции, при котором повторное применение не изменяет результат. Второй запуск роли должен давать `changed=0`.

## Основные концепции

### Стратегии отката в mixed-парках

| Стратегия | Уровень | Механизм | Кроссплатформенные нюансы |
| :--- | :--- | :--- | :--- |
| `block/rescue/always` | Задачи в плейбуке | Автоматический rescue при ошибке | rescue-действия отличаются по ОС |
| Package downgrade | Пакетный менеджер | `apt` reinstall, `dnf downgrade` | Разные команды и флаги |
| Service rollback | Сервисы | Перезапуск предыдущего unit/config | `systemd` vs `launchd` vs Windows Service |
| Blue-green | Инфраструктура | Переключение трафика между окружениями | Требует дублирования окружений |
| Canary + auto-rollback | Деплой | Автоматический откат при ошибке health-check | `serial: 1` + `until` + `block/rescue` |

### block/rescue/always с кроссплатформенным откатом

`block/rescue/always` позволяет реализовать атомарные изменения с автоматическим откатом при ошибке.

```yaml
- name: Атомарное обновление с кроссплатформенным откатом
  block:
    - name: Установка пакета
      ansible.builtin.package:
        name: "{{ pkg_name }}"
        state: present
      notify: Restart Service

    - name: Применение конфигурации
      ansible.builtin.template:
        src: app.conf.j2
        dest: "{{ config_path }}"
      notify: Restart Service

  rescue:
    - name: Откат: удаление пакета (Debian)
      ansible.builtin.apt:
        name: "{{ pkg_name }}"
        state: absent
      when: ansible_facts['os_family'] == 'Debian'

    - name: Откат: откат пакета (RedHat)
      ansible.builtin.dnf:
        name: "{{ pkg_name }}"
        state: downgrade
      when: ansible_facts['os_family'] == 'RedHat'

    - name: Откат: удаление пакета (Windows)
      ansible.windows.win_package:
        path: "{{ pkg_installer_path }}"
        state: absent
      when: ansible_facts['os_family'] == 'Windows'

    - name: Очистка временных файлов (POSIX)
      ansible.builtin.file:
        path: /tmp/install_temp
        state: absent
      when: ansible_facts['system'] != 'Win32NT'

    - name: Очистка временных файлов (Windows)
      ansible.windows.win_file:
        path: C:\Windows\Temp\install_temp
        state: absent
      when: ansible_facts['os_family'] == 'Windows'

  always:
    - name: Уведомление об ошибке
      ansible.builtin.debug:
        msg: "Операция завершилась с ошибкой, выполнен откат на {{ ansible_facts['os_family'] }}"
```

> **Production note:** Используйте `meta: clear_host_errors` в `rescue`, если планируете повторную попытку на том же хосте. `block` можно вкладывать внутрь других `block` для каскадного отката. На Windows `win_package` с `state: absent` удаляет только если знаете точный путь к installer'у — для MSI используйте `product_id`.

### Package downgrade и version lock

Разные ОС используют разные механизмы возврата к предыдущей версии.

| ОС | Установка версии | Downgrade | Lock/Hold |
| :--- | :--- | :--- | :--- |
| Debian/Ubuntu | `apt install pkg=1.2.3-1` | `apt install pkg=1.2.2-1` | `apt-mark hold pkg` |
| RedHat/Fedora | `dnf install pkg-1.2.3-1.el9` | `dnf downgrade pkg-1.2.2-1.el9` | `dnf versionlock add pkg` |
| Alpine | `apk add pkg=1.2.3-r1` | `apk add pkg=1.2.2-r1` | `apk add --no-cache` (нет lock) |
| Windows | `win_package` с `version` | Переустановка старой версии | `win_chocolatey` с `pin: yes` |

```yaml
# Версионирование и откат
- name: Установка конкретной версии
  ansible.builtin.package:
    name: "{{ pkg_name }}"
    version: "{{ pkg_version[ansible_facts['os_family']] }}"
    state: present
  vars:
    pkg_version:
      Debian: "=1.2.3-1"
      RedHat: "1.2.3-1.el9"

- name: Откат на предыдущую версию (Debian)
  ansible.builtin.apt:
    name: "{{ pkg_name }}={{ previous_version }}"
    state: present
  when: ansible_facts['os_family'] == 'Debian'

- name: Откат через downgrade (RedHat)
  ansible.builtin.dnf:
    name: "{{ pkg_name }}-{{ previous_version }}"
    state: downgrade
  when: ansible_facts['os_family'] == 'RedHat'
```

### Drift detection через `--check` mode

Drift detection — периодический запуск плейбуков в `--check` режиме для обнаружения несанкционированных изменений.

```yaml
# drift_detection.yml
- name: Аудит конфигурации
  hosts: all
  gather_facts: true
  tasks:
    - name: Проверка пакетов
      ansible.builtin.package:
        name: "{{ item }}"
        state: present
      loop: "{{ required_packages }}"
      check_mode: true
      diff: true
      register: pkg_drift

    - name: Проверка конфигурационных файлов
      ansible.builtin.template:
        src: "{{ item }}.j2"
        dest: "/etc/{{ item }}"
      loop: "{{ config_files }}"
      check_mode: true
      diff: true
      register: config_drift

    - name: Отчет о дрейфе
      ansible.builtin.debug:
        msg: |
          Дрейф пакетов: {{ pkg_drift.results | selectattr('changed', 'equalto', true) | list | length }}
          Дрейф конфигов: {{ config_drift.results | selectattr('changed', 'equalto', true) | list | length }}
```

```bash
# Запуск drift detection
ansible-playbook drift_detection.yml --check --diff --limit production
# → changed > 0 означает дрейф
```

### Molecule: тестирование ролей на матрице платформ

Molecule — инструмент для тестирования Ansible-ролей на матрице платформ. Подробное руководство: **[Тестирование с Molecule](../ansible_testing_with_molecule.md)**.

```yaml
# molecule/default/molecule.yml
---
driver:
  name: docker

platforms:
  - name: debian-12
    image: debian:12-slim
    pre_build_image: true
  - name: ubuntu-22
    image: ubuntu:22.04
    pre_build_image: true
  - name: ubuntu-24
    image: ubuntu:24.04
    pre_build_image: true
  - name: rockylinux-9
    image: rockylinux:9
    pre_build_image: true
  - name: almalinux-9
    image: almalinux:9
    pre_build_image: true

provisioner:
  name: ansible

verifier:
  name: ansible

scenarios:
  name: default
  test_sequence:
    - lint
    - syntax
    - create
    - converge
    - idempotence
    - verify
    - destroy
```

```bash
# Прогон тестов
molecule test

# Прогон только на конкретной платформе
molecule converge -s default -p debian-12

# Проверка идемпотентности
molecule idempotence
```

> **Production note:** Molecule с матрицей платформ — обязательный минимум для кроссплатформенных ролей. Используйте Docker для Linux-платформ (быстро, дешево). Для Windows используйте Vagrant или `molecule-windows`. В CI/CD запускайте `molecule test` на каждый merge request. `idempotence` сценарий проверяет, что повторный запуск дает `changed=0`.

## Практические сценарии

### Сценарий 1: Configuration snapshot перед изменением

```yaml
- name: Создание снапшота конфигурации
  ansible.builtin.command: "cp {{ config_path }} {{ config_path }}.bak.{{ ansible_date_time.epoch }}"
  changed_when: true
  register: snapshot
  when: ansible_facts['system'] != 'Win32NT'

- name: Применение изменений
  ansible.builtin.template:
    src: app.conf.j2
    dest: "{{ config_path }}"
  notify: Restart App
  register: config_change

- name: Откат при ошибке
  ansible.builtin.command: "cp {{ config_path }}.bak.{{ snapshot.stdout | regex_search('\\d+') }} {{ config_path }}"
  when: config_change is failed
```

### Сценарий 2: Canary с автоматическим откатом

```yaml
- name: Canary deployment
  hosts: webservers
  serial: 1
  max_fail_percentage: 0
  tasks:
    - name: Деплой на канарейку
      ansible.builtin.template:
        src: app.conf.j2
        dest: "{{ app_conf_path }}"
      notify: Restart App

    - name: Проверка работоспособности
      ansible.builtin.uri:
        url: "http://{{ inventory_hostname }}:{{ app_port }}/health"
        status_code: 200
        timeout: 10
      register: health
      retries: 10
      delay: 15
      until: health.status == 200

    - name: Автоматический откат при ошибке
      ansible.builtin.template:
        src: app.conf.backup.j2
        dest: "{{ app_conf_path }}"
      notify: Restart App
      when: health.status != 200
```

### Сценарий 3: Drift detection в cron (Linux) / Scheduled Task (Windows)

```yaml
# Drift detection через cron (Linux)
- name: Настройка drift detection
  ansible.builtin.cron:
    name: "Drift Detection"
    minute: "0"
    hour: "6"
    job: "/usr/local/bin/drift_check.sh >> /var/log/drift.log 2>&1"
  when: ansible_facts['system'] != 'Win32NT'

# Drift detection через Scheduled Task (Windows)
- name: Настройка drift detection (Windows)
  ansible.windows.win_scheduled_task:
    name: DriftDetection
    description: "Проверка конфигурационного дрейфа"
    actions:
      - path: C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe
        arguments: "-ExecutionPolicy Bypass -File C:\\scripts\\drift_check.ps1"
    triggers:
      - type: daily
        start_boundary: '2026-09-26T06:00:00'
    state: present
    enabled: yes
  when: ansible_facts['os_family'] == 'Windows'
```

### Сценарий 4: Аудит и snapshot переменных (SRE)

Фиксация состояния переменных и фактов для аудита изменений конфигурации.

```yaml
- name: Сбор всех переменных хоста
  ansible.builtin.setup:
  register: full_facts

- name: Сохранение snapshot в файл
  ansible.builtin.copy:
    content: "{{ full_facts.ansible_facts | to_nice_json }}"
    dest: "/var/tmp/audit/{{ inventory_hostname }}_facts_{{ ansible_date_time.date }}.json"
  delegate_to: localhost
  run_once: true
```

### Сценарий 5: Валидация инвентаря и фактов перед деплоем

```bash
# Визуализация групп
ansible-inventory --graph

# Проверка конкретного хоста
ansible-inventory -i inventories/production.yml --host web01.example.com

# Валидация синтаксиса инвентаря
ansible-playbook site.yml -i inventories/production.yml --syntax-check

# Проверка фактов
ansible all -m ansible.builtin.setup -a "filter=ansible_os_family*" | head -20
```

## Операции и команды

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `ansible-playbook site.yml --check --diff` | Drift detection | `changed` > 0 означает дрейф |
| `ansible-playbook site.yml --diff` | Diff без check mode | Текстовые различия при применении |
| `molecule test` | Полный цикл тестирования роли | Итог по сценариям (pass/fail) |
| `molecule converge -p <platform>` | Запуск на конкретной платформе | Развертывание на указанной ОС |
| `molecule idempotence` | Проверка идемпотентности | `changed=0` на втором запуске |
| `ansible-playbook site.yml --tags rollback` | Явный откат | Выполнение задач с тегом `rollback` |
| `ansible-inventory --graph --vars` | Граф групп и переменных | Дерево групп с переменными |
| `ansible all -m ansible.builtin.setup -a "filter=ansible_os_family*"` | Просмотр фактов ОС | `"ansible_facts": { "os_family": "Debian" }` |
| `ansible all -m ansible.builtin.setup -a "gather_subset=!all,min,distribution"` | Быстрый сбор фактов | Перечень хостов с минимальными фактами |
| `ansible all -m ping --limit webservers` | Проверка связи на подмножестве | `pong` от выбранных хостов |
| `ansible-config dump | grep fact_caching` | Проверка кэширования фактов | Текущие параметры кэша |
| `dpkg -l | grep pkg_name` | Проверка версии (Debian) | `ii pkg_name 1.2.3-1` |
| `rpm -q pkg_name` | Проверка версии (RedHat) | `pkg_name-1.2.3-1.el9` |
| `apk info pkg_name` | Проверка версии (Alpine) | `pkg_name-1.2.3-r1` |

## Диагностика и устранение неполадок

### Rollback и block/rescue

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `block/rescue` не срабатывает | `any_errors_fatal: true` | Проверьте директиву в плейбуке | `any_errors_fatal: false` для деплоев с откатом |
| `rescue` выполняется при `--check` | Некорректное использование `check_mode` | Проверьте `check_mode` в задачах | Используйте `check_mode: false` для rescue-задач |
| Откат пакета сломал зависимости | `dnf downgrade` нарушил граф | `dnf history rollback` | Используйте `dnf history rollback` или фиксируйте версии |
| `delegate_facts` не работает | `delegate_facts: false` по умолчанию | Проверьте директиву в задаче | Установите `delegate_facts: true` |
| `meta: clear_host_errors` не помогает | Хост в состоянии `unreachable` | `ansible-playbook -vvv` | Используйте `ignore_unreachable: true` или исправьте доступность |

### Drift detection

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `--check` не обнаруживает дрейф | Модуль не поддерживает check mode | Проверьте документацию модуля | Используйте модули с поддержкой `check_mode` |
| Drift detection падает на Windows | Разный набор фактов/модулей | `ansible win01 -m setup` | Используйте `ansible_facts['system'] == 'Win32NT'` в `when` |
| Слишком много false positives | Нестабильные параметры в проверках | Исключите динамические факты | Используйте идемпотентные проверки, игнорируйте время/случайные данные |
| Golden image устарел | Не обновляется при изменении desired state | Сравните дату файлов | Автоматически обновляйте golden image |
| Дрейф после автоматического обновления | Пакет обновил конфиг | Проверьте `apt changelog` | Используйте `hold`/`versionlock` для критичных пакетов |

### Molecule и тестирование

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `molecule test` падает с permission denied | Пользователь не в группе `docker` | `groups $USER` | `sudo usermod -aG docker $USER && newgrp docker` |
| Idempotence failed | `changed > 0` на втором запуске | `molecule idempotence -vvv` | Добавьте `changed_when: false` для `command`/`shell` |
| `verify` timeout | Медленный сбор фактов | `molecule verify -vvv` | `ansible_timeout: 600` в `provisioner.config_options` |
| systemd отсутствует в контейнере | Docker без init-процесса | `docker exec <id> systemctl status` | Используйте образы `geerlingguy/docker-*-ansible` |
| Конфиг не найден | Запуск вне корня роли | `pwd` | `cd ~/my_role && molecule test` |

### Package downgrade и зависимости

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `dnf downgrade` ломает зависимости | Граф зависимостей нарушен | `dnf history` | Используйте `dnf history rollback` |
| `apt install` с версией не работает | Неверный формат версии | `apt-cache policy pkg` | Используйте точное имя версии из `apt-cache policy` |
| Alpine не поддерживает lock | `apk` не имеет механизма hold | `apk policy` (не существует) | Фиксируйте версии в `requirements.yml` |

### Host patterns и `--limit`

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `--limit` не находит группу | Группа создана через `group_by` в текущем плее | Проверьте порядок плеев | Выполняйте группировку в отдельном плее |
| `~regex` паттерн не работает | Неверный синтаксис regex | `ansible-playbook --list-hosts --limit "~web.*"` | Используйте двойные кавычки в shell |
| Пересечение групп `:&` пустое | Группы не пересекаются | `ansible-inventory --graph` | Проверьте membership в обеих группах |

### Windows-инвентарь и факты

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `ansible_facts['os_family']` возвращает `Windows` | Корректно для Windows-хостов | Проверьте `when` условия | Используйте `ansible_facts['system'] == 'Win32NT'` |
| Факты Windows не кэшируются | Меньший набор фактов, чем POSIX | `ansible-inventory --host win01` | Ожидаемо: нет некоторых сетевых фактов |
| `ansible_python_interpreter` на Windows | Не требуется при WinRM | Проверьте `ansible_connection` | Для WinRM не задавайте `ansible_python_interpreter` |

## Граничные случаи и ограничения

- **`block/rescue` и `any_errors_fatal`**: при `any_errors_fatal: true` `rescue` не выполняется — плейбук останавливается. Используйте `any_errors_fatal: false` для деплоев с откатом.
- **Package downgrade и зависимости**: `dnf downgrade` может сломать зависимости. Используйте `dnf history rollback` или фиксируйте версии в `requirements.yml`.
- **Blue-green и stateful сервисы**: БД, очереди, кэши не поддерживают атомарное переключение. Требуют миграции данных.
- **Drift detection и `--check`**: не все модули поддерживают check mode. `command`/`shell` пропускаются. Для полного аудита используйте `diff: true` на уровне задачи.
- **Molecule и Windows**: Docker не поддерживает Windows. Используйте Vagrant или `molecule-windows` плагин.
- **Canary и health-check**: health-check должен быть кроссплатформенным (`uri`), иначе откат не сработает на mixed-парке.
- **Configuration snapshot и Windows**: `copy` модуль работает на Windows, но пути должны быть валидными (например, `C:\Windows\Temp\`).
- **Constructed plugin требует фактов**: для первого запуска факты должны быть собраны. Используйте `gather_facts: true` или статический `group_by`.
- **Fact cache и Windows**: набор фактов Windows меньше, чем POSIX. Кэшируются только доступные факты.

## Рекомендации и лучшие практики

1. **`block/rescue` для атомарных изменений**: всегда оборачивайте деплой в `block` с `rescue` для отката.
2. **Canary перед массовым деплоем**: `serial: 1` + health-check + автоматический откат.
3. **Package hold/lock для критичных версий**: `apt-mark hold`, `dnf versionlock`, `choco pin`.
4. **Configuration snapshot**: бэкап конфигов перед изменением через `command: cp` или `synchronize`.
5. **Drift detection в CI**: запускайте `--check --diff` nightly или при каждом merge request.
6. **Molecule на матрице платформ**: минимально Debian, Ubuntu, RHEL/Rocky, Alpine.
7. **Идемпотентность**: второй запуск роли должен дать `changed=0`. Проверяйте через `molecule idempotence`.
8. **`meta: clear_host_errors` для повторных попыток**: сбрасывает ошибки хоста для повторной попытки в rescue.
9. **Health-check через `uri`**: кроссплатформенный, универсальный. Интегрируйте в canary и drift detection.
10. **Версионирование пакетов**: фиксируйте версии в `vars/` с учетом ОС (`pkg_version[os_family]`).
11. **Валидация перед деплоем**: `ansible-inventory --graph --vars`, `--syntax-check`, `ansible all -m ping`.
12. **Раздельные окружения для тестов**: используйте изолированные стенды, не тестируйте на production.

## Дополнительная информация

- **[Стратегии отката в Ansible](../examples/ansible_rollback_strategies.md)** — подробное руководство по rollback стратегиям, blue/green, canary, Git, Vault, snapshot.
- **[Обнаружение дрейфа конфигурации](../examples/ansible_configuration_drift.md)** — drift detection, remediation, compliance, golden image.
- **[Тестирование с Molecule](../ansible_testing_with_molecule.md)** — подробное руководство по Molecule, Docker/Podman/Vagrant, Testinfra.
- **[Стратегии деплоя](../ansible_deployment_strategies.md)** — rolling updates, blue-green, canary, health-check, `serial`, `max_fail_percentage`.
- **[Поток управления и обработка ошибок](../PlaybookStructure/flow_control.md)** — `block/rescue`, `ignore_errors`, `any_errors_fatal`, `until`.
- **[Продвинутые возможности плейбуков](../PlaybookStructure/advanced.md)** — `async`, `delegate_to`, `delegate_facts`, `strategy`, `throttle`.
- **[Кроссплатформенные концепции](./concepts.md)** — матрица платформ, `ansible_facts`, общие паттерны.
- **[Валидация и тестирование плейбуков](../PlaybookStructure/testing_and_validation.md)** — `--check`, `--diff`, `ansible-lint`, `molecule`, pre-commit hooks.
