# Мониторинг здоровья и самодиагностика Wazuh

## Определения

**Мониторинг Wazuh** — комплекс процессов по контролю работоспособности узлов SIEM (агентов, менеджеров, индексаторов). В версии **Wazuh 5.0+** мониторинг трансформирован в систему глубокой наблюдаемости (Observability), интегрированную с отраслевыми стандартами передачи телеметрии.

**Самодиагностика (Self-monitoring)** — встроенный механизм Wazuh-Engine, использующий нативные средства (OTLP, внутренние очереди, логи) для анализа состояния процессов и автоматического предотвращения деградации производительности.

**Self-healing** — механизм автоматического восстановления после сбоев, при котором система сама перезапускает упавшие сервисы на основе правил корреляции без участия администратора.

**Backpressure (Indexing Pressure)** — механизм динамического ограничения входящего потока данных при перегрузке индексатора (OpenSearch 3.x), предотвращающий падение системы за счет регулировки скорости приема событий.

**KVDB (Key-Value Database)** — хранилище состояний Wazuh-Engine, используемое для агрегации временных окон корреляции, отслеживания статусов агентов и промежуточных результатов анализа.

**Golden Signals** — набор критических метрик (частота событий, объем очередей, задержки обработки, давление на индексатор), позволяющих оценить общее состояние SIEM за несколько секунд.

**wazuh-integratord** — фоновый процесс (демон) менеджера Wazuh, отвечающий за выполнение внешних скриптов интеграции при срабатывании правил. В Wazuh 5.0+ работает в многопоточном режиме с нормализованными путями `/var/wazuh-manager/integrations/`.

**Health Endpoint** — встроенный HTTP-эндпоинт Wazuh Manager (`https://localhost:55000/health`), возвращающий JSON-статус доступности компонентов для проверок со стороны балансировщиков и мониторинговых систем.

## Основные концепции

### Архитектура наблюдаемости (Wazuh 5.0)

В 2026 году мониторинг здоровья Wazuh базируется на четырех столпах:

1.  **OTLP-телеметрия**: Переход на стандарт OpenTelemetry. Движок Wazuh генерирует метрики (Counters, Gauges, Histograms), которые могут быть экспортированы во внешние коллекторы или внутренний индексатор.
2.  **Wazuh-Engine Health**: Контроль модульного ядра, включая KVDB (хранилище состояний), Router (маршрутизация событий) и Server (логика анализа).
3.  **Indexing Pressure (Backpressure)**: Механизм динамического ограничения входящего потока данных при перегрузке индексатора (OpenSearch 3.x), предотвращающий падение системы.
4.  **Единый кластер**: Мониторинг состояния синхронизации в режиме кластера, который в 5.0 активен по умолчанию для всех типов инсталляций.

### Компоненты здоровья Wazuh

| Компонент | Назначение | Метод проверки |
| :--- | :--- | :--- |
| **wazuh-engine** | Основной движок анализа событий | OTLP метрики, `/var/wazuh-manager/logs/wazuh.log` |
| **analysisd** | Демон анализа и сопоставления правил | `wazuh-control status`, метрики очередей |
| **logcollector** | Сбор логов из источников | `wazuh-control status`, локальные логи |
| **wdb** | База данных состояний (KVDB) | `wazuh-kvdb` утилиты, задержки операций |
| **integratord** | Выполнение внешних интеграций | `wazuh-control status modules` |
| **wazuh-indexer** | Индексация и хранение событий | OpenSearch Cluster Health API |
| **wazuh-dashboard** | Веб-интерфейс | HTTP 200 на порту 443, нативный health check |

### Методы мониторинга

| Метод | Источник данных | Скорость обновления | Сложность | Рекомендуемое применение |
| :--- | :--- | :--- | :--- | :--- |
| **REST API** | `/agents`, `/health` | 5–30s | Средняя | Автоматизация, балансировщики, Zabbix |
| **OTLP** | Метрики движка | 10–60s | Средняя | Внешние коллекторы (Prometheus, Grafana) |
| **CLI** | `wazuh-control`, `agent_control` | По запросу | Низкая | Ручная диагностика, скрипты |
| **Логи** | `/var/wazuh-manager/logs/wazuh.log` | По событию | Средняя | Глубокая диагностика, аудит |
| **Dashboard** | Встроенный UI | 1–5 мин | Низкая | Оперативный обзор, демо |

### Изменения в Wazuh 5.x для мониторинга

- **Пути**: `/var/ossec/` на агенте → `/var/wazuh-manager/` на менеджере. При развертывании agentless (monitoring of remote hosts) используйте пути менеджера.
- **OTLP**: В 5.x включен нативно через `wazuh.yaml`. В 4.x требовался обходной путь через логи и внешний парсинг.
- **Health Endpoint**: В 5.x добавлен единый `https://localhost:55000/health` для проверки состояния всех компонентов.
- **Кластеризация**: В 5.x кластерный режим включен по умолчанию. Мониторинг должен включать проверку синхронизации узлов.
- **integratord**: В 5.x работает в многопоточном режиме. Для диагностики используйте `wazuh-control status modules`.
- **Валидация**: В 5.x добавлен `wazuh-logtest` для тестирования декодеров и правил без перезапуска.

## Практические сценарии

### 1. Мониторинг через OpenTelemetry (OTLP)

Wazuh 5.0 позволяет получать детальные метрики производительности «на лету» без парсинга логов.

**Пример конфигурации телеметрии (`wazuh.yaml`):**
```yaml
telemetry:
  enabled: true
  metrics:
    reporting_frequency: 30s
    exporters:
      - name: internal-otlp
        type: otlp
        endpoint: "http://wazuh-indexer:4317"
        protocol: grpc
```

**Критические метрики OTLP:**
- `wazuh.engine.events.processed_total`: Общее количество обработанных событий.
- `wazuh.engine.queue.latency`: Задержка обработки событий в очередях.
- `wazuh.kvdb.operation_duration`: Время отклика базы данных состояний.
- `wazuh.engine.analysisd.queue_size`: Размер очереди необработанных событий.
- `wazuh.indexer.backpressure.active`: Состояние механизма throttling.

### 2. Контроль статуса агентов (v5 API)

В современных версиях для проверки статусов рекомендуется использовать REST API, так как он предоставляет более полную информацию о версии протокола и возможностях агента.

**Запрос статуса через CLI:**
```bash
# Получение списка отключенных агентов
curl -k -X GET "https://localhost:55000/agents?status=disconnected" -H "Authorization: Bearer $TOKEN"
# → Expected: JSON со списком агентов и временем последнего heartbeat

# Проверка здоровья конкретного агента
curl -k -X GET "https://localhost:55000/agents/001?pretty" -H "Authorization: Bearer $TOKEN"
# → Expected: поле "status" = "active", "last_keepalive" = "2026-09-18T..."
```

**Health Endpoint:**
```bash
# Проверка доступности Manager
curl -k https://localhost:55000/health
# → Expected: {"status":"ok","components":{...}}
```

**Legacy CLI (сохранено для совместимости):**
```bash
# Проверка связи на менеджере (4.x и 5.x)
/var/wazuh-manager/bin/agent_control -l
# → Expected: список агентов с колонками ID, Name, IP, Status
```

### 3. Самодиагностика и Self-healing (Wazuh-Engine)

Автоматизация реагирования на критические сбои внутренних сервисов.

**Скрипт проверки состояния (`/var/wazuh-manager/bin/wazuh-self-check.sh`):**
```bash
#!/bin/bash
# Проверка доступности порта API и здоровья Engine
if ! curl -s -k https://localhost:55000/health > /dev/null; then
  echo "{\"service\":\"wazuh-engine\", \"status\":\"unhealthy\", \"action\":\"restart\"}" >> /var/wazuh-manager/logs/health.json
  systemctl restart wazuh-manager
fi
```

**Правило корреляции в `local_rules.xml`:**
```xml
<group name="wazuh_health,">
  <rule id="100100" level="12">
    <decoded_as>json</decoded_as>
    <field name="status">unhealthy</field>
    <description>CRITICAL: Wazuh-Engine is unhealthy on $(hostname). Restart initiated.</description>
  </rule>
</group>
```

### 4. Мониторинг компонентов через CLI

Контроль состояния отдельных демонов Wazuh Manager.

```bash
# Общий статус всех компонентов
sudo /var/wazuh-manager/bin/wazuh-control status
# → Expected: таблица с колонками Name, Pid, Status для каждого модуля

# Статус модулей Wazuh 5.x (wodle, integratord)
sudo /var/wazuh-manager/bin/wazuh-control status modules
# → Expected: docker-listener active, vuln-detector active

# Проверка конкретного компонента (analysisd)
ps aux | grep wazuh-analysisd
# → Expected: PID и uptime процесса

# Мониторинг очередей в реальном времени
watch -n 1 'sudo /var/wazuh-manager/bin/wazuh-control status | grep -E "queue|analysisd|logcollector"'
```

### 5. Анализ логов для диагностики

Центлизованный анализ логов позволяет выявлять проблемы до их критического влияния.

```bash
# Общий лог менеджера (5.x)
tail -f /var/wazuh-manager/logs/wazuh.log | grep -E "ERROR|WARNING|backpressure|queue"
# → Expected: строки с ошибками или предупреждениями

# Поиск проблем с KVDB
grep -i "kvdb\|database" /var/wazuh-manager/logs/wazuh.log
# → Expected: ошибки доступа к базе состояний

# Мониторинг переполнения очередей
grep -i "queue.*full\|drop\|throttle\|backpressure" /var/wazuh-manager/logs/wazuh.log
# → Expected: сообщения о превышении capacity

# Логи агентов (на менеджере)
tail -f /var/wazuh-manager/logs/archives/agents/*.log | grep -E "disconnect|timeout|error"
```

### 6. Мониторинг места на диске и индексатора

Переполнение диска индексатора приводит к остановке приема событий.

```bash
# Проверка места на диске индексатора (OpenSearch)
curl -s -X GET "https://localhost:9200/_cat/allocation?v" -u admin:admin
# → Expected: столбцы shards, disk.indices, disk.used, disk.avail, disk.total

# Проверка watermark индексатора
curl -s -X GET "https://localhost:9200/_cluster/settings?include_defaults=true" -u admin:admin | grep watermark
# → Expected: flood_stage ~95%, high ~90%, low ~85%

# Очистка старых индексов (если disk watermark превышен)
curl -X DELETE "https://localhost:9200/wazuh-alerts-2026.01.*" -u admin:admin
```

### 7. Интеграция с Zabbix для мониторинга здоровья

Передача критических метрик здоровья во внешнюю систему мониторинга.

**Пример конфигурации Zabbix Trapper Item:**
- Имя: `Wazuh Engine Queue Size` | Ключ: `wazuh.engine.queue_size` | Тип: Числовой (Numeric (float)).
- Имя: `Wazuh Agents Disconnected` | Ключ: `wazuh.agents.disconnected` | Тип: Числовой.

**Скрипт сбора метрик (`/var/wazuh-manager/integrations/custom-wazuh-health`):**
```python
#!/var/wazuh-manager/framework/python/bin/python3
import json, requests, sys

# 1. Queue size из wazuh.yaml или OTLP
# 2. Disconnected agents через API
# 3. Disk usage индексатора
# 4. Отправка в Zabbix через history.push
```

Подробнее: [Интеграция Wazuh и Zabbix](./zabbix-integration.md).

### 8. Развертывание мониторинга через Ansible

Массовое включение самодиагностики и OTLP на парке агентов.

```yaml
---
- name: Deploy Wazuh Health Monitoring
  hosts: wazuh_managers
  become: yes
  vars:
    wazuh_telemetry_endpoint: "http://wazuh-indexer:4317"
  tasks:
    - name: Enable OTLP telemetry in wazuh.yaml
      blockinfile:
        path: /var/wazuh-manager/etc/wazuh.yaml
        marker: "# {mark} WAZUH TELEMETRY"
        block: |
          telemetry:
            enabled: true
            metrics:
              reporting_frequency: 30s
              exporters:
                - name: internal-otlp
                  type: otlp
                  endpoint: "{{ wazuh_telemetry_endpoint }}"
                  protocol: grpc

    - name: Deploy self-healing script
      copy:
        src: files/wazuh-self-check.sh
        dest: /var/wazuh-manager/bin/wazuh-self-check.sh
        mode: '0755'
        owner: root
        group: wazuh

    - name: Configure cron for self-check
      cron:
        name: "Wazuh self-health check"
        minute: "*/5"
        job: "/var/wazuh-manager/bin/wazuh-self-check.sh"

    - name: Deploy health monitoring rules
      copy:
        src: files/health_rules.xml
        dest: /var/wazuh-manager/etc/rules/local_rules.xml
        owner: root
        group: wazuh
        mode: '0640'
      notify: restart wazuh-manager

  handlers:
    - name: restart wazuh-manager
      systemd:
        name: wazuh-manager
        state: restarted
```

### 9. Резервное копирование и восстановление

#### Что бэкапить

| Компонент | Путь | Важность |
| :--- | :--- | :--- |
| Правила самодиагностики | `/var/wazuh-manager/etc/rules/local_rules.xml` | High |
| Скрипт self-healing | `/var/wazuh-manager/bin/wazuh-self-check.sh` | Medium |
| Конфигурация OTLP | `/var/wazuh-manager/etc/wazuh.yaml` (блок telemetry) | High |
| Скрипты интеграций | `/var/wazuh-manager/integrations/` | Medium |

#### Скрипт бэкапа

```bash
#!/bin/bash
BACKUP_DIR="/var/backups/wazuh-health-$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

tar czf "$BACKUP_DIR/health-monitoring.tar.gz" \
  -C /var/wazuh-manager etc/rules/local_rules.xml \
  -C /var/wazuh-manager etc/wazuh.yaml \
  -C /var/wazuh-manager bin/wazuh-self-check.sh \
  -C /var/wazuh-manager integrations/

echo "Backup saved to $BACKUP_DIR"
```

#### Восстановление

```bash
# 1. Остановите менеджер
sudo systemctl stop wazuh-manager

# 2. Восстановите файлы
tar xzf health-monitoring.tar.gz -C /

# 3. Проверьте права
sudo chown root:wazuh /var/wazuh-manager/bin/wazuh-self-check.sh
sudo chmod 0755 /var/wazuh-manager/bin/wazuh-self-check.sh

# 4. Запустите менеджер
sudo systemctl start wazuh-manager

# 5. Валидация
sudo /var/wazuh-manager/bin/wazuh-control status
sudo curl -k https://localhost:55000/health
```

## Дополнительная информация

### Критические показатели для SRE (Golden Signals)

| Метрика | Порог опасности | Действие |
| :--- | :--- | :--- |
| **Events Drop Rate** | > 1% | Масштабирование узлов `wazuh-engine`. |
| **Queue Latency** | > 500ms | Анализ источников «шумных» событий, увеличение `analysisd` workers. |
| **Disk Watermark** | > 85% | Очистка индексов или добавление нод индексатора. |
| **KVDB Lock Wait** | > 500ms | Оптимизация дисковой подсистемы (NVMe рекомендуется). |
| **Backpressure Active** | `true` | Анализ источников «шумных» событий, временное ограничение. |
| **Agents Disconnected** | > 5% от парка | Проверка сети, firewall, ресурсов на агентах. |

### Миграционные заметки (4.x → 5.x)

- **Пути**: `/var/ossec/` на агенте → `/var/wazuh-manager/` на менеджере. При развертывании agentless используйте пути менеджера.
- **OTLP**: В 5.x включен нативно через `wazuh.yaml`. В 4.x требовался обходной путь через логи.
- **Health Endpoint**: В 5.x добавлен единый `https://localhost:55000/health`.
- **integratord**: В 5.x работает в многопоточном режиме. Для диагностики: `wazuh-control status modules`.
- **Валидация**: В 5.x добавлен `wazuh-logtest` для тестирования декодеров и правил без перезапуска.

### Отладка и диагностика

Центральный журнал всех компонентов Wazuh 5.0 объединен:
- Путь: `/var/wazuh-manager/logs/wazuh.log`
- Для диагностики OTLP: `grep "telemetry" /var/wazuh-manager/logs/wazuh.log`
- Для диагностики очередей: `grep "queue" /var/wazuh-manager/logs/wazuh.log`
- Для диагностики KVDB: `grep "kvdb" /var/wazuh-manager/logs/wazuh.log`

### Best Practices

1. **Golden Signals First**: Настройте мониторинг 5-ти ключевых метрик (events rate, queue latency, disk watermark, KVDB latency, backpressure). Они дают 90% картины здоровья системы.
2. **Health Endpoint в балансировщике**: Если используется HAProxy/Nginx перед Wazuh Manager, настройте health check на `https://localhost:55000/health` для автоматического исключения нерабочих узлов.
3. **Self-healing с канарейками**: Скрипт self-check должен сначала проверять канареечного агента (test agent), и только потом перезапускать весь менеджер.
4. **Логи rotation**: Настройте `logrotate` для `/var/wazuh-manager/logs/wazuh.log` с ротацией по размеру (>1GB) или времени (>7 дней). Иначе диск заполнится быстрее, чем Wazuh обработает события.
5. **Disk Watermark Monitoring**: Регулярно проверяйте watermark индексатора (85%/90%/95%). Настройте алерт в Zabbix/Prometheus на `disk.avail < 20%`.
6. **OTLP Sampling**: На высоконагруженных системах (>10k events/sec) используйте sampling в OTLP-экспортере (например, 10% выборки) для снижения нагрузки на коллектор.
7. **Cluster Monitoring**: В кластере мониторьте не только каждый узел, но и синхронизацию между ними. При сбое синхронизации события могут теряться.
8. **Резервное копирование CA**: Бэкап `wazuh-passwords.txt` и сертификатов выполняется отдельно от мониторинга, но при потере CA Health Endpoint вернет 503.

### Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Health Endpoint возвращает 503** | Сертификат истек или Wazuh Engine не запущен | Проверьте `systemctl status wazuh-manager`, обновите сертификаты через `wazuh-passwords-tool` |
| **OTLP метрики не доходят** | Неверный endpoint или firewall блокирует порт 4317 | Проверьте сетевую доступность: `nc -zv wazuh-indexer 4317` |
| **Очереди постоянно растут** | Шумные источники или нехватка CPU/RAM на Manager | Временно включите backpressure, найдите источник через `wazuh-logtest`, масштабируйте hardware |
| **KVDB операции > 500ms** | Дисковая подсистема перегружена или база фрагментирована | Перейдите на NVMe, проверьте `iostat`, при необходимости перезапустите KVDB |
| **Agents Disconnected > 5%** | Проблемы с сетью, firewall, ресурсы на агентах | Проверьте `agent_control -l`, DNS-резолвинг, доступность порта 1514 |
| **Backpressure всегда активен** | Индексатор перегружен или размер шардов превышает лимиты | Очистите старые индексы, добавьте ноды в кластер OpenSearch, увеличьте replication |
| **Self-healing не работает** | Скрипт не имеет прав на `systemctl restart` или cron не настроен | Проверьте `sudo -l` для пользователя wazuh, логи cron `/var/log/syslog` |
| **wazuh-control status показывает "dead"** | Процесс упал из-за ошибки в конфигурации или нехватки памяти | Проверьте `journalctl -u wazuh-manager`, восстановите конфигурацию из бэкапа |

### Edge Cases и ограничения

- **Эпизодические агенты**: При массовом подключении агентов (>500 за минуту) может временно активироваться Backpressure. Это штатное поведение, а не ошибка.
- **Кластерная консистенция**: В кластере из 3+ узлов при потере кворума Health Endpoint может вернуть 503, хотя отдельные узлы работают. Мониторьте каждый узел индивидуально.
- **Windows Event Channel**: На Windows-агентах Health Endpoint может быть недоступен из-за правил firewall. Используйте `wazuh-control status` на агенте.
- **OTLP и Proxy**: Если Wazuh Manager находится за HTTP-прокси, OTLP/gRPC может не работать через стандартный порт 4317. Используйте HTTP/1.1 fallback (порт 4318) или настройте прокси для CONNECT.
- **Високосный год и DST**: При переходе на летнее/зимнее время могут возникать дублирующие события из-за сдвига часового пояса. Мониторьте `events.processed_total` в OTLP на аномальные пики.
- **Дисковые квоты**: Если `/var/wazuh-manager/` размещен на отдельном разделе с квотами, превышение квоты приведет к остановке менеджера. Мониторьте `df -h` и `quota` в Golden Signals.

### См. также

- [Wazuh: обзор SIEM](../wazuh.md)
- [Интеграция Wazuh и Zabbix](./zabbix-integration.md) — передача OTLP-метрик во внешний мониторинг.
- [Сбор логов (Logcollector)](./wazuh-log-collection.md) — конфигурация источников для самомониторинга.
