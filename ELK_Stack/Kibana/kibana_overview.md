# Kibana: Обзор

> Эта заметка является частью обзора [ELK стека](../elk_stack_overview.md) и служит основной точкой входа для изучения Kibana. Данные актуальны для версий **8.19** (финальный минор 8.x, поддержка до 15 июля 2027) и **9.x** (текущая стабильная — 9.5.5; из ветки 9.x поддерживаются только миноры 9.4 и 9.5 — более ранние 9.0–9.3 уже EOL).

## Определения

* **Kibana** — это центральный интерфейс управления и визуализации в Elastic Stack. Она служит "окном" в данные, хранящиеся в [Elasticsearch](../Elasticsearch/elasticsearch_overview.md), предоставляя инструменты для анализа логов, мониторинга инфраструктуры и обеспечения безопасности. В версии 9.x Kibana стала платформой для автоматизации рабочих процессов (Workflows).
* **Data View (ранее Index Pattern)** — логическая абстракция над индексами Elasticsearch. Она определяет, какие поля доступны для поиска и визуализации, их типы и форматы. Data View остаются обязательными для классических визуализаций Lens и дашбордов; ES|QL в ряде сценариев может работать напрямую с индексами и алиасами.
* **KQL (Kibana Query Language)** — основной язык запросов для фильтрации данных в Discover и на дашбордах. Отличается простым синтаксисом и мощным автодополнением. Оптимален для быстрой фильтрации; KQL умеет только фильтровать — агрегации и трансформации выполняются через Lens или ES|QL. Полный синтаксис и примеры — в [Kibana: Поиск, визуализация и управление](./kibana_search_and_visualization.md).
* **ES|QL (Elasticsearch Query Language)** — потоковый (piped) язык запросов, позволяющий выполнять поиск, фильтрацию, агрегацию и трансформацию данных в одном запросе на поколоночном движке Elasticsearch. GA с версии 8.14, в 9.x — основной рекомендуемый язык для аналитики.
* **Saved Objects** — сущности, создаваемые в Kibana (дашборды, визуализации, Data Views, алерты). Хранятся в специальных системных индексах Elasticsearch и могут экспортироваться в формате NDJSON для версионирования и GitOps.
* **Spaces (Пространства)** — механизм логической изоляции объектов. Позволяет разделять дашборды и настройки между командами или проектами внутри одного инстанса Kibana. Рекомендуется для мультитенантности и сегментации доступа.
* **Workflows** — система автоматизации рутинных задач в Kibana (версия 9.x). Позволяет создавать цепочки действий для обработки инцидентов, управления алертами и интеграции с внешними системами.

## Основные концепции

### Аналитика и визуализация
* **Discover** — инструмент для исследования необработанных данных. Включает режим **Document Explorer** для навигации по большим объемам записей. Поддерживает ES|QL-запросы для аналитики без создания дашбордов.
* **Dashboard** — интерактивные панели. С версии 9.4 элементы управления (фильтры) стали полноценными панелями: их можно размещать в любом месте дашборда, закреплять вверху или вкладывать в сворачиваемые секции с локальной областью действия (scoping).
* **Lens** — основной визуальный конструктор с поддержкой drag-and-drop. Автоматически выбирает оптимальный тип графика на основе перетащенных полей. Поддерживает формулы (Formula), справочные линии и ES|QL как источник данных.
* **Maps** — многослойные карты для анализа геоданных в реальном времени. Поддерживает добавление слоев через ES|QL запросы.
* **Vega и Vega-Lite** — создание полностью кастомных визуализаций на базе JSON-спецификаций для задач, которые невозможно решить стандартными инструментами.

### Решения
* **Observability** — унифицированный мониторинг логов, метрик и трассировок (APM). Активно использует **OpenTelemetry (OTel)** как стандарт доставки данных. С 9.4 (tech preview) доступна нативная поддержка Prometheus: доставка метрик через Remote Write и выполнение PromQL-запросов прямо в ES|QL-редакторе Kibana через команду `PROMQL` — существующие PromQL-запросы работают без переписывания.
* **Security** — полноценная SIEM-система и инструменты защиты конечных точек (Endpoint Security). Рутинные сценарии реагирования на инциденты автоматизируются через Workflows.
* **Machine Learning** — автоматическое обнаружение аномалий (anomaly detection) и прогнозирование временных рядов в Observability и Security. ML-задачи выполняются локально на узлах Elasticsearch (X-Pack ML), без внешних сервисов.

### Управление и безопасность
* **Fleet и Elastic Agent** — централизованное управление сбором данных. Kibana выступает в роли панели управления (Control Plane) для тысяч агентов. Детали — в [Fleet и Elastic Agent](../Elasticsearch/elastic_agent_and_fleet.md).
* **RBAC (Role-Based Access Control)** — гибкая настройка прав доступа. Можно ограничить пользователя конкретным Space или дать доступ "только на чтение" к определенным индексам. Рекомендуется принцип минимальных привилегий (least privilege). Продвинутые сценарии (DLS, FLS, SAML/OIDC) — в [Security Advanced](../Elasticsearch/elasticsearch_security_advanced.md).
* **Dev Tools (Console)** — интерактивная консоль для работы с Elasticsearch API и отладки ES|QL запросов.

### Требования к ресурсам и производительности

**Минимальные требования (для разработки/тестирования):**
* RAM: 2 ГБ (лимит памяти Kibana по умолчанию масштабируется от общего объема RAM хоста)
* CPU: 1 vCPU
* Диск: небольшой объем под логи Kibana

**Рекомендуемые требования для продакшена:**
* RAM: стартовая точка — 2 ГБ на каждые ~10 одновременных пользователей, выполняющих аналитику; масштабируйте вертикально на +2 ГБ RAM и +1 vCPU за каждые дополнительные 10 пользователей. Вертикальный потолок — ~8 vCPU / 8 ГБ, далее применяйте горизонтальное масштабирование (несколько инстансов Kibana за балансировщиком нагрузки).
* CPU: 4+ ядер для средних нагрузок
* Диск: Kibana сама по себе нетребовательна к диску (логи, временные файлы reporting); планирование ёмкости касается Elasticsearch, а не Kibana
* Сеть: стабильное соединение с Elasticsearch (низкая задержка)
* **Важно:** для функций Platinum/Enterprise (detection rules, reporting, workflows, SLO) рекомендуется минимум 2 ГБ RAM на инстанс Kibana — при меньшем объеме возможны перебои в работе этих функций.

**Оптимизация производительности:**
* Используйте **node.roles** (tech preview) для разделения режимов работы Kibana: `background_tasks` (фоновые задачи: алертинг, reporting) и `ui` (пользовательский интерфейс), или `*` для обоих (значение по умолчанию).
* Настройте **xpack.security.session.idleTimeout** и **xpack.security.session.lifespan** для автоматического завершения сессий (дефолты: 3 дня неактивности и 30 дней абсолютного срока — рекомендуется ужесточить).
* Обновляйте список полей Data View после изменения маппинга индекса (**Stack Management → Data Views → Refresh field list**), чтобы новые поля появлялись в Lens.

## Практические сценарии

### Установка и развертывание

Kibana распространяется в виде архива (.tar.gz), пакетов DEB/RPM и Docker-образа. **Версии Kibana и Elasticsearch должны совпадать** (например, 9.5.x с 9.5.x).

**Вариант 1 — Archive (.tar.gz):**

```bash
wget https://artifacts.elastic.co/downloads/kibana/kibana-9.5.5-linux-x86_64.tar.gz
tar -xzf kibana-9.5.5-linux-x86_64.tar.gz
cd kibana-9.5.5-linux-x86_64
./bin/kibana
# → Kibana запускается, конфиг по умолчанию: config/kibana.yml
```

**Вариант 2 — DEB/RPM (рекомендуется для серверов):**

```bash
# Debian/Ubuntu
echo "deb [signed-by=/usr/share/keyrings/elasticsearch-keyring.gpg] https://artifacts.elastic.co/packages/9.x/apt stable main" | sudo tee /etc/apt/sources.list.d/elastic-9.x.list
sudo apt-get update && sudo apt-get install kibana

# RHEL/CentOS — аналогично через yum-репозиторий artifacts.elastic.co/packages/9.x/yum

# Автозапуск и управление (systemd)
sudo systemctl daemon-reload
sudo systemctl enable --now kibana
sudo systemctl status kibana
# → active (running); логи: journalctl -u kibana.service
```

Расположение файлов в DEB/RPM-пакете:

| Компонент | Путь |
| :--- | :--- |
| home (`$KIBANA_HOME`) | `/usr/share/kibana` |
| Конфиг (`kibana.yml`) | `/etc/kibana` |
| Данные (`path.data`) | `/var/lib/kibana` |
| Логи (`path.logs`) | `/var/log/kibana` |

**Вариант 3 — Docker:**

```bash
docker run -d --name kibana \
  -p 5601:5601 \
  -e ELASTICSEARCH_HOSTS=https://es-cluster:9200 \
  -e ELASTICSEARCH_SERVICEACCOUNTTOKEN=AAEAAWVsYXN0aWMva2liYW5hL2Vucm9sbC10b2tlbi0... \
  docker.elastic.co/kibana/kibana:9.5.5
```

**Проверка работоспособности:**

```bash
curl -s http://localhost:5601/api/status
# → JSON со статусом: "status":{"overall":{"level":"available","summary":...},
#    "core":{"elasticsearch":{"level":...},"savedObjects":{"level":...}}, ...}
```

**Kibana Keystore** — хранилище секретных настроек (аналог Elasticsearch keystore). Пароли и ключи шифрования рекомендуется хранить здесь, а не в открытом `kibana.yml`:

```bash
sudo /usr/share/kibana/bin/kibana-keystore create
sudo /usr/share/kibana/bin/kibana-keystore add xpack.encryptedSavedObjects.encryptionKey
# → запросит значение; ключ требуется минимум 32 символа
```

Полное руководство по развертыванию стека в Docker Compose — в [Tutorials: практическая настройка](../Tutorials/practical_setup_with_docker.md).

### Создание Data View

1. Перейдите в **Stack Management** → **Data Views**.
2. Нажмите **Create data view**.
3. Укажите шаблон (например, `logs-*` или `metrics-nginx-*`).
4. Выберите поле времени (обычно `@timestamp`) для построения временных рядов.
5. **Важно:** Для production используйте конкретные шаблоны (например, `logs-app-2026.08.*`) вместо общих `logs-*` для оптимизации производительности.

### Организация работы через Spaces

Для изоляции данных команд (например, Dev и Ops):
1. Перейдите в **Stack Management** → **Spaces**.
2. Создайте пространство `Development`.
3. Настройте **Role**, разрешив доступ только к этому пространству.
4. Теперь объекты (дашборды, запросы), созданные в `Development`, не будут видны в пространстве `Default`.
5. **Best Practice:** Создайте отдельный Space для каждого проекта или сервиса, чтобы избежать пересечения данных.

### Конфигурация сервера (kibana.yml)

Протокол сервера задаётся параметром `server.protocol`. В **8.19** дефолт — **`http1`** безусловно, HTTP/2 включается явно (`server.protocol: http2`) и требует включенного TLS (`server.ssl.enabled: true`). В **9.x** дефолт становится условным: `http2`, если TLS включён, иначе `http1`; значение `http2` без TLS (h2c) валидируется отдельно и не поддерживается для обычного браузерного трафика. Статус настройки — Preview.

```yaml
# kibana.yml

# Сетевые настройки
server.host: "0.0.0.0"
server.port: 5601
server.name: "kibana-production"
# Публичный URL для формирования ссылок в алертах и email-уведомлениях
server.publicBaseUrl: "https://kibana.example.com"

# Подключение к Elasticsearch (версии ES и Kibana должны совпадать)
elasticsearch.hosts: ["https://es-cluster:9200"]

# Аутентификация: service token вместо пароля (рекомендуется для автоматизации)
elasticsearch.serviceAccountToken: "AAEAAWVsYXN0aWMva2liYW5hL2Vucm9sbC10b2tlbi0..."

# TLS для соединения Kibana -> Elasticsearch
elasticsearch.ssl.certificateAuthorities: [ "/etc/kibana/certs/ca.crt" ]

# HTTPS для браузера (опционально). HTTP/2 возможен только с включенным TLS:
# server.ssl.enabled: true
# server.ssl.certificate: /etc/kibana/certs/kibana.crt
# server.ssl.key: /etc/kibana/certs/kibana.key
# server.protocol: http2

# Локализация интерфейса
i18n.locale: "ru-RU"

# Сессии (дефолты: idleTimeout 3d, lifespan 30d — рекомендуется ужесточить)
xpack.security.session.idleTimeout: "30m"
xpack.security.session.lifespan: "24h"

# Ключ шифрования saved objects (минимум 32 символа; лучше хранить в keystore)
xpack.encryptedSavedObjects.encryptionKey: "минимум 32 символа"
logging.root.level: "info"
```

### Настройка безопасности

**SSL/TLS:**
1. Сгенерируйте сертификаты с помощью `elasticsearch-certutil` (для соединения с Elasticsearch) или собственного CA.
2. Настройте Kibana на использование HTTPS для подключения к Elasticsearch (`elasticsearch.ssl.certificateAuthorities`).
3. Для шифрования трафика браузер ↔ Kibana включите `server.ssl.enabled` и укажите сертификат сервера (`server.ssl.certificate` / `server.ssl.key`); сертификат должен содержать DNS-имя хоста, по которому пользователи открывают Kibana.
4. Убедитесь, что CA-сертификат доступен Kibana (монтирование в контейнер или указание пути в конфиге).

**RBAC (Role-Based Access Control):**
1. Создайте роли в **Stack Management** → **Roles**.
2. Определите privileges для индексов (например, `read` для `logs-*`).
3. Привяжите роли к пользователям или группам.
4. Для мультитенантности используйте **Space-aware roles** с ограничением по пространствам.

**Audit Logs:**
1. Включите аудит в `kibana.yml`:
   ```yaml
   xpack.security.audit.enabled: true
   xpack.security.audit.logfile.events.include:
     - "login_attempt"
     - "saved_objects_delete"
     - "space_delete"
   ```
2. Настройте отправку аудит-логов в Elasticsearch для централизованного мониторинга.

### Мониторинг Kibana

Kibana предоставляет встроенные эндпоинты для мониторинга:
* **Health Check:** `GET /api/status` — состояние Kibana: `status.overall.level` (`available` / `degraded` / `unavailable` / `critical`) плюс детализация по подсистемам — `status.core.elasticsearch`, `status.core.savedObjects`, `status.plugins.<plugin>`. Пока Kibana не готова (идут миграции Saved Objects или нет связи с ES), эндпоинт отдаёт **503** — это штатная readiness-проба; **200 + `level: available`** — критерий включения инстанса в балансировщик. Детали статуса для вызывающего без кластерной привилегии `monitor` отдаются обрезанными (redacted); полная картина и связанные настройки (`status.allowAnonymous`, `status.statusPageBypassMonitorPrivilege`) — в [Эксплуатации](./kibana_production_operations.md).
* **Metrics API:** `GET /api/stats` — метрики производительности (CPU, память, запросы, информация о соединениях с Elasticsearch).
* **Диагностика фоновых задач:** `GET /api/task_manager/_health` — конфигурация и runtime Task Manager (для правил и отчётов) — в [Эксплуатации](./kibana_production_operations.md).

**Рекомендации по мониторингу:**
* Настройте алертинг на основе метрик Kibana через Elasticsearch.
* Мониторьте использование памяти и времени отклика API.
* Отслеживайте количество активных соединений с Elasticsearch.
* Health-check балансировщика — `GET /api/status` (200, `status.overall.level: available`).
* Полноценный мониторинг всех компонентов стека (ES, Logstash, Beats, Kibana) с метриками и алертами — в [Stack Monitoring](../Elasticsearch/elasticsearch_stack_monitoring.md).
* Развёртывание Kibana в Kubernetes (пробы, ресурсы, типовые проблемы) — в [Kibana: практическое руководство в Kubernetes](../../Kubernetes/MonitoringLogging/EFK/kibana_guide.md).

## Дополнительная информация

### Сравнение Kibana и Grafana

| Функция | Kibana | [Grafana](../../Grafana/grafana_overview.md) |
| :--- | :--- | :--- |
| **Сильные стороны** | Глубокий анализ логов, SIEM, APM, автоматизация (Workflows) | Визуализация метрик из разных источников |
| **Источники данных** | Elasticsearch / OpenSearch | 100+ (Prometheus, Zabbix, SQL и др.) |
| **Языки запросов** | KQL, Lucene, ES|QL, PromQL (tech preview) | PromQL, LogQL, SQL |
| **Интеграция** | Бесшовная с Elastic Stack | Универсальная, OTel-нативная |
| **Machine Learning** | Встроенный ML (аномалии, прогнозы) | Ограниченные (через плагины) |
| **Автоматизация** | Workflows (9.x), Alerting | Alerting, OnCall |

### Troubleshooting

**Типичные проблемы и решения:**

1. **Kibana не подключается к Elasticsearch:**
   * Проверьте доступность Elasticsearch: `curl -k https://es-cluster:9200/_cluster/health`.
   * Убедитесь, что Service Token или учётные данные корректны.
   * Проверьте сертификаты SSL/TLS (пути, сроки действия).
   * Убедитесь, что версии Kibana и Elasticsearch совпадают (например, 9.5.x с 9.5.x).

2. **Дашборды загружаются медленно:**
   * Оптимизируйте Data View: используйте конкретные шаблоны индексов вместо общих.
   * Уменьшите количество панелей на дашборде (рекомендуется < 20).
   * Обновите список полей Data View и проверьте, что запросы не используют высококардинальные поля в top-N агрегациях.

3. **Ошибки при экспорте/импорте Saved Objects:**
   * Убедитесь, что версии Kibana совпадают (особенно при импорте из более новой версии).
   * Проверьте, все ли зависимости (Data Views, индексы) доступны в целевой системе.

4. **Проблемы с пространствами (Spaces):**
   * Убедитесь, что у пользователя есть роль с доступом к нужному пространству.
   * Проверьте, что объекты не привязаны к другому пространству.

5. **Kibana не стартует после обновления:**
   * Проверьте логи: `journalctl -u kibana.service` (DEB/RPM) или `logs/kibana.log` (архив).
   * Частая причина — несовпадение версий Kibana и Elasticsearch либо изменение `xpack.security.encryptionKey` (при смене ключа все активные сессии принудительно завершаются).

### Best Practices

**Для производственных сред:**
* Используйте **отдельные узлы Kibana** (не совмещайте с Elasticsearch).
* Настройте **балансировку нагрузки** для Kibana в кластерной конфигурации.
* Регулярно **экспортируйте Saved Objects** в NDJSON для резервного копирования.
* Используйте **Service Accounts** вместо паролей для автоматизации.
* Храните секреты в **Kibana Keystore**, а не в открытом `kibana.yml`.

**Для безопасности:**
* Включите **RBAC** и настройте принцип минимальных привилегий (least privilege).
* Используйте **SSL/TLS** для всех соединений (Kibana ↔ Elasticsearch, браузер ↔ Kibana).
* Включите **аудит-логи** для отслеживания действий пользователей.
* Регулярно обновляйте Kibana до последних патчей (особенно для версий 8.19.x и 9.x).

**Для производительности:**
* Ограничивайте время жизни сессий (`xpack.security.session.idleTimeout`, `xpack.security.session.lifespan`).
* Используйте **ES|QL** вместо KQL для сложных аналитических запросов.
* Мониторьте метрики Kibana и настраивайте алертинг на аномалии.

**Для мультитенантности:**
* Используйте **Spaces** для изоляции данных между командами/проектами.
* Настройте **Role-Based Access Control** с ограничением по индексам и пространствам.
* Используйте **Document-Level Security (DLS)** для дополнительной изоляции данных.

### См. также
* **[Kibana: Поиск, визуализация и управление](./kibana_search_and_visualization.md)** — детальное руководство по Lens, KQL, ES|QL и алертингу.
* **[Kibana: Эксплуатация](./kibana_production_operations.md)** — роли нод, reverse proxy и base path, таймауты, снапшоты, диагностика, апгрейды.
* **[Kibana: Reporting](./kibana_reporting.md)** — PDF/CSV/скриншоты, очередь заданий, расписания отчётов.
* **[Kibana: Workflows](./kibana_workflows.md)** — оркестрация: шаги, триггеры, cron/RRule.
* **[Kibana: Cases](./kibana_cases.md)** — инциденты: статусы, алерты, connector'ы, API.
* **[Kibana: Производительность дашбордов и запросов](./kibana_dashboard_performance.md)** — диагностика через Inspector, таймауты, Advanced Settings.
* **[Kibana: Observability](./kibana_observability.md)** — логи, трейсы, SLO и burn rate правила.
* **[Kibana: Security Solution](./kibana_security_solution.md)** — detection rules, алерты, исключения.
* **[Elasticsearch: Обзор](../Elasticsearch/elasticsearch_overview.md)** — база данных, на которой работает Kibana.
* **[Alerting: Kibana Alerting и Watcher](../Elasticsearch/elasticsearch_alerting.md)** — типы правил, Connectors, Actions.
* **[Security Advanced](../Elasticsearch/elasticsearch_security_advanced.md)** — DLS, FLS, Kibana Spaces, RBAC.
* **[Stack Monitoring](../Elasticsearch/elasticsearch_stack_monitoring.md)** — мониторинг Kibana и других компонентов.
* **[Fleet и Elastic Agent](../Elasticsearch/elastic_agent_and_fleet.md)** — управление агентами сбора данных.
* **[Обзор Elastic Stack](../elk_stack_overview.md)** — архитектура всей экосистемы.
