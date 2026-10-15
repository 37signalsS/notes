# Zabbix — мониторинг JMX (Zabbix Java Gateway)

**Актуально для:** Zabbix 7.0 LTS / 7.4

## Определения

* **JMX (Java Management Extensions)** — стандартный механизм управления и мониторинга Java-приложений и JVM. Управляемые ресурсы представлены **MBean** с именами вида `domain:key=value`.
* **MBean object name** — уникальное имя ресурса, например `java.lang:type=Memory` или `Catalina:type=ThreadPool,name="http-nio-8080"`.
* **Атрибут (attribute)** — именованное значение MBean (например, `HeapMemoryUsage.used`). Составные (CompositeData) атрибуты адресуются через точку: `attribute.key`.
* **Zabbix Java Gateway** — отдельный Java-демон, который принимает запросы от Zabbix Server/Proxy и сам выполняет JMX-запросы к целевой JVM. Server не умеет говорить по JMX напрямую — только через gateway.
* **JMX-интерфейс хоста** — сетевой реквизит хоста с IP и **портом JMX-агента** (не портом gateway). Используется для построения JMX-подключения.

Теорию JMX, JVM, GC и диагностики Java-приложений см. в [Управление Java в Linux](../Linux/Development/java_management.md); мониторинг JVM-метрик Kafka — в [Kafka в системах мониторинга](../Kafka/kafka_for_monitoring.md).

## Основные концепции

### Роль Java Gateway

```
Zabbix Server/Proxy  --(JMX-запрос)-->  Zabbix Java Gateway  --(JMX/RMI)-->  JVM приложения
```

Server/Proxy не содержит JMX-библиотек. Он отправляет gateway имя подключения и атрибут; gateway открывает JMX-сессию по RMI к целевой JVM, читает атрибут и возвращает значение. Один gateway обслуживает много JVM; на больших инсталляциях gateway становится узким местом и требует больше `START_POLLERS`.

### Формат ключа JMX-элемента

Ключ элемента типа `JMX agent` имеет две формы:

* `jmx[<endpoint>,<object name>,<attribute>]` — с явным JMX endpoint;
* `jmx[<object name>,<attribute>]` — endpoint выводится из JMX-интерфейса хоста (`service:jmx:rmi:///jndi/rmi://<IP>:<PORT>/jmxrmi`).

Примеры:

```
jmx["java.lang:type=Memory","HeapMemoryUsage.used"]
jmx["java.lang:type=Threading","ThreadCount"]
jmx["Catalina:type=ThreadPool,name=\"http-nio-8080\"","currentThreadsBusy"]
jmx["service:jmx:rmi:///jndi/rmi://10.0.0.5:12345/jmxrmi","java.lang:type=Memory","HeapMemoryUsage.used"]
```

### Как включить JMX на целевой JVM

Приложение должно слушать JMX. Для удалённого подключения JVM стартуют с флагами:

```bash
java -Dcom.sun.management.jmxremote \
     -Dcom.sun.management.jmxremote.port=12345 \
     -Dcom.sun.management.jmxremote.rmi.port=12345 \
     -Dcom.sun.management.jmxremote.authenticate=false \
     -Dcom.sun.management.jmxremote.ssl=false \
     -Djava.rmi.server.hostname=10.0.0.5 \
     -jar app.jar
```

* `jmxremote.port` и `rmi.port` задавать **одинаково** — иначе RMI отдаст случайный порт, который придётся отдельно открывать.
* `java.rmi.server.hostname` обязателен при работе за NAT/несколькими интерфейсами, иначе клиент получит недостижимый адрес.
* `authenticate`/`ssl=false` допустимы только в доверенной сети; в продакшене включайте аутентификацию и SSL.

## Практические сценарии

### Предварительные требования

* Установлен `zabbix-java-gateway` на отдельном хосте или на сервере.
* Java установлена (gateway — Java-приложение).
* На целевой JVM открыт JMX-порт (по умолчанию в примерах — 12345).
* В `zabbix_server.conf`/`zabbix_proxy.conf` указаны параметры gateway.

### Шаг 1. Установка и настройка Java Gateway

```bash
# Debian/Ubuntu
sudo apt install zabbix-java-gateway
# RHEL/Rocky/Alma
sudo dnf install zabbix-java-gateway
```

`/etc/zabbix/zabbix_java_gateway.conf`:

```ini
LISTEN_IP="0.0.0.0"
LISTEN_PORT=10052
START_POLLERS=5
TIMEOUT=3
```

```bash
sudo systemctl enable --now zabbix-java-gateway
systemctl status zabbix-java-gateway
# → active (running)
```

### Шаг 2. Подключение Server/Proxy к gateway

В `zabbix_server.conf`:

```ini
JavaGateway=127.0.0.1
JavaGatewayPort=10052
StartJavaPollers=5
Timeout=4
```

```bash
sudo systemctl restart zabbix-server
```

> `JavaGatewayPort` — порт **gateway** (10052), а не порт JMX целевой JVM. Их легко перепутать.

### Шаг 3. JMX-интерфейс и элемент данных хоста

1. `Data collection → Hosts → <host> → Interfaces → Add → JMX`: IP приложения и **порт JMX** (например, 12345).
2. `Create item`:
   * **Type:** `JMX agent`;
   * **Key:** `jmx["java.lang:type=Memory","HeapMemoryUsage.used"]`;
   * **Host interface:** JMX-интерфейс;
   * **Type of information:** `Numeric (unsigned)`/`Numeric (float)`.

### Шаг 4. Готовые шаблоны

Для типовых приложений используйте официальные шаблоны JMX (`Apache Tomcat by JMX`, `Generic Java by JMX` и др.). Начиная с Zabbix 7.0 официальные шаблоны JMX требуют Java Gateway и соответствующей версии агента не используют — JMX-проверки идут только через gateway.

### Шаг 5. Проверка

```bash
# Gateway слушает порт 10052
ss -tlnp | grep 10052
# → LISTEN 0 50 0.0.0.0:10052 ... java

# Порт JMX целевой JVM открыт
ss -tlnp | grep 12345
# → LISTEN 0 50 0.0.0.0:12345 ... java

# В форме item — кнопка "Test" проверяет атрибут через gateway
```

## Операции и команды

| Задача | Команда |
|---|---|
| Статус gateway | `systemctl status zabbix-java-gateway` |
| Лог gateway | `/var/log/zabbix/zabbix_java_gateway.log` |
| Порт gateway | `ss -tlnp \| grep 10052` |
| JMX-порт приложения | `ss -tlnp \| grep <jmx-port>` |
| Локальная проверка JMX (JDK) | `jconsole <host>:<jmx-port>` |
| Список MBean через CLI | `jcmd <pid> ManagementAgent.status` |

```bash
# Проверить, что JVM подняла JMX-агент
jcmd <java-pid> ManagementAgent.status
# → Agent: enabled

# Занятость Java-поллеров на сервере (внутренняя метрика)
# zabbix[process,java poller,avg,busy]  → 0..100%
```

## Устранение неисправностей

### «Zabbix Java Gateway is not running» / элементы Unsupported

* Сервис `zabbix-java-gateway` не запущен.
* `JavaGateway`/`JavaGatewayPort` на сервере не совпадают с конфигом gateway.
* Порт 10052 закрыт между сервером и gateway (если gateway на отдельном хосте).

### Таймаут JMX-подключения

* `-Dcom.sun.management.jmxremote.rmi.port` не задан — RMI отдал случайный порт, закрытый firewall.
* Не задан `-Djava.rmi.server.hostname`, клиент пошёл на внутренний/недостижимый адрес.
* Увеличьте `TIMEOUT` в gateway и `Timeout` в server.

### Атрибут возвращает пусто / ошибку

* Ошибка в object name или имени атрибута (регистр важен; имя `name="..."` требует экранирования кавычек).
* Составной атрибут запрашивается без `.key` (`HeapMemoryUsage` вместо `HeapMemoryUsage.used`).
* Атрибут недоступен (например, требует вызова операции, а не чтения).

### Нагрузка на gateway высокая

* Мало `START_POLLERS` — увеличьте.
* Слишком частый опрос большого числа JMX-атрибутов — агрегируйте через dependent items или снизьте частоту.
* Несколько gateway для балансировки при очень большом числе JVM.

## Лучшие практики

* **Gateway — отдельный сервис.** Держите его на выделенном хосте при большом числе JVM; gateway не должен делить ресурсы с сервером БД.
* **Начинайте с малого:** `START_POLLERS=5` обычно достаточно для десятков JVM; масштабируйте по занятости `zabbix[process,java poller,avg,busy]`.
* **Шаблоны JMX вместо ручных ключей** — покрывают типовые метрики heap, GC, thread pools, JDBC.
* **Единый `rmi.port`** при конфигурации JVM и явный `java.rmi.server.hostname`.
* **Мониторьте сам gateway** (порт, процесс, доступность JMX-портов приложений) — падение gateway «ослепляет» весь JMX-сегмент.
* **Ограничьте JMX-порт** firewall-правилами до адресов сервера/прокси; включайте аутентификацию и SSL в прода.

## Дополнительная информация

### См. также

* [Управление Java в Linux](../Linux/Development/java_management.md) — JVM, GC, диагностика.
* [Kafka в системах мониторинга](../Kafka/kafka_for_monitoring.md) — JMX Exporter и метрики JVM для Kafka.
* [Элементы данных](./zabbix_items.md) — типы элементов, предобработка.
* [Установка и настройка](./installation.md) — развёртывание сервера и прокси.
* [Устранение неисправностей и тюнинг](./zabbix_troubleshooting_and_performance_tuning.md) — занятость поллеров.

### Источники

* Zabbix documentation: [JMX monitoring](https://www.zabbix.com/documentation/current/en/manual/config/items/itemtypes/jmx_monitoring), [Zabbix Java gateway](https://www.zabbix.com/documentation/current/en/manual/concepts/java).
