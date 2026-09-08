# Kibana: Практическое руководство в Kubernetes

> **Примечание:** Данный файл описывает практическое использование Kibana в среде Kubernetes. Общий обзор инструмента и его базовых концепций приведен в документе [Kibana: Обзор](../../../ELK_Stack/Kibana/kibana_overview.md). Детальное руководство по поиску и визуализации — в [Kibana: Поиск, визуализация и управление](../../../ELK_Stack/Kibana/kibana_search_and_visualization.md).

> **Актуальные версии (август 2026):** Kibana **8.19 (LTS)** (поддержка до июля 2027) и **9.x** (текущая стабильная линия 9.5.x). Рекомендуется использовать 8.19 LTS для production-сред с длительным циклом поддержки или 9.x для доступа к новым функциям (ES|QL GA, Workflows, Agent Builder).

## Определения

* **Discover (Обнаружение)** — основной инструмент Kibana для интерактивного исследования, поиска и фильтрации необработанных записей (логов). В версиях 8.x включает режим **Document Explorer** с поддержкой мгновенной статистики по полям. В 9.x добавлена оптимизация для навигации по миллионам записей.
* **Data View (ранее Index Pattern)** — логический шаблон, определяющий набор индексов Elasticsearch для поиска. В Kubernetes обычно охватывает индексы агентов (например, `logs-kubernetes-*`). В 9.x рекомендуется использовать конкретные шаблоны (например, `logs-app-2026.08.*`) вместо общих `logs-*` для оптимизации производительности.
* **KQL (Kibana Query Language)** — основной язык запросов для простой фильтрации прямо в строке поиска. Поддерживает интуитивный синтаксис и автодополнение полей. Оптимален для быстрой фильтрации; для сложных аналитических задач используйте ES|QL.
* **ES|QL (Elasticsearch Query Language)** — мощный язык запросов с поддержкой конвейеров (pipes), позволяющий фильтровать, преобразовывать и агрегировать логи Kubernetes в одном окне. В 9.x стал основным рекомендуемым языком для аналитики (GA статус с версии 8.14).
* **Runtime Fields (Поля времени выполнения)** — вычисляемые поля («схема при чтении»), которые позволяют извлекать данные из логов (например, парсить регулярными выражениями) без их повторной индексации. Определяются на языке Painless.
* **Kibana Spaces (Пространства)** — механизм логического разделения объектов Kibana (дашбордов, Data Views, сохраненных поисков) для реализации мультитенантности, что особенно актуально для Kubernetes (например, создание отдельного Space для каждого Namespace или команды).
* **Lens** — встроенный drag-and-drop редактор для быстрого создания диаграмм и дашбордов. Автоматически выбирает оптимальный тип графика на основе перетащенных полей.
* **Fleet и Elastic Agent** — централизованная платформа управления сбором данных. В Kubernetes-среде Elastic Agent заменяет несколько отдельных агентов (Filebeat, Metricbeat) единым агентом с политиками, управляемыми через Fleet UI в Kibana.

## Предварительные требования

Для использования Kibana в Kubernetes необходимы:

1. **Работающий кластер Kubernetes** (1.25+).
2. **Развернутый Elasticsearch** (8.19 или 9.x) — как через ECK (рекомендуется), так и через Helm. См. [Настройка стека EFK](./efk_stack_setup_guide.md).
3. **Kibana**, подключенная к Elasticsearch — typically как Deployment в namespace `logging`.
4. **Агент сбора логов** — Fluent Bit (DaemonSet), Elastic Agent или Filebeat.
5. **Учетные данные** для доступа к Elasticsearch (пользователь `elastic` или сервисный токен).

**Проверка готовности:**

```bash
# Статус кластера Elasticsearch
kubectl get pods -n logging -l elasticsearch.elasticsearch.k8s.elastic.co/statefulset-name=elasticsearch
# → все поды в состоянии Running

# Доступность Kibana
kubectl get svc -n logging -l kibana.k8s.elastic.co/name
# → ClusterIP или LoadBalancer

# Проверка логов Fluent Bit
kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit --tail=10
# → логи отправляются в Elasticsearch
```

## Основные концепции

В среде Kubernetes Kibana служит «окном» в состояние кластера через анализ метаданных. Ключевые поля, добавляемые агентами (Fluent Bit, Elastic Agent, Filebeat):
* `kubernetes.namespace_name` — пространство имен.
* `kubernetes.pod_name` — имя пода.
* `kubernetes.container_name` — имя контейнера.
* `kubernetes.node.name` — узел (node), на котором запущен под.
* `kubernetes.labels.*` — метки (labels), привязанные к поду, позволяющие фильтровать логи по конкретному приложению (например, `kubernetes.labels.app`).

**Schema-on-read (схема при чтении)**: В Kibana 8.x акцент смещен в сторону динамической работы с данными. Если формат лога изменился или поле не было распарсено агентом при сборке, вы можете адаптировать поиск с помощью Runtime Fields, не меняя конфигурацию Fluent Bit или Ingest-конвейеров в Elasticsearch.

**Мультитенантность через Spaces и RBAC**: В Kubernetes-кластерах, где работают несколько команд (multi-tenant), настоятельно рекомендуется использовать **Kibana Spaces** совместно с ролевой моделью (RBAC). Каждой команде выделяется собственное пространство со своим `Data View` (отфильтрованным на уровне роли Elasticsearch через Document-Level Security (DLS), чтобы команда видела логи только своего Namespace).

## Практические сценарии

### Создание Data View для логов Kubernetes

Для визуализации данных, поступающих из кластера:

1. Перейдите в **Stack Management** → **Data Views**.
2. Нажмите **Create data view**.
3. Введите шаблон. Для стандартного EFK это часто `kube-logs-*` или `fluentbit-*`.
4. Выберите `@timestamp` в качестве основного поля времени.
5. (Опционально) В разделе **Runtime fields** можно сразу добавить логику парсинга для извлечения кастомных полей из текста сообщения.

**Best Practice для production:** Используйте конкретные шаблоны индексов (например, `logs-app-2026.08.*`) вместо общих `logs-*`. Это снижает нагрузку на Elasticsearch и ускоряет загрузку дашбордов.

### Настройка Spaces для мультитенантности

В Kubernetes-кластерах с несколькими командами или проектами:

1. Перейдите в **Stack Management** → **Spaces** → **Create space**.
2. Создайте пространство, например `team-backend` с идентификатором `team-backend`.
3. Настройте **Role** в **Stack Management** → **Roles**:
   - Вкладка **Kibana privileges** → выбрать Space `team-backend`.
   - Вкладка **Index privileges** → добавить `read` для индексов `logs-team-backend-*`.
4. Назначьте роль пользователям через LDAP/OIDC или локальные аккаунты.
5. Теперь в Space `team-backend` будут видны только логи соответствующего приложения.

### Поиск и фильтрация логов Kubernetes

#### Использование KQL
Стандартный поиск для быстрой диагностики:
* **Логи конкретного приложения:** `kubernetes.labels.app: "my-service"`
* **Поиск ошибок в Namespace:** `kubernetes.namespace_name: "prod" and log.level: "error"`
* **Исключение «шума» (например, health-checks):** `not url.path: "/healthz"`
* **Поиск по подстроке в message:** `message: "connection refused"`
* **Логи с определенным request_id:** `request_id: "abc-123"`

#### Использование ES|QL (Kibana 8.14+ GA)
Позволяет выполнять сложные цепочки действий прямо в интерфейсе **Discover**:

**Пример 1: Топ-10 подов по количеству ошибок в production:**
```esql
FROM logs-kubernetes-*
| WHERE kubernetes.namespace_name == "production"
| WHERE log.level == "ERROR"
| STATS count(*) BY kubernetes.pod_name
| SORT count(*) DESC
| LIMIT 10
```

**Пример 2: Частота ошибок по времени (с агрегацией по 5-минутным окнам):**
```esql
FROM logs-kubernetes-*
| WHERE log.level == "ERROR"
| WHERE @timestamp >= now() - 24h
| EVAL error_bucket = DATE_TRUNC(5m, @timestamp)
| STATS count(*) BY error_bucket
| SORT error_bucket ASC
```

**Пример 3: Поиск логов с определенным паттерном (GROK):**
```esql
FROM logs-kubernetes-*
| WHERE kubernetes.namespace_name == "default"
| DISSECT message "%{timestamp} %{level} %{message}"
| WHERE level == "ERROR"
| KEEP timestamp, level, message, kubernetes.pod_name
```

### Работа с Runtime Fields (извлечение данных на лету)

Если приложение пишет логи в текстовом формате, а вам нужно отфильтровать их по `request_id`, который не был распарсен:

1. В настройках **Data View** нажмите **Add field**.
2. Выберите тип (например, `keyword`).
3. Введите скрипт (Painless) для извлечения данных:
   ```painless
   def m = /request_id=([^\s,]+)/.matcher(doc['message'].value);
   if (m.find()) {
     emit(m.group(1));
   }
   ```
4. Теперь поле `request_id` доступно в **Discover** для фильтрации, группировки и создания дашбордов.

### Визуальный анализ и создание дашбордов (Kibana Lens)

Для мониторинга состояния Kubernetes-приложений часто требуется агрегированная статистика:
1. В **Discover** выберите поле `log.level` (или созданное Runtime-поле).
2. Нажмите на имя поля в боковой панели → откроется панель статистики.
3. Вы увидите круговую диаграмму или гистограмму распределения значений (Discover 2.0+).
4. Для создания полноценного дашборда перейдите в **Dashboard** → **Create dashboard** → **Create visualization** (Lens).
5. Перетащите поле `kubernetes.pod_name` в ось X, а `Records` в ось Y. Добавьте разбивку (Break down by) по `log.level`, чтобы визуально отслеживать поды с аномальным количеством ошибок.

**Типичные визуализации для Kubernetes-логов:**
- **Круговая диаграмма:** Распределение логов по уровням (INFO, WARN, ERROR).
- **Гистограмма:** Количество ошибок во времени с разбивкой по namespace.
- **Таблица:** Топ-10 подов по количеству ошибок за период.
- **Metric:** Общее количество ошибок за последний час.

### Настройка табличного вида

Для удобства потокового мониторинга (подобно `kubectl logs -f`):
1. В боковой панели выберите поля: `kubernetes.namespace_name`, `kubernetes.pod_name`, `message`.
2. Используйте кнопку **Field statistics** для быстрой проверки, нет ли всплесков логов в конкретном поде или контейнере.
3. Сохраните этот вид через кнопку **Save** вверху экрана, чтобы быстро возвращаться к настроенной таблице.

### Настройка алертинга (Alerting) на события Kubernetes

Для проактивного реагирования на проблемы в кластере (например, частые перезапуски или ошибки):
1. Перейдите в **Stack Management** → **Rules**.
2. Выберите тип правила **Log threshold**.
3. Укажите условие: например, более 100 записей с `log.level: "error"` и `kubernetes.namespace_name: "production"` за последние 5 минут.
4. Настройте действие (Action): отправка уведомления в Slack, Microsoft Teams, Webhook или создание тикета в Jira.

**Примеры типичных правил алертинга:**
- **Ошибки аутентификации:** Более 50 ошибок `401` за 5 минут в production.
- **Падения подов:** Упоминание `CrashLoopBackOff` или `OOMKilled` в логах Kubelet.
- **Деградация сервиса:** Рост количества `5xx` ошибок более чем на 20% за час.
- **Потеря данных:** Отсутствие логов от конкретного пода более 10 минут.

*Примечание: Если логи собираются Elastic Agent, можно использовать специализированные правила для интеграции Kubernetes (например, обнаружение `CrashLoopBackOff` или `OOMKilled` на основе системных логов Kubelet).*

### Экспорт и импорт Saved Objects (GitOps)

Для версионирования конфигурации Kibana:

1. Перейдите в **Stack Management** → **Saved Objects**.
2. Выберите объекты для экспорта (дашборды, Data Views, правила алертинга).
3. Нажмите **Export** → формат **NDJSON**.
4. Сохраните файл в Git-репозиторий.
5. Для импорта на другом кластере: **Import** → выберите NDJSON-файл.

**Best Practice:** Включайте экспорт в CI/CD pipeline для автоматического развёртывания конфигурации Kibana в разных окружениях (dev, staging, production).

## Best Practices

### Производительность
- **Используйте конкретные шаблоны индексов** вместо общих (например, `logs-app-2026.08.*` вместо `logs-*`).
- **Ограничивайте время поиска** в Discover (последние 15-30 минут вместо всех данных).
- **Создавайте index patterns с правильным order** для автоматического выбора нужного Data View.
- **Используйте Source Filtering** в Data View для исключения ненужных полей (ускоряет загрузку).

### Безопасность
- **Включите RBAC** для ограничения доступа к敏感ным данным.
- **Используйте Space-aware roles** для мультитенантности.
- **Включите Audit Logs** для отслеживания действий пользователей.
- **Настройте TLS** для соединения Kibana с Elasticsearch.

### Мониторинг
- **Health Check:** `GET /api/status` — проверка состояния Kibana.
- **Metrics API:** `GET /api/stats` — метрики производительности (CPU, память, запросы).
- **Настройте алертинг** на основе метрик Kibana через Elasticsearch.

## Диагностика и Troubleshooting

### Неразобранные JSON-логи
**Симптом:** Поле `message` (или `log`) содержит JSON-строку, но ее поля не вынесены в отдельные атрибуты (невозможен поиск по конкретным ключам внутри JSON).

**Решения:**
1. **На уровне агента:** Проверьте конфигурацию Fluent Bit (`Merge_Log On`) или наличие аннотаций у пода (`fluentbit.io/parser: json`). См. [Парсинг логов во Fluent Bit](./fluentbit/parsing.md).
2. **На уровне Kibana (Quick Fix):** Создайте Runtime Field, которое будет парсить JSON на лету для нужного подмножества логов (только для небольших объемов, так как это снижает производительность поиска).
3. **На уровне Elasticsearch (Рекомендуемое):** Используйте Ingest Pipeline с процессором `json`. Это предпочтительный метод для высоконагруженных систем Kubernetes.

### Kibana не видит индексы
**Симптом:** Data View создан, но в Discover нет данных.

**Диагностика:**
```bash
# Проверка наличия данных в индексе
kubectl exec -it <pod-elasticsearch> -n logging -- \
  curl -s -u elastic:$PASSWORD "https://localhost:9200/_cat/indices/fluentbit-*?v"

# Проверка маппинга индекса
kubectl exec -it <pod-elasticsearch> -n logging -- \
  curl -s -u elastic:$PASSWORD "https://localhost:9200/fluentbit-*/_mapping?pretty" | head -50
```

**Решения:**
1. Убедитесь, что шаблон Data View совпадает с именем индекса.
2. Проверьте, что агент (Fluent Bit) отправляет данные (см. его логи).
3. Проверьте права доступа роли Elasticsearch.

### Медленная загрузка дашбордов
**Симптом:** Дашборд загружается более 10 секунд.

**Решения:**
1. Уменьшите временной диапазон (последние 15 минут вместо 7 дней).
2. Используйте Source Filtering в Data View для исключения ненужных полей.
3. Проверьте производительность Elasticsearch (CPU, RAM, диск).
4. Оптимизируйте визуализации (меньше панелей, проще запросы).

### Ошибки аутентификации
**Симптом:** `401 Unauthorized` при подключении к Elasticsearch.

**Решения:**
1. Проверьте пароль пользователя `elastic`.
2. Убедитесь, что TLS-сертификаты действительны.
3. Проверьте конфигурацию `kibana.yml` (elasticsearch.hosts, elasticsearch.serviceAccountToken).

### Потеря данных между подами
**Симптом:** Логи от определенных подов не отображаются.

**Диагностика:**
```bash
# Проверка логов Fluent Bit на конкретном узле
kubectl logs -n logging -l app.kubernetes.io/name=fluent-bit --field-selector spec.nodeName=<node-name> --tail=20

# Проверка метаданных пода
kubectl get pod <pod-name> -o jsonpath='{.metadata.annotations}'
```

**Решения:**
1. Убедитесь, что Fluent Bit работает на всех узлах (DaemonSet).
2. Проверьте права доступа к файлам логов (`/var/log/containers/`).
3. Проверьте конфигурацию фильтра Kubernetes во Fluent Bit.

## Дополнительная информация

* [Настройка стека EFK](./efk_stack_setup_guide.md) — развертывание компонентов в кластере.
* [Устранение неполадок EFK](./efk_stack_troubleshooting.md) — если Kibana не видит индексы или выдает ошибки подключения.
* [Kibana: Поиск, визуализация и управление](../../../ELK_Stack/Kibana/kibana_search_and_visualization.md) — детальное руководство по Lens, KQL и алертингу.
* [Kibana: Обзор](../../../ELK_Stack/Kibana/kibana_overview.md) — фундаментальные основы, архитектура и сравнение с другими инструментами.