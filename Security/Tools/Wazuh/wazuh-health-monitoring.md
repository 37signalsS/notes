# Мониторинг здоровья и самодиагностика Wazuh

## Определения

**Мониторинг Wazuh** — комплекс процессов по контролю работоспособности узлов SIEM (агентов, менеджеров, индексаторов). В версии **Wazuh 5.0+** мониторинг трансформирован в систему глубокой наблюдаемости (**Observability**), интегрированную с отраслевыми стандартами передачи телеметрии.

**Самодиагностика (Self-monitoring)** — встроенный механизм **Wazuh-Engine**, использующий нативные средства (OTLP, внутренние очереди, логи) для анализа состояния процессов и автоматического предотвращения деградации производительности.

## Основные концепции

### Архитектура наблюдаемости (Wazuh 5.0)

В 2026 году мониторинг здоровья Wazuh базируется на четырех столпах:

1.  **OTLP-телеметрия**: Переход на стандарт **OpenTelemetry**. Движок Wazuh генерирует метрики (Counters, Gauges, Histograms), которые могут быть экспортированы во внешние коллекторы или внутренний индексатор.
2.  **Wazuh-Engine Health**: Контроль модульного ядра, включая **KVDB** (хранилище состояний), **Router** (маршрутизация событий) и **Server** (логика анализа).
3.  **Indexing Pressure (Backpressure)**: Механизм динамического ограничения входящего потока данных при перегрузке индексатора (OpenSearch 3.x), предотвращающий падение системы.
4.  **Единый кластер**: Мониторинг состояния синхронизации в режиме кластера, который в 5.0 активен по умолчанию для всех типов инсталляций.

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
*   `wazuh.engine.events.processed_total`: Общее количество обработанных событий.
*   `wazuh.engine.queue.latency`: Задержка обработки событий в очередях.
*   `wazuh.kvdb.operation_duration`: Время отклика базы данных состояний.

### 2. Контроль статуса агентов (v5 API)

В современных версиях для проверки статусов рекомендуется использовать REST API, так как он предоставляет более полную информацию о версии протокола и возможностях агента.

**Запрос статуса через CLI:**
```bash
# Получение списка отключенных агентов
curl -k -X GET "https://localhost:55000/agents?status=disconnected" -H "Authorization: Bearer $TOKEN"
```

**Legacy CLI (сохранено для совместимости):**
```bash
# Проверка связи на менеджере
/var/wazuh-manager/bin/agent_control -l
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

## Дополнительная информация

### Критические показатели для SRE (Golden Signals)

| Метрика | Порог опасности | Действие |
| :--- | :--- | :--- |
| **Events Drop Rate** | > 1% | Масштабирование узлов `wazuh-engine`. |
| **Disk Watermark** | > 85% | Очистка индексов или добавление нод индексатора. |
| **KVDB Lock Wait** | > 500ms | Оптимизация дисковой подсистемы (NVMe рекомендуется). |
| **Backpressure Active** | `true` | Анализ источников «шумных» событий. |

### Отладка и диагностика
Центральный журнал всех компонентов Wazuh 5.0 объединен:
*   Путь: `/var/wazuh-manager/logs/wazuh.log`
*   Для диагностики OTLP используйте: `grep "telemetry" /var/wazuh-manager/logs/wazuh.log`

### См. также
- [Wazuh: обзор SIEM](../wazuh.md)
- [Интеграция Wazuh и Zabbix](./zabbix-integration.md) — передача OTLP-метрик во внешний мониторинг.
- [Сбор логов (Logcollector)](./wazuh-log-collection.md) — конфигурация источников для самомониторинга.
