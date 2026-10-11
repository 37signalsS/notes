# Руководство: Настройка мультинодового кластера Elasticsearch (8.x / 9.x)

**Актуально для:** Elasticsearch 8.19 LTS / 9.5.x

> Эта заметка является авторитетным источником по развертыванию мультинодовых кластеров Elasticsearch версий 8.x и 9.x в self-managed среде. Она охватывает процессы автоматической и ручной настройки безопасности, системный тюнинг ОС, управление ролями узлов и обеспечение отказоустойчивости на уровне стоек, зон или дата-центров.
>
> Базовая архитектура кластера описана в [обзоре Elasticsearch](../Elasticsearch/elasticsearch_overview.md); развертывание single-node в Docker — в [руководстве по Docker Compose](./practical_setup_with_docker.md); сетевые требования — в [Network и Firewall](../elasticsearch_network_requirements.md).

## Определения

* **Токен регистрации (Enrollment Token)** — зашифрованный ключ (Base64-строка), содержащий информацию для автоматического подключения нового узла к кластеру: версию, адреса мастер-узла, отпечаток CA-сертификата и ключ доступа. Действует 30 минут с момента генерации.
* **Проверки при загрузке (Bootstrap Checks)** — набор тестов конфигурации ОС (память, лимиты файлов, потоки), которые Elasticsearch выполняет при старте в сетевом режиме (когда `network.host` привязан не только к loopback). Если проверки не пройдены, процесс завершается с ошибкой и не формирует кластер.
* **Allocation Awareness (Осведомленность о распределении)** — механизм, позволяющий Elasticsearch учитывать физическую топологию серверов (зоны, стойки) при размещении реплик для предотвращения потери данных при отказе целого сегмента инфраструктуры.
* **Elasticsearch Keystore** — защищенное хранилище для чувствительных настроек (пароли, ключи API, учётные данные для S3-репозиториев), которое предотвращает их хранение в открытом виде в `elasticsearch.yml`.
* **Compressed OOPs (Сжатые указатели)** — технология JVM, позволяющая использовать 32-битные указатели в 64-битной среде, что экономит память. Работает только до порога heap, который зависит от JVM: 26 ГБ безопасно на большинстве систем, на некоторых порог достигает 30 ГБ; точное значение можно проверить в стартовом логе или через `GET _nodes/_all/jvm`.
* **Кворум мастеров (Voting Configuration)** — подмножество master-eligible узлов, чьи голоса определяют выбор активного мастера и защиту от split brain. Решения принимаются только после ответа большинства (более половины) узлов кворума; поэтому число master-eligible узлов должно быть нечетным (обычно 3). При четном числе узлов Elasticsearch сам исключает один из них из кворума, чтобы сохранить нечетный размер.
* **Voting-only узел (dedicated tiebreaker)** — master-eligible узел, участвующий в кворуме, но никогда не избираемый мастером (`node.roles: [ master, voting_only ]`). Экономит ресурсы в схемах с выделенными мастерами и служит узлом-развязкой (tiebreaker) при двухзонных развёртываниях.
* **Security Auto-Configuration** — автоматическая настройка безопасности при первом запуске: генерация CA, выпуск TLS-сертификатов для transport- и HTTP-слоя, создание пароля суперпользователя `elastic`.
* **Дисковые пороги (Watermarks)** — уровни заполнения диска (по умолчанию 85%/90%/95%), при достижении которых кластер последовательно прекращает назначать шарды, мигрирует их с узла и блокирует запись в индексы.

## Основные концепции

### Параметры формирования кластера

В версиях 8.x/9.x процесс формирования кластера упрощен благодаря автоматизации, но требует понимания ключевых параметров:

| Параметр | Назначение | Особенности |
| :--- | :--- | :--- |
| **`cluster.initial_master_nodes`** | Список начальных мастеров | Используется **только один раз** при самом первом запуске (bootstrap). Задается только на master-eligible узлах первого формирования; после образования кластера настройку следует убрать из конфигурации. |
| **`discovery.seed_hosts`** | Список узлов для поиска | IP или DNS-имена master-eligible узлов. Постоянная настройка — нужна при каждом старте для повторного обнаружения кластера. |
| **`node.roles`** | Список ролей узла | Например `[master, data_hot]`. Каждый кластер требует роли `master` и (`data_content` + `data_hot`) либо `data`. Как только кластер насчитывает больше нескольких узлов (more than a handful), обычно имеет смысл выделять dedicated master-узлы с единственной ролью `master`. |

Механика выбора мастера: при первом запуске узлы из `cluster.initial_master_nodes` образуют voting configuration и выбирают активного мастера; далее состав кворума кластер поддерживает сам. Управлять составом кворума можно через API voting configuration exclusions: `POST /_cluster/voting_config_exclusions?node_names=<name>` исключает узел из кворума (требуется при плановом выводе мастеров, особенно когда за короткий период убирается половина или более master-eligible узлов); вместо имён можно указать постоянные ID узлов — `?node_ids=<id>` (одновременно с `node_names` не указывается); параметр `timeout` (дефолт 30s) ограничивает ожидание авто-переконфигурации. Ответ `200 OK` гарантирует, что узел удалён из voting configuration и не будет в него возвращён до очистки списка; при любом другом ответе вызов можно безопасно повторить. `DELETE /_cluster/voting_config_exclusions` очищает весь список (по умолчанию дожидается полного удаления исключённых узлов из кластера; `?wait_for_removal=false` очищает список, не дожидаясь), текущий список — `GET /_cluster/state?filter_path=metadata.cluster_coordination.voting_config_exclusions`. Исключения персистентны и ограничены по числу (`cluster.max_voting_config_exclusions`, дефолт 10) — в нормальной эксплуатации список должен быть пуст, исключения удаляют после завершения работ. Нарушение кворума останавливает выбор мастера и фиксацию изменений состояния — запись становится недоступной с ошибками `master not discovered`, это штатная защита от split brain, а не авария. HA-кластер требует минимум три master-eligible узла, из которых минимум два не voting-only; при этом кластер переносит потерю любого одного узла.

### Модель безопасности по умолчанию (Security Auto-Configuration)

При первом старте узла, установленного из DEB/RPM пакета, происходит следующее:

1. Генерируется локальный CA и сертификаты; TLS включается для transport-слоя (порт 9300) и HTTP-слоя (порт 9200). Сертификаты и ключи лежат в каталоге конфигурации (`config/certs`, для пакетов — `/etc/elasticsearch/certs`): `http_ca.crt` (CA для HTTP-слоя), `http.p12` и `transport.p12` (PKCS#12 keystore, пароли хранятся как secure-настройки). Настройки TLS записываются в `elasticsearch.yml`.
2. В keystore записывается seed, генерируется пароль пользователя `elastic` — он выводится **один раз** в консоль/лог при первом старте (см. ограничения ниже).
3. HTTP-слой привязывается ко всем интерфейсам (`0.0.0.0` — автоконфигурация записывает `http.host: 0.0.0.0` в `elasticsearch.yml`), transport-слой — только к `_local_` (localhost). Это позволяет single-node стартовать без вопросов, но означает, что узел сразу доступен по сети: TLS и аутентификация включены по умолчанию, однако порт 9200 всё равно нужно закрыть firewall-правилами, а для присоединения удаленных узлов требуется явно задать `network.host`.

Автоконфигурация пропускается, если при старте обнаруживается, что узел уже входит в кластер, что безопасность уже настроена или явно отключена. Если вывод процесса перенаправлен в файл или терминал не подключен (типичный случай — systemd-сервис), TLS при этом всё равно настраивается автоматически, но пароль `elastic` и токены не генерируются — их нужно задать/выпустить вручную. В пакетных (DEB/RPM) установках пароль `elastic` при старте не выводится вообще и его требуется сбросить вручную.

Условия пропуска автоконфигурации (узел стартует с существующей конфигурацией):

* **Среда**: каталог `data` существует и не пуст (узел уже запускался и, возможно, входит в кластер); `elasticsearch.yml` отсутствует/нечитаем или `elasticsearch.keystore` недоступен; каталог конфигурации недоступен для записи (узел запущен не тем пользователем или администратор ограничил права).
* **Настройки**: `node.roles` задано так, что узел не может быть избран мастером или хранить данные; `xpack.security.autoconfiguration.enabled: false`; явно заданное `xpack.security.enabled`; любые `xpack.security.transport.ssl.*` / `xpack.security.http.ssl.*` в `elasticsearch.yml` или keystore; заданные `discovery.type`, `discovery.seed_hosts` или `cluster.initial_master_nodes` (исключения — `discovery.type: single-node` и `cluster.initial_master_nodes`, содержащий только имя текущего узла).

Ограничения, которые важно знать заранее:

* Enrollment работает **только** с кластерами, настроенными автоконфигурацией безопасности (автосгенерированные сертификаты); если TLS настроен вручную через `elasticsearch-certutil`, токены узлов использовать нельзя. Инструмент `elasticsearch-create-enrollment-token` также не работает при отключенном file realm; для выполнения запроса он создаёт и сразу удаляет временного пользователя в file realm.
* Генерация токенов управляется настройкой `xpack.security.enrollment.enabled` (дефолт `false`), но автоконфигурация сама выставляет её в `true` при первом старте — задавать вручную требуется только если автоконфигурация отключена. Токен для Kibana (`-s kibana`) дополнительно опирается на TLS HTTP-слоя, который при автоконфигурации включен по умолчанию.
* Инструмент `elasticsearch-reconfigure-node` переконфигурирует узел DEB/RPM для присоединения к существующему кластру: прописывает TLS-настройки (сертификаты того же CA) и `discovery.seed_hosts` на узел-источник токена.

Для подключения клиентов (Beats, Logstash, standalone Elastic Agent) к HTTP-слою нужен отпечаток CA или сам сертификат. Отпечаток выводится в терминал при первом старте; получить его позже можно так:

```bash
openssl x509 -fingerprint -sha256 -in /etc/elasticsearch/certs/http_ca.crt
# → issuer= /CN=Elasticsearch security auto-configuration HTTP CA
# → SHA256 Fingerprint=28:28:4E:...
```

Пароли PKCS#12-keystore'ов (`http.p12`, `transport.p12`), созданных автоконфигурацией, хранятся как secure-настройки и извлекаются через:

```bash
sudo /usr/share/elasticsearch/bin/elasticsearch-keystore show xpack.security.http.ssl.keystore.secure_password
sudo /usr/share/elasticsearch/bin/elasticsearch-keystore show xpack.security.transport.ssl.keystore.secure_password
```

### Системный тюнинг (Production Ready)

Для прохождения Bootstrap Checks и стабильной работы под нагрузкой обязательны следующие настройки ([официальный список](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/bootstrap-checks)):

1.  **Память (mmap)**: Увеличение лимитов виртуальной памяти для Lucene. Bootstrap check требует минимум 262144; официально рекомендуемое значение — 1048576. Проверка применяется только при использовании mmapfs/hybridfs для хранения индексов (тип хранения задаётся `index.store.type`; при `niofs`/`simplefs` проверка не выполняется).
     ```bash
     sysctl -w vm.max_map_count=262144
     # Перманентно (предпочтительный путь для systemd-дистрибутивов):
     echo "vm.max_map_count=262144" > /etc/sysctl.d/99-elasticsearch.conf
     sysctl --system
     # → vm.max_map_count = 262144
     ```
2.  **Блокировка памяти (mlockall)**: Предотвращает уход JVM в swap.
    *   В `elasticsearch.yml`: `bootstrap.memory_lock: true`.
    *   В системных лимитах (systemd): `LimitMEMLOCK=infinity`.
    *   Проверка после старта:
    ```bash
    curl -k -u elastic:$PASS "https://localhost:9200/_nodes?filter_path=nodes.*.process.mlockall"
    # → {"nodes":{"<node_id>":{"process":{"mlockall":true}}}}
    ```
3.  **Дескрипторы файлов**: Официальный минимум — 65535 открытых файлов; bootstrap check проверяет значение 65536, поэтому 65536 — практический минимум.
     *   `LimitNOFILE=65536` (в DEB/RPM пакетах уже задано в unit-файле — проверьте переопределениями).
4.  **Отключение swap**: Свапинг heap вызывает непредсказуемые паузы длительностью в секунды.
    ```bash
    sudo swapoff -a                                   # временно, до ребута
    echo "vm.swappiness=1" | sudo tee /etc/sysctl.d/99-elasticsearch.conf
    # постоянный вариант — закомментировать swap-строку в /etc/fstab
    ```
5.  **Число потоков**: `nproc` минимум 4096 для пользователя `elasticsearch` (`LimitNPROC=4096` или `ulimit -u 4096`).
6.  **Синхронизация времени**: Кластерные протоколы чувствительны к рассинхронизации часов; настройте NTP/chrony на всех узлах.
7.  **Выделенный пользователь**: Запуск от непривилегированного пользователя `elasticsearch` с одинаковыми UID/GID на всех узлах (важно при NFS-хранилищах и переносе данных).

Способы применения лимитов зависят от типа установки: для DEB/RPM используйте systemd override:

```bash
sudo systemctl edit elasticsearch
# [Service]
# LimitMEMLOCK=infinity
# LimitNOFILE=65536
sudo systemctl daemon-reload
```

### Осведомленность о топологии (Zones/Racks)

Для защиты от падения целого дата-центра или стойки используйте Allocation Awareness:
1.  **Метка узла**: `node.attr.zone: "zone-a"`.
2.  **Настройка кластера**: `cluster.routing.allocation.awareness.attributes: "zone"`.
3.  **Принудительная защита**: `cluster.routing.allocation.awareness.force.zone.values: ["zone-a", "zone-b"]`. Это предотвратит "скучивание" реплик в одной зоне, если вторая временно недоступна: при forced awareness первичные шарды в выжившей зоне не будут принимать реплики, пока вторая зона не вернется — ценой снижения отказоустойчивости записи, но сохранением емкости дисков.
4.  **Voting-only узел (dedicated tiebreaker)**: `node.roles: [ master, voting_only ]`. Узел участвует в кворуме, но никогда не становится мастером — экономит ресурсы в схеме «два полноценных мастера + tiebreaker» и в двухзонных развёртываниях, где третий master-eligible узел-развязка живёт в отдельной зоне. Помечать `voting_only` можно только узлы с ролью `master`.

## Практические сценарии

### Предварительные требования

* Установлены пакеты Elasticsearch 8.19 LTS или 9.5.x (DEB/RPM) на всех узлах; оптимизированный JDK поставляется в комплекте.
* Открыты порты: **9200** (HTTP — клиенты, Beats, Logstash) и **9300** (transport — межузловой трафик); детали и примеры правил см. в [сетевых требованиях](../elasticsearch_network_requirements.md).
* `cluster.name` идентичен на всех узлах; `node.name` уникален на каждом узле.
* Синхронизация времени (NTP/chrony) на всех узлах; одинаковые UID/GID пользователя `elasticsearch`.
* Системные лимиты настроены (раздел «Системный тюнинг» выше) — иначе Bootstrap Checks остановят узел при привязке к сетевому интерфейсу.
* Для сценария Enrollment: первый узел запущен с автоконфигурацией безопасности (TLS-сертификаты сгенерированы автоматически); на присоединяемом узле каталог `data` пуст (узел ни разу не запускался) — `elasticsearch-reconfigure-node` выполняется до первого старта сервиса.

### Сценарий 1: Автоматическое развертывание (Enrollment)

Наиболее безопасный и простой метод для новых инсталляций (DEB/RPM).

#### Шаг 1: Инициализация первого узла

1.  Установите пакет, задайте `network.host` (иначе удаленные узлы не смогут подключиться) и запустите сервис:

```yaml
# /etc/elasticsearch/elasticsearch.yml (первый узел)
network.host: 10.0.1.10          # IP этого узла, доступный другим
xpack.security.enrollment.enabled: true   # опционально: автоконфигурация выставит сама при первом старте
```

```bash
systemctl enable --now elasticsearch
# Пароль elastic при пакетной установке в консоль не выводится (сервис работает без терминала) — задайте его вручную:
sudo /usr/share/elasticsearch/bin/elasticsearch-reset-password -u elastic -i
# → Enter new password for [elastic]:
```
2.  Сохраните пароль в переменной окружения: `export ELASTIC_PASSWORD="<новый_пароль>"`. (При запуске из архива в интерактивном терминале пароль выводится на экран один раз — в лог-файл он не записывается.)
3.  Сгенерируйте токен для нового узла (действует 30 минут). Токен можно выпускать на любом узле существующего кластера:
     ```bash
     sudo /usr/share/elasticsearch/bin/elasticsearch-create-enrollment-token -s node
     # → eyJ2ZXIiOiI4LjAuMCIsImFkciI6WyIxMC4wLjEuMTA6OTIwMCJdLCJmZ3IiOiI...
     ```
     Флаг `-s kibana` аналогично генерирует токен подключения Kibana. Если инструмент не может достучаться до локального узла, явно укажите его: `--url "https://10.0.1.10:9200"`; флаг `-f/--force` позволяет выпускать токен на нездоровом кластере.

#### Шаг 2: Присоединение нового узла

На чистом узле (без предварительно настроенного `elasticsearch.yml`) выполните **до первого старта** сервиса:

```bash
sudo /usr/share/elasticsearch/bin/elasticsearch-reconfigure-node --enrollment-token <TOKEN>
# This node will be reconfigured to join an existing cluster...
# Do you want to continue with the reconfiguration process [y/N]y
# → Tool successfully reconfigured the node
systemctl start elasticsearch
```

Инструмент требует `sudo`: он редактирует файлы в каталоге конфигурации, принадлежащие `root:elasticsearch`. Он пропишет TLS (сертификаты того же CA), `discovery.seed_hosts` на первый узел и отключит локальную автоконфигурацию.

#### Шаг 3: Верификация кластера

```bash
curl -k -u elastic:$PASS "https://10.0.1.10:9200/_cat/nodes?v&h=name,ip,node.role,master"
# → name     ip        node.role master
# → es-node1 10.0.1.10 cdfhilmrstw *
# → es-node2 10.0.1.11 cdfhilmrstw -
# → es-node3 10.0.1.12 cdfhilmrstw -
curl -k -u elastic:$PASS "https://localhost:9200/_cluster/health?pretty"
# → "status" : "green", "number_of_nodes" : 3

# Факт присоединения узлов подтверждается в логах:
journalctl -u elasticsearch | grep -i "joined cluster"
# → ... [cluster.service] ... [node-2] ... joined cluster [prod-logs]

# Transport-соединение между узлами зашифровано тем же CA — проверка TLS на 9300:
openssl s_client -connect 10.0.1.11:9300 -CAfile /etc/elasticsearch/certs/http_ca.crt </dev/null 2>/dev/null | grep "Verify return code"
# → Verify return code: 0 (ok)
```

Если пароль утерян, сбросьте его без остановки кластера:

```bash
sudo /usr/share/elasticsearch/bin/elasticsearch-reset-password -u elastic -i
```

### Сценарий 2: Ручная конфигурация (config-first)

Когда политика запрещает автоконфигурацию (или используется архивная установка), топология задается явно. Минимальный пример для трех выделенных мастеров:

```yaml
# /etc/elasticsearch/elasticsearch.yml (узел es-master-1)
cluster.name: prod-logs
node.name: es-master-1
node.roles: [ master ]              # выделенный мастер без данных
network.host: 10.0.1.10
discovery.seed_hosts: ["10.0.1.10", "10.0.1.11", "10.0.1.12"]
cluster.initial_master_nodes: ["es-master-1", "es-master-2", "es-master-3"]
xpack.security.enabled: true
path.data: /var/lib/elasticsearch   # быстрый локальный диск; для мастеров без данных можно не выделять
path.logs: /var/log/elasticsearch
```

На остальных двух мастерах — то же с заменой `node.name`/`network.host`. После успешного формирования кластера строку `cluster.initial_master_nodes` удаляют со всех узлов. Ручной выпуск TLS-сертификатов (`elasticsearch-certutil`) выходит за рамки этого файла — пошаговый пример генерации и раздачи сертификатов см. в [руководстве по Docker Compose](./practical_setup_with_docker.md) (механика идентична для пакетной установки).

### Сценарий 3: Использование Keystore для секретов

Для хранения пароля к S3-репозиторию или кастомных настроек безопасности:

```bash
# 1. Создание хранилища
sudo /usr/share/elasticsearch/bin/elasticsearch-keystore create
# → Created elasticsearch keystore in /etc/elasticsearch/elasticsearch.keystore

# 2. Добавление секрета
sudo /usr/share/elasticsearch/bin/elasticsearch-keystore add s3.client.default.access_key
# -> введите значение интерактивно
```

Полезные операции обслуживания:

```bash
sudo /usr/share/elasticsearch/bin/elasticsearch-keystore list
# → keystore.seed
# → s3.client.default.access_key

# Обновление секрета без рестарта узла (для настроек с флагом Reloadable):
curl -k -u elastic:$PASS -X POST "https://localhost:9200/_nodes/reload_secure_settings"
# → {"nodes":{"<id>":{"name":"es-node1"}}}
```
*В `elasticsearch.yml` теперь можно использовать переменные или полагаться на то, что плагины сами найдут ключи в Keystore. Часть secure-настроек помечена как reloadable — они применяются через API выше; остальные требуют перезапуска узла.*

### Сценарий 4: Устранение неполадок кластера (Troubleshooting)

Если узлы не видят друг друга или кластер находится в статусе `Yellow`/`Red`:

```bash
# Проверка связности и ролей
curl -k -u elastic:$PASS "https://localhost:9200/_cat/nodes?v"

# Анализ проблем с аллокацией шардов (почему шард unassigned?)
curl -k -u elastic:$PASS -H 'Content-Type: application/json' \
  -X GET "https://localhost:9200/_cluster/allocation/explain?pretty"
# → "allocate_explanation" : "Elasticsearch isn't allowed to allocate this shard..."

# Проверка порогов диска (Watermarks)
curl -k -u elastic:$PASS "https://localhost:9200/_cluster/settings?include_defaults=true" | \
  jq '.defaults.cluster.routing.allocation.disk.watermark'
# → {"enable_for_single_data_node":"false","flood_stage.frozen.max_headroom":"20GB",
#    "flood_stage.frozen":"95%","flood_stage":"95%","high":"90%","low":"85%"}

# Здоровье и кворум: pending_tasks не пустой = кластер перегружен метаданными
curl -k -u elastic:$PASS "https://localhost:9200/_cluster/health?pretty"
# → "status" : "yellow", "timed_out" : false, "number_of_pending_tasks" : 0
```

Интерпретация статусов здоровья: `green` — все реплики размещены; `yellow` — есть неразмещенные реплики (частая норма: единственная копия индекса или временная недоступность узла); `red` — потеряны первичные шарды (данные частично недоступны). При деградации до `red` начинайте всегда с `_cluster/allocation/explain` — API отвечает причиной отказа в размещении конкретного шарда.

Типовые ошибки формирования кластера:

| Симптом / ошибка | Причина | Диагностика и решение |
| :--- | :--- | :--- |
| `handshake failed: remote cluster name [X] does not match local cluster name [Y]` | Разный `cluster.name` на узлах | Выровнять `cluster.name` во всех `elasticsearch.yml` |
| `master_not_discovered_exception`, кластер не выбирает мастера | Нет кворума master-eligible узлов | Логи всех master-eligible узлов: `ClusterFormationFailureHelper` пишет причину каждые 10 сек; проверить `discovery.seed_hosts`, доступность порта 9300, синхронизацию времени |
| Узел не присоединяется: TLS-ошибка при верификации сертификата на 9300 | Разные CA на узлах (ручная настройка TLS) или несовпадение отпечатка | Сравнить `openssl x509 -fingerprint -sha256 -in /etc/elasticsearch/certs/http_ca.crt` на всех узлах; при ручном TLS — выдать сертификаты одного CA |
| Узел присоединяется и сразу отключается (`node-join` → `node-left`) | Узел помечен неисправным мастером; частая причина — клонирование каталога `data` (дублируется UUID узла) | В логах мастера: `found existing node ... with the same id but is a different node instance`; очистить `data` на клоне, перезапустить |
| `ERROR: [1] bootstrap checks failed: max virtual memory areas vm.max_map_count [...] is too low` | Системные лимиты ОС не выполнены | Раздел «Системный тюнинг»; проверить `sysctl vm.max_map_count`, `ulimit -n`, `ulimit -u` |
| Узел не может присоединиться после долгого простоя | Локальное состояние узла устарело или привязано к другому cluster UUID | Плановый случай — voting exclusions (ниже); аварийный (кластер потерян) — процедуры ниже |

Плановый вывод мастер-узла из эксплуатации — двухшаговая процедура (path-форма `/_cluster/voting_config_exclusions/<name>` deprecated с 7.8 и не применяется):

```bash
# 1. Исключить узел из кворума ДО остановки (кластер перестроит voting configuration)
curl -k -u elastic:$PASS -X POST \
  "https://localhost:9200/_cluster/voting_config_exclusions?node_names=es-master-old"
# 2. Остановить узел
sudo systemctl stop elasticsearch
# 3. Очистить список исключений после полного удаления узла из кластера
curl -k -u elastic:$PASS -X DELETE \
  "https://localhost:9200/_cluster/voting_config_exclusions"
```

Аварийное восстановление при потере кворума (все или большинство master-eligible узлов безвозвратно потеряны). Крайняя мера с риском потери последних операций — сначала попробуйте вернуть узлы в строй или восстановить данные из snapshot (см. [Disaster Recovery](../Elasticsearch/elasticsearch_disaster_recovery.md)):

```bash
# 1. На узле со свежей копией метаданных — принудительное формирование нового кластера
sudo /usr/share/elasticsearch/bin/elasticsearch-node unsafe-bootstrap
# → Master node was successfully bootstrapped
# 2. На каждом выжившем узле — сброс привязки к старому cluster UUID
sudo /usr/share/elasticsearch/bin/elasticsearch-node detach-cluster
# → Node was successfully detached from the cluster
# 3. Перезапустить узлы; они присоединятся к новому кластру
```

Оба инструмента требуют подтверждения (`Confirm [y/N]`) и выводят сводку удаляемых данных. `unsafe-bootstrap` формирует новый кластер из локальных метаданных одного узла; `detach-cluster` сбрасывает cluster UUID, позволяя узлу перейти в новый кластер. Полная процедура и предупреждения — в [обзоре Elasticsearch](../Elasticsearch/elasticsearch_overview.md) (раздел «Устранение неполадок»).

Плановое удаление data-узла без потери данных:

```bash
# 1. Запретить аллокацию шардов на узел
curl -k -u elastic:$PASS -X PUT "https://localhost:9200/_cluster/settings" \
  -H 'Content-Type: application/json' \
  -d '{"persistent":{"cluster.routing.allocation.exclude._name":"es-data-old"}}'
# 2. Дождаться переноса шардов: на узле не должно остаться шардов
curl -k -u elastic:$PASS "https://localhost:9200/_cat/shards?v&h=index,shard,prirep,state,node" | grep es-data-old
# 3. Снять запрет и остановить узел
curl -k -u elastic:$PASS -X PUT "https://localhost:9200/_cluster/settings" \
  -H 'Content-Type: application/json' \
  -d '{"persistent":{"cluster.routing.allocation.exclude._name":null}}'
sudo systemctl stop elasticsearch
```

## Рекомендации и очистка

**Чек-лист после развёртывания:**

* Удалите `cluster.initial_master_nodes` из `elasticsearch.yml` на всех master-eligible узлах после успешного формирования кластера (повторный запуск с ней опасен расщеплением кластера).
* Убедитесь, что список voting config exclusions пуст: `GET /_cluster/state?filter_path=metadata.cluster_coordination.voting_config_exclusions`.
* Проверьте прохождение bootstrap checks: `GET /_nodes?filter_path=nodes.*.process.mlockall` (должно быть `true` при `bootstrap.memory_lock: true`).
* Зафиксируйте пароль `elastic` в менеджере секретов; при утере — `elasticsearch-reset-password -u elastic -i` (без остановки кластера).

**Применение изменений конфигурации:**

* Настройки из `elasticsearch.yml`, требующие перезапуска, применяют rolling restart-ом (по одному узлу, master-eligible последними); пошаговая процедура — в [Upgrades и миграция](../Elasticsearch/elasticsearch_upgrades.md).
* Часть secure-настроек keystore применяется без рестарта через `POST /_nodes/reload_secure_settings` (см. Сценарий 3).

**Очистка и откат:**

* Токены enrollment живут 30 минут и не требуют отзыва; если генерация токенов не нужна — не задавайте `xpack.security.enrollment.enabled: true` вручную (автоконфигурация выставляет её только при первом старте).
* При выводе узла из эксплуатации: запретите аллокацию, дождитесь переноса шардов, остановите сервис, затем (при необходимости) удалите каталог `data` и верните системные лимиты (`/etc/sysctl.d/99-elasticsearch.conf`, systemd override через `systemctl edit elasticsearch`) к значениям по умолчанию.
* Перед удалением узла из кластера с чётным числом master-eligible узлов помните: кворум должен остаться нечётным — выводите мастеров так, чтобы в кворуме всегда оставалось большинство.

## Дополнительная информация

### Рекомендации по JVM

*   **Heap Size**: Всегда устанавливайте `Xms` равным `Xmx` — это исключает дорогие ресайзы heap в runtime.
*   **Правило 50%**: Не более половины RAM узла отдавайте heap; остальное нужно Lucene и файловой системе для кэша сегментов.
*   **Лимит ~31 ГБ**: Не выделяйте 32 ГБ и более. При пересечении порога compressed oops JVM перестает использовать сжатые указатели, что приводит к резкому росту потребления памяти и снижению производительности. Точный порог зависит от версии JVM и лежит в диапазоне примерно 26–31 ГБ; консервативно безопасны значения до 26 ГБ, а фактический порог виден в стартовом логе узла или через `GET _nodes/jvm` (поле `using_compressed_ordinary_object_pointers`). На серверах с 64+ ГБ RAM стандарт де-факто — heap 26–31 ГБ.
*   **Автосайзинг**: По умолчанию Elasticsearch сам рассчитывает размер heap (50% RAM с ограничением по порогу OOPs, с учетом ролей узла). Переопределяйте только осознанно — через файл в каталоге `jvm.options.d/`, а не правкой основного `jvm.options`:

```text
# /etc/elasticsearch/jvm.options.d/heap.options
-Xms16g
-Xmx16g
```

*   **Bundled JDK**: Начиная с 7.x/8.x, Elasticsearch поставляется с оптимизированной версией JDK (в ветках 9.x — современный JDK с G1 GC по умолчанию). Используйте её, если нет строгой необходимости в специфической версии Java. Не меняйте GC-флаги без рекомендации поддержки: дефолты протестированы Elastic.
*   **Эксплуатационный ориентир**: алерт при устойчивом использовании heap выше 75%; проверка фактического размера — `GET _nodes/stats/jvm`.

### Пороги заполнения диска (Watermarks)

Elasticsearch автоматически блокирует запись при нехватке места:
1.  **Low (85%)**: Перестает назначать новые шарды на узел.
2.  **High (90%)**: Пытается выселить существующие шарды на другие узлы.
3.  **Flood Stage (95%)**: Переводит все индексы на узле в режим `read-only`. Снять блокировку после очистки места можно через API:
    ```http
    PUT /*,_all/_settings
    {
      "index.blocks.read_only_allow_delete": null
    }
    ```

Нюансы эксплуатации:

* Пороги могут задаваться и в процентах, и в абсолютных байтах (`100gb`) — смешивание типов значений между low/high/floodstage запрещено.
* Для frozen-тира существует отдельный порог `flood_stage.frozen` со своим headroom.
* На узле с одним data-узлом пороги по умолчанию отключены (переносить шарды некуда); управляется флагом `cluster.routing.allocation.disk.watermark.enable_for_single_data_node`.
* Мониторьте свободное место так, чтобы flood stage никогда не наступал: снятие read-only блокировки — ручная операция, а до нее все записи в затронутые индексы отбрасываются источником ошибок.

---

*   **[Elasticsearch: Обзор](../Elasticsearch/elasticsearch_overview.md)** — архитектура, роли и возможности 8.15+.
*   **[Elasticsearch: Жизненный цикл (ILM)](../Elasticsearch/elasticsearch_ilm_and_retention.md)** — автоматизация ротации после настройки.
*   **[Elasticsearch: Upgrades и миграция](../Elasticsearch/elasticsearch_upgrades.md)** — rolling restart и rolling upgrade конфигурации.
*   **[Elasticsearch: Disaster Recovery](../Elasticsearch/elasticsearch_disaster_recovery.md)** — snapshot-стратегии и восстановление.
*   **[Развертывание ELK стека в Docker Compose](./practical_setup_with_docker.md)** — генерация TLS-сертификатов вручную и single-node стенд.
