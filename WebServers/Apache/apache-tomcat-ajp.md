# Apache: Интеграция с Tomcat (AJP, mod_proxy_ajp)

**Актуально для:** Apache HTTP Server 2.4.x / Apache Tomcat 9.0.x, 10.1.x, 11.0.x

---

## Определения

**Tomcat (Apache Tomcat)** — сервер приложений и контейнер сервлетов с открытым исходным кодом, разрабатываемый Apache Software Foundation. Реализует спецификации Jakarta Servlet, Jakarta Server Pages (JSP), Jakarta Expression Language и Jakarta WebSocket. Точкой входа для сетевых запросов является сетевой компонент **Connector**.

**AJP (Apache JServ Protocol, версия 1.3 / AJP13)** — бинарный пакетный протокол взаимодействия между внешним веб-сервером (Apache HTTP Server) и бэкенд-контейнером сервлетов (Tomcat). Представляет собой оптимизированное бинарное представление HTTP/1.1: стандартные HTTP-заголовки кодируются числовыми байтовыми константами, соединения между серверами мультиплексируются и удерживаются постоянными (persistent pool), а параметры окружения и SSL-атрибуты передаются напрямую внутри протокольных фреймов. Порт по умолчанию — `8009/TCP`.

**mod_proxy_ajp** — протокольный модуль Apache HTTP Server, обеспечивающий поддержку схемы `ajp://` для базового механизма `mod_proxy`. Преобразует клиентские HTTP-запросы в бинарные кадры AJP13 и передает их в коннектор Tomcat. Является стандартным решением вместо устаревшего внешнего модуля `mod_jk`.

**mod_jk (Apache Tomcat Connector)** — исторический внешний C-модуль для веб-серверов Apache, IIS и iPlanet, взаимодействующий с Tomcat через конфигурационный файл `workers.properties`. Не входит в базовое дерево исходных кодов `httpd`, требует отдельной компиляции и в современной инфраструктуре сохраняется только на легаси-инсталляциях.

**Ghostcat (CVE-2020-1938)** — критическая уязвимость протокола AJP13, обнаруженная в начале 2020 года. В силу отсутствия аутентификации и открытого по умолчанию порта 8009 неавторизованный злоумышленник мог внедрять произвольные AJP-атрибуты запроса, что приводило к чтению любых файлов приложения (включая `WEB-INF/web.xml`, исходные коды JSP и файлы конфигураций), а при возможности загрузки файлов на сервер — к удаленному выполнению кода (RCE). Устранение уязвимости привело к кардинальному ужесточению стандартов безопасности AJP в Tomcat (обязательный секрет, привязка к loopback по умолчанию, фильтрация атрибутов).

**secret / secretRequired** — механизм взаимной аутентификации (shared secret) между Apache (`ProxyPass ... secret=KEY`) и Tomcat (`<Connector ... secret="KEY" secretRequired="true">`). Предотвращает обработку коннектором Tomcat AJP-пакетов, поступивших от неавторизованных сетевых источников.

**jvmRoute** — системный атрибут директивы `<Engine>` в конфигурации Tomcat (`server.xml`). Автоматически добавляется сервлетами в конец идентификатора сессии через точку (например, `JSESSIONID=8F3C1A2D4E5B6.node1`). Служит маркером для балансировщика Apache (`mod_proxy_balancer`), указывающим, на какой конкретный бэкенд должен направляться запрос пользователя (sticky session).

**CPing / CPong** — легковесный протокольный механизм проверки доступности (heartbeat / health check) на уровне AJP. Apache отправляет проверочный бинарный пакет `CPing`, а Tomcat немедленно отвечает пакетом `CPong` на уровне коннектора, не задействуя рабочий пул потоков сервлетов. Активируется параметром `ping` в конфигурации Apache.

**packetSize** — максимальный размер одного бинарного AJP-пакета в байтах (по умолчанию 8192 байта / 8 КБ). Ограничивает суммарный размер HTTP-заголовков, cookies и первого фрагмента тела. При превышении этого лимита (например, при использовании крупных JWT-токенов или Kerberos/SPNEGO) требуется синхронное увеличение значения как в Tomcat (`packetSize`), так и в Apache (`ProxyIOBufferSize`).

---

## Основные концепции и архитектура

### Архитектура взаимодействия и топология запроса

В инфраструктурной схеме Apache HTTP Server выступает в роли граничного сервера (Edge / Reverse Proxy), выполняя терминацию TLS/HTTPS, отдачу статического контента, компрессию, ограничение частоты запросов и балансировку нагрузки, а Tomcat выполняет исключительно динамический код Java-сервлетов:

```
[ Клиент (Браузер / API-клиент) ]
             │
             │ HTTPS (Порт 443)
             ▼
┌────────────────────────────────────────────────────────┐
│ Apache HTTP Server 2.4 (event MPM)                     │
│  ├── Модуль mod_ssl: терминация TLS, проверка mTLS     │
│  ├── Обслуживание статики: Alias /static/ /var/www/... │
│  └── Балансировка / Проксирование:                     │
│      ├── mod_proxy                                     │
│      ├── mod_proxy_balancer (Sticky Sessions)          │
│      └── mod_proxy_ajp (Трансляция HTTP ──► AJP13)     │
└────────────┬───────────────────────────────┬───────────┘
             │                               │
             │ AJP13 (TCP:8009, secret)      │ AJP13 (TCP:8009, secret)
             ▼                               ▼
┌───────────────────────────┐   ┌───────────────────────────┐
│ Tomcat Node 1             │   │ Tomcat Node 2             │
│  ├── AJP/1.3 Connector    │   │  ├── AJP/1.3 Connector    │
│  │   (порт 8009, secret)  │   │   (порт 8009, secret)  │
│  ├── Engine jvmRoute=node1│   │  ├── Engine jvmRoute=node2│
│  └── JVM / Сервлеты       │   │  └── JVM / Сервлеты       │
└───────────────────────────┘   └───────────────────────────┘
```

### Формат и жизненный цикл пакета AJP13

AJP13 — синхронный бинарный протокол. В отличие от текстового протокола HTTP/1.1, где каждый запрос требует разбора строк ASCII, AJP передает данные в бинарных фреймах фиксированной структуры:

1. **Заголовок пакета (4 байта):**
   - 2 байта магического числа (`Magic Number`): `0x1234` для пакетов от Apache к Tomcat; `0x4142` (ASCII-символы `'A'`, `'B'`) для пакетов от Tomcat к Apache.
   - 2 байта длины полезной нагрузки (`Payload Length`): размер данных пакета без учета 4 байт заголовка. Максимальный размер по умолчанию равен `8192 - 4 = 8188` байт.
2. **Тело пакета (Payload):**
   - Для запросов от веб-сервера первым байтом передается код команды: `2` (Forward Request), `7` (Shutdown), `10` (CPing).
   - При передаче запроса (`Forward Request`) метод (GET, POST и т.д.) кодируется 1 байтом, протокол — строкой, стандартные заголовки (Host, Cookie, Authorization, User-Agent) передаются 2-байтовыми целочисленными кодами (`0xA001`–`0xA00E`).
   - Дополнительно передаются бинарные атрибуты: удаленный IP-адрес клиента (`remote_addr`), SSL-сертификаты, шифры и секрет аутентификации (`AJP_SECRET`).
3. **Ответ Tomcat:**
   - Передает пакеты типов `Send Headers` (код 4), серию пакетов `Send Body Chunk` (код 3) и завершающий пакет `End Response` (код 5).

### Сравнение протоколов: AJP vs HTTP Reverse Proxy (mod_proxy_http)

| Критерий | `mod_proxy_ajp` (AJP13) | `mod_proxy_http` (HTTP/1.1) |
|---|---|---|
| **Формат передачи** | Бинарный, оптимизированный | Текстовый HTTP/1.1 |
| **Накладные расходы CPU** | Минимальные (заголовки уже предразобраны) | Низкие (на современных CPU разница < 3–5%) |
| **Передача метаданных SSL** | Нативная передача атрибутов (сертификат, шифр, IP) внутри протокола | Требует ручной настройки заголовков (`X-Forwarded-*`) и `RemoteIPValve` |
| **Ограничение заголовков** | Жесткий лимит `packetSize` (8 КБ по умолчанию) | Гибко настраивается через `LimitRequestFieldSize` |
| **Шифрование канал-канал** | Нативно отсутствует (требует IPsec, WireGuard или SSH-туннеля) | Нативная поддержка HTTPS к бэкенду (`ProxyPass https://`) |
| **Диагностика и трассировка** | Сложная (требуются дампы Wireshark или утилиты AJP) | Тривиальная (`curl`, HTTP/REST-клиенты, стандартный `tcpdump`) |
| **Совместимость с микросервисами** | Только Apache Tomcat и некоторые Java EE серверы | Универсальная (Spring Boot, Quarkus, Node.js, Go, Python) |
| **Рекомендация SRE** | **Легаси-монолиты и сценарии с mTLS-пробросом** | **Стандарт для новых систем и контейнерных сред** |

### Последствия уязвимости Ghostcat (CVE-2020-1938)

До 2020 года AJP-коннектор по умолчанию слушал сетевой адрес `0.0.0.0` без пароля и позволял передавать произвольные атрибуты запроса. Уязвимость Ghostcat показала, что через механизм `javax.servlet.include.*` атакующий мог заставить стандартный `DefaultServlet` прочитать любой файл внутри веб-приложения или исполнить код через `JspServlet`.

Начиная с версий Tomcat 9.0.31+, 8.5.51+, 10.0.0-M1+, 10.1.x и 11.x:
1. Коннектор AJP слушает **только loopback-интерфейс** (`127.0.0.1` для IPv4 или `::1` для IPv6), если явно не указан `address`.
2. Параметр `secretRequired` по умолчанию равен `true`. Если он включен, но параметр `secret` пуст, коннектор **отказывается запускаться**.
3. Добавлен параметр `allowedRequestAttributesPattern` (регулярное выражение). Все входящие AJP-атрибуты, не подходящие под шаблон, отбрасываются с ошибкой `403 Forbidden`.
4. В Apache HTTP Server начиная с версии 2.4.42 директивы `ProxyPass` и `BalancerMember` получили обязательный параметр `secret=` для передачи ключа в Tomcat.

### Механизм Sticky Sessions (jvmRoute)

Для приложений с сохранением состояния (Stateful Java Applications) критично, чтобы повторные запросы пользователя попадали на тот экземпляр Tomcat, где в оперативной памяти создана его сессия `HttpSession`:

1. В Tomcat настраивается уникальное имя узла: `<Engine name="Catalina" defaultHost="localhost" jvmRoute="node1">`.
2. При вызове `request.getSession()` Tomcat генерирует случайный идентификатор сессии и прикрепляет к нему суффикс `.node1`, отдавая заголовок:
   ```http
   Set-Cookie: JSESSIONID=6B8E29A4D10F7C3E5A2.node1; Path=/; HttpOnly
   ```
3. Apache с модулем `mod_proxy_balancer` анализирует значение cookie `JSESSIONID`:
   ```apacheconf
   ProxySet stickysession=JSESSIONID|jsessionid
   ```
4. Балансировщик извлекает суффикс после разделителя (`.`) и перенаправляет запрос на участника кластера (`BalancerMember`), у которого параметр `route` равен `node1`.
5. Если в запросе cookie отсутствует, но сессия передается через URL-rewriting (например, `/app/page;jsessionid=6B8E29A4D10F7C3E5A2.node1`), символ `|` в параметре `stickysession` указывает проверять URL-параметр `jsessionid`.

### Синхронизация пулов соединений (Apache MPM vs Tomcat Connector)

Распространенная архитектурная ошибка — несоответствие емкости пула потоков Apache и Tomcat. 

* В Apache каждый процесс `event` или `worker` MPM удерживает постоянные соединения с Tomcat. Максимальное число соединений от Apache к Tomcat равно:
  $$\text{Max Apache Connections} = \text{ServerLimit} \times \text{ThreadsPerChild}$$
* В Tomcat коннектор AJP имеет параметры:
  - `maxThreads` — максимальное число потоков обработки запросов (по умолчанию 200).
  - `acceptCount` — размер очереди ожидания входящих TCP-соединений в ОС при занятости всех потоков (по умолчанию 100).
  - `maxConnections` — максимальное число параллельно удерживаемых TCP-сокетов (для коннектора NIO по умолчанию 8192).

**Правило SRE:** Лимит соединений Apache к бэкенду (`max=` в `BalancerMember` или суммарная емкость воркеров) не должен превышать значение `maxThreads` в Tomcat. В противном случае при всплеске трафика запросы начнут накапливаться в очереди `acceptCount`, задержка (latency) лавинообразно вырастет, а после переполнения очереди Tomcat начнет сбрасывать соединения с ошибкой `Connection refused`.

---

## Практические сценарии и конфигурация

### Сценарий 1: Базовая локальная интеграция (Single Node)

Топология: Apache HTTPD и Tomcat запущены на одном хосте. Apache выполняет роль фронтенда, принимает внешний трафик на портах 80 и 443, отдает статические файлы напрямую с диска, а все запросы к приложению проксирует на локальный AJP-порт `127.0.0.1:8009` с аутентификацией по секрету.

#### 1. Настройка Tomcat (`/opt/tomcat/conf/server.xml`)

Найдите или добавьте блок `<Connector>` протокола `AJP/1.3`:

```xml
<Connector port="8009"
           protocol="AJP/1.3"
           address="127.0.0.1"
           secretRequired="true"
           secret="d8f4e2a6b0c1e5d7f9a3b8c2e4a7d1f5"
           maxThreads="200"
           minSpareThreads="20"
           connectionTimeout="20000"
           keepAliveTimeout="60000"
           maxConnections="8192"
           redirectPort="8443" />
```

> [!IMPORTANT]
> Директива `address="127.0.0.1"` гарантирует, что порт 8009 недоступен из внешней сети. Никогда не указывайте `0.0.0.0`. Секрет должен быть стойкой случайной строкой (рекомендуется генерация через `openssl rand -hex 16`).

#### 2. Настройка Apache VirtualHost (`/etc/apache2/sites-available/app.conf` или `/etc/httpd/conf.d/app.conf`)

```apacheconf
# Включение необходимых модулей
# Debian/Ubuntu: a2enmod proxy proxy_ajp ssl
# RHEL/Rocky: проверяется в /etc/httpd/conf.modules.d/00-proxy.conf

<VirtualHost *:80>
    ServerName app.example.com
    ServerAdmin sysadmin@example.com

    DocumentRoot /var/www/app/public

    # Журналирование с замером времени ответа бэкенда в микросекундах (%D)
    LogFormat "%h %l %u %t \"%r\" %>s %b \"%{Referer}i\" \"%{User-Agent}i\" %D" combined_perf
    CustomLog /var/log/apache2/app_access.log combined_perf
    ErrorLog /var/log/apache2/app_error.log

    # Прямая отдача статических ресурсов средствами Apache
    Alias /static/ /var/www/app/public/static/
    <Directory "/var/www/app/public/static">
        Options -Indexes +FollowSymLinks
        AllowOverride None
        Require all granted
        
        # Кэширование статики в браузерах
        <IfModule mod_expires.c>
            ExpiresActive On
            ExpiresDefault "access plus 1 month"
        </IfModule>
    </Directory>

    # Исключение статики из проксирования
    ProxyPass /static/ !

    # Проксирование всех остальных запросов в Tomcat по AJP
    # ping=2: быстрый CPing/CPong перед отправкой запроса (таймаут 2 сек)
    # timeout=60: таймаут чтения ответа от Tomcat
    # retry=5: пауза в секундах перед повторной попыткой при сбое
    ProxyPass / ajp://127.0.0.1:8009/ secret=d8f4e2a6b0c1e5d7f9a3b8c2e4a7d1f5 ping=2 timeout=60 retry=5
    ProxyPassReverse / ajp://127.0.0.1:8009/
</VirtualHost>
```

---

### Сценарий 2: Отказоустойчивый кластер с балансировкой нагрузки и Sticky Sessions

Топология: Один фронтенд Apache HTTPD балансирует трафик между двумя независимыми серверами приложений Tomcat (Node 1 и Node 2) в локальной сети, с выделенным горячим резервом (Node 3, Hot Standby). Используется сессионная привязка пользователей (`JSESSIONID`) и активный мониторинг состояния через `CPing`.

```
                  ┌───────────────────────────────┐
                  │ Apache (mod_proxy_balancer)   │
                  └──────────────┬────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │ (Active: load=1)      │ (Active: load=1)      │ (Hot Standby: status=+H)
         ▼                       ▼                       ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Tomcat Node 1    │    │ Tomcat Node 2    │    │ Tomcat Node 3    │
│ 192.168.10.11    │    │ 192.168.10.12    │    │ 192.168.10.13    │
│ jvmRoute=node1   │    │ jvmRoute=node2   │    │ jvmRoute=node3   │
└──────────────────┘    └──────────────────┘    └──────────────────┘
```

#### 1. Настройка Tomcat Node 1 (`server.xml` на хосте 192.168.10.11)

```xml
<!-- Привязка к приватному сетевому интерфейсу -->
<Connector port="8009"
           protocol="AJP/1.3"
           address="192.168.10.11"
           secretRequired="true"
           secret="ClusterSecretPass98765"
           maxThreads="300"
           minSpareThreads="25"
           connectionTimeout="20000" />

<!-- Задание jvmRoute для Engine -->
<Engine name="Catalina" defaultHost="localhost" jvmRoute="node1">
    <Host name="localhost" appBase="webapps" unpackWARs="true" autoDeploy="false" />
</Engine>
```

*(На Node 2 указывается `address="192.168.10.12"` и `jvmRoute="node2"`; на Node 3 — `address="192.168.10.13"` и `jvmRoute="node3"`).*

#### 2. Настройка сетевого экрана на узлах Tomcat (nftables)

Для защиты порта 8009 разрешается доступ исключительно с IP-адреса Apache (например, `192.168.10.5`):

```bash
sudo nft add rule inet filter input ip saddr 192.168.10.5 tcp dport 8009 ct state new,established accept
sudo nft add rule inet filter input tcp dport 8009 drop
```

#### 3. Настройка Apache Balancer (`/etc/apache2/sites-available/cluster.conf`)

```apacheconf
# Загрузка необходимых модулей:
# proxy, proxy_ajp, proxy_balancer, lbmethod_byrequests, status

<Proxy balancer://tomcat_cluster>
    # Рабочий узел 1: route совпадает с jvmRoute в server.xml
    BalancerMember ajp://192.168.10.11:8009 route=node1 loadfactor=1 \
        secret=ClusterSecretPass98765 ping=1 retry=10 connectiontimeout=2 timeout=60 \
        min=5 smax=20 max=100 ttl=120

    # Рабочий узел 2: аналогичные параметры
    BalancerMember ajp://192.168.10.12:8009 route=node2 loadfactor=1 \
        secret=ClusterSecretPass98765 ping=1 retry=10 connectiontimeout=2 timeout=60 \
        min=5 smax=20 max=100 ttl=120

    # Резервный узел (Hot Standby): активируется только при падении обоих основных
    BalancerMember ajp://192.168.10.13:8009 route=node3 status=+H \
        secret=ClusterSecretPass98765 ping=1 retry=10 connectiontimeout=2 timeout=60

    # Параметры кластера:
    # stickysession: поиск сессии в cookie JSESSIONID или параметре jsessionid
    ProxySet stickysession=JSESSIONID|jsessionid
    # lbmethod: алгоритм распределения (byrequests, bytraffic, bybusyness)
    ProxySet lbmethod=byrequests
    # nofailover=Off: при падении узла перенаправлять запрос на рабочий (сессия пересоздается)
    ProxySet nofailover=Off
</Proxy>

<VirtualHost *:80>
    ServerName cluster.example.com

    ProxyPass / balancer://tomcat_cluster/
    ProxyPassReverse / balancer://tomcat_cluster/

    # Веб-консоль управления балансировщиком (доступ строго ограничен)
    <Location /balancer-manager>
        SetHandler balancer-manager
        Require ip 127.0.0.1 192.168.10.0/24
    </Location>
</VirtualHost>
```

---

### Сценарий 3: Терминация SSL на Apache и передача клиентских сертификатов (mTLS) в Tomcat

В системах со строгой аутентификацией (клиентские сертификаты x509, смарт-карты, государственные токены) Apache выполняет проверку TLS и валидацию цепочки сертификатов, после чего `mod_proxy_ajp` автоматически передает весь контекст безопасности в бинарных атрибутах AJP.

#### Конфигурация Apache (`/etc/apache2/sites-available/secure-app.conf`)

```apacheconf
<VirtualHost *:443>
    ServerName secure.example.com

    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/server.crt
    SSLCertificateKeyFile /etc/ssl/private/server.key
    SSLCACertificateFile /etc/ssl/certs/ca-chain.crt

    # Запрос и обязательная проверка клиентского сертификата
    SSLVerifyClient require
    SSLVerifyDepth 3

    # Экспорт переменных окружения и полного тела сертификата в mod_proxy_ajp
    SSLOptions +StdEnvVars +ExportCertData

    # mod_proxy_ajp автоматически формирует внутренний AJP-атрибут
    # AJP_LOCAL_ADDR, SSL_CLIENT_CERT, SSL_CIPHER_SUITE
    ProxyPass / ajp://127.0.0.1:8009/ secret=d8f4e2a6b0c1e5d7f9a3b8c2e4a7d1f5 ping=2 timeout=60
    ProxyPassReverse / ajp://127.0.0.1:8009/
</VirtualHost>
```

#### Чтение сертификата в сервлете Java на стороне Tomcat

В отличие от HTTP-проксирования, где сертификат приходится сериализовать в кастомный заголовок (например, `X-Client-Cert`), в AJP Tomcat автоматически преобразует данные в стандартный массив объектов `X509Certificate`:

```java
// Для Jakarta EE (Tomcat 10+):
import java.security.cert.X509Certificate;

X509Certificate[] certs = (X509Certificate[]) request.getAttribute("jakarta.servlet.request.X509Certificate");
if (certs != null && certs.length > 0) {
    String clientDN = certs[0].getSubjectX500Principal().getName();
    // Использование DN клиента для авторизации
}

// Для легаси Java EE (Tomcat 9 и ниже):
// request.getAttribute("javax.servlet.request.X509Certificate");
```

---

### Сценарий 4: Тюнинг размера пакета (packetSize) для крупных заголовков (SSO / Kerberos / JWT)

По умолчанию максимальный размер пакета AJP составляет **8192 байта (8 КБ)**. Если клиент передает массивные HTTP-заголовки (например, Negotiate/SPNEGO билет Kerberos в заголовке `Authorization`, либо цепочку JWT-токенов в нескольких cookies), запрос завершается ошибкой `500 Internal Server Error` или аварийным разрывом соединения со стороны Apache:
`AH01026: ajp_ilink_receive() can't receive header`.

Для решения проблемы размер буфера синхронно увеличивается до 65536 байт (64 КБ).

#### 1. Настройка Tomcat (`conf/server.xml`)

Добавьте параметр `packetSize="65536"` в AJP Connector:

```xml
<Connector port="8009"
           protocol="AJP/1.3"
           address="127.0.0.1"
           secretRequired="true"
           secret="d8f4e2a6b0c1e5d7f9a3b8c2e4a7d1f5"
           packetSize="65536"
           maxThreads="200" />
```

#### 2. Настройка Apache HTTPD

В конфигурации Apache размер буфера задается директивой `ProxyIOBufferSize`:

```apacheconf
# Задается на уровне сервера или внутри <VirtualHost>
ProxyIOBufferSize 65536

<VirtualHost *:80>
    ServerName sso.example.com

    ProxyPass / ajp://127.0.0.1:8009/ secret=d8f4e2a6b0c1e5d7f9a3b8c2e4a7d1f5
    ProxyPassReverse / ajp://127.0.0.1:8009/
</VirtualHost>
```

> [!CAUTION]
> Значение `packetSize` в Tomcat и `ProxyIOBufferSize` в Apache **обязаны быть согласованы**. Если Apache попытается отправить пакет размером 64 КБ на Tomcat с дефолтным буфером 8 КБ, Tomcat разорвет сокет из-за переполнения входящего буфера.

---

### Сценарий 5: Перехват ошибок Tomcat и кастомные страницы (Maintenance Mode)

Когда Tomcat перезагружается, обновляется или падает, пользователи не должны видеть стандартные технические страницы `503 Service Unavailable` или `500 Internal Server Error`. Apache может перехватывать ответы бэкенда и отдавать брендированные страницы обслуживания:

```apacheconf
<VirtualHost *:80>
    ServerName app.example.com

    # Перехват кодов ответов от бэкенда со статусом >= 400
    ProxyErrorOverride On

    # Кастомные страницы ошибок
    ErrorDocument 502 /errors/maintenance.html
    ErrorDocument 503 /errors/maintenance.html
    ErrorDocument 500 /errors/server_error.html

    # Каталог со статическими страницами ошибок (не проксируется)
    Alias /errors/ /var/www/error_pages/
    <Directory "/var/www/error_pages">
        Options -Indexes
        AllowOverride None
        Require all granted
    </Directory>

    ProxyPass /errors/ !
    ProxyPass / ajp://127.0.0.1:8009/ secret=d8f4e2a6b0c1e5d7f9a3b8c2e4a7d1f5 ping=2 timeout=30
    ProxyPassReverse / ajp://127.0.0.1:8009/
</VirtualHost>
```

---

## Операции и команды

### 1. Проверка модулей и синтаксиса Apache

```bash
# Проверка загрузки модулей проксирования AJP
apache2ctl -M | grep -E 'proxy|ajp'
# → proxy_module (shared)
# → proxy_ajp_module (shared)
# → proxy_balancer_module (shared)

# Валидация синтаксиса конфигурационных файлов
apachectl configtest
# → Syntax OK
```

### 2. Инспекция сетевых сокетов и портов

```bash
# Проверка, открыт ли AJP-порт Tomcat и на каком интерфейсе
ss -tulpn | grep 8009
# → tcp   LISTEN 0      100        127.0.0.1:8009       0.0.0.0:*    users:(("java",pid=14820,fd=54))

# Анализ активных постоянных соединений между Apache и Tomcat
ss -tan 'sport = :8009 or dport = :8009'
# → State    Recv-Q Send-Q   Local Address:Port    Peer Address:Port
# → ESTAB    0      0        127.0.0.1:8009        127.0.0.1:48210
# → ESTAB    0      0        127.0.0.1:8009        127.0.0.1:48214
```

### 3. Проверка прохождения запросов и сессий через curl

```bash
# Базовый HTTP-запрос к приложению через Apache
curl -i http://app.example.com/api/health
# → HTTP/1.1 200 OK
# → Date: Mon, 14 Oct 2026 19:30:00 GMT
# → Server: Apache/2.4.62 (Debian)
# → Content-Type: application/json;charset=UTF-8
# → {"status":"UP"}

# Проверка генерации sticky-cookie и последующая фиксация за нодой
curl -i -c /tmp/cookies.txt http://cluster.example.com/login
# → Set-Cookie: JSESSIONID=9D8F1A2C4E5B6.node1; Path=/; HttpOnly

# Повторный запрос с сохранением сессии
curl -i -b /tmp/cookies.txt http://cluster.example.com/profile
# → HTTP/1.1 200 OK
# (Запрос гарантированно направлен на node1)
```

### 4. Мониторинг потоков Tomcat (CLI / Diagnostic)

```bash
# Получение списка потоков AJP через jcmd без перезапуска JVM
jcmd $(pgrep -f "org.apache.catalina.startup.Bootstrap") Thread.print | grep -A 5 "ajp-nio"
# → "ajp-nio-127.0.0.1-8009-exec-1" #32 daemon prio=5 os_prio=0 cpu=12.4ms elapsed=340s tid=0x00007f nid=0x39f8 waiting on condition
# →    java.lang.Thread.State: WAITING (parking)
# →         at jdk.internal.misc.Unsafe.park(java.base@21.0.3/Native Method)
```

### 5. Анализ системных журналов

```bash
# Отслеживание сбоев соединения к AJP в логах Apache
grep -i "ajp" /var/log/apache2/error.log | tail -n 10
# → [Thu Oct 15 10:14:22.102341 2026] [proxy_ajp:error] [pid 1234:tid 5678] (70007)The timeout specified has expired: [client 192.168.1.50:54321] AH01030: ajp_ilink_receive() can't receive header
# → [Thu Oct 15 10:14:22.102390 2026] [proxy_ajp:error] [pid 1234:tid 5678] [client 192.168.1.50:54321] AH00992: ajp_read_header: ajp_ilink_receive failed

# Отслеживание ошибок AJP в каталоге Tomcat
tail -n 20 /opt/tomcat/logs/catalina.out
# → 15-Oct-2026 10:14:22.105 WARNING [ajp-nio-127.0.0.1-8009-exec-3] org.apache.coyote.ajp.AjpProcessor.process An error occurred during request processing
```

---

## Диагностика и устранение неполадок

| Код ошибки / Симптом | Корневая причина | Диагностика | Решение |
|---|---|---|---|
| **503 Service Unavailable**<br>`AH00957: ajp: attempt to connect to 127.0.0.1:8009 failed` | 1. Процесс Tomcat остановлен.<br>2. Порт заблокирован сетевым экраном.<br>3. Коннектор AJP закомментирован в `server.xml`. | `ss -tulpn \| grep 8009`<br>`systemctl status tomcat` | 1. Запустить сервис Tomcat.<br>2. Раскомментировать `<Connector protocol="AJP/1.3">`.<br>3. Проверить правила `iptables`/`nftables`. |
| **400 Bad Request** / **403 Forbidden**<br>`AJP connection rejected` | Несовпадение или отсутствие ключа `secret` между Apache и Tomcat (Ghostcat protection). | В логах Tomcat: `Invalid secret provided`<br>`secretRequired="true"` в `server.xml` | Задать одинаковый секрет: `secret="XYZ"` в `server.xml` и `secret=XYZ` в директиве `ProxyPass` в Apache. |
| **500 Internal Server Error**<br>`AH01026: ajp_ilink_receive() can't receive header` | Заголовок запроса (SPNEGO/Kerberos билет, длинные cookies, JWT) превышает лимит 8 КБ. | В логах Tomcat: `Header block is too large`<br>`tcpdump -X -s 0 port 8009` | Синхронно увеличить буфер: `packetSize="65536"` в `server.xml` и `ProxyIOBufferSize 65536` в Apache. |
| **Сессии "скачут" между серверами**<br>(Потеря авторизации пользователя) | 1. Не задан `jvmRoute` в `server.xml`.<br>2. Значение `route` в `BalancerMember` отличается от `jvmRoute`.<br>3. Cookie перезаписывается приложением. | В браузере проверить значение cookie: `JSESSIONID=...node1`.<br>Проверить `<Engine jvmRoute="...">` | Привести атрибут `jvmRoute="nodeX"` в `server.xml` в точное соответствие с `route=nodeX` в блоке `<Proxy balancer://...>`. |
| **Периодические зависания (Spikes)**<br>`AH01030: ajp_alloc_data_msg: packet size is too small` / `All workers are busy` | Пул потоков Tomcat исчерпан из-за медленных SQL-запросов или блокировок, запросы копятся в `acceptCount`. | `jstack <pid> \| grep -c "ajp-nio"`<br>`ss -lnt '( sport = :8009 )'` (проверка Recv-Q) | 1. Включить `ping=1` в Apache для fail-fast.<br>2. Увеличить `maxThreads` в Tomcat.<br>3. Найти блокирующие потоки через `jstack`. |
| **AJP слушает внешний интерфейс**<br>(Угроза безопасности) | В директиве `<Connector>` опущен параметр `address` или указан `0.0.0.0`. | `ss -lnt \| grep 8009`<br>Показывает `0.0.0.0:8009` или `*:8009` | Добавить `address="127.0.0.1"` (или приватный IP кластера) в `server.xml` и перезапустить Tomcat. |
| **Не перенаправляются 4xx/5xx ошибки**<br>Пользователь видит стек-трейс Tomcat | Директива `ProxyErrorOverride` не включена или перехватывает служебные редиректы. | Проверить ответ сервера при недоступности приложения | Включить `ProxyErrorOverride On` и определить шаблоны `ErrorDocument 502/503`. |

---

## Лучшие практики (DevOps / SRE / Sysadmin)

### 1. Сетевая безопасность и изоляция

* **Принцип минимальной сетевой доступности:** Коннектор AJP никогда не должен быть доступен из публичной сети. При локальном размещении используйте строго `address="127.0.0.1"`. При размещении в кластере биндите коннектор к изолированному VLAN бэкенда и защищайте порт правилами межсетевого экрана хоста.
* **Криптографически стойкий секрет:** Генерируйте уникальный секрет для каждого кластера:
  ```bash
  openssl rand -hex 32
  ```
* **Запуск от непривилегированного пользователя:** Tomcat должен запускаться под выделенным пользователем `tomcat` без доступа к shell (`/usr/sbin/nologin`) с минимальными правами на чтение в директории `conf/` (`chmod 600 server.xml`).

### 2. Отказоустойчивость и параметры надежности (Fail-Fast)

* **Обязательное использование директивы `ping`:** Без параметра `ping=1` или `ping=2` в `ProxyPass` при аварии Tomcat веб-сервер Apache попытается отправить запрос в зависший TCP-сокет и будет ожидать системного таймаута ядра (до 60–120 секунд). Механизм CPing/CPong за 1 секунду определяет факт сбоя бэкенда и немедленно передает запрос резервному серверу (`status=+H`).
* **Конфигурация параметров повтора (`retry`):** Задавайте `retry=5` или `retry=10`. По умолчанию Apache выводит упавший бэкенд из ротации на 60 секунд. Для динамических сред 5–10 секунд обеспечивают более быстрое возвращение бэкенда в строй после рестарта.
* **Таймаут установления соединения (`connectiontimeout`):** Всегда указывайте `connectiontimeout=2` (секунды), чтобы Apache не тратил время на попытки соединения с недоступным сетевым хостом.

### 3. Observability и мониторинг метрик

* **Учет времени ответа бэкенда в логах:** Добавьте в формат `LogFormat` макрос `%D` (время обработки запроса в микросекундах) и `%{ms}T` (в миллисекундах). Это позволяет выявлять деградацию сервлетов до поступления жалоб пользователей.
* **Мониторинг соединений в Prometheus / node_exporter:**
  Настройте мониторинг очередей сокетов через `textfile_collector` или экспортер метрик сокетов (`ss -s`), отслеживая рост состояния `SYN-RECV` и `TIME-WAIT` на порту 8009.
* **Консоль Balancer Manager:** Включите веб-интерфейс `balancer-manager` для ручного перевода узлов в режим обслуживания (`Drain` / `Disabled`) при проведении регламентных работ (Rolling Updates) без остановки всего сервиса.

### 4. Стратегия миграции с AJP на HTTP/1.1 (mod_proxy_http)

Для новых систем и микросервисной архитектуры рекомендуется переходить с AJP на прямой HTTP-прокси (`mod_proxy_http`):

* **Почему стоит мигрировать:** HTTP/1.1 стандартизирован, поддерживает сквозное TLS-шифрование, тривиально отлаживается стандартным `curl`, поддерживается всеми балансировщиками (HAProxy, Envoy) и не имеет проблем с переполнением 8 КБ пакетов.
* **Конфигурация HTTP-проксирования в Apache:**
  ```apacheconf
  ProxyPass / http://127.0.0.1:8080/
  ProxyPassReverse / http://127.0.0.1:8080/
  RequestHeader set X-Forwarded-Proto "https"
  ```
* **Настройка Tomcat для приема HTTP от Apache (`server.xml`):**
  Для корректного определения удаленного IP-клиента и протокола HTTPS в блоке `<Host>` настраивается клапан `RemoteIpValve`:
  ```xml
  <Valve className="org.apache.catalina.valves.RemoteIpValve"
         internalProxies="127\.0\.0\.1|192\.168\.10\.\d+"
         remoteIpHeader="x-forwarded-for"
         protocolHeader="x-forwarded-proto" />
  ```

---

## Дополнительная информация

### Внутренние ссылки базы знаний

* [Балансировка нагрузки в Apache (mod_proxy_balancer)](./apache_load_balancing.md) — алгоритмы балансировки, failover-стратегии, параметры участников кластера.
* [Продвинутое обратное проксирование (mod_proxy)](./apache-reverse-proxy-advanced.md) — переопределение ошибок (`ProxyErrorOverride`), манипуляция cookies и WebSocket.
* [Тюнинг производительности Apache](./apache_performance_tuning.md) — настройка MPM `event`, лимиты `ServerLimit`, `ThreadsPerChild` и параметры TCP-стека Linux.
* [Харденинг и безопасность веб-сервера Apache](./apache_hardening.md) — защита от атак, скрытие баннеров, настройка прав и изоляция модулей.
* [Сборка Apache из исходного кода](./apache-install-from-source.md) — сборка `httpd` с модулями `mod_proxy` и `mod_proxy_ajp`.
* [Миграция конфигураций с Apache на Nginx](../Nginx/Scenarios/nginx-migration-from-apache.md) — перенос правил проксирования сервлетов на Nginx.

### Внешние авторитетные ресурсы

* [Официальная документация Apache HTTP Server: mod_proxy_ajp](https://httpd.apache.org/docs/2.4/mod/mod_proxy_ajp.html)
* [Официальная документация Apache Tomcat: The AJP Connector](https://tomcat.apache.org/tomcat-10.1-doc/config/ajp.html)
* [Уведомление безопасности Apache Tomcat: CVE-2020-1938 (Ghostcat)](https://tomcat.apache.org/security-9.html#Fixed_in_Apache_Tomcat_9.0.31)