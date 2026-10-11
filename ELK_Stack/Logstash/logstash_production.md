# Logstash: Production-эксплуатация

**Актуально для:** Logstash 8.19 (LTS) / 9.5.x

> Эта заметка закрывает производственные аспекты: горизонтальное масштабирование и отказоустойчивость, запуск в Docker и Kubernetes, эксплуатация на bare-metal/VM (systemd, лимиты ОС, собственные логи), безопасность конфигурации, управление конфигурацией через CI/Git и Centralized Pipeline Management, расчет ресурсов. Базовые понятия и сценарии стенда — в [общем обзоре](./logstash_overview.md), архитектура конвейеров и тюнинг — в [заметке о конвейерах](./logstash_pipelines.md), конфигурации входов/выходов — в [заметке о входах и выходах](./logstash_inputs_outputs.md), мониторинг и проверка конфигураций — в [заметке о мониторинге и валидации](./logstash_monitoring_alerts_validation.md), горячая перезагрузка конфигурации — в [заметке о перезагрузке](./logstash_config_reload.md).

## Определения

* **Отказоустойчивость (HA) Logstash** — способность конвейера продолжать прием и обработку при отказе отдельного узла. Важно: Logstash **не является кластером** — у него нет протокола обнаружения (discovery), election лидера и общей памяти между узлами. Отказоустойчивость строится только снаружи: несколько независимых экземпляров плюс балансировка на входе и реплицированное хранилище на выходе.
* **Состояние (state) Logstash** — данные, которые живут за пределами процесса: страницы Persistent Queue и сегменты DLQ на диске, файл `last_run_metadata_path` у jdbc-входа, смещения (offset) в Kafka consumer group. Именно эти три вида состояния определяют, что происходит при рестарте и масштабировании.
* **Capacity planning (Планирование ресурсов)** — расчет CPU, heap, диска под очереди и пропускной способности под прогнозируемый поток событий до развертывания, а не постфактум через деградацию.
* **Centralized Pipeline Management** — режим, при котором конфигурации конвейеров хранятся в Elasticsearch и редактируются в Kibana; локальные `pipelines.yml`, `path.config` и `config.string` при этом становятся неактивны (subscription-функция).
* **GitOps для конфигов Logstash** — практика хранения `.conf`, `logstash.yml` и `pipelines.yml` в Git с проверкой в CI и развертыванием через конфигурационный менеджер или контейнерный образ.
* **Лимит открытых файлов (RLIMIT_NOFILE / `LimitNOFILE`)** — предел числа файловых дескрипторов процесса. Logstash потребляет их на соединения входов/выходов, на файлы file-входа и на страницы PQ/DLQ; исчерпание лимита — типовая причина отказа приёма на нагруженном узле.
* **Собственные логи Logstash** — логи самого процесса (в отличие от пересылаемых событий) в `/var/log/logstash` или `$LS_HOME/logs`, которые пишутся через log4j2 и ротируются его политикой, а не `logrotate`.

## Предпосылки и предварительная настройка (Prerequisites)

1. **Версии стека.** Версия Logstash не выше версии Elasticsearch, major-версии совпадают; обновление стека идёт в порядке Elasticsearch → Logstash — [порядок обновления](../Elasticsearch/elasticsearch_upgrades.md#обновление-logstash).
2. **Узел.** ОС с systemd (пакеты deb/rpm), Docker или Kubernetes; сервис работает от непривилегированного пользователя `logstash` (запуск от root запрещён с 9.0). Лимит открытых файлов, drop-in юнита и права на файлы секретов — в разделе «Эксплуатация на bare-metal и VM» ниже.
3. **Диск под `path.data`.** Место под PQ и DLQ всех конвейеров конкретного узла: формула — в разделе «Расчет ресурсов», пример — в [обзоре](./logstash_overview.md#настройка-persistent-queue-для-защиты-от-потери-данных).
4. **Секреты.** Keystore создан и защищен паролем `LOGSTASH_KEYSTORE_PASS` ([обзор](./logstash_overview.md#настройка-секретов-через-keystore)); сертификаты и пароли в Git не попадают.
5. **Centralized Pipeline Management (опционально).** Лицензия, включающая feature pipeline management (subscription или бесплатный 30-дневный trial), и роли `logstash_admin`/`logstash_system` у пользователя, от которого Logstash подключается к Elasticsearch.
6. **CI-контур и staging.** Место, где выполняются `logstash -t` и smoke-тест на тех же версиях образов, что в проде: без него сломанная конфигурация доходит до production.

## Основные концепции

### Модель отказоустойчивости

Logstash не реплицирует данные сам. Три уровня, на которых HA достигается по-разному:

1. **Вход (прием).** Несколько экземпляров за балансировщиком (для `tcp`/`http`/`beats`/`syslog`) — каждый принимает часть соединений; при отказе узла клиенты переподключаются к живым. Для `kafka` балансировка не нужна: несколько экземпляров с одинаковым `group_id` — это одна consumer group, партиции делятся между ними автоматически, при отказе участника происходит rebalance и партиции перераспределяются ([детали kafka-входа](./logstash_inputs_outputs.md#чтение-из-kafka)).
2. **Обработка.** Экземпляры полностью независимы: общий узел обработки, общей очереди или синхронизации воркеров между узлами нет. Это и позволяет масштабировать линейно — добавление узла просто добавляет емкость.
3. **Выход (доставка).** Все экземпляры пишут в один Elasticsearch-кластер; надежность на этом уровне — репликация шардов и retry/DLQ [elasticsearch output](./logstash_inputs_outputs.md#семантика-retry-в-elasticsearch-output).

Что **не** покрывается HA автоматически:

* **Persistent Queue локальна.** PQ и DLQ живут на диске конкретного узла. Если узел погиб вместе с диском, события, лежащие в его очереди, теряются — поэтому размер PQ рассчитывают под простой выхода ([формула в обзоре](./logstash_overview.md#настройка-persistent-queue-для-защиты-от-потери-данных)), а исходные потоки (Kafka, Beats) должны уметь переигрывать данные.
* **JDBC-импорт не масштабируется горизонтально.** Состояние инкрементального чтения — локальный файл `last_run_metadata_path`; два экземпляра с одинаковым `schedule` прочитают одни и те же строки и продублируют их в индекс. На нескольких узлах jdbc-конвейер запускается строго на одном (выделенный «reader»), либо состояние переносится на общий сетевой том (с осторожностью: файловые lock'и на NFS не поддерживаются).
* **Агрегация требует одного воркера** — это свойство конвейера, а не узла: выделенный однопоточный конвейер ([паттерн P2P](./logstash_pipelines.md#использование-pipeline-to-pipeline-с-изоляцией-агрегации)) тоже должен быть один на поток событий.

### Стратегии масштабирования

| Поток данных | Стратегия | Комментарий |
| :--- | :--- | :--- |
| Beats / Agent | Несколько узлов + балансировщик (L4) на порт 5044 | Агенты переподключаются при отказе узла |
| Syslog / TCP / UDP | Несколько узлов за L4-балансировщиком | UDP — только балансировка потоков, потери при отказе неизбежны |
| HTTP / webhooks | Несколько узлов за HTTP-балансировщиком | Отправитель получает 202 только после приема живым узлом |
| Kafka | Многие узлы, один `group_id` | Балансировка встроенная, на уровне партиций; `consumer_threads` ≤ партиций |
| JDBC | Один штатный узел (hot standby опционально) | Горизонтальное масштабирование невозможно без дублей |
| Выход в ES | Все узлы в один кластер | Отказоустойчивость — за счет репликации шардов ES |

Правило выбора: **масштабируйтесь со стороны источника** (кто поставляет данные в Logstash), а не со стороны назначения — выход в Elasticsearch уже отказоустоек, а вход определяет, примет ли система второй узел.

### Управление конфигурацией: три подхода

1. **Файлы в Git + конфигурационный менеджер** (Ansible/Chef) или пересборка образа — базовый и наиболее гибкий подход; проверка синтаксиса выполняется в CI (`logstash -t`), деплой — привычным инструментом.
2. **Centralized Pipeline Management** — конвейеры редактируются в Kibana и хранятся в Elasticsearch; Logstash опрашивает изменения (`xpack.management.logstash.poll_interval`, по умолчанию `5s`) и перезагружает их без рестарта. Требует subscription и отключает локальные `pipelines.yml`/`path.config`/`config.string`.
3. **Гибрид** — жесткие настройки уровня `logstash.yml` (очереди, воркеры, security) держатся в Git/образе, а содержимое конвейеров управляется централизованно.

Ключевые факты Centralized Pipeline Management:

```yaml
# logstash.yml
xpack.management.enabled: true
xpack.management.elasticsearch.hosts: "https://es:9200"
xpack.management.elasticsearch.username: logstash_admin_user
xpack.management.elasticsearch.password: ${ES_MGMT_PASSWORD}   # значение из Keystore
xpack.management.logstash.poll_interval: 5s
xpack.management.pipeline.id: ["apache", "cloudwatch_logs"]    # поддерживаются wildcard: ["*logs"]
```

* Пользователь для management-доступа должен иметь роли `logstash_admin` и `logstash_system`; для просмотра неуправляемых конвейеров в UI дополнительно `monitoring_user`.
* Валидации конфигурации **на стороне UI нет** — ошибки синтаксиса видны только в локальных логах Logstash, поэтому проверяйте `logstash -t` и логи после каждой правки.
* Удаление запущенного конвейера в Kibana сначала останавливает его и дожидается обработки всех событий — это может привести к потере данных, если источники продолжают поставлять.
* Keystore при centralized management должен быть в локальной копии на **каждом** экземпляре — секреты не распространяются через Elasticsearch ([официальный документ](https://www.elastic.co/docs/reference/logstash/keystore)).
* Keystore **не поддерживается** в `pipelines.yml` и в `-e`; обращения `${KEY}` в `logstash.yml` и `.conf` — рабочий путь.

### Безопасность production-конфигурации

* **Monitoring API.** По умолчанию — только loopback (`api.http.host: 127.0.0.1`, порт `9600–9700`), и этого достаточно для локального мониторинга. При внешнем доступе включайте Basic auth и TLS (`api.auth.type: basic`, `api.ssl.enabled: true`) — и учитывайте, что с включёнными auth/TLS API биндится уже на все интерфейсы, поэтому доступ должен закрываться сетевыми ACL. Полный пример — в [заметке о мониторинге](./logstash_monitoring_alerts_validation.md#предпосылки-и-предварительная-настройка-prerequisites).
* **Входы.** Сетевой приём — с TLS там, где он поддерживается: `beats` и `tcp` ([готовые конфигурации TLS](../elasticsearch_network_requirements.md#logstash-beats-input-с-tls)). У `syslog`-плагина опций шифрования нет; для защищённого syslog используйте `tcp` с syslog-кодеком.
* **Секреты.** Только Keystore или переменные окружения, никогда — в `.conf` в Git. Keystore должен принадлежать пользователю Logstash и быть недоступен остальным: `chown logstash:root logstash.keystore && chmod 0600 logstash.keystore`; пароль keystore на deb/rpm-установке задаётся в `/etc/sysconfig/logstash` (принадлежит root, права `0600`).
* **Права и порты.** Сервис — от непривилегированного пользователя `logstash`. Наружу открываются только порты входов (5044, 514, …); порт 9600 — только сети мониторинга и не через публичный балансировщик.
* **Роли для Centralized Pipeline Management.** Пользователь Logstash в Elasticsearch — `logstash_admin` + `logstash_system`; пользователь Kibana, работающий в UI управления конвейерами, — `logstash_admin` + `logstash_writer`, и дополнительно `monitoring_user`, если нужно read-only видеть неуправляемые конвейеры.

### CI/CD и версионирование

Минимальный набор проверок в CI перед слиянием конфигурации:

```bash
# 1. Синтаксис всех конвейеров
bin/logstash --path.settings config/ci-settings -t
# → Configuration OK

# 2. Проверка в Docker-контейнере той же версии, что в проде
docker run --rm -v "$PWD/pipeline:/usr/share/logstash/pipeline:ro" \
  docker.elastic.co/logstash/logstash:9.5.5 -t
# → Configuration OK

# 3. Линт стиля/опечаток (например, поиск неизвестных опций вручную
#    по справочнику плагинов) и фиксация версий плагинов
bin/logstash-plugin list --verbose > plugins.lock.txt
```

Что версионировать в Git: `logstash.yml`, `pipelines.yml`, каталог `conf.d/*.conf`, шаблоны индексов и паттерны grok/дictionaries. Что **не** версионировать: Keystore (`logstash.keystore`), сертификаты, `jvm.options` с секретными опциями окружения — они доставляются секрет-менеджером.

Рекомендации:

* **Пиннинг версий:** тег образа и версия Logstash фиксируются явно (`9.5.5`, не `latest`) — совместимость версий стека (ES → Logstash) описана в [обзоре совместимости](./logstash_overview.md#совместимость-версий-с-elastic-stack).
* **Обновление плагинов в образе:** если используются сторонние плагины, `logstash-plugin install` включается в сборку Docker-образа — установка «на живом узле» при деплое делает конфигурацию невоспроизводимой.
* **Проверка совместимости после апгрейда:** breaking changes мажорных версий (Kafka-integration 12.x, удаление модулей в 9.0) — в [обзоре](./logstash_overview.md#совместимость-версий-с-elastic-stack); сам порядок апгрейда стека — в [заметке об обновлениях Elasticsearch](../Elasticsearch/elasticsearch_upgrades.md#обновление-logstash).
* **Staging-стенд** с тем же конфигом, но отдельным индексом/кластером — обязательное звено перед промоушеном; `logstash -t` не проверяет корректность grok-шаблонов и маппинга.
* **Границы проверок и порядок применения** не дублируются здесь: что именно `-t` не проверяет и полный чек-лист валидации/post-deploy — в [заметке о мониторинге и валидации](./logstash_monitoring_alerts_validation.md#ci-cd-пайплайн-минимальный-практический); последовательность деплоя конфигурации без остановки конвейеров — в [заметке о перезагрузке конфигурации](./logstash_config_reload.md#zero-downtime-деплой-конфига).

## Практические сценарии

### Развертывание в Docker Compose

Официальный образ: `docker.elastic.co/logstash/logstash:9.x.y` (с 9.0 — UBI9). Конфигурация монтируется в `/usr/share/logstash/config/`, конвейеры — в `/usr/share/logstash/pipeline/`, данные очередей — в `path.data` (отдельный том, иначе PQ/DLQ исчезнут при пересоздании контейнера).

```yaml
# docker-compose.yml (фрагмент сервиса logstash)
services:
  logstash:
    image: docker.elastic.co/logstash/logstash:9.5.5   # тег пиннинг
    environment:
      LS_JAVA_OPTS: "-Xms2g -Xmx2g"        # heap: равные -Xms/-Xmx
      ES_URL: "https://es01:9200"
      # пароли — через env из .env / docker secrets, не в образе
    volumes:
      - ./logstash.yml:/usr/share/logstash/config/logstash.yml:ro
      - ./pipelines.yml:/usr/share/logstash/config/pipelines.yml:ro
      - ./pipeline:/usr/share/logstash/pipeline:ro     # .conf конвейеры
      - lsdata:/usr/share/logstash/data                 # PQ, DLQ, keystore
    ports:
      - "5044:5044"      # beats
      - "9600:9600"      # Monitoring API (для мониторинга)
    restart: unless-stopped
volumes:
  lsdata:
```

Особенности контейнерного запуска:

* **Heap и лимиты:** задавайте `LS_JAVA_OPTS` с равными `-Xms`/`-Xmx`; bundled JDK учитывает cgroup-лимиты, но лучше ставьте явные `mem_limit` контейнера и выделяйте heap не больше 50–75% от него. Ориентиры heap — в [тюнинге](./logstash_pipelines.md#оптимизация-и-тюнинг-logstash-9x).
* **Пользователь:** контейнер работает от непривилегированного пользователя образа; с 9.0 запуск Logstash от root запрещен по умолчанию.
* **Том под `path.data`:** обязателен для production — на нем лежат PQ, DLQ и keystore. Для Docker Desktop достаточно named volume; на узлах кластера — привязка к ноде (см. Kubernetes ниже).
* **Keystore в контейнере:** создается внутри тома (`bin/logstash-keystore create`), пароль передается `LOGSTASH_KEYSTORE_PASS` через окружение.
* **Валидация после правок:**

```bash
docker compose exec logstash bin/logstash -t
# → Configuration OK

# Monitoring API должен отвечать изнутри/снаружи
curl -s localhost:9600/_node/stats | jq '.version, .pipelines | keys'
# → "9.5.5", ["main", ...]
```

Базовый стенд целиком (ES + Kibana + логирование) разворачивается по [Tutorial Docker Compose](../Tutorials/practical_setup_with_docker.md); образы Elastic подписаны Cosign — проверяйте `cosign verify` перед развертыванием (порядок описан в том же руководстве).

### Развертывание в Kubernetes

Два рабочих пути:

**1. ECK (Elastic Cloud on Kubernetes)** — оператор управляет Logstash через CRD `logstash.k8s.elastic.co/v1alpha1` (доступна с версии стека 8.12+); жизненный цикл, конфигурация и связь с Elasticsearch описываются манифестом, как у остальных ресурсов стека. Детали установки оператора и совместимости версий — в заметке [ECK](../elastic_cloud_on_k8s.md).

**2. Самостоятельный Deployment/StatefulSet** — когда нужен полный контроль над конфигурацией:

```yaml
# фрагмент StatefulSet для конвейера с Persistent Queue
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: logstash
spec:
  serviceName: logstash
  replicas: 2
  selector:
    matchLabels: { app: logstash }
  template:
    metadata:
      labels: { app: logstash }
    spec:
      containers:
        - name: logstash
          image: docker.elastic.co/logstash/logstash:9.5.5
          env:
            - name: LS_JAVA_OPTS
              value: "-Xms1g -Xmx1g"
          ports:
            - { containerPort: 5044, name: beats }
            - { containerPort: 9600, name: monitoring }
          volumeMounts:
            - name: config
              mountPath: /usr/share/logstash/config
            - name: data
              mountPath: /usr/share/logstash/data   # PQ / DLQ
      volumes:
        - name: config
          configMap: { name: logstash-config }
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        resources: { requests: { storage: 10Gi } }
```

Организационные правила в Kubernetes:

* **Один под — одна PQ.** Volume с `accessModes: ReadWriteOnce` монтируется только одному поду: при пересоздании пода данные очереди переезжают вместе с ним (поэтому `StatefulSet`, а не `Deployment`). NFS для PQ не поддерживается (та же причина, что и в [ограничениях DLQ](./logstash_pipelines.md#управление-dead-letter-queue)).
* **Если PQ не нужна** (источник — Kafka или включена репликация на стороне агента), конвейер можно вынести в `Deployment` без тома — тогда рестарты и горизонтальное масштабирование дешевле.
* **Одна реплика на jdbc-конвейер** — см. предупреждение выше; при `replicas: 2` будет двойной импорт.
* **Anti-affinity / spreading:** разносите поды Logstash по нодам, иначе весь прием умрет с одной нодой.
* **Service:** для tcp/http/beats — `ClusterIP` за балансировщиком (ingress L4/или отдельный LB); для Kafka входа балансировочный Service не нужен — consumer group сам распределит партиции.
* **Готовность (readiness):** проверяйте Monitoring API (`/_node/pipelines`) на порту 9600 — он становится доступен после старта конвейеров; liveness — аккуратнее, рестарт при перегрузке убьет нераспроданные события PQ.
* **Ресурсы:** задавайте `requests`/`limits` одинаково по памяти (иначе возможен OOMKill при росте heap); heap — через `LS_JAVA_OPTS`.

### Эксплуатация на bare-metal и VM: systemd, лимиты ОС и логи Logstash

Пакеты deb/rpm размещают юнит `logstash.service` в `/etc/systemd/system` и запускают сервис от пользователя `logstash`:

```bash
sudo systemctl enable --now logstash
systemctl status logstash --no-pager
# → Active: active (running)

journalctl -u logstash -f
```

**Лимит открытых файлов (`LimitNOFILE`).** Каждое TCP-соединение входа, каждое соединение с Elasticsearch/Kafka, каждый файл file-входа и сама PQ/DLQ потребляют файловые дескрипторы: базовый расход JVM — 50–100, одно соединение — 1 дескриптор, примерно 3 дескриптора на конвейер с включённой PQ и ещё 3 — на конвейер с DLQ. Пакетный systemd-юнит задаёт `LimitNOFILE=16384`; для нагруженных узлов (много соединений, десятки конвейеров) ориентируйтесь на 65536 и выше, с запасом 2–3× от расчёта ([справочник по файловым дескрипторам](https://www.elastic.co/docs/reference/logstash/file-descriptors)).

```bash
# Эффективное значение юнита
systemctl show logstash -p LimitNOFILE
# → LimitNOFILE=16384

# Лимиты уже запущенного процесса
grep 'Max open files' /proc/$(systemctl show --property MainPID --value logstash)/limits
# → Max open files            16384            16384            files

# Поднять лимит без правки пакетного юнита (drop-in)
sudo systemctl edit logstash.service
# → [Service]
# → LimitNOFILE=65536
sudo systemctl restart logstash
```

Если большое значение из drop-in не применяется — смотрите системный hard-лимит: на systemd младше v240 (RHEL 7/8, SLES 12, Amazon Linux 2) он ограничен 4096, и сначала поднимается системно силами дистрибутива; на systemd v240+ hard-лимит обычно 524288 и выше, поднять soft-значение можно сразу. Механика drop-in, `systemctl show` и диагностика юнитов — в [заметке об управлении сервисами systemd](../../Linux/Core/systemd/service_management.md).

**Переменные окружения.** На deb/rpm-установке переменные окружения сервиса (в том числе `LOGSTASH_KEYSTORE_PASS`) задаются в `/etc/sysconfig/logstash`: файл принадлежит root с правами `0600`, формат — `ИМЯ=значение` по одной строке.

**Собственные логи Logstash.** Логи процесса пишутся в `/var/log/logstash` (deb/rpm) или `$LS_HOME/logs` (zip/Docker) через log4j2 — `logrotate` для них не нужен. Встроенная политика уже пригодна для продакшена: rollover раз в сутки либо при достижении 100 МБ, хранится не больше 30 файлов, файлы старше 7 дней удаляются. Политика задаётся в `log4j2.properties` и применяется после рестарта; оперативное изменение уровней логирования — через Logging API, без рестарта, но эти изменения не переживают рестарт ([документация по logging](https://www.elastic.co/docs/reference/logstash/logging)):

```bash
# Точечно включить DEBUG по конкретному плагину (забудется при рестарте)
curl -X PUT 'localhost:9600/_node/logging' -H 'Content-Type: application/json' -d '
{"logger.logstash.outputs.elasticsearch": "DEBUG"}'
# → acknowledged

# Вернуть уровни, заданные в log4j2.properties
curl -X PUT 'localhost:9600/_node/logging/reset'
# → acknowledged
```

Для поиска медленных событий включайте `slowlog.threshold.warn/info` в `logstash.yml` (значения с единицей — `500ms`, `2s`): по умолчанию slowlog выключен (`-1`), в лог пишутся событие и ответственные за задержку фильтры.

### Расчет ресурсов (capacity planning)

Порядок расчета под прогнозируемый поток `R` событий/с:

1. **Пропускная способность CPU.** Замерьте на стенде `worker_millis_per_event` по каждому фильтру ([методика Flow Metrics](./logstash_pipelines.md#диагностика-узкого-места-через-flow-metrics)) и умножьте на `R`: суммарное CPU-время обработки в секунду не должно превышать выделенные ядра с запасом 30–50%. Ограничение обычно создает `grok`/`translate`/обогащения — их выносят в ingest-пайплайны ES (`elastic_integration`).
2. **Heap.** От `inflight count = pipeline.workers × pipeline.batch.size` (сколько событий одновременно в памяти) плюс запас на пиковые крупные события и JVM. Ориентиры: 4–8 ГБ heap для типовых нагрузок, не более 31 ГБ; heap = 50–75% ОЗУ узла ([тюнинг](./logstash_pipelines.md#оптимизация-и-тюнинг-logstash-9x)).
3. **Диск под PQ.** `поток_байт/с × часы_простоя_выхода × 3600 × 1.10` — формула и пример (50 ГБ под 12 часов простоя ES) в [обзоре](./logstash_overview.md#настройка-persistent-queue-для-защиты-от-потери-данных). Диск должен вмещать суммарный `queue.max_bytes` всех конвейеров **всех** узлов плюс DLQ.
4. **Сеть.** Пропускная способность `R × размер_события` от источников к Logstash и от Logstash к ES; для сжатия в elasticsearch output включенный gzip (уровень 1 по умолчанию) заметно снижает исходящий трафик ценой CPU.
5. **Число узлов.** `ceil(текущая_нагрузка / целевая_утилизация)`, где целевая утилизация — 60–70% по `worker_utilization` в пиковых окнах `last_15_minutes`; узлы добавляются со стороны входа (балансировщик/consumer group).
6. **Лимиты ОС.** Файловые дескрипторы на узел: 50–100 на процесс + по одному на соединение входа/выхода + по 3 на каждый конвейер с PQ и на каждый с DLQ; сумма умножается на запас 2–3× и сверяется с `LimitNOFILE` юнита (16384 в пакетном, для высоких нагрузок 65536+) — расчет и drop-in описаны в разделе «Эксплуатация на bare-metal и VM».

Валидация после развертывания: сравните прогноз с фактом по `_node/stats` — `events.in/out`, `flow.worker_utilization`, `queue_persisted_growth_events`; рост PQ в стабильном состоянии означает, что узлов/производительности не хватает ([шаг «Интерпретируйте комбинацию показателей»](./logstash_pipelines.md#диагностика-узкого-места-через-flow-metrics)).

### Rolling update без потери данных

Порядок обновления одного узла из группы:

1. Снять узел с балансировщика (для kafka-входа — достаточно остановки, rebalance сам уводит партиции).
2. Дождаться, пока очередь опустеет: `queue.size` → 0 в `_node/stats/pipelines` либо `queue.drain: true` при остановке.
3. Обновить узел (пакетно или пересоздать контейнер), убедиться в `Configuration OK` и старте конвейеров.
4. Вернуть узел в балансировщик, перейти к следующему.

С PQ шаг 2 опционален — данные сохраняются на диске; без PQ без него происходит потеря событий. Совместимость версий (Logstash обновляется **после** Elasticsearch, major-версия должна совпадать) и общий чек-лист — в [заметке об обновлениях](../Elasticsearch/elasticsearch_upgrades.md#обновление-logstash).

## Типичные проблемы и их решение (Troubleshooting)

1. **После масштабирования на второй узел события дублируются.**
   Причины: jdbc-конвейер запущен на обоих узлах; либо источник-«at-most-once» (например, `udp`) отправляет поток всем балансировщикам вместо разделения.
   Решение: jdbc — один штатный узел; для балансировки используйте L4-балансировщик, распределяющий соединения, а не broadcast.
2. **При рестарте пода «пропали» события из очереди.**
   Причина: том под `path.data` не персистентный (emptyDir/пересозданный named volume) либо `queue.type: memory`.
   Решение: PVC/StatefulSet для данных, `queue.type: persisted`; проверьте `pqcheck` на наличие страниц после рестарта.
3. **Конвейер стартует, но Monitoring API недоступен.**
   Причины: `api.http.host` по умолчанию `127.0.0.1` (в контейнере обращение извне не пройдет), порт занят, конфиг упал на `-t`.
   Решение: `api.http.host: 0.0.0.0` в контейнере (с сетевым ограничением доступа и, желательно, Basic auth + TLS), проверить `docker logs`/`journalctl` на `[ERROR]`, выполнить `logstash -t`; полная диагностика и проверки после правок — в [заметке о мониторинге](./logstash_monitoring_alerts_validation.md#типичные-проблемы-и-их-решение-troubleshooting).
4. **После включения Centralized Pipeline Management конвейеры пропали.**
   Причина: в этом режиме `pipelines.yml` и `path.config` неактивны — читаются только ID из `xpack.management.pipeline.id`.
   Решение: перечислить нужные pipeline ID (поддерживаются wildcard), иметь роли `logstash_admin`/`logstash_system`, перезапустить Logstash; ошибки конфигураций искать в его логе (валидации в UI нет).
5. **В Kubernetes два пода борются за volume.**
   Причина: `Deployment` + PVC `ReadWriteOnce` на ноде, где уже смонтирован второй под.
   Решение: `StatefulSet` с `volumeClaimTemplates` (один PVC на под) либо отказ от PQ для данного конвейера.
6. **Кластер не переживает обновление: все узлы обновились одновременно.**
   Причина: отсутствует выкатка по одному узлу, балансировщик не выводит узлы из ротации.
   Решение: следовать процедуре rolling update выше; для kafka входа обновление по одному узлу безопасно — rebalance перераспределяет партиции.
7. **В логах `Too many open files`, входы перестают принимать соединения.**
   Причина: исчерпан `LimitNOFILE` (16384 в пакетном юните) из-за большого числа соединений или конвейеров с PQ/DLQ; либо на systemd младше v240 системный hard-лимит 4096 не позволяет поднять soft-значение.
   Решение: drop-in `systemctl edit logstash.service` с `LimitNOFILE=65536` и перезапуск сервиса, на старом systemd — сначала поднять системный hard-лимит; проверка значений и формула расчета — в разделе «Эксплуатация на bare-metal и VM».
8. **Диск занят собственными логами Logstash.**
   Причина: испорчена или отключена политика rollover в `log4j2.properties`, включён DEBUG на всех подсистемах подряд, либо `path.logs` указывает на системный раздел.
   Решение: вернуть политику (сутки / 100 МБ, максимум 30 файлов, удаление старше 7 дней), сбросить уровни через `PUT /_node/logging/reset`, DEBUG включать точечно и временно через Logging API — см. раздел «Эксплуатация на bare-metal и VM».

## Лучшие практики и очистка окружения

* **Один конфигурационный источник (Git)** на все среды; отличия — только переменные окружения/Keystore, а не ветки конфигурации.
* **`logstash -t` в CI и перед каждым деплоем** — стоп-фактор для сломанных конфигов.
* **PQ + DLQ на каждом production-узле**, диск рассчитан по формуле, каталог DLQ в мониторинге.
* **Горизонтальное масштабирование — со стороны входа**, jdbc-конвейер — всегда в единственном экземпляре.
* **Раскатка по одному узлу**, узел выводится из балансировки и дожидается опустошения очереди (или полагается на PQ).
* **Версии пиннингом** (тег образа, версия пакета), обновление стека в порядке Elasticsearch → Logstash, breaking changes — перед апгрейдом.
* **Наблюдаемость:** метрики каждого узла в кластер через Elastic Agent (integration Logstash) + алерты на `worker_utilization`, рост PQ, объем DLQ и недоступность Monitoring API — готовый чек-лист порогов и порядок разбора — в [заметке о мониторинге](./logstash_monitoring_alerts_validation.md#чек-лист-алертов-prod-ready).
* **Лимиты ОС проверены на каждом узле:** `systemctl show logstash -p LimitNOFILE` — не ниже 16384, под нагрузкой 65536+; правки только через drop-in, не правкой пакетного юнита.
* **Доступ закрыт по умолчанию:** Monitoring API без auth/TLS не выходит за loopback, входы — с TLS, секреты — в Keystore (раздел «Безопасность production-конфигурации»).
* **Дубли после масштабирования** разбираются не только по источнику: общая семантика at-least-once, идемпотентный приём и дедупликация — в [заметке о семантике доставки логов](../log-delivery-and-deduplication.md).
* Очистка стенда/узла после экспериментов:

```bash
sudo systemctl stop logstash        # или docker compose stop logstash

# Конфиги эксперимента
sudo rm -rf /etc/logstash/conf.d/99-experiment.conf
docker volume rm <project>_lsdata   # только для тестового стенда!

# Состояние очередей (НЕВОЗВРАТНО — невыгруженные события теряются)
sudo rm -rf /var/lib/logstash/queue/* /var/lib/logstash/dead_letter_queue/*

# Проверка освобождения портов
ss -tlnp | grep -E '5044|9600'
# → пустой вывод
```

## Дополнительная информация

### См. также

* **[Logstash: Обзор](./logstash_overview.md)** — установка, Keystore, Persistent Queue, Monitoring API, troubleshooting.
* **[Logstash: Конвейеры и производительность](./logstash_pipelines.md)** — flow-метрики, тюнинг, DLQ, P2P.
* **[Logstash: Входы, выходы и маршрутизация](./logstash_inputs_outputs.md)** — конфигурации плагинов, retry-семантика.
* **[Logstash: Мониторинг, алерты, валидация конфигов](./logstash_monitoring_alerts_validation.md)** — чтение метрик, чек-лист алертов, что не проверяет `-t`, post-deploy проверки.
* **[Logstash: Конфигурация, перезагрузка и zero-downtime](./logstash_config_reload.md)** — hot-reload, SIGHUP, поведение очередей при переключении конвейеров.
* **[Logstash: Backpressure, batching и поведение Input](./logstash_backpressure_batching.md)** — как конвейер тормозит под нагрузкой и что с этим делать.
* **[Logstash: Multiline, агрегация, DLQ и эксплуатация PQ](./logstash_multiline_aggregate_dlq_pq_ops.md)** — операции с DLQ и PQ непосредственно на узле.
* **[Логи: семантика доставки и дедупликация](../log-delivery-and-deduplication.md)** — откуда берутся дубли и как их устранять на стороне приёма.
* **[Сетевые требования Elasticsearch](../elasticsearch_network_requirements.md)** — TLS-конфигурации `beats` и `tcp` входов Logstash, порты, латентность.
* **[systemd: управление сервисами](../../Linux/Core/systemd/service_management.md)** — drop-in, `systemctl show`, лимиты юнита.
* **[Elastic Cloud on Kubernetes](../elastic_cloud_on_k8s.md)** — оператор и CRD `Logstash` для Kubernetes.
* **[Обновление Elasticsearch и стека](../Elasticsearch/elasticsearch_upgrades.md#обновление-logstash)** — порядок и rolling update Logstash.
* **[Развертывание ELK в Docker Compose](../Tutorials/practical_setup_with_docker.md)** — базовый стенд, TLS, проверка образов Cosign.
* **[Elasticsearch: Capacity Planning](../Elasticsearch/elasticsearch_capacity_planning.md)** — расчет ресурсов кластера назначения.
* **[Configure Centralized Pipeline Management (Официально)](https://www.elastic.co/docs/reference/logstash/configuring-centralized-pipelines)** — все ключи `xpack.management.*`.
* **[Logstash Docker (Официально)](https://www.elastic.co/docs/reference/logstash/docker)** — управление конфигурацией и томами в контейнере.
* **[File descriptors (Официально)](https://www.elastic.co/docs/reference/logstash/file-descriptors)** — расход файловых дескрипторов, лимиты ОС и рекомендации по `LimitNOFILE`.
* **[Logging (Официально)](https://www.elastic.co/docs/reference/logstash/logging)** — log4j2, политика rollover собственных логов, Logging API, slowlog.
* **[Running Logstash as a Service (Официально)](https://www.elastic.co/docs/reference/logstash/running-logstash)** — systemd-юнит deb/rpm-пакета, `systemctl`.
