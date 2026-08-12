# Инвентаризация и мониторинг контейнеров в Wazuh

## Определения

**Container Inventory (Инвентаризация контейнеров)** — процесс автоматического сбора метаданных о запущенных контейнерах (образы, дайджесты, открытые порты, переменные окружения) для контроля соответствия корпоративным политикам безопасности.

**Docker Listener** — встроенный модуль (`wodle`) агента Wazuh, который взаимодействует с Docker API для мониторинга событий в реальном времени (создание, запуск, выполнение команд в контейнере) и сбора статистики ресурсов.

**Kubernetes Audit Monitoring** — механизм интеграции Wazuh с журналом аудита Kubernetes для отслеживания действий в кластере (кто создал под, кто получил доступ к секретам).

**Runtime Security (eBPF)** — использование программ eBPF для глубокого мониторинга системных вызовов и сетевой активности контейнеров без внедрения агента внутрь каждого контейнера.

## Основные концепции

### Уровни мониторинга и обеспечения безопасности

| Уровень | Описание | Метод в Wazuh |
| :--- | :--- | :--- |
| **Хост (Host)** | Проверка конфигурации Docker демона и ОС. | Модуль SCA (CIS Benchmark). |
| **Инвентарь (Inventory)** | Глубокий аудит параметров запуска контейнеров. | Wodle Command + Скрипты. |
| **События (Runtime)** | Реакция на запуск, остановку и команды `exec`. | Docker Listener. |
| **Контроль ядра** | Обнаружение попыток побега и аномальных syscalls. | eBPF / Auditd. |

### Отслеживаемые параметры риска (KPI Безопасности)

| Параметр | Угроза | Рекомендация |
| :--- | :--- | :--- |
| `privileged: true` | Полный доступ к ресурсам хоста. | Заменить на конкретные capabilities. |
| `user: root` | Облегчение эскалации при взломе приложения. | Использовать `USER` в Dockerfile (UID > 1000). |
| `readonly: false` | Возможность модификации бинарных файлов внутри. | Включать `--read-only` для неизменяемых слоев. |
| `mount: docker.sock` | Полный контроль над Docker-демоном хоста. | Использовать Docker Socket Proxy (RO). |
| `env: SECRET=...` | Утечка паролей через метаданные образа. | Использовать Secrets Management (Vault, K8s). |

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
  # Извлечение метаданных в формате JSON для автоматического декодирования в Wazuh
  docker inspect --format \
    '{"type":"container_inventory","name":"{{.Name}}","image":"{{.Config.Image}}","user":"{{.Config.User}}","privileged":{{.HostConfig.Privileged}},"readonly":{{.HostConfig.ReadonlyRootfs}},"ports":{{json .NetworkSettings.Ports}},"mounts":{{json .Mounts}},"env":{{json .Config.Env}}}' \
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
</group>
```

### 2. Настройка Docker Listener (Real-time события)

Модуль обеспечивает видимость действий внутри контейнеров (например, кто запустил `sh` внутри `nginx`).

#### Шаг 1: Подготовка Python-окружения
Установите зависимости, совместимые с Wazuh 4.9+ (Python 3.8–3.12):

```bash
# Для систем с менеджером пакетов pip
pip3 install docker==7.1.0 urllib3==1.26.20 requests==2.32.3 --break-system-packages
```

#### Шаг 2: Настройка и включение
В файле `/var/ossec/wodles/docker/DockerListener` проверьте Shebang: `#!<path_to_your_python>/bin/python3`.
Затем активируйте в `ossec.conf`:

```xml
<wodle name="docker-listener">
  <disabled>no</disabled>
  <run_on_start>yes</run_on_start>
  <attempts>5</attempts>
</wodle>
```

### 3. Мониторинг Kubernetes Audit Logs

Для интеграции с K8s рекомендуется настроить Webhook или чтение логов `kube-apiserver`.

**Пример конфигурации `<localfile>` на мастер-ноде (подробнее о параметрах: [Сбор логов](./wazuh-log-collection.md)):**
```xml
<localfile>
  <location>/var/log/kubernetes/audit.log</location>
  <log_format>json</log_format>
  <label key="source">k8s-audit</label>
</localfile>
```

## Дополнительная информация

### Оптимизация и борьба с шумом
*   **Фильтрация событий**: При высокой динамике (много кратковременных контейнеров) Docker Listener может генерировать тысячи событий. Используйте `<ignore>` в правилах для событий `top` и `stats`.
*   **eBPF Драйвер**: В Wazuh 4.9+ рекомендуется переключать провайдер Whodata на `ebpf` в настройках Syscheck для мониторинга файлов внутри контейнеров с минимальным оверхедом.

### Типовые проблемы
*   **Docker Socket**: Агент должен иметь права на чтение `/var/run/docker.sock`. Проверьте членство пользователя `wazuh` в группе `docker`: `sudo usermod -aG docker wazuh`.
*   **Python Path**: Если модуль не запускается, проверьте логи `/var/ossec/logs/ossec.log`. Часто проблема в отсутствии библиотеки `docker` в системном пути, используемом демоном.

### См. также
- [Wazuh: обзор SIEM](../wazuh.md)
- [Обнаружение уязвимостей (Vulnerability Detector) в Wazuh](./wazuh-vulnerability-detector.md)
- [Мониторинг безопасности контейнеров](../../../Docker/Docker_security/runtime_monitoring.md)
- [Интеграция Docker с Prometheus](../../../Docker/Docker_metrics/docker_prometheus_integration.md)
- [Мониторинг ядра через Wazuh](./kernel_monitoring.md) — детали eBPF и системных вызовов.
