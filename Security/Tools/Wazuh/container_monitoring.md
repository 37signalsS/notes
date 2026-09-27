# Инвентаризация и мониторинг контейнеров в Wazuh

## Определения

**Container Inventory (Инвентаризация контейнеров)** — процесс автоматического сбора метаданных о запущенных контейнерах (образы, дайджесты, открытые порты, переменные окружения, Security Context) для контроля соответствия корпоративным политикам безопасности и compliance (PCI DSS, ФЗ-152, CIS Kubernetes Benchmark).

**Docker Listener** — встроенный модуль (`wodle`) агента Wazuh, который взаимодействует с Docker API для мониторинга событий в реальном времени (создание, запуск, выполнение команд в контейнере) и сбора статистики ресурсов. В Wazuh 5.x выполняется как отдельный процесс `wodle_docker_listener` через `integratord`.

**Kubernetes Audit Monitoring** — механизм интеграции Wazuh с журналом аудита Kubernetes для отслеживания действий в кластере (кто создал под, кто получил доступ к секретам, изменения RBAC). Источником данных служит файл audit.log API-сервера или webhook-эндпоинт.

**Runtime Security (eBPF)** — использование программ eBPF для глубокого мониторинга системных вызовов и сетевой активности контейнеров без внедрения агента внутрь каждого контейнера. В Wazuh eBPF используется как провайдер Whodata для FIM и как источник событий ядра через wodle.

**Container Runtime** — программа, управляющая жизненным циклом контейнеров на хосте. В контексте Wazuh мониторинга поддерживаются:
- **Docker Engine** — классический runtime с REST API на `/var/run/docker.sock`
- **containerd** — стандартный runtime в Kubernetes 1.24+, exposes CRI socket
- **CRI-O** — легковесный runtime, ориентированный на Kubernetes

**Container Image Layer** — неизменяемый слой файловой системы образа. Wazuh инвентаризирует дайджесты слоев (SHA256) для детекции drift между развернутым контейнером и зарегистрированным образом в registry.

**Container Escape** — класс атак, при которых злоумышленник выходит за границы изоляции контейнера и получает доступ к хосту. Детекция строится на мониторинге нетипичных mount-points (`/var/run/docker.sock`, `/proc`, `/sys`), системных вызовов и загрузки модулей ядра.

**Wodle (Wazuh Module)** — архитектурный паттерн расширения агента Wazuh. Контейнерный мониторинг реализован через wodle `command` (инвентаризация) и `docker-listener` (real-time события).

**Syscollector** — встроенный модуль агента, собирающий данные об оборудовании, ПО и сетевых интерфейсах. В контексте контейнеров используется для инвентаризации пакетов внутри контейнеров через анализ образов или вызовов на хосте.

**CRI (Container Runtime Interface)** — стандартный API Kubernetes для управления runtime. Wazuh не взаимодействует с CRI напрямую, но может собирать метаданные через Docker API или K8s API Server.

## Основные концепции

### Уровни мониторинга и обеспечения безопасности

| Уровень | Описание | Метод в Wazuh |
| :--- | :--- | :--- |
| **Хост (Host)** | Проверка конфигурации Docker демона и ОС. | Модуль SCA (CIS Docker Benchmark, CIS Kubernetes Benchmark). |
| **Инвентарь (Inventory)** | Глубокий аудит параметров запуска контейнеров. | Wodle Command + Скрипты + Syscollector. |
| **События (Runtime)** | Реакция на запуск, остановку и команды `exec`. | Docker Listener / K8s Audit Logs. |
| **Контроль ядра** | Обнаружение попыток побега и аномальных syscalls. | eBPF / Auditd / FIM на `/proc/modules`. |

### Архитектура сбора данных о контейнерах

Поток данных от контейнера к аналитике в Wazuh 5.x:

```
Источник события
    │
    ├─ Docker Engine / containerd
    │     └─ Docker API (socket / TCP)
    │           └─ Wodle docker-listener
    │                 └─ JSON события (create, start, exec, destroy)
    │                       └─ Wazuh-Engine / analysisd
    │                             └─ Правила (local_rules.xml)
    │                                   └─ Alert → Indexer → Dashboard
    │
    ├─ K8s API Server
    │     └─ Audit Log (файл /var/log/kubernetes/audit.log или webhook)
    │           └─ Logcollector (localfile)
    │                 └─ JSON события (pods, secrets, RBAC, exec)
    │                       └─ Wazuh-Engine / analysisd
    │                             └─ Правила
    │                                   └─ Alert
    │
    └─ Кастомные скрипты (wodle command)
          └─ docker inspect / crictl inspect
                └─ Инвентарь (образы, mounts, env, privileged)
                      └─ Wazuh-Engine
                            └─ SCA-политики / Правила
```

### Отслеживаемые параметры риска (KPI Безопасности)

| Параметр | Угроза | Рекомендация |
| :--- | :--- | :--- |
| `privileged: true` | Полный доступ к ресурсам хоста. | Заменить на конкретные capabilities. |
| `user: root` | Облегчение эскалации при взломе приложения. | Использовать `USER` в Dockerfile (UID > 1000). |
| `readonly: false` | Возможность модификации бинарных файлов внутри. | Включать `--read-only` для неизменяемых слоев. |
| `mount: docker.sock` | Полный контроль над Docker-демоном хоста. | Использовать Docker Socket Proxy (RO) или rootless режим. |
| `env: SECRET=...` | Утечка паролей через метаданные образа. | Использовать Secrets Management (Vault, K8s Secrets). |
| `cap_add: SYS_ADMIN` | Право на монтирование ФС, изменение namespace. | Избегать в production; использовать granular capabilities. |
| `pid: host` | Видимость всех процессов хоста. | Использовать только для диагностических sidecar-контейнеров. |
| `network: host` | Обход network policy Kubernetes. | Использовать конкретные порты и ClusterIP. |

### Сравнение методов мониторинга контейнеров

| Метод | Источник данных | Детализация | Оверхед | Рекомендуемое применение |
| :--- | :--- | :--- | :--- | :--- |
| **Docker Listener** | Docker API события | Высокая (create, start, exec, destroy, stats) | Низкий | Монохостные среды с Docker Engine. |
| **K8s Audit Logs** | audit.log API-сервера | Высокая (pods, secrets, RBAC, exec) | Низкий | Kubernetes-кластеры любого размера. |
| **Wodle Inventory** | docker inspect / crictl | Средняя (метаданные образа, mounts) | Средний (интервал опроса) | Инвентаризация и compliance. |
| **FIM (hostPath)** | inotify / eBPF / Audit | Высокая (изменения файлов контейнера) | Средний | Обнаружение модификации файлов внутри контейнера. |
| **eBPF Syscalls** | Ядро Linux (kprobes/tracepoints) | Максимальная (syscall, сеть, файлы) | Низкий | Runtime Security, container escape detection. |

### Изменения в Wazuh 5.x для контейнерного мониторинга

- **Архитектура wodle**: Docker Listener теперь запускается через `integratord` как изолированный процесс с собственным Python-окружением. Пути изменились: `/var/ossec/wodles/docker/DockerListener` (4.x) → `/var/wazuh-manager/wodles/docker/DockerListener` (5.x на менеджере) или `/var/ossec/wodles/docker/DockerListener` (на агенте).
- **Параллельное выполнение**: В 5.x несколько wodle могут работать параллельно без блокировки `analysisd`.
- **Нормализация путей**: В 5.x агент использует `/var/ossec/` как корень, а менеджер — `/var/wazuh-manager/`. При развертывании wodle на менеджере (agentless) используйте пути менеджера.
- **Изолированное окружение**: Python-зависимости Docker Listener (библиотека `docker`) должны быть установлены в виртуальном окружении или системном Python, доступном демону Wazuh.
- **Блокировка `<options>`**: В `ossec.conf` для `docker-listener` появилась поддержка `<options>` для передачи аргументов в wodle (например, `--socket /var/run/docker.sock`).

## Практические сценарии

### 1. Расширенная инвентаризация через кастомный скрипт

Этот метод позволяет получить более детальные данные, чем стандартный модуль.

#### Шаг 1: Скрипт инвентаризации (`/var/ossec/custom-scripts/container_inventory.sh`)

```bash
#!/bin/sh
# Проверка доступности Docker
command -v docker >/dev/null 2>&1 || exit 0
docker info >/dev/null 2>&1 || exit 0

docker ps --format "{{.ID}}" | while read -r cid; do
  docker inspect --format \
    '{"type":"container_inventory","name":"{{.Name}}","image":"{{.Config.Image}}","user":"{{.Config.User}}","privileged":{{.HostConfig.Privileged}},"readonly":{{.HostConfig.ReadonlyRootfs}},"ports":{{json .NetworkSettings.Ports}},"mounts":{{json .Mounts}},"env":{{json .Config.Env}},"pid_mode":"{{.HostConfig.PidMode}}","network_mode":"{{.HostConfig.NetworkMode}}","cap_add":{{json .HostConfig.CapAdd}},"security_opt":{{json .HostConfig.SecurityOpt}}}' \
    "$cid" 2>/dev/null
done
```

#### Шаг 2: Конфигурация агента (`ossec.conf`)

```xml
<wodle name="command">
  <disabled>no</disabled>
  <tag>container_inventory</tag>
  <command>/var/ossec/custom-scripts/container_inventory.sh</command>
  <interval>6h</interval>
  <run_on_start>yes</run_on_start>
  <log_format>json</log_format>
</wodle>
```

#### Шаг 3: Правила алертинга на менеджере (`local_rules.xml`)

```xml
<group name="container_inventory,">
  <rule id="100200" level="0">
    <decoded_as>json</decoded_as>
    <field name="type">^container_inventory$</field>
    <description>Событие инвентаризации контейнеров</description>
  </rule>

  <rule id="100201" level="12">
    <if_sid>100200</if_sid>
    <field name="privileged">^true$</field>
    <description>КРИТИЧЕСКИЙ РИСК: Обнаружен привилегированный контейнер $(name)</description>
  </rule>

  <rule id="100202" level="7">
    <if_sid>100200</if_sid>
    <field name="user">^root$|^$</field>
    <description>Процесс в контейнере запущен от пользователя root: $(name)</description>
  </rule>

  <rule id="100203" level="8">
    <if_sid>100200</if_sid>
    <field name="cap_add">.*SYS_ADMIN.*</field>
    <description>Контейнер имеет capability SYS_ADMIN: $(name)</description>
  </rule>

  <rule id="100204" level="9">
    <if_sid>100200</if_sid>
    <field name="mounts">.*docker.sock.*</field>
    <description>Контейнер монтирует docker.sock: $(name)</description>
  </rule>
</group>
```

### 2. Настройка Docker Listener (Real-time события)

Модуль обеспечивает видимость действий внутри контейнеров (например, кто запустил `sh` внутри `nginx`).

#### Шаг 1: Подготовка Python-окружения

Установите зависимости, совместимые с Wazuh 4.9+ / 5.x (Python 3.8–3.12):

```bash
# Для систем с менеджером пакетов pip
pip3 install docker==7.1.0 urllib3==1.26.20 requests==2.32.3 --break-system-packages
```

Для Wazuh 5.x на менеджере (agentless-режим):
```bash
# Проверьте путь Python, используемого демоном Wazuh
/var/wazuh-manager/bin/wazuh-control status | grep python
# → /var/wazuh-manager/venv/bin/python3

# Установите библиотеку docker в venv
/var/wazuh-manager/venv/bin/pip install docker==7.1.0
```

#### Шаг 2: Настройка и включение

В файле `/var/ossec/wodles/docker/DockerListener` проверьте Shebang: `#!<path_to_your_python>/bin/python3`.
Затем активируйте в `ossec.conf`:

```xml
<wodle name="docker-listener">
  <disabled>no</disabled>
  <run_on_start>yes</run_on_start>
  <attempts>5</attempts>
  <socket>/var/run/docker.sock</socket>
  <interval>5s</interval>
</wodle>
```

Параметры:
- `<socket>`: путь к Docker API сокету (по умолчанию `/var/run/docker.sock`).
- `<interval>`: интервал опроса событий (по умолчанию 5s). Для высоконагруженных сред увеличьте до 10–15s.
- `<attempts>`: число попыток переподключения при недоступности сокета.

#### Шаг 3: Правила алертинга

```xml
<group name="docker_listener,">
  <rule id="100300" level="0">
    <decoded_as>json</decoded_as>
    <field name="source">^docker-listener$</field>
    <description>Событие Docker Listener</description>
  </rule>

  <rule id="100301" level="10">
    <if_sid>100300</if_sid>
    <field name="event">^exec_start$</field>
    <field name="user">^root$</field>
    <description>Выполнение команды от root в контейнере: $(container_name)</description>
  </rule>

  <rule id="100302" level="12">
    <if_sid>100300</if_sid>
    <field name="event">^exec_start$</field>
    <field name="command">^.*sh$|^.*bash$</field>
    <description>Запуск оболочки в контейнере: $(container_name)</description>
  </rule>
</group>
```

### 3. Мониторинг Kubernetes Audit Logs

Для интеграции с K8s рекомендуется настроить Webhook или чтение логов `kube-apiserver`.

#### Шаг 1: Настройка K8s Audit Policy

Пример минимальной политики аудита (`audit-policy.yaml`):

```yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
  # Секреты
  - level: Metadata
    resources:
    - group: ""
      resources: ["secrets", "configmaps"]
  # Под(s) с exec
  - level: RequestResponse
    verbs: ["create", "update", "patch", "delete"]
    resources:
    - group: ""
      resources: ["pods", "pods/exec", "pods/attach"]
  # RBAC изменения
  - level: Metadata
    resources:
    - group: "rbac.authorization.k8s.io"
      resources: ["clusterroles", "clusterrolebindings", "roles", "rolebindings"]
  # Игнорировать частые запросы healthz
  - level: None
    userGroups: ["system:authenticated"]
    resources:
    - group: ""
      resources: ["componentstatuses", "events"]
```

Примените политику через флаг `kube-apiserver`:
```bash
kube-apiserver \
  --audit-policy-file=/etc/kubernetes/audit-policy.yaml \
  --audit-log-path=/var/log/kubernetes/audit.log \
  --audit-log-maxage=30 \
  --audit-log-maxbackup=10 \
  --audit-log-maxsize=100
```

#### Шаг 2: Конфигурация Logcollector (`ossec.conf`)

```xml
<localfile>
  <location>/var/log/kubernetes/audit.log</location>
  <log_format>json</log_format>
  <label key="source">k8s-audit</label>
  <only-future-events>yes</only-future-events>
</localfile>
```

Для сбора через journald (если audit.log пересылается в journal):
```xml
<localfile>
  <location>journald</location>
  <log_format>journald</log_format>
  <filter field="_SYSTEMD_UNIT">^kube-apiserver.service$</filter>
  <label key="source">k8s-audit-journald</label>
</localfile>
```

#### Шаг 3: Правила алертинга для K8s Audit

```xml
<group name="k8s_audit,">
  <rule id="100400" level="0">
    <decoded_as>json</decoded_as>
    <field name="source">^k8s-audit$</field>
    <description>Событие аудита Kubernetes</description>
  </rule>

  <rule id="100401" level="12">
    <if_sid>100400</if_sid>
    <field name="verb">^create$</field>
    <field name="objectRef.resource">^secrets$</field>
    <description>Создание Secret в кластере</description>
  </rule>

  <rule id="100402" level="10">
    <if_sid>100400</if_sid>
    <field name="verb">^patch$</field>
    <field name="objectRef.resource">^clusterrolebindings$</field>
    <description>Изменение ClusterRoleBinding</description>
  </rule>
</group>
```

### 4. Валидация и тестирование конфигурации

Перед включением в production выполните проверку конфигурации:

```bash
# Проверка синтаксиса ossec.conf
sudo /var/wazuh-manager/bin/wazuh-logtest -t alert -u 001 < /dev/null
# → Expected: "logtest started" без критических ошибок

# Проверка статуса wodle
sudo /var/ossec/bin/wazuh-control status | grep -i docker
# → Expected: wodle docker-listener active

# Тестовое событие: запуск контейнера
docker run --rm -d --name wazuh-test-001 nginx:alpine
sleep 10
# Проверка логов агента
sudo tail -f /var/ossec/logs/ossec.log | grep -i docker
# → Expected: события create/start для wazuh-test-001

# Проверка в Dashboard
# Wazuh Dashboard → Security Events → поиск по "docker-listener" или "container_inventory"

# Очистка тестового контейнера
docker rm -f wazuh-test-001
```

#### Валидация K8s Audit

```bash
# Проверка формата audit.log
head -n 5 /var/log/kubernetes/audit.log | jq .
# → Expected: валидный JSON с полями "kind", "apiVersion", "items"

# Проверка, что Logcollector читает файл
sudo tail -f /var/ossec/logs/wazuh.log | grep -i "localfile.*audit"
# → Expected: "reading file: /var/log/kubernetes/audit.log"

# Тестовое событие: создание pod
kubectl run test-pod --image=nginx --dry-run=server
# Проверьте появление события в alerts.log
sudo grep -i "test-pod" /var/wazuh-manager/logs/alerts/alerts.log
```

### 5. Мониторинг containerd (кроме Docker)

Для сред, использующих containerd в качестве CRI-рантайма (Kubernetes 1.24+), Docker API недоступен. Используйте K8s Audit Logs или прямой wodle с `crictl`:

```bash
#!/bin/sh
# /var/ossec/custom-scripts/containerd_inventory.sh
command -v crictl >/dev/null 2>&1 || exit 0

crictl ps --output json 2>/dev/null | \
  jq -r '.containers[] | "\(.id) \(.image.image)"' | \
  while read -r cid cimage; do
    printf '{"type":"containerd_inventory","id":"%s","image":"%s"}\n' "$cid" "$cimage"
  done
```

Конфигурация wodle:
```xml
<wodle name="command">
  <disabled>no</disabled>
  <tag>containerd_inventory</tag>
  <command>/var/ossec/custom-scripts/containerd_inventory.sh</command>
  <interval>6h</interval>
  <run_on_start>yes</run_on_start>
  <log_format>json</log_format>
</wodle>
```

Для детекции exec/attach в Kubernetes используйте Audit Logs (сценарий 3) или admission webhook (см. ниже).

### 6. Развертывание через Ansible

Пример плейбука для массового развертывания Docker Listener:

```yaml
---
- name: Deploy Wazuh Container Monitoring
  hosts: wazuh_agents
  become: yes
  vars:
    wazuh_container_interval: "10"
  tasks:
    - name: Install Python docker library
      pip:
        name: docker==7.1.0
        executable: pip3

    - name: Deploy container inventory script
      copy:
        src: files/container_inventory.sh
        dest: /var/ossec/custom-scripts/container_inventory.sh
        mode: '0755'
        owner: root
        group: wazuh

    - name: Configure Docker Listener wodle
      xml:
        path: /var/ossec/etc/ossec.conf
        xpath: /ossec-config/wodle[name='docker-listener']
        pretty_print: yes
      notify: restart wazuh-agent

    - name: Deploy custom rules for container inventory
      copy:
        src: files/container_rules.xml
        dest: /var/ossec/etc/rules/local_rules.xml
        owner: root
        group: wazuh
        mode: '0640'
      notify: restart wazuh-agent

  handlers:
    - name: restart wazuh-agent
      systemd:
        name: wazuh-agent
        state: restarted
```

### 7. CI/CD пайплайн для политик безопасности контейнеров

Пример GitHub Actions workflow для валидации и деплоя правил:

```yaml
name: Container Security Policy CI/CD

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Validate XML rules syntax
        run: python3 scripts/lint_wazuh_rules.py rules/container_inventory.xml
      - name: Validate shell scripts
        run: bash -n custom-scripts/container_inventory.sh
      - name: Test wodle output
        run: |
          docker ps --format "{{.ID}}" | head -1 | xargs -I{} docker inspect --format '{"type":"test"}' {}
      - name: Deploy to staging
        if: github.ref == 'refs/heads/main'
        run: ansible-playbook -i inventory/staging playbooks/deploy_container_monitoring.yml
```

### 8. Резервное копирование и восстановление

#### Что бэкапить

| Компонент | Путь | Важность |
| :--- | :--- | :--- |
| Правила контейнерного мониторинга | `/var/ossec/etc/rules/local_rules.xml` | High |
| Кастомные скрипты | `/var/ossec/custom-scripts/container_inventory.sh` | High |
| Конфигурация wodle | `/var/ossec/etc/ossec.conf` (блоки wodle) | High |
| Wodle Docker Listener | `/var/ossec/wodles/docker/DockerListener` | Medium |

#### Скрипт бэкапа

```bash
#!/bin/bash
BACKUP_DIR="/var/backups/wazuh-container-$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# Конфигурации и скрипты
tar czf "$BACKUP_DIR/container-monitoring.tar.gz" \
  -C /var/ossec etc/rules/local_rules.xml \
  -C /var/ossec custom-scripts/container_inventory.sh \
  -C /var/ossec wodles/docker/

# Если используется agentless на менеджере (Wazuh 5.x)
tar czf "$BACKUP_DIR/container-monitoring-manager.tar.gz" \
  -C /var/wazuh-manager etc/ossec.conf \
  -C /var/wazuh-manager wodles/docker/

echo "Backup saved to $BACKUP_DIR"
```

#### Восстановление

```bash
# 1. Остановите агент
sudo systemctl stop wazuh-agent

# 2. Восстановите файлы
tar xzf container-monitoring.tar.gz -C /

# 3. Проверьте права
sudo chown root:wazuh /var/ossec/custom-scripts/container_inventory.sh
sudo chmod 0755 /var/ossec/custom-scripts/container_inventory.sh

# 4. Запустите агент
sudo systemctl start wazuh-agent

# 5. Валидация
sudo /var/ossec/bin/wazuh-control status
sudo tail -f /var/ossec/logs/ossec.log | grep -i container
```

### 9. Мониторинг ephemeral контейнеров

Ephemeral-контейнеры (jobs, CronJobs, init-containers) имеют короткий жизненный цикл. Docker Listener может не успеть собрать события до завершения контейнера.

Рекомендации:
- Уменьшите `<interval>` wodle до 2–5s для сред с высоким количеством кратковременных контейнеров.
- Используйте K8s Audit Logs как более надежный источник (события записываются в audit.log до завершения контейнера).
- Для агента, установленного на worker-ноде, добавьте FIM на директорию `/var/log/pods/` для отслеживания логов завершенных подов:
```xml
<directories check_all="no" real_time="yes">/var/log/pods</directories>
```
- В правилах добавьте фильтр по `reason=Completed` или `reason=Error` для алертинга только на аномальные завершения.

## Дополнительная информация

### Оптимизация и борьба с шумом

- **Фильтрация событий**: При высокой динамике (много кратковременных контейнеров) Docker Listener может генерировать тысячи событий. Используйте `<ignore>` в правилах для событий `top` и `stats`. Для игнорирования конкретных контейнеров добавьте фильтр по `name`:
```xml
<rule id="100299" level="0">
  <if_sid>100300</if_sid>
  <field name="container_name">^wazuh-test-.*$</field>
  <description>Игнорирование тестовых контейнеров</description>
</rule>
```
- **Auto-ignore**: Для частых событий (например, healthcheck) используйте `auto_ignore` в wodle:
```xml
<wodle name="docker-listener">
  <auto_ignore frequency="5" timeframe="300">no</auto_ignore>
</wodle>
```
- **eBPF Драйвер**: В Wazuh 4.9+ рекомендуется переключать провайдер Whodata на `ebpf` в настройках Syscheck для мониторинга файлов внутри контейнеров с минимальным оверхедом.
- **Выбор источника**: В Kubernetes-средах отдавайте предпочтение Audit Logs вместо Docker Listener, так как API Server является единой точкой сбора, а Docker API недоступен при использовании containerd.

### Безопасность и сегментация

- **Docker Socket**: Агент должен иметь права на чтение `/var/run/docker.sock`. Проверьте членство пользователя `wazuh` в группе `docker`: `sudo usermod -aG docker wazuh`. Никогда не монтируйте docker.sock в контейнеры без необходимости. Для ограниченного доступа используйте **Docker Socket Proxy** (Tecnativa) с whitelist методов GET.
- **Сетевая сегментация**: Трафик Docker API (сокет) не выходит за пределы хоста. Для K8s Audit Logs используйте отдельный log-collection агент на мастер-ноде или sidecar DaemonSet с read-only доступом к `/var/log/kubernetes/`.
- **Secrets в переменных окружения**: Скрипт инвентаризации собирает `env` контейнеров. Убедитесь, что алерты не содержат секретов в логах менеджера. Используйте `report_changes="no"` для правил, передающих контент переменных, или маскируйте чувствительные поля:
```xml
<rule id="100205" level="6">
  <if_sid>100200</if_sid>
  <field name="env">^.*SECRET.*$</field>
  <description>Контейнер содержит переменную с секретом: $(name)</description>
  <options>no_full_log</options>
</rule>
```
- **Kubernetes RBAC**: Для сбора audit.log агент должен иметь доступ к `/var/log/kubernetes/` на хосте. В managed-средах (EKS, GKE, AKS) используйте DaemonSet с привилегированным доступом к хостовым путям.

### Телеметрия и мониторинг интеграции

Для отслеживания здоровья самого процесса мониторинга контейнеров добавьте метрики:

```bash
# На агенте: скрипт /var/ossec/custom-scripts/container_monitoring_health.sh
#!/bin/sh
EVENT_COUNT=$(tail -n 100 /var/ossec/logs/ossec.log | grep -c "docker-listener" || true)
ERROR_COUNT=$(tail -n 100 /var/ossec/logs/ossec.log | grep -c "docker-listener.*error" || true)
CONTAINER_COUNT=$(docker ps -q 2>/dev/null | wc -l || echo 0)

printf '{"type":"container_monitoring_health","events":%s,"errors":%s,"containers":%s}\n' \
  "$EVENT_COUNT" "$ERROR_COUNT" "$CONTAINER_COUNT"
```

Конфигурация wodle:
```xml
<wodle name="command">
  <disabled>no</disabled>
  <tag>container_monitoring_health</tag>
  <command>/var/ossec/custom-scripts/container_monitoring_health.sh</command>
  <interval>5m</interval>
  <run_on_start>yes</run_on_start>
  <log_format>json</log_format>
</wodle>
```

### Миграционные заметки (4.x → 5.x)

- В Wazuh 5.x формат `ossec.conf` остается XML, но появилась поддержка YAML-конфигурации для Logcollector. Для контейнерных wodle используйте XML.
- Пути на менеджере изменились: `/var/ossec/` → `/var/wazuh-manager/`. При развертывании wodle на менеджере (agentless) используйте пути менеджера.
- `wazuh-modulesd` в 5.x управляет wodle через `integratord`. Для диагностики используйте:
```bash
sudo /var/wazuh-manager/bin/wazuh-control status modules
# → Expected: docker-listener активен
```
- eBPF-провайдер в 5.x требует `libbpf` 1.0+; на старых дистрибутивах может потребоваться обновление `bcc`/`libbpf`.
- В 5.x изменился формат SCA-политик: добавлены поля `file` и `requirements`. Для проверки конфигурации Docker/K8s обновите SCA-политики.

### Сравнительная таблица методов

| Метод | Docker | containerd | Kubernetes | Оверхед | Сложность настройки |リアルタイム |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Docker Listener** | Да | Нет | Нет | Низкий | Низкая | Да |
| **K8s Audit Logs** | Нет | Да (через API) | Да | Низкий | Средняя | Да |
| **Wodle Inventory** | Да | Да (crictl) | Частично | Средний | Низкая | Нет |
| **FIM (hostPath)** | Да | Да | Да | Средний | Средняя | Да |
| **eBPF Syscalls** | Да | Да | Да | Низкий | Высокая | Да |

### Best Practices

1. **Приоритет Audit Logs в Kubernetes**: Используйте K8s Audit Logs как primary источник в K8s-средах. Docker API недоступен при containerd, а Audit Logs покрывают все операции API Server.
2. **Сегментация скриптов**: Размещайте кастомные скрипты в `/var/ossec/custom-scripts/`, а не в `/tmp/`. Устанавливайте права `0755 root:wazuh`.
3. **Ограничение scope Docker Listener**: На хостах с большим количеством контейнеров (>100) увеличьте `<interval>` до 10–15s и добавьте `<ignore>` для служебных контейнеров (kube-system, docker-gc).
4. **Защита docker.sock**: Никогда не запускайте Docker Listener от root без необходимости. Используйте группу `docker` для пользователя `wazuh`. Рассмотрите Docker Socket Proxy для production.
5. **Снижение шума**: Используйте `auto_ignore` и фильтрацию по `container_name` для игнорирования системных и тестовых контейнеров.
6. **Масштабирование**: При >500 контейнеров используйте K8s Audit Logs + DaemonSet с Logcollector вместо per-host Docker Listener. Это снижает нагрузку на API Server и упрощает отладку.
7. **Compliance**: Для PCI DSS, ФЗ-152 и CIS Kubernetes Benchmark комбинируйте SCA-политики (проверка конфигурации хоста) с Docker Listener/K8s Audit (мониторинг runtime).

### Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Docker Listener не запускается** | Отсутствует библиотека `docker` в Python | Установите `pip3 install docker==7.1.0` в окружение, используемое демоном Wazuh |
| **Нет событий docker-listener** | Агент не имеет доступа к `/var/run/docker.sock` | Проверьте `sudo usermod -aG docker wazuh` и права на сокет |
| **Event flood (тысячи алертов)** | Высокая динамика контейнеров без фильтров | Увеличьте `<interval>` до 15s, добавьте `<ignore>` для `stats`/`top` |
| **Секреты в логах менеджера** | Скрипт инвентаризации передает `env` в открытом виде | Добавьте `<options>no_full_log</options>` в правила для `env` или маскируйте поля |
| **K8s Audit Logs не парсятся** | Неправильный `log_format` или multiline события | Используйте `log_format: json` и убедитесь, что Wazuh 5.x собирает многoline audit.json корректно |
| **Отсутствуют события exec в K8s** | Audit Policy не включает `pods/exec` или verb `create` | Проверьте `audit-policy.yaml`, добавьте `pods/exec` с уровнем `RequestResponse` |
| **Высокий CPU на агенте** | Слишком частый опрос Docker API или FIM на `/var/lib/containers` | Увеличьте `<interval>` до 15s, добавьте `<ignore>` для `/var/lib/containers` в FIM |

### Типовые проблемы

- **Docker Socket**: Агент должен иметь права на чтение `/var/run/docker.sock`. Проверьте членство пользователя `wazuh` в группе `docker`: `sudo usermod -aG docker wazuh`.
- **Python Path**: Если модуль не запускается, проверьте логи `/var/ossec/logs/ossec.log`. Часто проблема в отсутствии библиотеки `docker` в системном пути, используемом демоном.
- **Контейнеры в K8s**: При использовании managed Kubernetes (EKS/GKE/AKS) audit.log может быть недоступен на хосте. Используйте webhook-форвардинг audit событий в Syslog или напрямую в Wazuh через `<socket>`.
- **containerd vs Docker**: В Kubernetes 1.24+ containerd — стандартный runtime. Docker Listener работает только с Docker Engine. Для containerd используйте K8s Audit Logs или `crictl`-скрипты.
- **Журналы Auditd**: При использовании Audit-провайдера настройте ротацию логов через `logrotate`, иначе диск заполнится быстрее, чем Wazuh обработает события. Пример конфигурации: `/etc/logrotate.d/auditd`.

### Edge Cases и ограничения

- **Сетевые ФС**: Мониторинг NFS/CIFS в режиме Real-time/Whodata не поддерживается большинством механизмов ядра на стороне клиента (требуется установка агента на сервер хранения). Рекомендуется использовать периодическое сканирование (`<interval>`) для сетевых путей.
- **Объем данных**: Включение `report_changes="yes"` (diff) для больших файлов (>1 MB) может быстро переполнить хранилище менеджера. Для таких файлов используйте `report_changes="no"` и полагайтесь на изменение хеша.
- **Количество файлов**: По умолчанию лимит мониторинга — 100 000 файлов на агента (регулируется в `internal_options.conf` параметром `syscheck.max_files`).
- **tmpfs и виртуальные ФС**: Изменения в `/proc`, `/sys`, `/dev` не отслеживаются, так как они генерируются ядром. Используйте отдельные директории для приложения.
- **Контейнеры**: FIM работает на уровне хоста. Для мониторинга контейнеров используйте `hostPath`-монтирования и отслеживайте пути внутри контейнера как обычные директории хоста. Не монтируйте `/var/lib/containers` в режиме Whodata — это вызывает event flood.
- **Rootless Docker**: При использовании rootless Docker сокет находится в `$XDG_RUNTIME_DIR/docker.sock` (обычно `/run/user/<UID>/docker.sock`). Укажите правильный путь в `<socket>` и убедитесь, что агент имеет доступ к runtime директории пользователя.

### См. также
- [Wazuh: обзор SIEM](../wazuh.md)
- [Мониторинг безопасности контейнеров в Runtime](../../../Docker/Docker_security/runtime_monitoring.md)
- [Мониторинг ядра через Wazuh](./kernel_monitoring.md) — детали eBPF и Auditd.
