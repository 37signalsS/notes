# Salt-SSH продвинутый

## Определения

- **Roster**: Файл `/etc/salt/roster` (или `-i roster`) содержащий список целевых хостов для Salt-SSH с параметрами подключения (host, user, port, sudo, priv).
- **Thin mode**: Режим Salt-SSH, при котором на целевой хост копируется минимальный набор Python-библиотек (`salt-thin`) в `/tmp/`, выполняется команда, и файлы удаляются. Не требует установки Salt на целевом хосте.
- **Pre-flight commands**: Команды, выполняемые Salt-SSH на целевом хосте перед запуском thin-режима (установка зависимостей, настройка окружения).
- **Roster grains**: Механизм передачи Grains данных через roster-файл для таргетинга.
- **SSH ProxyJump**: Механизм прыжка через промежуточный хост (jump host/bastion) для доступа к хостам в приватных сетях.
- **ControlMaster**: Параметр SSH для мультиплексирования соединений — одно SSH-соединение переиспользуется для нескольких параллельных команд.
- **ssh_wipe**: Параметр roster, управляющий удалением thin-файлов после выполнения (по умолчанию `True`).
- **ssh_scan_ports**: Параметр для сканирования доступных портов SSH на целевом хосте перед подключением.

---

## Основные концепции

### Ограничения Salt-SSH vs Master Mode

| Возможность | Master Mode | Salt-SSH |
|:---|:---:|:---:|
| Beacons | Да | Нет |
| Reactors | Да | Нет |
| Scheduler | Да | Нет |
| Event Bus | Да | Нет |
| Salt-API | Да | Нет |
| Job Cache | Да | Ограничен |
| Pillar | Полный | Через roster/grains |
| File Server | Через Master | Через `salt://` в thin |
| State Apply | Да | Да |
| Execution Modules | Все | Ограниченные |

### Архитектура Salt-SSH

```
Master → SSH → Target Host
  │               │
  │  1. Копирование salt-thin в /tmp/
  │  2. Запуск salt-call --local
  │  3. Возврат результатов
  │  4. Удаление thin-файлов (ssh_wipe: True)
```

---

## Практические сценарии

### 1. Продвинутый Roster файл

```yaml
# /etc/salt/roster
# Базовый entry
web-01:
  host: 192.168.1.10
  user: salt-ssh
  port: 22
  sudo: True
  priv: /etc/salt/ssh_keys/salt_rsa

# Entry с ProxyJump через bastion
db-01:
  host: 10.0.0.50
  user: admin
  port: 22
  sudo: True
  priv: /etc/salt/ssh_keys/salt_rsa
  ssh_options:
    - ProxyJump: bastion.example.com
    - StrictHostKeyChecking: no

# Entry с ControlMaster
app-01:
  host: 10.0.0.100
  user: deploy
  port: 2222
  sudo: True
  priv: /etc/salt/ssh_keys/deploy_rsa
  ssh_options:
    - ControlMaster: auto
    - ControlPath: /tmp/salt-ssh-%r@%h:%p
    - ControlPersist: 300

# Entry с Pre-flight commands
new-server:
  host: 10.0.0.200
  user: root
  port: 22
  sudo: False
  pre_flight: |
    apt-get update && apt-get install -y python3 python3-pip
  ssh_options:
    - StrictHostKeyChecking: no

# Entry с Roster Grains
db-replica:
  host: 10.0.0.60
  user: admin
  port: 22
  sudo: True
  priv: /etc/salt/ssh_keys/salt_rsa
  roster_grains:
    os: Ubuntu
    roles:
      - database
      - replica
    environment: production
```

### 2. SSH ProxyJump через Bastion

**Конфигурация SSH:**

```bash
# /etc/ssh/ssh_config.d/salt-ssh.conf
Host bastion
    HostName bastion.example.com
    User jumpuser
    IdentityFile ~/.ssh/bastion_key

Host 10.0.0.*
    ProxyJump bastion
    User admin
    IdentityFile ~/.ssh/internal_key
```

**Roster:**

```yaml
internal-host:
  host: 10.0.0.50
  user: admin
  port: 22
  sudo: True
  priv: /etc/salt/ssh_keys/salt_rsa
  ssh_options:
    - ProxyJump: bastion.example.com
    - ProxyCommand: ssh -W %h:%p bastion.example.com
```

**Вызов:**

```bash
salt-ssh -i roster internal-host test.ping
# → internal-host: True
```

### 3. Pre-flight команды

```bash
salt-ssh '*' state.apply nginx pre_flight="apt-get update && apt-get install -y python3"
```

**Roster с pre-flight:**

```yaml
debian-hosts:
  host: 10.0.0.10
  user: root
  pre_flight: |
    apt-get update
    apt-get install -y python3 python3-dev libssl-dev
  sudo: False

redhat-hosts:
  host: 10.0.0.20
  user: root
  pre_flight: |
    yum install -y python3 python3-devel openssl-devel
  sudo: False
```

### 4. Сканирование портов

```bash
# Автоматическое определение порта SSH
salt-ssh --scan-ports '10.0.0.0/24' test.ping

# Указание диапазона портов
salt-ssh --scan-ports '10.0.0.0/24' --scan-timeout 5 test.ping
```

### 5. Управление thin-файлами

```bash
# Принудительное удаление thin-файлов
salt-ssh '*' --clean

# Отключение удаления (для отладки)
salt-ssh '*' test.ping ssh_wipe=False

# Проверка thin-файлов на целевом хосте
ssh admin@10.0.0.50 'ls -la /tmp/salt-*'
```

### 6. Salt-SSH с Pillar

```bash
# Передача Pillar данных через --pillar
salt-ssh '*' state.apply nginx pillar='{"nginx": {"worker_processes": 4}}'

# Передача Pillar через файл
salt-ssh '*' state.apply nginx pillar_roots="/srv/pillar" pillarenv=production
```

### 7. Таргетинг в Salt-SSH

```bash
# Globbing
salt-ssh 'web-*' test.ping

# Regex
salt-ssh -E '^(web|app)-*' test.ping

# Список
salt-ssh -L 'web-01,web-02,app-01' test.ping

# Grains (через roster_grains)
salt-ssh -G 'os:Ubuntu' test.ping

# Nodegroups (требует конфигурации на мастере)
salt-ssh -N webservers test.ping
```

### 8. Salt-SSH в CI/CD

```yaml
# .gitlab-ci.yml
salt-ssh-deploy:
  stage: deploy
  image: python:3.12-slim
  before_script:
    - pip install salt
    - eval $(ssh-agent -s)
    - echo "$SSH_PRIVATE_KEY" | tr -d '\r' | ssh-add -
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - echo "$SSH_KNOWN_HOSTS" > ~/.ssh/known_hosts
  script:
    - salt-ssh -i roster 'web-*' state.apply nginx test=True
    - salt-ssh -i roster 'web-*' state.apply nginx
  only:
    - main
  when: manual
```

---

## Дополнительная информация

### Таблица troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| `Salt-SSH error: No auth methods available` | Неверный ключ или пароль | Проверить `priv` путь, права доступа (600) |
| `Salt-SSH error: Connection refused` | SSH не запущен или неверный порт | Проверить `sshd` на целевом хосте, `ssh_scan_ports` |
| `thin` файлы не удаляются | `ssh_wipe: False` или ошибка | `salt-ssh --clean`, проверить `/tmp/salt-*` |
| `ProxyJump` не работает | Bastion недоступен | Проверить SSH-подключение к bastion, `ssh -v` |
| `Pre-flight` падает | Зависимости не установлены | Проверить команды pre-flight, доступ к репозиториям |
| `roster_grains` не применяется | Неверный формат YAML | Проверить иерархию, использовать `salt-ssh --roster-grains` |
| Медленная работа | Нет ControlMaster | Добавить `ControlMaster: auto` в ssh_options |
| `Permission denied` | sudo запрещен | Проверить sudoers на целевом хосте |

### Best practices

1. **Отдельные SSH-ключи**: Используйте отдельную ключевую пару для Salt-SSH, не общую с пользователями.
2. **ControlMaster**: Включайте мультиплексирование для ускорения параллельных операций.
3. **ProxyJump**: Используйте bastion для доступа к приватным сетям.
4. **Pre-flight**: Устанавливайте зависимости через `pre_flight` на чистых хостах.
5. **ssh_wipe**: Оставляйте `True` в продакшене для безопасности.
6. **Тестирование**: Всегда проверяйте через `test=True` перед apply.
7. **Pillar**: Передавайте секреты через `--pillar`, а не через roster.
8. **Версионирование roster**: Храните roster в Git, используйте code review.

### Версии и совместимость

| Версия Salt | Особенности Salt-SSH |
|:---|:---|
| 3006 LTS | Стандартный thin mode, roster basics |
| 3007 STS | Улучшенное сканирование портов |
| 3008 LTS | Улучшенная безопасность thin-файлов, `ssh_wipe` по умолчанию |

### См. также

- [Архитектура SaltStack](Architecture.md) — overview Salt-SSH
- [Безопасность SaltStack](Security_Approaches.md) — Salt-SSH security
- [Masterless mode](Salt_Call_and_Masterless.md) — salt-call --local
