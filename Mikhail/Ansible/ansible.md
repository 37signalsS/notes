# Ansible: Руководство по автоматизации

## 1. Основы настройки

### Файл конфигурации (`ansible.cfg`)

Для централизованного управления настройками создайте в корне проекта файл `ansible.cfg`.

```ini
[defaults]
# Путь к файлу инвентаризации (списку хостов).
inventory = inventory

# Путь к директории с ролями.
roles_path = roles

# Отключает проверку SSH-ключа хоста при первом подключении.
# Рекомендуется для упрощения первоначальной настройки в изолированных средах.
host_key_checking = False

# Подавляет предупреждения о том, что Ansible управляет данным хостом впервые.
deprecation_warnings = False
```

### Файл инвентаризации (`inventory`)

Файл `inventory` определяет хосты и группы хостов, которыми управляет Ansible.

**Пример с SSH-ключом:**

```ini
[servers]
# Синтаксис: alias ansible_host=IP ansible_user=...
server1 ansible_host=195.2.73.85 ansible_user=root ansible_port=2414 ansible_ssh_private_key_file=~/.ssh/id_rsa
```

**Пример с группами и паролями:**


```ini
[master]
192.168.0.138

[nodes]
192.168.0.139
192.168.0.140

# Переменные для группы master
[master:vars]
ansible_user=master
ansible_ssh_pass=${MASTER_PASSWORD} # Используйте переменные окружения или Vault
ansible_become_pass=${MASTER_PASSWORD}

# Переменные для группы nodes
[nodes:vars]
ansible_user=vagrant
ansible_ssh_pass=vagrant
ansible_become_pass=vagrant
```

> **⚠️ Внимание:** Хранение паролей в открытом виде небезопасно. Всегда используйте `ansible-vault` для шифрования чувствительных данных.

## 2. Ad-Hoc Команды

Ad-hoc команды — это быстрый способ выполнить одну задачу на управляемых узлах. Они идеально подходят для простых действий, таких как проверка подключения или сбор информации.

**Проверка подключения (`ping`):**

```bash
# Проверить доступность хостов в группе master
ansible master -m ping

# Проверить доступность всех хостов
ansible all -m ping
```

**Выполнение команд (`command` и `shell`):**

*   `command`: для простых команд без конвейеров (`|`) или перенаправлений (`>`).
*   `shell`: для выполнения сложных скриптов и команд.

```bash
# Получить время работы системы (безопасно)
ansible all -m command -a "uptime"

# Посмотреть содержимое корневого каталога
ansible all -m shell -a "ls -la /"
```

## 3. Плейбуки (Playbooks)

Плейбук — это YAML-файл, описывающий упорядоченный набор задач для выполнения на хостах. Это основной инструмент для оркестрации.

**Ключевые компоненты:**

*   `hosts`: Целевые хосты или группы из инвентари.
*   `tasks`: Список задач для выполнения.
*   `vars`: Переменные для использования в плейбуке.
*   `handlers`: Обработчики, которые запускаются по уведомлению от задач.
*   `become: true`: Выполнять задачи с повышенными привилегиями (`sudo`).

### Пример плейбука

Этот плейбук копирует файл `authorized_keys` и перезапускает службу SSH только в том случае, если файл был изменен.

```yaml
- name: Configure SSH access
  hosts: all
  become: true # Выполнять как root

  tasks:
    - name: Copy authorized_keys for the user
      copy:
        src: /home/user/.ssh/authorized_keys # Локальный путь
        dest: /root/.ssh/authorized_keys      # Удаленный путь
        owner: root
        group: root
        mode: '0600'
      notify: Restart SSHD # Уведомить обработчик

  handlers:
    - name: Restart SSHD
      service:
        name: sshd
        state: restarted
```

## 4. Ключевые концепции

### Идемпотентность

**Идемпотентность** — это фундаментальный принцип Ansible. Он гарантирует, что повторное выполнение операции не приведет к изменениям, если система уже находится в целевом состоянии.

*   `ok` (зеленый): Изменения не требуются.
*   `changed` (желтый): Были внесены изменения для достижения целевого состояния.

### Роли

Роли — это стандартный способ организации и переиспользования кода в Ansible. Они инкапсулируют задачи, переменные и шаблоны в модульную структуру.

**Создание роли:**

```bash
ansible-galaxy init <имя_роли>
```

**Структура роли:**

*   `tasks/main.yml`: Основной файл с задачами.
*   `handlers/main.yml`: Обработчики для этой роли.
*   `defaults/main.yml`: Переменные по умолчанию (самый низкий приоритет).
*   `vars/main.yml`: Переменные роли (высокий приоритет).
*   `files/`: Статические файлы для копирования на узлы.
*   `templates/`: Шаблоны Jinja2 (`.j2`).
*   `meta/main.yml`: Метаданные роли и зависимости.

### Шаблоны (Jinja2)

Шаблоны позволяют создавать динамические конфигурационные файлы с использованием переменных.

```yaml
- name: Create config from template
  template:
    src: config.j2 # Файл шаблона в директории templates
    dest: /etc/app/config.conf
```

### Установка Python на "голые" хосты (Bootstrapping)

Большинство модулей Ansible требуют Python. Для его установки на системах без Python используется модуль `raw`.

```bash
# Установка Python 3 на Debian/Ubuntu
ansible my-raw-node -m raw -a "apt-get update && apt-get install -y python3" --become
```

### Ansible Galaxy

[Ansible Galaxy](https://galaxy.ansible.com) — это центральный репозиторий для поиска и обмена ролями с сообществом.

## 6. Лучшие практики

### Безопасность: Ansible Vault

**Всегда** используйте `ansible-vault` для шифрования секретов (паролей, токенов, ключей API).

```bash
# Создать новый зашифрованный файл
ansible-vault create secrets.yml

# Редактировать существующий файл
ansible-vault edit secrets.yml

# Зашифровать существующий файл
ansible-vault encrypt old_secrets.yml

# Расшифровать файл
ansible-vault decrypt secrets.yml

# Запустить плейбук, указав пароль в командной строке
ansible-playbook my_playbook.yml --ask-vault-pass
```

### Качество кода: Ansible Lint

Используйте `ansible-lint` для статического анализа плейбуков и ролей на соответствие лучшим практикам.

```bash
# Установка
pip install ansible-lint

# Проверка плейбука
ansible-lint my_playbook.yml
```

## 7. Примеры плейбуков

### Включение TCP BBR на Ubuntu

Этот плейбук автоматизирует включение алгоритма контроля перегрузки TCP BBR, что может значительно улучшить производительность сети.

```yaml
- name: Enable TCP BBR on Ubuntu
  hosts: all
  become: yes
  tasks:
    - name: Ensure tcp_bbr module is loaded
      modprobe:
        name: tcp_bbr
        state: present

    - name: Add BBR to /etc/modules-load.d
      lineinfile:
        path: /etc/modules-load.d/modules.conf
        line: tcp_bbr
        create: yes

    - name: Set BBR parameters in sysctl
      blockinfile:
        path: /etc/sysctl.conf
        marker: "# {mark} TCP BBR CONFIG"
        block: |
          net.core.default_qdisc = fq
          net.ipv4.tcp_congestion_control = bbr

    - name: Apply sysctl changes
      command: sysctl -p
```
