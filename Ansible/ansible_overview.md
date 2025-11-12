# Ansible

Ansible — это система с открытым исходным кодом для автоматизации развертывания программного обеспечения, управления конфигурацией и оркестрации. Он работает без агентов, подключаясь к узлам по SSH, и использует декларативные YAML-файлы (плейбуки) для описания желаемого состояния системы.

## Установка Ansible

Ansible — это мощный инструмент автоматизации, который позволяет управлять множеством серверов одновременно. Установка Ansible проста и занимает всего несколько шагов.

### Debian/Ubuntu
```bash
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository --yes --update ppa:ansible/ansible
sudo apt install -y ansible
```
*Использование официального PPA гарантирует получение свежей версии Ansible.*

### CentOS/RHEL
```bash
sudo yum install -y epel-release
sudo yum install -y ansible
```

### С помощью `pip` (универсальный способ)
Этот способ позволяет установить последнюю версию Ansible в изолированное окружение.
```bash
python3 -m venv ansible_env
source ansible_env/bin/activate
pip install ansible
```

---

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

**Пример с [SSH-ключом](../Linux/ssh.md):**

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

> **Внимание:** Хранение паролей в открытом виде небезопасно. Всегда используйте `ansible-vault` для шифрования чувствительных данных.

## Ad-Hoc Команды

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

## Плейбуки (Playbooks)

Плейбук — это YAML-файл, описывающий упорядоченный набор задач для выполнения на хостах. Это основной инструмент для оркестрации.

Для более подробной информации о структуре, директивах и примерах использования см. [Ansible: Плейбуки](ansible_playbooks.md).

### Идемпотентность

**Идемпотентность** — это фундаментальный принцип Ansible. Он гарантирует, что повторное выполнение операции не приведет к изменениям, если система уже находится в целевом состоянии.

*   `ok` (зеленый): Изменения не требуются.
*   `changed` (желтый): Были внесены изменения для достижения целевого состояния.

### Роли

Роли — это стандартный способ организации и переиспользования кода в Ansible. Они инкапсулируют задачи, переменные и шаблоны в модульную структуру.

Для более подробной информации см. [Ansible: Роли](ansible_roles.md).

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

### Безопасность: Ansible Vault

**Всегда** используйте `ansible-vault` для шифрования секретов (паролей, токенов, ключей API).

Для более подробной информации о командах и лучших практиках см. [Ansible: Vault](ansible_vault.md).

### Качество кода: Ansible Lint

Используйте `ansible-lint` для статического анализа плейбуков и ролей на соответствие лучшим практикам.

```bash
# Установка
pip install ansible-lint

# Проверка плейбука
ansible-lint my_playbook.yml
```

## Примеры плейбуков

### Включение TCP BBR на Ubuntu

Этот плейбук автоматизирует включение алгоритма контроля перегрузки [TCP BBR](../Networking/networks.md), что может значительно улучшить производительность сети.

```yaml
- name: Enable TCP BBR on Ubuntu
  hosts: all
  become: yes
  tags:
    - system
    - network
    - bbr
  tasks:
    - name: Ensure tcp_bbr module is loaded
      modprobe:
        name: tcp_bbr
        state: present

    - name: Make tcp_bbr module load on boot
      lineinfile:
        path: /etc/modules-load.d/bbr.conf
        line: tcp_bbr
        create: yes
        mode: '0644'

    - name: Apply BBR sysctl settings
      sysctl:
        name: "{{ item.key }}"
        value: "{{ item.value }}"
        sysctl_set: yes
        state: present
        reload: yes
      with_items:
        - { key: 'net.core.default_qdisc', value: 'fq' }
        - { key: 'net.ipv4.tcp_congestion_control', value: 'bbr' }
```
