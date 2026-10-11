# Модели доставки конфигурации: Push против Pull — Сравнение

**Актуально для:** Configuration Management Delivery Models — обзор 2026 года

## Определения

**Модели доставки конфигурации** — это архитектурные паттерны, определяющие направление инициации соединения и поток управляющих данных между центральной системой управления конфигурацией (**Configuration Management, CM**) и целевыми узлами.

*   **Push-модель (Проталкивание):** Центральный сервер активно инициирует сессию (обычно SSH или WinRM) к узлу. Управляющий узел «диктует» изменения.
*   **Pull-модель (Вытягивание):** Управляемый узел (агент) инициирует исходящее соединение (обычно HTTPS/gRPC) к серверу. Узел «запрашивает» изменения.

Выбор модели определяет сетевую топологию, требования к безопасности (Firewall/NAT) и масштабируемость всей системы.

## Базовые концепции

### Push-модель (Проталкивание)

В этой модели управляющий узел (Control Node) является инициатором TCP-соединения. Он последовательно или параллельно подключается к хостам из инвентаря.

*   **Транспорт и протоколы:** Основным протоколом является **SSH** (порт 22) для Linux или **WinRM/PSRP** (порты 5985/5986) для Windows. В современных средах 2026 года также используется **WinSSH**.
*   **Архитектурные особенности:**
    *   **Agentless:** На целевых узлах не требуется специфическое ПО, кроме интерпретатора (Python/PowerShell) и системных утилит.
    *   **Централизация управления:** Все полномочия (приватные ключи, пароли) сосредоточены на контроллере.
    *   **Сетевой периметр:** Требует прямой видимости узлов со стороны контроллера. Firewall должен разрешать *входящие* соединения на порты управления.
*   **Примеры:** Ansible, Terraform, Fabric, SaltStack (в режиме `salt-ssh`).

### Pull-модель (Вытягивание)

В этой модели активной стороной выступает локальное ПО на целевом узле — агент. Он работает как системная служба (демон).

*   **Транспорт и протоколы:** Преимущественно **HTTPS** (порт 443) или **gRPC**. Соединение всегда инициируется *изнутри* защищенного контура наружу к серверу управления.
*   **Архитектурные особенности:**
    *   **Автономность:** Агент может выполнять цикл сверки локально по расписанию, даже при временной потере связи с мастером.
    *   **Распределенные вычисления:** Процесс вычисления «дельты» (разницы между текущим и желаемым состоянием) происходит на конечном узле, что снимает нагрузку с центрального сервера.
    *   **NAT и Firewall:** Идеально подходит для сред, где узлы находятся за NAT или в разных облаках, так как требует только *исходящего* доступа.
*   **Примеры:** Puppet, Chef, SaltStack (Minions), **[Ansible Pull](../Ansible/ansible_pull.md)**.
*   **Современный контекст (GitOps):** Контроллеры (ArgoCD, Flux) внутри Kubernetes-кластера «тянут» состояние из Git и применяют его локально, реализуя чистую Pull-модель.

## Сетевые топологии

Каждая модель диктует свою сетевую архитектуру. Понимание топологии критично для проектирования отказоустойчивой CM-системы.

### Push-модель: Прямой доступ

```
┌─────────────────────────────────────────────────────────────┐
│                  ЦЕНТРАЛЬНЫЙ КОНТРОЛЛЕР                      │
│            (Control Node / CI-CD Runner)                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  ansible.cfg  │  │  inventory/  │  │  playbooks/  │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└──────────────────────────┬──────────────────────────────────┘
                           │ SSH (порт 22) / WinRM (5985/5986)
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   Web-01     │  │   Web-02     │  │   Web-03     │
│  (Agentless) │  │  (Agentless) │  │  (Agentless) │
│  Python+SSH  │  │  Python+SSH  │  │  Python+SSH  │
└──────────────┘  └──────────────┘  └──────────────┘

Правила файрвола (на контроллере):
  Исходящие: TCP 22 (SSH), TCP 5985/5986 (WinRM)
  Входящие:  отсутствуют

Правила файрвола (на целевых узлах):
  Входящие:  TCP 22 (только с IP контроллера)
  Исходящие: нет специальных требований
```

### Push-модель: Через NAT/Bastion

```
┌──────────────────┐          ┌──────────────────┐
│  Контроллер      │          │  Bastion Host    │
│  (Целевой сегмент)│────SSH──▶│  (Промежуточный) │
│                  │          │  ProxyJump=yes   │
└──────────────────┘          └────────┬─────────┘
                                       │ SSH (22)
                  ┌────────────────────┼────────────────────┐
                  ▼                    ▼                    ▼
          ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
          │   Web-01     │    │   Web-02     │    │   DB-01      │
          │  (10.0.1.x)  │    │  (10.0.1.x)  │    │  (10.0.2.x)  │
          └──────────────┘    └──────────────┘    └──────────────┘

# ansible.cfg — настройка ProxyJump
[defaults]
inventory = ./inventory/production.yml

[ssh_connection]
ssh_args = -o ProxyJump=bastion.company.com -o ControlMaster=auto -o ControlPersist=60s
pipelining = True
```

### Pull-модель: Стандартная архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                 СЕРВЕР УПРАВЛЕНИЯ (Master)                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  PuppetDB/   │  │  CA Server   │  │  File Server  │      │
│  │  Chef Server │  │  (PKI)       │  │  (Modules)    │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS (443) — исходящее от агентов
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   Web-01     │  │   Web-02     │  │   DB-01      │
│  ┌────────┐  │  │  ┌────────┐  │  │  ┌────────┐  │
│  │ Agent  │  │  │  │ Agent  │  │  │  │ Agent  │  │
│  │ (cyc)  │  │  │  │ (cyc)  │  │  │  │ (cyc)  │  │
│  └────────┘  │  │  └────────┘  │  │  └────────┘  │
└──────────────┘  └──────────────┘  └──────────────┘

Правила файрвола (на целевых узлах):
  Исходящие: TCP 443 к Master (API), TCP 8140 (Puppet), TCP 4505-4506 (Salt)
  Входящие:  отсутствуют (агент инициирует соединение)

Преимущество для NAT/VPN:
  Агенты за NAT не требуют проброса портов — они сами подключаются наружу.
```

### Air-gapped среда (Push-модель)

```
┌─────────────────────────────────────────────────────────────┐
│                ИЗОЛИРОВАННЫЙ СЕГМЕНТ (Офлайн)                │
│                                                             │
│  ┌──────────────────┐     ┌──────────────────┐             │
│  │ Control Node     │     │  Локальное        │             │
│  │ (Ansible)        │────▶│  зеркало пакетов  │             │
│  └────────┬─────────┘     │  (apt-mirror)     │             │
│           │ SSH            └──────────────────┘             │
│     ┌─────┼─────┐                                          │
│     ▼     ▼     ▼                                          │
│  ┌─────┐┌─────┐┌─────┐                                    │
│  │DB-01││DB-02││App-01│                                    │
│  └─────┘└─────┘└─────┘                                    │
└─────────────────────────────────────────────────────────────┘

Доставка обновлений:
  1. Синхронизация Git-репозитория через Data Diode/USB
  2. Обновление локального зеркала пакетов
  3. Применение через Control Node (Push)
```

## Сравнительный анализ

| Характеристика | Push-модель | Pull-модель |
| :--- | :--- | :--- |
| **Инициатор сессии** | Узел управления (Control Node) | Агент на управляемом узле |
| **Сложность внедрения** | Низкая (не нужен инсталл агентов) | Средняя (нужен жизненный цикл агента) |
| **Сетевая доступность** | Контроллер должен видеть узлы | Узлы должны видеть сервер управления |
| **Оперативность (Latency)** | Мгновенная (Ad-hoc команды) | Зависит от интервала опроса (Polling) |
| **Масштабируемость** | Ограничена ресурсами контроллера | Почти неограничена (распределенный Diff) |
| **Безопасность (Lateral)** | Высокий риск при взломе контроллера | Изоляция (взлом узла не дает доступа к другим) |
| **Контроль дрейфа** | Периодический запуск по расписанию | Непрерывный автоматический возврат к эталону |
| **Поддержка Air-gapped** | Удобнее (контроллер в защищенной зоне) | Сложнее (нужны локальные зеркала/серверы) |

## Практические сценарии

### Сценарий 1: Оперативное исправление уязвимостей (Push)

**Задача:** Срочно обновить критический пакет на 500 серверах в ответ на Zero-day уязвимость.

**Решение:** Использование Ansible. Контроллер немедленно инициирует сессии на всех узлах.

```bash
# Мгновенное обновление OpenSSL на всех серверах
ansible-playbook emergency_patch.yml -l all -f 50

# Проверка без применения (dry-run)
ansible-playbook emergency_patch.yml -l all --check --diff

# Обновление только конкретного пакета через ad-hoc
ansible all -m apt -a "name=openssl state=latest update_cache=yes" --become -f 50
```

```yaml
# emergency_patch.yml
---
- name: Экстренное обновление уязвимого пакета
  hosts: all
  become: yes
  gather_facts: yes
  serial: "30%"    # Поэтапное применение (Canary)
  max_fail_percentage: 5

  tasks:
    - name: Проверка текущей версии пакета
      ansible.builtin.package_facts:
      tags: always

    - name: Вывод текущей версии
      ansible.builtin.debug:
        msg: >
          Текущая версия {{ item.key }}: {{ item.value[0].version }}
      loop: "{{ ansible_facts.packages | dict2items }}"
      when: "'openssl' in item.key"

    - name: Обновление уязвимого пакета
      ansible.builtin.apt:
        name: openssl
        state: latest
        update_cache: yes
        cache_valid_time: 3600
      register: update_result

    - name: Перезапуск сервисов, зависящих от OpenSSL
      ansible.builtin.service:
        name: "{{ item }}"
        state: restarted
      loop:
        - nginx
        - apache2
        - sshd
      when: update_result.changed

    - name: Верификация обновления
      ansible.builtin.command: openssl version
      register: new_version
      changed_when: false

    - name: Проверка успеха
      ansible.builtin.assert:
        that: "'1.1.1' in new_version.stdout or '3.0' in new_version.stdout"
        fail_msg: "Обновление не применилось! Версия: {{ new_version.stdout }}"
        success_msg: "Успешно обновлено: {{ new_version.stdout }}"
```

**Преимущество:** Полный контроль над временем начала и завершения операции. Параметр `serial: "30%"` обеспечивает поэтапное применение — сначала 30% серверов, затем следующие, что позволяет обнаружить проблемы до массового обновления.

### Сценарий 2: Поддержание долгосрочного соответствия (Pull)

**Задача:** Гарантировать, что конфигурация веб-серверов на 5000 узлах соответствует корпоративному стандарту безопасности (Compliance).

**Решение:** Использование Puppet. Агенты на узлах каждые 30 минут сверяют локальное состояние с эталоном.

```bash
# Принудительное применение манифеста (немедленно)
sudo puppet agent --test --server puppet.example.com

# Проверка текущего каталога без применения
sudo puppet agent --test --server puppet.example.com --noop

# Просмотр примененных изменений за последние сутки
sudo puppet history --last 24h
```

```puppet
# security_compliance.pp
class security_compliance {
  # Запрещенные пакеты
  package { ['telnet', 'rsh-server', 'rsh-client']:
    ensure => absent,
  }

  # Обязательные пакеты
  package { ['fail2ban', 'auditd', 'aide']:
    ensure => installed,
  }

  # Конфигурация SSH
  file { '/etc/ssh/sshd_config':
    ensure  => file,
    owner   => 'root',
    group   => 'root',
    mode    => '0600',
    source  => 'puppet:///modules/security_compliance/sshd_config',
    notify  => Service['sshd'],
  }

  # Отключение парольной аутентификации
  file_line { 'disable_password_auth':
    path  => '/etc/ssh/sshd_config',
    line  => 'PasswordAuthentication no',
    notify => Service['sshd'],
  }

  # Включение аудита
  service { ['auditd', 'fail2ban']:
    ensure => running,
    enable => true,
  }

  # Проверка прав на критические файлы
  file { ['/etc/passwd', '/etc/shadow']:
    ensure => file,
    owner  => 'root',
    group  => 'root',
    mode   => '0644',
  }
}
```

**Преимущество:** Автоматическое подавление **дрейфа конфигурации (Configuration Drift)**. Любая ручная правка системного администратора будет автоматически отменена агентом в течение 30 минут.

### Сценарий 3: Динамические среды (GitOps/Pull)

**Задача:** Автоматическая настройка новых экземпляров приложения при срабатывании Auto-scaling.

**Решение:** Использование ArgoCD. Новые поды в Kubernetes при появлении сами регистрируются и подтягивают актуальные манифесты из Git.

```yaml
# argocd-application.yml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: web-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://gitlab.company.com/infra/web-app.git
    targetRevision: production
    path: k8s/overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: web-app
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

```bash
# Проверка статуса синхронизации
argocd app list
argocd app get web-app

# Ручная синхронизация (если нужно немедленно)
argocd app sync web-app

# Просмотр diff между Git и кластером
argocd app diff web-app
```

**Преимущество:** Нет необходимости настраивать доступы от CI-системы внутрь кластера. Secrets не покидают кластер.

### Сценарий 4: Защищенная изолированная сеть (Air-gapped Push)

**Задача:** Управление конфигурацией в сегменте сети, полностью отключенном от интернета.

**Решение:** Развертывание Control Node внутри этого сегмента. Плейбуки и пакеты доставляются через доверенный шлюз (Data Diode или съемный носитель).

```bash
# На Control Node внутри изолированного сегмента
# Создание локального зеркала репозитория
git clone --mirror https://gitlab.company.com/infra/config.git /srv/git/config.git

# Настройка HTTP-сервера для раздачи пакетов (apt-mirror)
apt-mirror /etc/apt/mirror.list

# Запуск Ansible с локальным inventory
ansible-playbook -i /srv/inventory/production.yml \
                 -e "package_mirror=http://mirror.internal:8080" \
                 site.yml
```

```yaml
# site.yml — плейбук для изолированной среды
---
- name: Настройка серверов в изолированном сегменте
  hosts: isolated_segment
  become: yes
  vars:
    apt_mirror: "http://mirror.internal:8080"
    ntp_server: "ntp.internal"
    dns_servers:
      - 10.0.0.1
      - 10.0.0.2

  tasks:
    - name: Настройка локального зеркала пакетов
      ansible.builtin.template:
        src: templates/sources.list.j2
        dest: /etc/apt/sources.list
        owner: root
        group: root
        mode: '0644'

    - name: Настройка NTP
      ansible.builtin.template:
        src: templates/chrony.conf.j2
        dest: /etc/chrony/chrony.conf
      notify: restart chrony

    - name: Базовые пакеты (без интернета)
      ansible.builtin.apt:
        name: [vim, tmux, htop, curl, wget]
        state: present
        update_cache: yes

  handlers:
    - name: restart chrony
      ansible.builtin.service:
        name: chrony
        state: restarted
```

**Преимущество:** Push-модель проще в реализации в таких условиях, так как не требует настройки сложных прокси-серверов или локальных зеркал для сотен агентов.

### Сценарий 5: Глобально распределенная сеть и Edge (Pull)

**Задача:** Управление тысячами устройств (IoT, кассовые терминалы), подключенными через нестабильные мобильные каналы (4G/5G).

**Решение:** Pull-агенты на устройствах. Агент «просыпается», когда появляется связь, и запрашивает обновления.

```yaml
# Системный таймер для ansible-pull на Edge-устройстве
# /etc/systemd/system/ansible-pull.timer
[Unit]
Description=Run Ansible Pull on cellular connection
After=network-online.target
Wants=network-online.target

[Timer]
OnCalendar=*-*-* 02:00:00
RandomizedDelaySec=1800
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
# Сервис для ansible-pull
# /etc/systemd/system/ansible-pull.service
[Unit]
Description=Ansible Pull for Edge device
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/ansible-pull \
  -U https://gitlab.company.com/edge-config.git \
  -C stable \
  -d /opt/ansible \
  -i localhost, \
   -e "device_type=kiosk region=eu-01" \
  -o \
  -s 120 \
  local.yml
StandardOutput=journal
User=ansible
```

**Преимущество:** Система устойчива к обрывам связи. Контроллеру не нужно знать текущий динамический IP-адрес каждого устройства.

### Сценарий 6: Гибридная модель Push + Pull

**Задача:** Использовать Push для срочных операций и Pull для долгосрочного compliance.

**Решение:** Bootstrap через Ansible (Push), затем Puppet/Salt для постоянного контроля.

```bash
# Этап 1: Bootstrap через Push (Ansible)
ansible-playbook bootstrap.yml -l new_servers

# Этап 2: Установка агента Pull
ansible-playbook install_puppet.yml -l new_servers

# Этап 3: Проверка, что агент работает
ansible all -m shell -a "puppet agent --test --server puppet.example.com" -l new_servers
```

```yaml
# install_puppet.yml
---
- name: Установка Puppet-агента
  hosts: new_servers
  become: yes
  tasks:
    - name: Установка репозитория Puppet
      ansible.builtin.package:
        name: https://apt.puppet.com/puppet8-release-focal.deb
        state: present

    - name: Установка puppet-agent
      ansible.builtin.package:
        name: puppet-agent
        state: present

    - name: Настройка сервера
      ansible.builtin.lineinfile:
        path: /etc/puppetlabs/puppet/puppet.conf
        regexp: '^\[main\]'
        line: "[main]\nserver = puppet.example.com\ncertname = {{ inventory_hostname }}"

    - name: Запуск агента для получения сертификата
      ansible.builtin.command: puppet agent --test --waitforcert 60
      register: puppet_result
      changed_when: "'Notice: Finished catalog' in puppet_result.stdout"

    - name: Включение и запуск сервиса
      ansible.builtin.service:
        name: puppet
        state: started
        enabled: yes
```

## Дополнительная информация

### Сетевые требования и файрвол

Правильная настройка сетевого доступа — критический фактор успеха CM-проекта.

**Push-модель (Ansible):**

| Порт | Протокол | Направление | Описание |
| :--- | :--- | :--- | :--- |
| 22 | TCP | Контроллер → Целевой узел | SSH (Linux) |
| 5985 | TCP | Контроллер → Целевой узел | WinRM HTTP (Windows) |
| 5986 | TCP | Контроллер → Целевой узел | WinRM HTTPS (Windows) |

```bash
# Проверка доступности SSH
ansible all -m ping -u deploy --private-key ~/.ssh/id_ed25519

# Подключение через ProxyJump (Bastion)
ansible all -m shell -a "uptime" \
  --ssh-extra-args "-o ProxyJump=bastion.company.com"

# Настройка SSH-конфига (~/.ssh/config)
Host 10.0.1.*
    ProxyJump bastion.company.com
    User deploy
    IdentityFile ~/.ssh/id_ed25519
```

**Pull-модель (Puppet/Chef/Salt):**

| Порт | Протокол | Направление | Описание |
| :--- | :--- | :--- | :--- |
| 443 | TCP | Агент → Сервер | HTTPS API |
| 8140 | TCP | Агент → Сервер | Puppet Master |
| 8141 | TCP | Агент → Сервер | Puppet CA |
| 4505 | TCP | Агент → Salt Master | Salt Publish |
| 4506 | TCP | Агент → Salt Master | Salt Return |

```bash
# Проверка подключения агента к серверу (Puppet)
sudo puppet agent --test --server puppet.example.com --summarize

# Проверка подключения агента к серверу (Salt)
sudo salt-call --local test.ping

# Проверка сетевой доступности Salt Master
nc -zv salt-master.example.com 4505 4506
```

**Маскировка трафика (обход DPI):**

В средах с агрессивным файрволом или DPI (Deep Packet Inspection) рекомендуется:

```bash
# Для Ansible: туннелирование через SSH (по умолчанию)
# Принудительное использование SSH-доступа через ProxyCommand
ansible-playbook site.yml \
  -e "ansible_ssh_common_args='-o ProxyCommand=\"ssh -W %h:%p bastion\"'"

# Для SaltStack: использование ZeroMQ через WebSocket
# salt/master.conf
# transport: websocket
# webhook_port: 8123
```

### Расписание Pull-операций

Pull-агенты работают по расписанию. Правильная настройка таймеров критична для баланса между актуальностью и нагрузкой.

**Systemd Timer (рекомендуемый подход):**

```ini
# /etc/systemd/system/puppet-agent.timer
[Unit]
Description=Puppet Agent Run Timer

[Timer]
OnCalendar=*:00/30
RandomizedDelaySec=600
Persistent=true

[Install]
WantedBy=timers.target
```

**Cron (классический):**

```bash
# Puppet: каждые 30 минут с jitter
*/30 * * * * /usr/bin/sleep $((RANDOM \% 300)) && /opt/puppetlabs/bin/puppet agent --test

# SaltStack: каждую минуту с проверкой изменений
* * * * * /usr/bin/salt-call state.highstate --state-output=changes_id

# CFEngine: каждые 5 минут (стандарт)
*/5 * * * * /var/cfengine/bin/cf-agent --no-lock --inform
```

**Сравнение интервалов:**

| Инструмент | Интервал по умолчанию | Рекомендуемый интервал | Jitter |
| :--- | :--- | :--- | :--- |
| **Puppet** | 30 минут | 30 минут | +600 сек |
| **Chef** | 30 минут | 30 минут | +1800 сек |
| **SaltStack** | 60 секунд | 5–15 минут | +60 сек |
| **CFEngine** | 5 минут | 5 минут | +300 сек |
| **Ansible Pull** | По cron | 1–24 часа | +1800 сек |

### Миграция с Push на Pull

Пошаговая стратегия перехода от Ansible (Push) к Puppet/SaltStack (Pull):

**Этап 1: Аудит текущего состояния (1–2 недели)**
```bash
# Сбор фактов со всех узлов
ansible all -m setup --tree /tmp/facts/

# Анализ используемых ролей
grep -r "include_role\|import_role" playbooks/ | awk -F: '{print $3}' | sort -u

# Группировка узлов по ролям
ansible-inventory --graph
```

**Этап 2: Параллельная работа (4–8 недель)**
```bash
# 1. Установка Pull-агента через Ansible
ansible-playbook install_puppet.yml

# 2. Конвертация Ansible-ролей в Puppet-классы (по одному)
# Используйте ansible-puppet-converter или пишите вручную

# 3. Запуск обоих инструментов параллельно
# Puppet работает с --noop (не применяет, только логирует)
# Ansible продолжает Apply как обычно
```

**Этап 3: Валидация (2–4 недели)**
```bash
# Сравнение состояний: Puppet видит vs Ansible видит
ansible all -m shell -a "puppet agent --test --noop --server puppet.example.com 2>&1 | tail -5"

# Проверка дрейфа: что изменилось за время параллельной работы
diff <(ansible all -m shell -a "cat /etc/nginx/nginx.conf" --tree /tmp/ansible/) \
     <(puppet filesum /etc/nginx/nginx.conf)
```

**Этап 4: Полный переход (1 неделя)**
```bash
# 1. Отключение Ansible-задач через cron
# 2. Включение Puppet-агента в production
sudo systemctl enable --now puppet

# 3. Верификация
sudo puppet agent --test --server puppet.example.com
```

### Откат и Rollback-стратегии

Откат изменений в контексте Push и Pull существенно различается.

**Push-откат (Ansible):**
```yaml
# Блок с автоматическим откатом при ошибке
- name: Безопасное развертывание с откатом
  block:
    - name: Копирование новой конфигурации
      ansible.builtin.copy:
        src: files/nginx.conf.new
        dest: /etc/nginx/nginx.conf
        backup: yes
      notify: restart nginx

    - name: Проверка здоровья сервиса
      ansible.builtin.uri:
        url: "http://localhost/health"
        status_code: 200
      retries: 5
      delay: 5

  rescue:
    - name: Восстановление из backup
      ansible.builtin.copy:
        src: /etc/nginx/nginx.conf.backup
        dest: /etc/nginx/nginx.conf
      notify: restart nginx

  handlers:
    - name: restart nginx
      ansible.builtin.service:
        name: nginx
        state: restarted
```

**Pull-откат (Puppet):**
```bash
# Простой откат — возврат манифеста к предыдущему коммиту
cd /etc/puppetlabs/code/environments/production
git log --oneline -5              # Найти нужный коммит
git revert HEAD                   # Откатить последнее изменение

# Агенты автоматически применят откат при следующем цикле
# Немедленный откат:
sudo puppet agent --test --server puppet.example.com
```

**Pull-откат (SaltStack):**
```bash
# Откат состояния
sudo salt '*' state.apply previous_release

# Откат через gitfs (Salt может читать из Git)
sudo salt-run fileserver.clear_cache
sudo salt '*' state.apply webserver saltenv=production
```

**Сравнение стратегий отката:**

| Инструмент | Механизм отката | Время отката | Автоматизация |
| :--- | :--- | :--- | :--- |
| **Ansible** | `git revert` + повторный Apply | Мгновенно | Требует запуска |
| **Puppet** | `git revert` + автоприменение | 30 минут | Автоматически |
| **SaltStack** | `state.apply` предыдущей версии | Мгновенно | Требует запуска |
| **Chef** | `git revert` + `chef-client` | 30 минут | Автоматически |

### Диагностика и устранение неисправностей

**Типичные ошибки Push-модели:**

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `UNREACHABLE!` | Нет SSH-доступа к хосту | Проверить файрвол, ключи, ProxyJump |
| `Authentication failure` | Неверный ключ/пароль | `ssh -vvv user@host` для диагностики |
| `Module timeout` | Долгая задача превысила таймаут | Увеличить `timeout` в задаче или `async` |
| `Maximum of 5 retries exceeded` | Нестабильная сеть | Настроить `retries` и `delay` в задаче |

**Типичные ошибки Pull-модели:**

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Could not retrieve catalog` | Агент не может подключиться к серверу | Проверить DNS, firewall, mTLS |
| `Certificate signed but waiting` | Сертификат не подписан | `puppetserver ca sign --certname <name>` |
| `Salt minion not responding` | Минион не запущен | `systemctl status salt-minion` |
| `Catalog compilation failed` | Ошибка в манифесте | `puppet parser validate <file>` |

```bash
# Диагностические команды (Push)
ansible all -m ping -vvv                    # Проверка SSH с детализацией
ansible all -m setup -l web01               # Сбор фактов с одного хоста

# Диагностические команды (Pull)
sudo puppet agent --test --debug            # Puppet с отладкой
sudo salt '*' test.ping                     # Проверка доступности всех Minions
sudo salt-call --local state.show_highstate # Показать планируемые изменения
sudo journalctl -u puppet -f               # Логи Puppet-агента в реальном времени
```

### Масштабирование и производительность

**Push-модель (Ansible):**

```bash
# Увеличение параллелизма
ansible-playbook site.yml -f 50              # 50 forks (параллельных соединений)
ansible-playbook site.yml --forks 100        # Максимальный параллелизм

# Пайплайнинг (ускорение через буферизацию команд)
# ansible.cfg
[ssh_connection]
pipelining = True
```

| Параметр | Значение по умолчанию | Рекомендуемое | Эффект |
| :--- | :--- | :--- | :--- |
| `forks` | 5 | 20–50 | Количество параллельных SSH-сессий |
| `pipelining` | False | True | Снижение количества SSH-сессий на задачу |
| `timeout` | 10 | 30 | Таймаут подключения к хосту |
| `ssh_args` | пусто | `-o ControlPersist=60s` | Переиспользование SSH-сессий |

**Pull-модель (Puppet/Salt):**

```bash
# Puppet: оптимизация каталог-компиляции
# Мастер: увеличение количества thread-沤ов
# /etc/default/puppetserver
JAVA_ARGS="-Xms2g -Xmx4g -XX:+UseG1GC"

# Salt: увеличение скорости через ZeroMQ
# /etc/salt/master
worker_threads: 16
event_return: mysql
job_cache: True
```

**Сравнение производительности на 1000 узлов:**

| Инструмент | Время Apply | Параллелизм | Ограничение |
| :--- | :--- | :--- | :--- |
| **Ansible (Push)** | 30–60 мин | 5–100 forks | Пропускная способность контроллера |
| **Puppet (Pull)** | 10–30 мин | Распределенный | Компиляция каталога на мастере |
| **SaltStack (Push/Pull)** | 1–5 мин | 10 000+ одновременно | Пропускная способность ZeroMQ |

### Метрики и мониторинг Push/Pull операций

```yaml
# Пример Prometheus-метрик для мониторинга CM
# ansible_callback_prometheus.yml
- name: Отправка метрик в Prometheus
  uri:
    url: "http://prometheus-pushgateway:9091/metrics/job/ansible/instance/{{ inventory_hostname }}"
    method: PUT
    body: |
      ansible_playbook_duration_seconds{{ playbook="{{ playbook_name }}" }} {{ playbook_duration }}
      ansible_task_duration_seconds{{ task="{{ task_name }}", status="{{ task_status }}" }} {{ task_duration }}
      ansible_tasks_total{{ status="ok" }} {{ tasks_ok }}
      ansible_tasks_total{{ status="changed" }} {{ tasks_changed }}
      ansible_tasks_total{{ status="failed" }} {{ tasks_failed }}
    headers:
      Content-Type: "text/plain"
  delegate_to: localhost
  run_once: true
  ignore_errors: true
```

| Метрика | Описание | Алерт |
| :--- | :--- | :--- |
| `ansible_playbook_duration_seconds` | Время выполнения плейбука | > 600 сек |
| `puppet_agent_last_run` | Время последнего запуска агента | > 2 часов |
| `salt_job_duration` | Время выполнения salt-задачи | > 300 сек |
| `drift_detection_count` | Количество исправлений drift | > 0 (compliance) |
| `cm_success_rate` | Процент успешных операций | < 95% |

### Стоимость владения (TCO) и выбор модели
Выбор модели влияет не только на технологии, но и на операционные затраты:
- **Push (Низкий TCO на старте):** Минимальные затраты на инфраструктуру. Идеально для стартапов и команд, где админы уже умеют пользоваться SSH.
- **Pull (Экономия на масштабе):** Высокие затраты на внедрение (PKI, жизненный цикл агентов), но значительно меньшие затраты на поддержку при росте парка до 10 000+ узлов, так как риск "затыка" в очереди на выполнение задач контроллером исчезает.

### GitOps: Push vs Pull
В контексте Kubernetes (K8s) разделение становится еще более четким:
*   **Push-GitOps (CI-driven):** Пайплайны (GitLab CI, Jenkins) имеют сертификат кластера и выполняют `kubectl apply`. 
    *   *Риск:* Секреты кластера хранятся в CI-системе.
*   **Pull-GitOps (Operator-driven):** Внутри кластера работает ArgoCD/Flux. 
    *   *Преимущество:* Секреты не покидают кластер. Выше безопасность. Контроллер автоматически исправляет ручные правки в K8s.

### Безопасность и сетевая топология
*   **Push-безопасность:** Основная проблема — хранение приватных ключей SSH на Control Node. Рекомендуется использовать SSH-агенты и системы JIT-доступа (Just-in-Time). При компрометации контроллера злоумышленник получает доступ ко всей инфраструктуре (Lateral Movement).
*   **Pull-безопасность:** Безопасность строится на взаимной TLS-аутентификации (mTLS). Агент должен иметь сертификат, подписанный доверенным CA (Certificate Authority).

### Гибридные подходы
В современных enterprise-инфраструктурах часто используют обе модели:
1.  **Ansible (Push)** используется для **Bootstrap** (начальной настройки) системы: создание пользователей, настройка сети и установка агента (Puppet/Salt).
2.  **Pull-агент** берет на себя долгосрочное управление и соблюдение политик безопасности.
3.  **SaltStack** предлагает уникальный баланс: постоянные агенты (Pull) связаны с мастером через шину событий (ZeroMQ), что позволяет мастеру мгновенно «проталкивать» команды (Push-over-Pull).

**См. также:**
*   **[Модели управления конфигурацией](./configuration_management_models.md)**
*   **[Инструменты управления конфигурацией](./configuration_management_tools.md)**
*   **[Инфраструктура как код (IaC)](./iac_overview.md)**
*   **[GitOps: Обзор](../GitOps/GitOps_overview.md)**
*   **[Ansible Pull — управление в pull-режиме](../Ansible/ansible_pull.md)**
