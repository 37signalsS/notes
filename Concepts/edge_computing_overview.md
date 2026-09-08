# Граничные вычисления (Edge Computing) — Обзор

В условиях роста объема данных от IoT-устройств и требований к мгновенному отклику пользовательских интерфейсов (5G/6G, Metaverse), традиционная централизованная облачная модель сталкивается с ограничениями скорости света и пропускной способности каналов. Граничные вычисления (Edge Computing) решают эти проблемы, перенося обработку данных в непосредственную близость к их источнику.

## Определения

**Граничные вычисления (Edge Computing)** — это распределенная ИТ-архитектура, в которой обработка клиентских данных происходит на периферии сети, как можно ближе к источнику данных. 

**Ключевые термины:**
*   **Edge Node (Граничный узел):** Любое устройство, обладающее вычислительной мощностью и расположенное между источником данных и облаком (от сенсора до микро-ЦОД).
*   **PoP (Point of Presence):** Географически распределенная точка присутствия (обычно у CDN-провайдеров), где размещаются граничные серверы.
*   **Cloud Repatriation (Репатриация в облако):** Процесс отправки только критически важных или агрегированных данных с границы в центральное облако для долгосрочного хранения или глубокого анализа.

## Предварительные требования

Для работы с Edge-архитектурами необходимо понимание следующих концепций:
*   **[Протокол HTTP и Fetch API](../Networking/Protocols/HTTP/http_basics.md):** База для разработки Edge-функций.
*   **Контейнеризация (Docker):** Основа для Fog-узлов, хотя на самой границе чаще используется WASM.
*   **[Принципы кэширования](./Caching/caching_overview.md):** Edge неразрывно связан с CDN и инвалидацией данных.

## Базовые концепции

### Сравнение архитектурных моделей

| Характеристика | Cloud Computing (Центр) | Edge Computing (Граница) |
| :--- | :--- | :--- |
| **Задержка (Latency)** | Высокая (50–250 мс) | **Низкая (1–10 мс)** |
| **Пропускная способность** | Ограничена магистралью ЦОД | Максимальная (локальная сеть) |
| **Безопасность** | Периметральная защита | **Zero Trust, Аппаратные анклавы** |
| **Масштабирование** | Вертикальное и Горизонтальное | Распределенное (тысячи малых узлов) |
| **Среда выполнения** | VM, Kubernetes, Bare Metal | **WASM, Serverless Functions** |

### Иерархия: Edge vs Fog vs Cloud

Часто термины Edge и Fog путают. В современной инженерии принята следующая иерархия:
1.  **Edge Layer (Уровень устройств):** Датчики, камеры, смартфоны. Минимальная обработка (фильтрация).
2.  **Fog Layer (Туманный уровень):** Локальные шлюзы (IoT Gateways), микро-ЦОД в офисе/заводе. Агрегация данных от группы Edge-устройств, принятие быстрых решений (например, остановка конвейера).
3.  **Cloud Layer (Облачный уровень):** Глобальные дата-центры. Обучение ML-моделей, Big Data аналитика, хранение истории.

### Архитектурные паттерны Edge

1.  **Local-First Architecture:** Приложение работает полностью автономно на устройстве, используя облако только для синхронизации (например, Figma или SQLite в браузере).
2.  **Edge Aggregator:** Граничный узел собирает тысячи метрик в секунду, вычисляет среднее/максимальное и отправляет в облако одну запись раз в минуту.
3.  **Programmable CDN:** Выполнение логики (авторизация, трансформация изображений) на узлах CDN до того, как запрос дойдет до бэкенда.

### CAP-теорема на границе

На границе сети компромисс смещается в сторону **Availability (Доступность)** и **Partition Tolerance (Устойчивость к разделению)**. Консистентность (Consistency) часто приносится в жертву ради скорости отклика. 
*Подробнее:* **[CAP-теорема в распределенных системах](../Databases/Concepts/cap_theorem.md)**.

## Практические сценарии

### Пошаговое развертывание Edge-функции (Wasm/Spin)

WebAssembly стал стандартом де-факто для Edge из-за отсутствия «холодного старта» и малого потребления памяти.

**Шаг 1: Установка инструментария (например, Fermyon Spin)**
```bash
curl -fsSL https://developer.fermyon.com/install.sh | bash
```

**Шаг 2: Создание компонента на Rust/Go/JS**
```bash
spin new -t http-js hello-edge
```

**Шаг 3: Реализация логики (обработка на границе)**
```javascript
// index.js
export async function handleRequest(request) {
    const userAgent = request.headers.get("user-agent");
    
    // Блокировка ботов на границе без обращения к БД
    if (userAgent.includes("BadBot")) {
        return { status: 403, body: "Access Denied" };
    }

    return {
        status: 200,
        headers: { "content-type": "text/plain" },
        body: "Hello from the Edge!"
    };
}
```

**Шаг 4: Деплой**
Развертывание происходит одной командой в глобальную сеть провайдера (Cloudflare, Akamai, Fastly).

### Оркестрация Edge-узлов (K3s / Nomad)

Когда у вас сотни локальных серверов (в каждом магазине сети), использовать тяжелый Kubernetes нецелесообразно.

*   **K3s:** Легковесный дистрибутив Kubernetes, оптимизированный для ARM и Edge. Использует SQLite вместо etcd, встроенные ServiceLB и Local Path Provisioner. Идеален для одно- и малонодовых кластеров на удаленных объектах. Подробнее: **[Архитектура K3s](../Kubernetes/Installation/k3s_dev_environment/k3s_architecture.md)**.
*   **Nomad:** Легковесный оркестратор от HashiCorp, позволяющий запускать Docker-контейнеры, бинарные файлы и WASM-модули в едином кластере. Минимальный оверхед (один бинарный файл), нативная интеграция с Consul и Vault. Подробнее: **[Nomad — определения и базовые концепции](../Nomad/definitions_and_concepts.md)**, **[Практические сценарии Nomad](../Nomad/practical_scenarios.md)**.

**Kритерий выбора оркестратора для Edge:**

| Критерий | K3s | Nomad |
| :--- | :--- | :--- |
| **Размер кластера** | 1–100 узлов | 1–1000+ узлов |
| **Минимальные ресурсы** | 512 МБ RAM | 64 МБ RAM |
| **Типы нагрузок** | Контейнеры (OCI) | Контейнеры, бинарники, WASM, Java, QEMU |
| **Обучение команды** | Kubernetes (широкие навыки) | Минимальный порог входа |
| **Экосистема** | Огромная (Helm, Operators) | Умеренная (Nomad Pack) |
| **Autoscaling** | HPA/VPA/Karpenter | Nomad Autoscaler |

### Безопасность на Edge

Edge-узлы находятся в физически недоступных или слабо защищенных местах (торговые точки, производственные линии, уличные шкафы), что делает безопасность критическим требованием.

**Принцип Zero Trust на границе:**
1.  **Device Identity:** Каждый Edge-узел должен иметь уникальный идентификатор (TPM-based certificate или X.509). Никаких shared secrets между узлами.
2.  **mTLS (Mutual TLS):** Все通信ы между Edge и Fog/Cloud шифруются с взаимной аутентификацией. Сертификаты выдаются через внутренний CA (Vault, step-ca) с автоматической ротацией.
3.  **Network Segmentation:** Edge-узлы не имеют прямого доступа друг к другу. Вся коммуникация идет через Fog-шлюз или центральный Endpoint.
4.  **Secure Boot и Measured Boot:** Проверка целостности загрузочной цепочки (UEFI Secure Boot + TPM) для обнаружения подмены ОС или firmware.
5.  **Minimal Attack Surface:** На Edge-узле запущен только необходимый набор сервисов. Лишние порты, сервисы и пользователи отключены.

**Практическая реализация — управление сертификатами:**
```bash
# Установка step-ca (Mesh Secretary) на Fog-узле
step ca init --name "Edge-Internal-CA" --provisioner "edge-bootstrapper"

# Получение сертификата на Edge-узле (при первичной настройке)
step ca certificate "edge-node-001.example.internal" \
    /etc/edge/tls/cert.pem \
    /etc/edge/tls/key.pem \
    --ca-url https://fog-ca.example.internal:8443 \
    --root /etc/edge/tls/root_ca.pem \
    --not-after 720h  # 30 дней

# Автоматическая ротация через systemd timer
# /etc/systemd/system/cert-renew.timer
[Timer]
OnBootSec=5min
OnUnitActiveSec=24h

# Проверка срока действия сертификата
step certificate inspect /etc/edge/tls/cert.pem | grep "Not After"
```

**Сегментация сети для Edge:**
```bash
# iptables: разрешить только исходящие подключения к Fog-шлюзу
iptables -A INPUT -s 10.0.1.0/24 -j ACCEPT  # Fog subnet
iptables -A INPUT -s 127.0.0.1 -j ACCEPT     # localhost
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -j DROP                      # Всё остальное — запрещено

# Ограничение доступа к сервисам Edge-узла
iptables -A INPUT -p tcp --dport 22 -s 10.0.1.10 -j ACCEPT  # SSH только с Fog
iptables -A INPUT -p tcp --dport 22 -j DROP
```

### Мониторинг и Observability на Edge

Мониторинг тысяч распределенных Edge-узлов требует иного подхода, чем мониторинг централизованного кластера. Ключевой принцип: **сбор данных на границе, агрегация и анализ на Fog/Cloud уровне**.

**Архитектура наблюдаемости:**

| Уровень | Что собирается | Инструмент | Частота |
| :--- | :--- | :--- | :--- |
| **Edge** | CPU, RAM, disk, network, service health | Prometheus Node Exporter, Vector | 15–60 сек |
| **Fog** | Агрегированные метрики, логи, алерты | Prometheus (federation), Loki | 5–15 сек |
| **Cloud** | Дашборды, long-term storage, аналитика | Grafana, Thanos/Cortex | 1–5 мин |

**Сбор логов на Edge (Vector):**
```yaml
# /etc/vector/vector.toml — конфигурация агента на Edge-узле
[sources.system_logs]
type = "file"
include = ["/var/log/syslog", "/var/log/edge-app/*.log"]
read_from = "beginning"

[transforms.parse]
type = "remap"
inputs = ["system_logs"]
source = '''
  .timestamp = now()
  .hostname = get_hostname!()
  .edge_node = "edge-node-001"
  .level = upcase!(.level)
'''

[sinks.fog_destination]
type = "http"
inputs = ["parse"]
uri = "http://fog-collector.example.internal:8080/api/v1/logs"
encoding = "json"
batch.max_events = 100
batch.timeout_secs = 30
# Буферизация при потере связи с Fog
buffer.type = "memory"
buffer.max_events = 10000
```

**Healthcheck Edge-узлов (простой скрипт):**
```bash
#!/bin/bash
# /opt/edge/healthcheck.sh — выполняется через cron каждые 60 секунд
HEALTH_ENDPOINT="http://fog-collector.example.internal:8080/health"

STATUS=$(curl -sf --max-time 5 "$HEALTH_ENDPOINT" 2>/dev/null)
if [ $? -ne 0 ]; then
    # Fog-шлюз недоступен — переключение на локальный режим
    systemctl stop edge-app-forwarder
    echo "$(date -Iseconds) WARNING: Fog unreachable, switching to local mode" >> /var/log/edge-health.log
    # Запуск автономного режима (см. раздел "Автономность")
    systemctl start edge-app-local
fi
```

**Ключевые метрики для Edge:**

| Метрика | Описание | Порог алерта |
| :--- | :--- | :--- |
| `edge_up` | Доступность узла (ping/Fog connection) | 0 (узел offline) |
| `edge_disk_usage_percent` | Использование диска | > 85% |
| `edge_sync_lag_seconds` | Задержка синхронизации данных | > 300 сек |
| `edge_cert_expiry_days` | Дней до истечения сертификата | < 14 дней |
| `edge_app_restart_count` | Количество перезапусков приложения | > 3 за час |

### Синхронизация данных и автономность

Edge-узлы должны работать в условиях нестабильной или полностью отсутствующей связи с Fog/Cloud. Паттерн **Local-First** гарантирует работоспособность приложения без внешних зависимостей.

**Паттерн: Offline Queue (очередь отправки)**
```python
# Простая реализация очереди на SQLite для edge-устройств
import sqlite3, json, time, requests

DB = sqlite3.connect("/var/lib/edge/pending_events.db")
DB.execute("""CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    payload TEXT,
    created_at REAL,
    synced INTEGER DEFAULT 0
)""")

def queue_event(event: dict):
    """Сохранить событие в очередь (вызывается при каждом действии пользователя)"""
    DB.execute("INSERT INTO events (payload, created_at) VALUES (?, ?)",
               (json.dumps(event), time.time()))
    DB.commit()

def sync_events(fog_url: str):
    """Отправить все несинхронизированные события при наличии связи"""
    unsynced = DB.execute("SELECT id, payload FROM events WHERE synced = 0").fetchall()
    for event_id, payload in unsynced:
        try:
            resp = requests.post(fog_url, data=payload, timeout=10)
            if resp.status_code == 200:
                DB.execute("UPDATE events SET synced = 1 WHERE id = ?", (event_id,))
        except requests.ConnectionError:
            break  # Связь потеряна — попробуем позже
    DB.commit()
```

**CRDT (Conflict-free Replicated Data Type):**
Для данных, которые модифицируются на нескольких Edge-узлах одновременно, используются CRDT-структуры, гарантирующие автоматическое разрешение конфликтов без централизованного координатора.

*   **G-Counter:** Счетчик, который можно только инкрементировать. Каждый узел хранит свой counter; итоговое значение — сумма по всем узлам.
*   **LWW-Register (Last-Writer-Wins):** Регистр с разрешением по времени. При конфликте побеждает запись с более поздним timestamp.
*   **OR-Set (Observed-Remove Set):** Множество с поддержкой добавления и удаления. Обеспечивает eventual consistency даже при параллельных модификациях.

**Паттерн: Data Reconciliation (примирение данных):**
```
1. Edge-узел работает автономно, накапливая изменения в локальном хранилище
2. При восстановлении связи — отправка всех изменений Fog-шлюзу
3. Fog-шлюз сравнивает версии данных (vector clocks или timestamps)
4. Конфликтные изменения разрешаются через CRDT или Business Logic
5. Результат рассылается обратно на все Edge-узлы
```

### Стратегии деплоя и обновлений на Edge

Обновление сотен распределенных Edge-узлов требует автоматизации и механизмов безопасного отката.

**GitOps для Edge (Flux pull-per-cluster):**
Каждый Edge-узел (или кластер K3s) самостоятельно тянет конфигурацию из Git-репозитория. Это обеспечивает:
*   Автономность: при потере связи с central hub узел продолжает работать в текущей версии.
*   Идемпотентность: повторный pull не изменяет состояние, если Git не обновлен.
*   Откат: откат версии — это коммит в Git, который будет применен на всех узлах.

**Паттерн: Canary Deployment на Edge:**
```
1. Новая версия деплоится на 5% Edge-узлов (canary группа)
2. Мониторинг метрик в течение N минут
3. Если метрики в норме — раскатка на оставшиеся 95%
4. Если обнаружены проблемы — автоматический откат canary
5. Рассылка уведомления команде
```

**OTA (Over-the-Air) обновления для bare-metal Edge:**
```bash
# /opt/edge/update.sh — скрипт обновления на bare-metal Edge-узле
#!/bin/bash
set -euo pipefail

CURRENT_VERSION=$(cat /opt/edge/VERSION)
REMOTE_VERSION=$(curl -sf https://releases.example.internal/edge/latest-version.txt)
LOG_FILE="/var/log/edge-update.log"

echo "$(date -Iseconds) Starting update: $CURRENT_VERSION -> $REMOTE_VERSION" >> "$LOG_FILE"

# Скачивание нового образа
curl -sf -o /tmp/edge-update.tar.gz \
    "https://releases.example.internal/edge/${REMOTE_VERSION}/edge-rootfs.tar.gz"

# Проверка целостности
echo "$(sha256sum /tmp/edge-update.tar.gz | awk '{print $1}')" | \
    diff - <(curl -sf "https://releases.example.internal/edge/${REMOTE_VERSION}/sha256sum.txt") || {
    echo "$(date -Iseconds) ERROR: Checksum mismatch" >> "$LOG_FILE"
    exit 1
}

# Бэкап текущей версии
cp -a /opt/edge/current /opt/edge/backup-$(date +%Y%m%d%H%M)

# Применение обновления
tar -xzf /tmp/edge-update.tar.gz -C /opt/edge/current
echo "$REMOTE_VERSION" > /opt/edge/current/VERSION

# Перезапуск сервиса
systemctl restart edge-app
echo "$(date -Iseconds) Update completed successfully" >> "$LOG_FILE"
```

### Ограничения ресурсов и аппаратная специфика

Edge-устройства работают в условиях жестких аппаратных ограничений, что влияет на выбор технологий и архитектурных решений.

**Типичные конфигурации Edge-узлов:**

| Класс | CPU | RAM | Storage | Примеры устройств |
| :--- | :--- | :--- | :--- | :--- |
| **Micro Edge** | 1-2 ядра (ARM Cortex-A) | 256 МБ–1 ГБ | 8–32 ГБ eMMC/SD | Raspberry Pi, ESP32, промышленные PLC |
| **Small Edge** | 2-4 ядра (ARM/x86) | 2–8 ГБ | 32–120 ГБ SSD | Intel NUC, Cisco IR1101, outpost-серверы |
| **Medium Edge** | 4-8 ядер (x86) | 8–32 ГБ | 120–500 ГБ SSD | Рacks в телеком-шкафах, микро-ЦОД |

**Оптимизация для ограниченных ресурсов:**
*   **Архитектура ARM:** Большинство Edge-устройств используют ARM (Raspberry Pi, Qualcomm, NXP). Контейнеры и бинарники должны компилироваться под `linux/arm64` или `linux/arm/v7`.
*   **Агрессивное кэширование:** Приложение должно работать с локальными данными, обращаясь к Fog/Cloud только при необходимости.
*   **Энергопотребление:** Для удаленных объектов с питанием от батарей или солнечных панелей — критичен TDP. WASM-модули потребляют в 10–50 раз меньше RAM, чем Docker-контейнеры.
*   **Пространство на диске:** Используйте read-only rootfs (OverlayFS), ротацию логов с жесткими квотами, и агрегацию логов на Fog-уровне.

### Автономность и disaster recovery

Edge-узлы должны быть спроектированы для длительной работы без связи с Fog/Cloud.

**Режимы работы при потере связи:**

| Режим | Описание | Применение |
| :--- | :--- | :--- |
| **Full Mode** | Связь с Fog есть, данные синхронизируются в реальном времени | Штатная работа |
| **Degraded Mode** | Связь нестабильна, данные буферизуются локально | Проблемы с сетью |
| **Local Mode** | Связь отсутствует, работает только локальная логика | Outage Fog/Cloud |
| **Safe Mode** | Критические системы, минимальный набор функций | Аварийные ситуации |

**Паттерн: Watchdog с автоперезапуском:**
```bash
# /etc/systemd/system/edge-watchdog.service
[Unit]
Description=Edge Application Watchdog
After=edge-app.service

[Service]
Type=oneshot
ExecStartPre=/bin/sh -c 'systemctl is-active edge-app || systemctl start edge-app'
ExecStart=/opt/edge/watchdog.sh
Restart=always
RestartSec=30

# /opt/edge/watchdog.sh
#!/bin/bash
APP_PID=$(systemctl show edge-app -p MainPID --value)
if [ "$APP_PID" -eq 0 ]; then
    echo "$(date -Iseconds) CRITICAL: edge-app not running, restarting" >> /var/log/edge-watchdog.log
    systemctl restart edge-app
fi

# Проверка дискового пространства
DISK_USAGE=$(df / --output=pcent | tail -1 | tr -d '% ')
if [ "$DISK_USAGE" -gt 90 ]; then
    echo "$(date -Iseconds) WARNING: Disk usage ${DISK_USAGE}%, cleaning logs" >> /var/log/edge-watchdog.log
    find /var/log/edge-app/ -name "*.log" -mtime +7 -delete
fi
```

**Паттерн: Last Resort Recovery:**
При критическом сбое (boot failure, filesystem corruption) Edge-узел должен уметь:
1.  Загрузиться с read-only корневого раздела (OverlayFS).
2.  Восстановить конфигурацию из Fog (если связь есть) или из локального бэкапа.
3.  Отправить alert о необходимости физического вмешательства.

## Валидация и тестирование

Тестирование Edge-систем требует имитации реальных сетевых условий:
1.  **Latency Benchmarking:** Использование инструментов вроде `wrk` или `k6` из разных географических регионов.
2.  **Chaos Engineering на границе:** Эмуляция потери связи между Fog-узлом и Облаком для проверки режима автономности (Local Survivability).
3.  **Cold Start Analysis:** Замер времени от прихода запроса до исполнения первой инструкции (для WASM это обычно < 1 мс).

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Дрифт конфигурации** | Разные версии кода на разных Edge-узлах. | Использовать GitOps (Flux pull-per-cluster) с поддержкой иерархических кластеров. |
| **Исчерпание ресурсов** | Утечки памяти в WASM-рантайме или переполнение диска логами. | Квотирование ресурсов, агрегация логов через Vector/Fluentd на Fog-уровне, ротация с квотами. |
| **Проблемы с TLS** | Устаревшие сертификаты на изолированных устройствах. | Автоматическая ротация через step-ca/Vault с systemd timer; graceful renewal за 14 дней до истечения. |
| **Потеря связи с Fog** | Обрыв сети, outage Fog-шлюза. | Local-First архитектура с offline queue; автоматическое переключение в Local Mode. |
| **Конфликт данных** | Параллельные записи на разных Edge-узлах без связи. | CRDT-структуры (G-Counter, LWW-Register) или Application-level conflict resolution при reconciliation. |
| **Неудачный OTA-деплой** | Баг в новой версии, «заморозка» Edge-узла. | A/B-обновления с автоматическим откатом watchdog-таймером; хранение предыдущей версии на диске. |
| **Целостность прошивки** | Подмена ОС или tampering с файловой системой. | UEFI Secure Boot + TPM measured boot; регулярная верификация rootfs через dm-verity. |
| **Засорение каталога сервисов** | Записи от удаленных или переехавших Edge-узлов в Consul/Nomad. | Настройка `deregister_critical_service_after` для автоматической очистки. |

## Лучшие практики

1.  **Stateless by Design:** Edge-функции должны быть максимально легкими и не хранить состояние в памяти. Для состояния используйте **[Global KV-stores](../Databases/redis_overview.md)** или локальные SQLite с offline queue.
2.  **Zero Trust Edge:** Никогда не доверяйте данным с Edge-устройств. Проверяйте mTLS и подписи на каждом этапе. Подробнее в разделе "Безопасность на Edge".
3.  **Оптимизация полезной нагрузки:** Используйте бинарные форматы (Protobuf, Avro) вместо JSON для экономии трафика между Edge и Fog.
4.  **Observability First:** Внедряйте OpenTelemetry с самого начала. Отладка распределенной системы из 10 000 узлов без трассировки невозможна.
5.  **Idempotent Operations:** Все операции (деплой, синхронизация, обновление) должны быть идемпотентными — повторное выполнение не должно изменять результат. Подробнее: **[Идемпотентность](./idempotency.md)**.
6.  **Defense in Depth:** Комбинируйте Secure Boot, шифрование диска (LUKS), межсетевое экранирование (iptables/nftables), и регулярное сканирование уязвимостей (Trivy, Grype) для образов.
7.  **Graceful Degradation:** Приложение должно корректно работать в каждом режиме (Full/Degraded/Local/Safe), а не падать при потере связи.
8.  **Hardware-agnostic Design:** Используйте multi-arch образы (amd64 + arm64) и избегайте зависимостей от конкретного железа. Для ARM-устройств компилируйте с CGO_ENABLED=0 или используйте статическую линковку.

## Дополнительная информация

### См. также
*   **[Обзор CDN](../Networking/CDN/cdn_overview.md)** — инфраструктурный фундамент и PoP-узлы.
*   **[SQLite для Edge-вычислений](../Databases/SQLite/sqlite_overview.md)** — локальные БД для автономной работы.
*   **[Nomad — определения и базовые концепции](../Nomad/definitions_and_concepts.md)** — легковесная оркестрация Edge-кластеров.
