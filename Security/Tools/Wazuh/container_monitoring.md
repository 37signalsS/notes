# Инвентаризация и мониторинг контейнеров в Wazuh

## Определения

**Container Inventory (Инвентаризация контейнеров)** — процесс автоматического сбора данных о запущенных контейнерах (образы, дайджесты, реестры, привилегии) для контроля соответствия политикам безопасности.

**Docker Listener** — встроенный модуль (wodle) агента Wazuh, который взаимодействует с Docker API для мониторинга событий в реальном времени (создание, запуск, выполнение команд в контейнере) и сбора статистики ресурсов.

**Wodle Command** — модуль агента для выполнения пользовательских сценариев по расписанию и передачи их вывода (stdout) на сервер для анализа.

## Базовые концепции

### Уровни мониторинга
1.  **Инвентаризация (Inventory)**: Глубокий аудит конфигураций (раз в несколько часов).
2.  **Событийный мониторинг (Runtime)**: Мгновенное обнаружение действий (exec, stop, start).
3.  **Мониторинг ресурсов**: Статистика CPU, памяти и сети.

### Отслеживаемые параметры риска

| Параметр | Риск | Рекомендация |
| :--- | :--- | :--- |
| `privileged: true` | Полный доступ к ресурсам хоста. | Заменить на конкретные capabilities. |
| `user: root` | Эскалация при побеге из контейнера. | Использовать директиву `USER` в Dockerfile. |
| `tag: latest` | Непредсказуемость обновлений, сложность аудита. | Использовать фиксированные теги или digest. |
| `registry: local` | Образ без подтвержденного источника. | Использовать только доверенные реестры. |
| `cap_add: [...]` | Расширенные системные привилегии. | Использовать `cap_drop: ALL` + Whitelist. |

## Практические сценарии

### 1. Глубокая инвентаризация через кастомный скрипт

#### Шаг 1: Скрипт инвентаризации (`container_inventory.sh`)
Разместите скрипт в `/var/ossec/custom-scripts/container_inventory.sh`:

```bash
#!/bin/sh
# Проверка доступности Docker
command -v docker >/dev/null 2>&1 || exit 0
docker info >/dev/null 2>&1 || exit 0

docker ps --format "{{.Names}}|{{.ID}}" | while IFS="|" read -r name cid; do
  image=$(docker inspect --format '{{.Config.Image}}' "$cid" 2>/dev/null)
  [ -z "$image" ] && continue

  # Извлечение подробных метаданных
  info=$(docker inspect --format \
    "{{.HostConfig.Privileged}}|{{.Config.User}}|{{json .HostConfig.CapAdd}}|{{json .HostConfig.CapDrop}}" \
    "$cid" 2>/dev/null)
  
  privileged="${info%%|*}"
  rest="${info#*|}"
  user="${rest%%|*}"
  
  # Вывод в JSON для Wazuh
  printf '{"type":"container_inventory","name":"%s","image":"%s","privileged":%s,"user":"%s"}\n' \
    "$name" "$image" "${privileged:-false}" "${user:-root}"
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
    <description>Container inventory event</description>
  </rule>

  <rule id="100201" level="12">
    <if_sid>100200</if_sid>
    <field name="privileged">^true$</field>
    <description>КРИТИЧЕСКИЙ РИСК: Обнаружен привилегированный контейнер $(name)</description>
  </rule>

  <rule id="100204" level="7">
    <if_sid>100200</if_sid>
    <field name="user">^root$</field>
    <description>Процесс в контейнере запущен от root: $(name)</description>
  </rule>
</group>
```

### 2. Настройка Docker Listener (Real-time события)

#### Шаг 1: Подготовка Python-окружения
Требуется Python 3.8–3.12. Установите зависимости:

```bash
pip3 install --upgrade pip
pip3 install docker==7.1.0 urllib3==1.26.20 requests==2.32.2 --break-system-packages
```

#### Шаг 2: Настройка интерпретатора
В файле `/var/ossec/wodles/docker/DockerListener` проверьте Shebang:
`#!<path_to_your_python>/bin/python3`

#### Шаг 3: Включение модуля в `ossec.conf`
```xml
<wodle name="docker-listener">
  <disabled>no</disabled>
  <run_on_start>yes</run_on_start>
  <interval>10m</interval> <!-- Ожидание перед перезапуском при сбое -->
  <attempts>5</attempts>    <!-- Кол-во попыток запуска -->
</wodle>
```

### 3. Проверка и верификация

Выполните команды на агенте:
```bash
sudo docker run -d --name security_test_nginx nginx
sudo docker exec -it security_test_nginx cat /etc/passwd
```
Проверьте появление событий в Wazuh Dashboard (модуль Docker или Security Events).

## Дополнительная информация

### Расширение мониторинга
- **Сеть**: Сбор проброшенных портов (`.NetworkSettings.Ports`).
- **Volumes**: Анализ монтирования чувствительных путей хоста.
- **Env**: Сбор переменных окружения (внимание к секретам!).

### Типовые проблемы
- **Python Path**: Самая частая причина — агент не видит библиотеки `docker` в системном Python. Рекомендуется использовать venv.
- **Docker Socket**: Агент должен иметь права на чтение `/var/run/docker.sock`.

### См. также
- [Wazuh: обзор SIEM](../wazuh.md)
- [Мониторинг безопасности контейнеров](../../../Docker/Docker_security/runtime_monitoring.md)
- [Интеграция Docker с Prometheus](../../../Docker/Docker_metrics/docker_prometheus_integration.md)
