# Руководство: Настройка мультинодового кластера Elasticsearch (8.x / 9.x)

> Эта заметка является авторитетным источником по развертыванию мультинодовых кластеров Elasticsearch версий 8.x и 9.x в self-managed среде. Она охватывает процессы автоматической и ручной настройки безопасности, системный тюнинг ОС, управление ролями узлов и обеспечение отказоустойчивости на уровне стоек или зон доступности.
>
> Базовая архитектура кластера описана в [обзоре Elasticsearch](../Elasticsearch/elasticsearch_overview.md); развертывание single-node в Docker — в [руководстве по Docker Compose](./practical_setup_with_docker.md); сетевые требования — в [Network и Firewall](../elasticsearch_network_requirements.md).

## Определения

* **Токен регистрации (Enrollment Token)** — зашифрованный ключ (Base64-строка), содержащий информацию для автоматического подключения нового узла к кластеру: версию, адреса мастер-узла, отпечаток CA-сертификата и ключ доступа. Действует 30 минут с момента генерации.
* **Проверки при загрузке (Bootstrap Checks)** — набор тестов конфигурации ОС (память, лимиты файлов, потоки), которые Elasticsearch выполняет при старте в сетевом режиме (когда `network.host` привязан не только к loopback). Если проверки не пройдены, процесс завершается с ошибкой и не формирует кластер.
* **Allocation Awareness (Осведомленность о распределении)** — механизм, позволяющий Elasticsearch учитывать физическую топологию серверов (зоны, стойки) при размещении реплик для предотвращения потери данных при отказе целого сегмента инфраструктуры.
* **Elasticsearch Keystore** — защищенное хранилище для чувствительных настроек (пароли облачных провайдеров, ключи API), которое предотвращает их хранение в открытом виде в `elasticsearch.yml`.
* **Compressed OOPs (Сжатые указатели)** — технология JVM, позволяющая использовать 32-битные указатели в 64-битной среде, что экономит память. Работает только до порога heap, который зависит от JVM (~26–31 ГБ); точное значение можно проверить в логах или через `GET _nodes/jvm`.
* **Кворум мастеров (Voting Configuration)** — подмножество master-eligible узлов, чьи голоса определяют выбор активного мастера и защиту от split brain. Кластер работоспособен, пока доступны больше половины узлов кворума; поэтому число master-eligible узлов должно быть нечетным (обычно 3).
* **Security Auto-Configuration** — автоматическая настройка безопасности при первом запуске: генерация CA, выпуск TLS-сертификатов для transport- и HTTP-слоя, создание пароля суперпользователя `elastic`.
* **Дисковые пороги (Watermarks)** — уровни заполнения диска (по умолчанию 85%/90%/95%), при достижении которых кластер последовательно прекращает назначать шарды, мигрирует их с узла и блокирует запись в индексы.

## Основные концепции

### Параметры формирования кластера

В версиях 8.x/9.x процесс формирования кластера упрощен благодаря автоматизации, но требует понимания ключевых параметров:

| Параметр | Назначение | Особенности |
| :--- | :--- | :--- |
| **`cluster.initial_master_nodes`** | Список начальных мастеров | Используется **только один раз** при самом первом запуске (bootstrap). Задается только на master-eligible узлах первого формирования; после образования кластера настройку следует убрать из конфигурации. |
| **`discovery.seed_hosts`** | Список узлов для поиска | IP или DNS-имена master-eligible узлов. Постоянная настройка — нужна при каждом старте для повторного обнаружения кластера. |
| **`node.roles`** | Список ролей узла | Например `[master, data_hot]`. Для стабильности рекомендуется выделять 3 выделенных узла с ролью `master` в кластерах от 10 узлов. |

Механика выбора мастера: при первом запуске узлы из `cluster.initial_master_nodes` образуют voting configuration и выбирают активного мастера; далее состав кворума кластер поддерживает сам (API `_cluster/voting_config_exclusions` нужен только при выводе мастеров из эксплуатации). Нарушение кворума останавливает запись и выбор мастера — кластер остается в режиме чтения недоступным (`master not discovered`), это штатная защита от split brain, а не авария.

### Модель безопасности по умолчанию (Security Auto-Configuration)

При первом старте узла, установленного из DEB/RPM пакета, происходит следующее:

1. Генерируется локальный CA и сертификаты; TLS включается для transport-слоя (порт 9300) и HTTP-слоя (порт 9200).
2. В keystore записывается seed, генерируется пароль пользователя `elastic` — он выводится **один раз** в консоль/лог при первом старте.
3. HTTP-слой привязывается к `_site_` и `_local_`, transport-слой — только к `_local_`. Это позволяет single-node стартовать без вопросов, но означает, что для присоединения удаленных узлов нужно явно задать `network.host`.

Ограничения, которые важно знать заранее:

* Enrollment работает **только** с автосгенерированными сертификатами; если TLS настроен вручную через `elasticsearch-certutil`, токены узлов использовать нельзя.
* Генерация токенов требует настройки `xpack.security.enrollment.enabled: true`. Токен для Kibana (`-s kibana`) дополнительно опирается на TLS HTTP-слоя, который при автоконфигурации включен по умолчанию.
* Инструмент переписывает существующую автоконфигурацию нового узла: удаляет его локальные сертификаты и связанные secure-настройки, заменяя их данными из токена.

### Системный тюнинг (Production Ready)

Для прохождения Bootstrap Checks и стабильной работы под нагрузкой обязательны следующие настройки ([официальный список](https://www.elastic.co/docs/deploy-manage/deploy/self-managed/bootstrap-checks)):

1.  **Память (mmap)**: Увеличение лимитов виртуальной памяти для Lucene.
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
3.  **Дескрипторы файлов**: Минимум 65536 открытых файлов.
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

## Практические сценарии

### Сценарий 1: Автоматическое развертывание (Enrollment)

Наиболее безопасный и простой метод для новых инсталляций (DEB/RPM).

#### Шаг 1: Инициализация первого узла

1.  Установите пакет, задайте `network.host` (иначе удаленные узлы не смогут подключиться) и запустите сервис:

```yaml
# /etc/elasticsearch/elasticsearch.yml (первый узел)
network.host: 10.0.1.10          # IP этого узла, доступный другим
xpack.security.enrollment.enabled: true   # разрешает генерацию токенов
```

```bash
systemctl enable --now elasticsearch
# → в логе появится одноразовый пароль elastic:
grep -A2 "Password for the elastic user" /var/log/elasticsearch/elasticsearch.log
```
2.  Сохраните вывод в консоли или найдите пароль в логах: `/var/log/elasticsearch/elasticsearch.log`.
3.  Сгенерируйте токен для нового узла (действует 30 минут):
    ```bash
    sudo /usr/share/elasticsearch/bin/elasticsearch-create-enrollment-token -s node
    # → eyJ2ZXIiOiI4LjAuMCIsImFkciI6WyIxMC4wLjEuMTA6OTIwMCJdLCJmZ3IiOiI...
    ```
    Флаг `-s kibana` аналогично генерирует токен подключения Kibana.

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

### Сценарий 4: Диагностика формирования кластера

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

Для планового вывода мастер-узла из эксплуатации исключите его из кворума заранее:

```bash
curl -k -u elastic:$PASS -X DELETE \
  "https://localhost:9200/_cluster/voting_config_exclusions/es-master-old"
```

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
*   **[Развертывание ELK стека в Docker Compose](./practical_setup_with_docker.md)** — генерация TLS-сертификатов вручную и single-node стенд.
