# Ansible Pull — управление конфигурацией в pull-режиме

## Определения

**Ansible Pull** — это системная утилита, реализующая **pull-модель** управления конфигурацией в экосистеме Ansible. В отличие от стандартной **[push-модели](./ansible_core_concepts.md#определения)**, где контрольный узел инициирует соединение и активно передает конфигурацию на управляемые машины, `ansible-pull` позволяет узлам самостоятельно запрашивать, скачивать и применять конфигурацию.

Технически это скрипт на Python, который объединяет функционал `git` и `ansible-playbook`: он клонирует Git-репозиторий и запускает плейбук (обычно `local.yml`) непосредственно на локальной машине (`localhost`).

## Предварительные требования

Для использования `ansible-pull` необходимо выполнение следующих условий:

- **Python:** версия 3.11–3.14 (рекомендуется 3.12 или 3.13)
- **Ansible Core:** версия 2.18+ (актуальные поддерживаемые: 2.18, 2.19, 2.20, 2.21; рекомендуется целевая версия проекта)
- **Git:** версия 2.34+ (установлен и доступен в `$PATH`)
- **Доступ к Git-серверу:** HTTPS или SSH (с соответствующими ключами/токенами)
- **Systemd или Cron:** для периодического запуска по расписанию
- **Пользователь:** рекомендуется отдельный непривилегированный пользователь для запуска `ansible-pull`

Проверка версий:
```bash
ansible --version        # → ansible-core 2.21.x
python3 --version       # → Python 3.12.x
git --version           # → git version 2.42.x
systemctl --version     # → systemd 255+
```

## Основные концепции

В pull-режиме управляемые узлы (ноды) становятся активными инициаторами изменений. Вместо того чтобы центральный сервер подключался к сотням или тысячам машин, каждая машина обращается к Git-репозиторию по расписанию (через **Systemd Timers** или **Cron**), скачивает актуальное описание желаемого состояния и применяет его к себе.

### Архитектурная схема

```
┌─────────────────────────────────────────────────────────────────┐
│                    ЦЕНТРАЛЬНЫЙ ГИТ-СЕРВЕР                       │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Репозиторий конфигурации:                              │   │
│  │  - local.yml (главный плейбук)                          │   │
│  │  - roles/ (роли Ansible)                                │   │
│  │  - collections/requirements.yml (зависимости)           │   │
│  │  - host_vars/ и group_vars/ (переменные)               │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────┬───────────────────────────────────────────┘
                      │ git clone (исходящее соединение)
          ┌───────────┼───────────┐
          ▼           ▼           ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ Узел A (web-01)  │ │ Узел B (db-01)   │ │ Узел C (app-01)  │
│ ┌──────────────┐ │ │ ┌──────────────┐ │ │ ┌──────────────┐ │
│ │ ansible-pull │ │ │ │ ansible-pull │ │ │ │ ansible-pull │ │
│ │ (systemd)    │ │ │ │ (systemd)    │ │ │ │ (systemd)    │ │
│ └──────────────┘ │ │ └──────────────┘ │ │ └──────────────┘ │
│ localhost:       │ │ localhost:        │ │ localhost:        │
│  connection=local│ │  connection=local │ │  connection=local │
└──────────────────┘ └──────────────────┘ └──────────────────┘
```

### Преимущества

* **Масштабируемость:** Нагрузка на контрольный узел практически отсутствует. Ограничением становится только пропускная способность Git-сервера, что легко решается через зеркалирование или использование read-only реплик.
* **Автономность и мобильность:** Узлы могут обновляться даже при нахождении за NAT, использовании динамических IP-адресов или нестабильном подключении к сети (например, Edge-устройства или ноутбуки).
* **Децентрализация:** Идеально подходит для филиальных офисов, отдельно стоящих дата-центров и базовых станций, где управляемые машины находятся в разных сегментах сети без постоянного VPN-туннеля к центральному серверу.
* **Безопасность:** Управляемые узлы инициируют только исходящие соединения (HTTPS/SSH), что упрощает настройку файрволов и снижает поверхность атаки.
* **Живучесть (Resilience):** При отсутствии связи с центральным репозиторием узел продолжает работать в текущем состоянии. Восстановление связи происходит автоматически без участия администратора.

### Недостатки и риски

* **Управление секретами:** Требует безопасного хранения или передачи паролей Vault и SSH-ключей на каждый узел. В корпоративной среде это решается через интеграцию с локальными Key Management Service (KMS) или Hardware Security Module (HSM).
* **Зависимость от локального ПО:** На каждой машине должны быть предварительно установлены Python, Git и Ansible. В среде с жестким compliance требуется формализованная процедура управления пакетами.
* **Трудности с координацией:** Сложно выполнять задачи, требующие синхронизации между несколькими хостами (например, последовательное обновление компонентов кластера). Для этого требуется комбинация push- и pull-моделей.
* **Латентность:** Задержка между появлением изменения в Git и его применением на узле зависит от интервала опроса (polling interval). В системах с высокими требованиями к скорости распространения изменений (RTO) требуется уменьшение интервала или использование webhooks.
* **Отсутствие ad-hoc команд:** Невозможно выполнить разовую команду на всех узлах одновременно (требуется push-режим).
* **Управление состоянием (State Reconciliation):** При каждом запуске `ansible-pull` применяет конфигурацию к текущему состоянию системы. При наличии ручных изменений (configuration drift) возможен конфликт. Требуется формализованный процесс управления изменениями (Change Management).
* **Согласованность версий:** При использовании тегов или веток в Git требуется поддержка механизма канарейкового развертывания (canary deployment) для снижения риска распространения неработающей конфигурации на весь парк.

## Параметры командной строки

### Полная таблица опций

| Опция | Описание | Пример |
| :--- | :--- | :--- |
| `-U`, `--url` | URL Git-репозитория (обязательный) | `-U https://github.com/user/repo.git` |
| `-C`, `--checkout` | Ветка, тег или хэш коммита | `-C production`, `-C v1.2.3` |
| `-d`, `--directory` | Директория для клонирования | `-d /opt/ansible-pull` |
| `-i`, `--inventory` | Инвентарь (обычно `localhost,`) | `-i localhost,` |
| `-l`, `--limit` | Ограничение целевых хостов | `-l webservers` |
| `-e`, `--extra-vars` | Дополнительные переменные | `-e "env=prod version=1.0"` |
| `-f`, `--forks` | Количество параллельных процессов | `-f 10` |
| `-v`, `--verbose` | Уровень детализации вывода | `-vvv` |
| `-m`, `--module-name` | Модуль для запуска (вместо плейбука) | `-m setup` |
| `-M`, `--module-path` | Путь к дополнительным модулям | `-M ./plugins/modules` |
| `-S`, `--setup` | Скрипт инициализации после клонирования | `-S bootstrap.sh` |
| `-s`, `--sleep` | Случайная задержка до N секунд | `-s 60` |
| `-o`, `--only-if-changed` | Запуск только при изменениях в Git | `-o` |
| `--full` | Полное клонирование (без shallow) | `--full` |
| `--purge` | Удаление репозитория после выполнения | `--purge` |
| `--verify-commit` | Проверка GPG-подписи коммита | `--verify-commit` |
| `--accept-host-key` | Автоматическое добавление ключа хоста | `--accept-host-key` |
| `--vault-id` | Идентификатор Vault для пароля | `--vault-id prod@script.sh` |
| `--vault-password-file` | Файл с паролем Vault | `--vault-password-file ~/.vault_pass` |
| `--tags` | Запуск задач с определенными тегами | `--tags "deploy,config"` |
| `--skip-tags` | Пропуск задач с тегами | `--skip-tags "test"` |
| `--start-at-task` | Начало выполнения с указанной задачи | `--start-at-task "deploy"` |
| `-k`, `--ask-pass` | Запрос пароля SSH | `-k` |
| `-K`, `--ask-become-pass` | Запрос пароля для become | `-K` |
| `--private-key` | Путь к приватному SSH-ключу | `--private-key ~/.ssh/id_ed25519` |

### Примеры сложных команд

**Запуск с фильтрацией по тегам и переменным:**
```bash
ansible-pull \
  -U https://github.com/user/config.git \
  -C main \
  -e "env=staging deploy_version=2.1.0" \
  --tags "deploy,healthcheck" \
  --skip-tags "backup" \
  -i localhost, \
  local.yml
```

**Запуск с ограничением по конкретным задачам:**
```bash
ansible-pull \
  -U https://github.com/user/config.git \
  -C main \
  --start-at-task "restart nginx" \
  -i localhost, \
  local.yml
```

**Запуск модуля вместо плейбука (ad-hoc через pull):**
```bash
ansible-pull \
  -U https://github.com/user/config.git \
  -m setup \
  -i localhost, \
  --tags "gather_facts"
```

## Практические сценарии

### Базовый запуск с публичным репозиторием

По умолчанию `ansible-pull` ищет плейбук с именем `local.yml` или по имени хоста (FQDN). Для обеспечения безопасности и чистоты окружения рекомендуется использовать дополнительные флаги проверки и очистки.

```bash
ansible-pull \
  -U https://github.com/user/ansible-config.git \
  -C production \
  -d /opt/ansible-pull \
  --verify-commit \
  --purge \
  -i localhost, \
  local.yml
```

* `-U` (`--url`): URL Git-репозитория.
* `-C` (`--checkout`): Ветка, тег или хэш коммита для загрузки.
* `-d` (`--directory`): Путь для клонирования (рекомендуется абсолютный путь).
* `--verify-commit`: Проверка GPG-подписи коммита перед выполнением (защита от компрометации репозитория).
* `--purge`: Удаление склонированного репозитория после завершения работы (предотвращает утечку структуры проекта).
* `-i` (`--inventory`): Список хостов. Для pull-режима это почти всегда `localhost,`.
* `local.yml`: Имя плейбука для запуска.

### Продвинутые параметры запуска

* **`--sleep [N]`**: Добавляет случайную задержку до N секунд перед началом работы. Это критически важно при одновременном запуске на сотнях узлов (например, через Cron), чтобы не перегрузить Git-сервер или сетевой канал.
* **`-o` (`--only-if-changed`)**: Плейбук запускается только в том случае, если в репозитории появились новые коммиты. Значительно экономит ресурсы CPU и время выполнения.
* **`--full`**: При клонировании скачивает всю историю репозитория (по умолчанию выполняется shallow clone для ускорения).
* **`--accept-host-key`**: Автоматически добавляет ключ хоста Git-сервера в `known_hosts` (использовать с осторожностью).

### Работа с зависимостями (Collections и Roles)

Если ваш проект использует внешние коллекции или роли, их необходимо установить перед основным запуском. Для этого используется флаг `-S` (`--setup`), который позволяет запустить скрипт инициализации сразу после клонирования репозитория.

**Пример скрипта `bootstrap.sh`:**
```bash
#!/bin/bash
# Установка зависимостей из requirements.yml
ansible-galaxy collection install -r requirements.yml --force
ansible-galaxy role install -r requirements.yml --force
```

**Запуск с инициализацией:**
```bash
ansible-pull -U <url> -S bootstrap.sh local.yml
```

**Современный подход с `collections/requirements.yml`:**
```yaml
# collections/requirements.yml
collections:
  - name: community.general
    version: ">=8.0.0"
  - name: ansible.posix
  - name: ansible.mysql

roles:
  - name: geerlingguy.docker
    version: ">=8.0.0"
  - name: geerlingguy.nginx
    version: ">=3.3.0"
```

### Доступ к приватным репозиториям

Для доступа к приватным репозиториям используются SSH-ключи (Deploy Keys). Рекомендуется настроить SSH-конфиг для пользователя, от которого запускается `ansible-pull`.

```bash
ansible-pull \
  -U git@github.com:user/ansible-private-config.git \
  -d /opt/ansible-pull \
  local.yml
```

**Использование Git-токенов (GitHub/GitLab):**
```bash
# GitHub Personal Access Token
ansible-pull \
  -U https://<token>@github.com/user/private-repo.git \
  -d /opt/ansible-pull \
  local.yml

# GitLab Personal Access Token
ansible-pull \
  -U https://oauth2:<token>@gitlab.com/user/repo.git \
  -d /opt/ansible-pull \
  local.yml
```

**Настройка SSH-конфига (~/.ssh/config):**
```
Host github.com
    IdentityFile ~/.ssh/ansible_pull_key
    IdentitiesOnly yes
    StrictHostKeyChecking no
```

### Использование переменных и управление логикой

Для адаптации конфигурации под конкретный узел используются дополнительные переменные (`extra-vars`).

```bash
ansible-pull \
  -U https://github.com/user/ansible-config.git \
  -e "env=production role=webserver site=office1" \
  local.yml
```

**Переменные из файла:**
```bash
ansible-pull \
  -U https://github.com/user/ansible-config.git \
  -e "@vars/host_specific.yml" \
  local.yml
```

**Пример файла `vars/host_specific.yml`:**
```yaml
---
env: production
role: webserver
site: office1
app_version: "2.1.0"
enable_monitoring: true
enable_logging: true
```

**Автоматическое определение окружения:**
```bash
# Определение окружения по имени хоста
ansible-pull \
  -U https://github.com/user/ansible-config.git \
  -e "env={{ 'production' if 'prod' in ansible_hostname else 'staging' }}" \
  local.yml
```

### Работа с секретами (Ansible Vault)

В режиме pull хосту необходим доступ к паролю Vault.

**Рекомендуемый подход (современный):** Использование `--vault-id` со скриптом, получающим пароль из защищенного хранилища (HashiCorp Vault — on-prem или self-hosted, или системный keyring).

```bash
ansible-pull \
  -U https://github.com/user/ansible-config.git \
  --vault-id prod@/usr/local/bin/get_vault_pass.sh \
  local.yml
```

Скрипт `get_vault_pass.sh` должен возвращать пароль в `stdout` и иметь права доступа `0700`. Использование `--vault-password-file` также поддерживается, но `--vault-id` обеспечивает большую гибкость при работе с несколькими хранилищами.

**Пример скрипта `get_vault_pass.sh` (HashiCorp Vault — on-prem или self-hosted):**
```bash
#!/bin/bash
# Получение пароля из HashiCorp Vault
export VAULT_ADDR='https://vault.company.com:8200'
export VAULT_TOKEN=$(cat /etc/vault/token)

vault kv get -field=password secret/ansible/vault_password
```

**Пример скрипта `get_vault_pass.sh` (системный keyring):**
```bash
#!/bin/bash
# Получение пароля из системного keyring (Linux Secret Service API)
secret-tool lookup service ansible-vault
```

## Автоматизация по расписанию

### Systemd Timers (рекомендуемый подход)

Использование **Systemd Timers** является современным отраслевым стандартом. Оно предпочтительнее **Cron** благодаря интеграции с `journalctl`, возможности контроля зависимостей и гибкому управлению расписанием.

1. **Создайте сервис (`/etc/systemd/system/ansible-pull.service`):**
```ini
[Unit]
Description=Ansible Pull Service
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
# -o (only-if-changed): выполнять запуск только при наличии обновлений в Git
# -s 60: случайная задержка до 60 секунд перед началом для распределения нагрузки
ExecStart=/usr/bin/ansible-pull -o -s 60 -U https://github.com/user/repo.git -d /opt/ansible local.yml
StandardOutput=journal
```

2. **Создайте таймер (`/etc/systemd/system/ansible-pull.timer`):**
```ini
[Unit]
Description=Run Ansible Pull periodically

[Timer]
OnCalendar=hourly
Persistent=true
# Дополнительный разброс запуска для предотвращения одновременного обращения сотен нод к Git
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

3. **Активация и управление:**
```bash
# Активация таймера
sudo systemctl daemon-reload
sudo systemctl enable --now ansible-pull.timer

# Проверка статуса
sudo systemctl status ansible-pull.timer
sudo systemctl list-timers --all | grep ansible

# Просмотр логов
sudo journalctl -u ansible-pull.service

# Ручной запуск
sudo systemctl start ansible-pull.service
```

### Cron (классический подход)

```bash
# Редактирование crontab для пользователя root
sudo crontab -e

# Запуск каждый час с случайной задержкой до 5 минут
0 * * * * /usr/bin/sleep $((RANDOM \% 300)) && /usr/bin/ansible-pull -o -U https://github.com/user/repo.git -d /opt/ansible -i localhost, local.yml >> /var/log/ansible-pull.log 2>&1

# Запуск каждые 30 минут
*/30 * * * * /usr/bin/ansible-pull -o -U https://github.com/user/repo.git -d /opt/ansible -i localhost, local.yml >> /var/log/ansible-pull.log 2>&1

# Запуск каждый день в 3:00
0 3 * * * /usr/bin/ansible-pull -o -U https://github.com/user/repo.git -d /opt/ansible -i localhost, local.yml >> /var/log/ansible-pull.log 2>&1
```

**Более безопасный подход с отдельным скриптом:**
```bash
#!/bin/bash
# /usr/local/bin/ansible-pull-wrapper.sh
set -euo pipefail

LOCKFILE="/run/ansible-pull.lock"
LOGFILE="/var/log/ansible-pull.log"
REPO_URL="https://github.com/user/repo.git"
WORKDIR="/opt/ansible"

exec 200>"$LOCKFILE"
flock -n 200 || { echo "Another instance is running"; exit 1; }

{
    echo "=== $(date) ==="
    cd "$WORKDIR"
    ansible-pull -o -U "$REPO_URL" -d "$WORKDIR" -i localhost, local.yml
    echo "=== Completed $(date) ==="
} >> "$LOGFILE" 2>&1
```

### Сравнение: Systemd Timer vs Cron

| Характеристика | Systemd Timer | Cron |
| :--- | :--- | :--- |
| **Журналирование** | Встроенное через `journalctl` | Требует редиректа в файл |
| **Зависимости** | `After=`, `Wants=` (управление порядком запуска) | Нет встроенной поддержки |
| **Расписание** | Гибкое (календарь, интервалы, boot-time) | crontab-синтаксис |
| **Управление** | `systemctl start/stop/enable` | `crontab -e/-l` |
| **Персистентность** | `Persistent=true` (выполнение при пропуске) | Зависит от реализации |
| **Отладка** | `systemctl list-timers`, `journalctl -u` | Просмотр лог-файлов |
| **Производительность** | Легче для частых запусков | Каждый запуск — новый процесс |

## Безопасность и управление доступом

Pull-модель инвертирует риски безопасности: каждый узел получает доступ к репозиторию с кодом инфраструктуры.

*   **Разделение репозиториев:** Не храните конфигурацию всей инфраструктуры в одном репозитории. Используйте отдельные репозитории для разных функциональных групп (например, `frontend-config`, `db-config`), чтобы компрометация одного узла не привела к утечке данных о всей сети.
*   **Deploy Tokens вместо SSH-ключей:** Для доступа к приватным репозиториям используйте Git Deploy Tokens с правами **только на чтение (Read-Only)**. Никогда не используйте личные SSH-ключи администраторов на управляемых узлах.
*   **Ansible Vault + External Secrets:** Используйте `no_log: true` в задачах, обрабатывающих секреты. Для динамического получения паролей рекомендуется использовать lookup-плагины для интеграции с **HashiCorp Vault** (on-prem или self-hosted) или системными keyring (Linux Secret Service API), вместо хранения файлов с паролями на диске.
*   **GPG-проверка коммитов:** Всегда используйте флаг `--verify-commit`, чтобы убедиться, что код не был подменен злоумышленником на стороне Git-сервера.
*   **Ограничение прав:** Запускайте `ansible-pull` от отдельного пользователя с минимальными правами (не от root), если это возможно.

### Рекомендуемая структура репозитория

```
ansible-config/
├── local.yml                    # Главный плейбук
├── requirements.yml             # Зависимости (collections, roles)
├── bootstrap.sh                 # Скрипт инициализации
├── ansible.cfg                  # Конфигурация Ansible
├── inventory/
│   ├── production/
│   │   ├── hosts                # Инвентарь production
│   │   └── group_vars/
│   │       ├── all.yml          # Общие переменные
│   │       ├── webservers.yml   # Переменные для веб-серверов
│   │       └── dbservers.yml    # Переменные для БД
│   └── staging/
│       ├── hosts
│       └── group_vars/
├── roles/
│   ├── common/
│   ├── nginx/
│   ├── postgresql/
│   └── monitoring/
├── collections/
│   └── requirements.yml
├── plugins/
│   ├── modules/
│   └── lookup/
└── tests/
    └── integration/
```

## Логирование и мониторинг

Поскольку `ansible-pull` запускается локально и автономно, стандартный вывод в консоль неэффективен для контроля состояния парка машин.

### Централизованный сбор логов

*   Настройте `log_path` в `ansible.cfg` (например, `/var/log/ansible-pull.log`).
*   Используйте callback-плагины (например, `community.general.log_plays`) для отправки данных в **ELK (Elasticsearch/Logstash/Kibana)** или **Graylog**.
*   Настройте `syslog` или `rsyslog` для перенаправления логов в центральный сервер.

**Пример `ansible.cfg` для централизованного логирования:**
```ini
[defaults]
log_path = /var/log/ansible-pull.log
callback_whitelist = timer, profile_tasks, profile_roles

[inventory]
enable_plugins = host_list, script, yaml, ini
```

**Пример syslog-конфигурации (`/etc/rsyslog.d/ansible-pull.conf`):**
```
# Отправка логов ansible-pull в центральный сервер
local0.* @@logserver.company.com:514
```

### Мониторинг и метрики

*   **Zabbix/Prometheus:** Используйте финальную задачу для отправки метрики (timestamp) через `uri` модуль в Prometheus Pushgateway или Zabbix Sender. Если метрика не обновлялась долгое время — значит, pull перестал работать.
*   **Уведомления:** Настройте отправку алертов в Telegram/Slack при возникновении ошибок (`failed_when` или `rescue` блоки).

**Пример задачи для отправки метрики в Prometheus:**
```yaml
# В конце плейбука local.yml
- name: Отправка метрики успешного выполнения
  uri:
    url: "http://pushgateway:9091/metrics/job/ansible_pull/instance/{{ inventory_hostname }}"
    method: PUT
    body: |
      ansible_pull_success_timestamp {{ ansible_date_time.epoch }}
      ansible_pull_success_count 1
    headers:
      Content-Type: "text/plain"
  delegate_to: localhost
  run_once: true
  ignore_errors: true
```

**Пример уведомления в Telegram:**
```yaml
- name: Уведомление об ошибке
  uri:
    url: "https://api.telegram.org/bot{{ telegram_bot_token }}/sendMessage"
    method: POST
    body_format: json
    body:
      chat_id: "{{ telegram_chat_id }}"
      text: "❌ Ansible-pull failed on {{ inventory_hostname }}: {{ ansible_failed_task }}"
  when: ansible_failed_task is defined
  delegate_to: localhost
  ignore_errors: true
```

## GitOps и управление изменениями (Change Management)

Pull-модель инвертирует стандартное управление изменениями: код конфигурации хранится в Git, а каждый узел самостоятельно применяет изменения.

### Принципы GitOps для ansible-pull

* **Ветвление сред:** Используйте отдельные ветки или теги для staging и production (`staging`, `production`, `v1.2.3`). Узлы production должны ссылаться на стабильный тег, а не на ветку `main`.
* **Обязательный Code Review:** Все изменения в конфигурации проходят через Merge Request с approval минимум от одного второго администратора. Автоматический merge в `main` запрещен.
* **Защита ветки `main`:** Ветка `main` защищена: требуется подпись коммитов (GPG), прохождение CI-проверок (sanity-тесты), успешное слияние.
* **Канареечное развертывание (Canary):** Применяйте изменения сначала на ограниченной группе узлов (канарейки), наблюдайте за метриками в течение N минут, затем распространяйте на весь парк.
* **Откат (Rollback):** При возникновении проблем выполните откат через Git: переключите узел на предыдущий стабильный тег (`-C v1.2.2`) и перезапустите `ansible-pull`.
* **Аудит изменений:** Каждый коммит содержит ссылку на задачу в трекере (Jira, Redmine), номер изменения (RFC), имя администратора. Используйте формат Conventional Commits (`feat:`, `fix:`, `chore:`, `docs:`).

### Процедура изменения (Change Management)

1. Создание ветки от текущего стабильного тега production.
2. Разработка и тестирование в staging.
3. Создание Merge Request с описанием изменений, рисков, плана отката.
4. Обязательный Code Review + approval.
5. Слияние в `main` после прохождения CI-проверок.
6. Подпись коммита GPG-ключом.
7. Создание тега production (`v1.2.3`) с подписью.
8. Обновление узлов production через `-C v1.2.3`.

### Интеграция с CI/CD пайплайном

```yaml
# Пример GitLab CI для проверки ansible-pull конфигурации
stages:
  - sanity
  - test
  - deploy

sanity:
  stage: sanity
  script:
    - ansible-test sanity --docker default

test_staging:
  stage: test
  script:
    - ansible-pull -U $REPO_URL -C staging -d /tmp/ansible-test local.yml --check

deploy_production:
  stage: deploy
  script:
    - git tag -a v$CI_COMMIT_SHORT_SHA -m "Release $CI_COMMIT_SHORT_SHA"
    - git push origin v$CI_COMMIT_SHORT_SHA
  only:
    - tags
```

## Безопасность и аудит (Security & Audit)

### Управление доступом

* **Отдельный пользователь:** Создайте непривилегированного пользователя (например, `ansible-pull`) с минимальными правами. Используйте `sudo` только для необходимых операций.
* **SSH-ключи:** Используйте отдельные Deploy Keys для доступа к репозиторию. Ключ должен иметь тип `ed25519`, длину 4096 бит, парольную фразу (ssh-agent).
* **Ограничение прав ключа:** В `authorized_keys` укажите ограничения: `no-port-forwarding`, `no-X11-forwarding`, `no-agent-forwarding`, `no-pty`, `command="git-upload-pack 'repo.git'"`.
* **Rotate credentials:** Регулярно ротируруйте SSH-ключи (каждые 90 дней) и Vault-пароли (каждые 30 дней). Отслеживайте срок действия в CMDB.

### Аудит и compliance

* **Подпись коммитов:** Все изменения в конфигурации подписываются GPG-ключом администратора. Верификация происходит через `--verify-commit`.
* **Журнал изменений:** Настройте `git log --pretty=format:"%h %an %ad %s" --date=short` для просмотра истории изменений с указанием автора и даты.
* **Контроль целостности:** Настройте `git fsck` для проверки целостности репозитория после клонирования.
* **Секреты в Git:** Никогда не храните секреты (пароли, ключи, токены) в Git-репозитории. Используйте `ansible-vault encrypt` или внешние секретные хранилища.
* **Сканирование зависимостей:** Используйте `ansible-galaxy collection install --force` с проверкой подлинности коллекций через `--server https://galaxy.ansible.com` и `--api-key`.

### Изоляция сети

* **Outbound только:** Узлы ansible-pull должны иметь доступ только к Git-серверу (порт 443/22) и системам логирования. Доступ к остальным ресурсам сети запрещен.
* **Нет inbound:** На узлах закрыты все входящие порты. Управление происходит только через исходящие соединения.
* **Внутренний Git-сервер:** Для критичных сред используйте внутренний Git-сервер (например, GitLab CE) с replica и backup. Внешние сервисы (GitHub, GitLab.com) разрешены только для не критичных сред.

## Pre-commit hooks

Настройте pre-commit hooks для автоматической проверки конфигурации перед коммитом:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/ansible/ansible-lint
    rev: v26.8.0
    hooks:
      - id: ansible-lint
        files: \.(yaml|yml)$
        args: ['--force-color']
  
  - repo: https://github.com/adrienverge/yamllint
    rev: v1.35.1
    hooks:
      - id: yamllint
        files: \.(yaml|yml)$
        args: ['-d', '{extends: default, rules: {line-length: {max: 160}}}']
  
  - repo: https://github.com/PyCQA/flake8
    rev: 7.1.1
    hooks:
      - id: flake8
        files: \.py$
        args: ['--max-line-length=160']
```

Установка:
```bash
pip install pre-commit ansible-lint yamllint flake8
pre-commit install
```

## Поиск и устранение неисправностей (Troubleshooting)

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `ERROR: Repository not found` | Неверный URL или отсутствие доступа | Проверьте URL и права доступа к репозиторию |
| `ERROR: Permission denied (publickey)` | Отсутствие SSH-ключа | Настройте SSH-ключ или используйте HTTPS с токеном |
| `ERROR: ModuleNotFoundError` | Отсутствие Python-зависимостей | Установите required packages |
| `ERROR: AnsibleUndefinedVariable` | Не определена переменная | Проверьте `group_vars/` и `host_vars/` |
| `ERROR: Vault password not set` | Отсутствует пароль Vault | Настройте `--vault-id` или `--vault-password-file` |
| `ERROR: Git clone failed` | Проблемы с сетью или Git-сервером | Проверьте доступ к сети и URL репозитория |
| `ERROR: Module not found` | Отсутствует коллекция или роль | Настройте `requirements.yml` и скрипт `bootstrap.sh` |
| `CRITICAL: No such file or directory` | Неверный путь к плейбуку | Укажите полное имя плейбука (например, `playbooks/site.yml`) |
| `ERROR: Unable to parse inventory` | Ошибка в файле инвентаря | Проверьте синтаксис `inventory/hosts` |
| `WARN: The host is currently in check mode` | Плейбук запущен в check mode | Используйте `--check` только для проверки |

### Диагностические команды

```bash
# Просмотр логов systemd
sudo journalctl -u ansible-pull.service -f
sudo journalctl -u ansible-pull.service --since "1 hour ago"

# Ручной запуск с подробным выводом
sudo ansible-pull -vvv -U https://github.com/user/repo.git -d /opt/ansible -i localhost, local.yml

# Проверка Git-репозитория
cd /opt/ansible && git status && git log --oneline -5

# Проверка версий компонентов
ansible --version
python3 --version
git --version

# Проверка подключения к Git-серверу
ssh -T git@github.com
git ls-remote https://github.com/user/repo.git

# Проверка прав доступа
ls -la /opt/ansible/
id ansible_pull_user
```

### Отладка через ANSIBLE_KEEP_REMOTE_FILES

Если модуль падает с невнятной ошибкой, установите переменную окружения `ANSIBLE_KEEP_REMOTE_FILES=1`. Ansible не удалит временный файл на удаленном узле. Вы сможете зайти на хост и запустить его вручную:
```bash
export ANSIBLE_KEEP_REMOTE_FILES=1
ansible-pull -U <url> local.yml
# Затем на хосте:
python3 ~/.ansible/tmp/ansible-tmp-.../AnsiballZ_module.py explode
cd debug_dir
python3 ansible_module_module.py args.json
```

### Решение проблем с блокировками (Race Conditions)

Если запуск происходит часто, возможны наслоения процессов. Используйте утилиту `flock` для предотвращения одновременного выполнения:

```bash
# Обертка для cron
flock -n /run/ansible-pull.lock ansible-pull -U <url> -d /opt/ansible -i localhost, local.yml

# Или с таймаутом (600 секунд = 10 минут)
flock -w 600 -n /run/ansible-pull.lock ansible-pull -U <url> -d /opt/ansible -i localhost, local.yml
```

### Решение проблем с дрейфом артефактов (Artifact Drift)

Если вы не используете `--purge`, локальные изменения или неудачные слияния могут вызвать конфликты в Git. При возникновении ошибок очистите директорию `-d` вручную:

```bash
# Очистка и повторное клонирование
sudo rm -rf /opt/ansible
sudo ansible-pull -U https://github.com/user/repo.git -d /opt/ansible -i localhost, local.yml

# Использование git reset для восстановления
cd /opt/ansible
sudo git fetch origin
sudo git reset --hard origin/main
```

## Интеграция с CI/CD

### GitHub Actions: Триггер ansible-pull на удаленных узлах

```yaml
name: Trigger Ansible Pull
on:
  push:
    branches: [main]
    paths:
      - 'ansible/**'

jobs:
  trigger-pull:
    runs-on: ubuntu-latest
    steps:
      - name: Trigger ansible-pull на серверах
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.SERVER_HOSTS }}
          username: ${{ secrets.SERVER_USER }}
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            sudo systemctl start ansible-pull.service
```

### GitLab CI: Автоматический запуск ansible-pull

```yaml
stages:
  - deploy

trigger-pull:
  stage: deploy
  script:
    - |
      for host in $SERVER_LIST; do
        ssh $host "sudo systemctl start ansible-pull.service"
      done
  only:
    - main
  when: on_success
```

## Рекомендации и лучшие практики

1.  **Безусловная идемпотентность:** Плейбуки должны быть строго идемпотентными. Любое отклонение приведет к бесконечным попыткам изменения системы при каждом запуске.
2.  **Локальное соединение:** Всегда используйте `hosts: localhost` и `connection: local`.
3.  **Случайная задержка (Jitter):** Всегда используйте `--sleep` (для `ansible-pull`) или `RandomizedDelaySec` (для systemd), чтобы распределить нагрузку на Git-сервер.
4.  **Контроль версий:** Используйте конкретные ветки или теги (`-C`) для разных сред (staging, production). Ветка `main` защищена GPG-подписью и Code Review.
5.  **Минимализм на узле:** Устанавливайте на управляемые узлы только необходимые зависимости для работы Ansible. Используйте containerized deployment (Podman) если возможно.
6.  **Тестирование:** Тестируйте изменения плейбуков в staging перед применением в production. Используйте `--check` для dry-run.
7.  **Мониторинг и наблюдаемость:** Настройте отправку метрик (Prometheus Pushgateway) и уведомлений (Telegram, Slack) для контроля состояния pull-модели.
8.  **Управление секретами:** Используйте `--vault-id` со скриптами, получающими пароли из локальных секретных хранилищ (HashiCorp Vault, системный keyring). Никогда не храните секреты в Git.
9.  **Безопасность:** Запускайте `ansible-pull` от непривилегированного пользователя с минимальными правами. Используйте Deploy Keys с ограничениями (`no-port-forwarding`, `no-agent-forwarding`).
10. **Отказоустойчивость (Resilience):** Используйте `--purge` для предотвращения накопления артефактов. Используйте `flock` для предотвращения race conditions. Настройте мониторинг для обнаружения остановки таймера.
11. **Изменения:** Используйте Conventional Commits (`feat:`, `fix:`, `chore:`). Подписывайте коммиты GPG. Создавайте теги для версионирования. Используйте Merge Request с approval для Code Review.
12. **Документация:** В репозитории должен быть README с описанием архитектуры, процесса изменения, контактами ответственных. Используйте CHANGELOG для истории изменений.
13. **Согласованность:** Используйте единый `ansible.cfg` для всех узлов. Настройте callback-плагины для единого формата вывода. Используйте единую версию ansible-core на всех узлах.
14. **Change Management:** Используйте канареечное развертывание (canary). Настройте откат (rollback) через Git. Используйте `--only-if-changed` для экономии ресурсов.
15. **Аудит:** Настройте `log_path` в `ansible.cfg`. Используйте callback-плагины для отправки логов в центральный сервер (ELK, Graylog). Архивируйте логи в соответствии с политикой retention.

## Дополнительная информация

- [Модели доставки конфигурации: Push vs Pull](../Concepts/configuration_management_push_vs_pull.md) — детальное сравнение архитектурных подходов.
- [Основные концепции Ansible](./ansible_core_concepts.md#определения) — базовая терминология и принципы работы.
- [HashiCorp Vault: Обзор](./Vault/overview.md) — методы шифрования и управления секретами.
- [Таймеры systemd](../../Linux/Core/systemd/timers.md) — подробное руководство по настройке расписаний в Linux.
- [Управление задачами через cron](../../Linux/SystemAdministration/cron.md) — классический метод планирования задач.
- [Традиционная инфраструктура: Deployment](../CI-CD/Deployment_Strategies/traditional_infrastructure.md) — практические примеры использования ansible-pull в CI/CD.
