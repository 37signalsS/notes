# Apache: Балансировка нагрузки (mod_proxy_balancer)

---

## Определения

**mod_proxy_balancer** — модуль Apache (начиная с 2.2), реализующий балансировку трафика между несколькими backend-серверами в рамках обратного проксирования. Работает совместно с `mod_proxy`, `mod_proxy_http` и `mod_proxy_fcgi`.

**Balancer** — логическая группа из `BalancerMember` (backend-ов), к которым Apache распределяет входящие запросы через специальный URL `balancer://имя`.

**`mod_lbmethod_*`** — модули, реализующие алгоритмы выбора backend: `byrequests` (по количеству запросов), `bytraffic` (по объёму трафика), `bybusyness` (по количеству активных соединений).

**Sticky Session (прилипание сессии)** — механизм привязки запросов клиента к одному backend на время сессии (cookie или параметр маршрута).

---

## Основные концепции

### Архитектура

```
Client ──► Apache (mod_proxy_balancer)
              │ balancer://webcluster
              ├──► backend1:8080 (node1, loadfactor=1)
              ├──► backend2:8080 (node2, loadfactor=2)
              └──► backend3:8080 (node3, status=+H — hot standby)
```

Apache выполняет роль L7-балансировщика: принимает соединения, выбирает backend по алгоритму, проксирует HTTP(S)/FCGI-запрос и обрабатывает сбои.

### Алгоритмы выбора (lbmethod)

| Метод | Модуль | Принцип | Применение |
|---|---|---|---|
| `byrequests` | `mod_lbmethod_byrequests` (по умолчанию) | Ротация с учётом `loadfactor` | Равное распределение запросов |
| `bytraffic` | `mod_lbmethod_bytraffic` | Ротация с учётом размера ответов | Backend с разной производительностью |
| `bybusyness` | `mod_lbmethod_bybusyness` | Выбор наименее загруженного (`mod_status`) | Долгие/тяжёлые запросы |
| `heartbeat` | `mod_lbmethod_heartbeat` | Выбор по здоровью из `Heartbeat` | Продвинутые сценарии HA |

**`loadfactor`** — весовой коэффициент (целое число, по умолчанию 1). Распределение между членами `a` и `b` с `loadfactor=1` и `2` — примерно 33%/66% (для byrequests/bytraffic).

### Статусы backend и failover

| Статус | Значение |
|---|---|
| `+H` (Hot Standby) | Участник используется только если все остальные недоступны |
| `+I` (Initialized/On) | Участник включён |
| `+D` (Disabled) | Вручную отключён (balancer-manager) |
| `+S` (Stopped) | Вручную остановлен (balancer-manager) |
| `+E` (Error) | Ошибка при последней попытке; на ретрае через `retry` |

**Ключевые параметры `BalancerMember`/`ProxySet`:** `loadfactor`, `route`, `status`, `failonstatus`, `retry` (сек., по умолчанию 60), `maxattempts`, `timeout`, `connectiontimeout`, `ping`.

### Sticky Sessions

Задаётся через `ProxySet stickysession=<параметр>`:

```apacheconf
ProxySet stickysession=JSESSIONID
```

*   `JSESSIONID` может быть cookie или query-параметром, разделитель `|`: `stickysession=JSESSIONID|jsessionid`.
*   При `route=node1` у `BalancerMember` Apache понимает, что значение `node1` в конце cookie (после `.`) принадлежит данному члену, и направляет запрос на него.
*   Cookie выставляется backend-приложением; Apache не создаёт cookie автоматически.
*   Ограничение: если backend с роутом недоступен, запрос уйдёт на другой backend (при отсутствии «второго» члена с тем же роутом).

---

## Практические сценарии

### 1. Базовая балансировка с health-проверкой

```apacheconf
LoadModule proxy_module modules/mod_proxy.so
LoadModule proxy_balancer_module modules/mod_proxy_balancer.so
LoadModule proxy_http_module modules/mod_proxy_http.so

<Proxy balancer://webcluster>
    BalancerMember http://10.0.0.11:8080 loadfactor=1 route=node1
    BalancerMember http://10.0.0.12:8080 loadfactor=2 route=node2
    BalancerMember http://10.0.0.13:8080 status=+H
    ProxySet lbmethod=byrequests
    ProxySet stickysession=JSESSIONID
    ProxySet failonstatus=500,502,503
    ProxySet retry=5 maxattempts=5 timeout=30
</Proxy>

ProxyPass / balancer://webcluster/
ProxyPassReverse / balancer://webcluster/
```

**Включение модулей (Debian/Ubuntu):**
```bash
sudo a2enmod proxy proxy_balancer proxy_http lbmethod_byrequests lbmethod_bytraffic
sudo systemctl reload apache2
```

### 2. Failover на резерв (Hot Standby)

`status=+H` гарантирует, что standby-сервер получает трафик только при недоступности всех активных членов — удобно для аварийного сервера, который не должен деградировать под нагрузкой.

```apacheconf
BalancerMember http://10.0.0.11:8080
BalancerMember http://10.0.0.12:8080
BalancerMember http://10.0.0.13:8080 status=+H   # DR / резерв
```

### 3. Прокси с TLS (haproxy-стиль терминации + backend по HTTPS)

```apacheconf
ProxyPass /secure-pool/ https://backend-notls.example.internal/
ProxyPassReverse /secure-pool/ https://backend-notls.example.internal/

SSLProxyEngine on
SSLProxyCACertificateFile /etc/pki/tls/certs/internal-ca.pem
ProxySSLVerify require
```

`SSLProxyCACertificateFile`/`SSLProxyCACertificatePath` — доверие к сертификату backend. Для лёгкого распространения trusts можно ограничить проверку (`ProxySSLVerify*`).

### 4. Active health checks (mod_proxy_hcheck)

Модуль `mod_proxy_hcheck` (доступен с Apache 2.4.31) выполняет периодические проверки независимо от трафика:

```apacheconf
ProxyHCMethod GET
ProxyHCExpr pong {%{REQUEST_STATUS} =~ /^[234][0-9][0-9]$/}
ProxyHCExpr slow {%{REQUEST_STATUS} =~ /^(5|503)/}

<Proxy balancer://webcluster>
    BalancerMember http://10.0.0.11:8080 hcmethod=GET hcexpr=pong hcuri=/healthz hcinterval=10
    BalancerMember http://10.0.0.12:8080 hcmethod=GET hcexpr=pong hcuri=/healthz hcinterval=10
</Proxy>
```

*   `hcmethod`, `hcuri`, `hcinterval`, `hcexpr` — параметры проверки для участника.
*   При несоответствии `hcexpr` участник помечается недоступным; запросы уходят на здоровые.

### 5. Drift-контроль и оперативный статус (balancer-manager)

```apacheconf
<Location "/balancer-manager">
    SetHandler balancer-manager
    Require ip 10.0.0.0/8
    Require ip 127.0.0.1
</Location>
```

Доступ: `curl http://localhost/balancer-manager`. Страница показывает состояние всех balancer-ов, статусы участников, `LoadFactor`, `Route`, `BusyWorkers` и позволяет отключать/включать членов без перезапуска Apache.

### 6. Смена алгоритма и «мягкая» остановка

```bash
# Применить новую конфигурацию без разрыва соединений
sudo apachectl graceful
# или
sudo systemctl reload httpd

# Проверить активный модуль
apache2ctl -M | grep balancer
```

### 7. Балансировка PHP-FPM пулов (FCGI)

```apacheconf
<Proxy balancer://phpcluster>
    BalancerMember fcgi://127.0.0.1:9000 loadfactor=2
    BalancerMember fcgi://127.0.0.1:9001 loadfactor=1
    ProxySet lbmethod=byrequests
</Proxy>

<FilesMatch \.php$>
    SetHandler "proxy:balancer://phpcluster"
</FilesMatch>
```

`mod_proxy_fcgi` принимает `fcgi://` участников; между пулами PHP-FPM работает ротация по весам `loadfactor`.

### 8. Балансировка Tomcat по AJP

Tomcat-кластер балансируется так же, но через нативный AJP-протокол (порт 8009) и `route` в `jvmRoute`. Подробности протокола, `secret` и sticky-роуты — в [AJP-интеграции Tomcat](./apache-tomcat-ajp.md), здесь только схема:

```apacheconf
LoadModule proxy_ajp_module modules/mod_proxy_ajp.so

<Proxy balancer://tomcat>
    BalancerMember ajp://10.0.0.21:8009 route=tomcat1
    BalancerMember ajp://10.0.0.22:8009 route=tomcat2
    BalancerMember ajp://10.0.0.23:8009 status=+H
    ProxySet lbmethod=bytraffic
    ProxySet stickysession=JSESSIONID
    ProxySet timeout=30 retry=5
</Proxy>

ProxyPass /app balancer://tomcat/
ProxyPassReverse /app balancer://tomcat/
```

`jsessionid` на физические серверы маппится через `route` (`tomcat1`/`tomcat2`), а `status=+H` — резерв. Проверка накопителя: `curl http://localhost/balancer-manager`.

### 9. Сквозные сессии через mod_authn_dbd/mod_session (backend-агностично)

Apache сам ведёт сессию (см. [Аутентификация: mod_session](./apache_authentication.md)), что упрощает sticky-less балансировку приложений без собственных session-функций:

```apacheconf
LoadModule session_module modules/mod_session.so
LoadModule session_crypto_module modules/mod_session_crypto.so

Session On
SessionCryptoPassphrase top-secret
SessionCookieName session path=/; HttpOnly; Secure

# Тогда достаточно любого backend — сессия живёт в cookie Apache
ProxyPass / balancer://webcluster/
```

---

## Операции и команды

| Команда/проверка | Назначение | Пример вывода |
|---|---|---|
| `apache2ctl -M \| grep -i balancer` | Проверка модулей балансировки | `proxy_balancer_module (shared)` |
| `curl http://localhost/server-status?auto` | Нагрузка и статусы | `BusyWorkers: 4` |
| `curl http://localhost/balancer-manager` | Состояние участников | `E|P|I|H` статусы |
| `ss -tnp \| grep :8080` | Активные соединения к backend | `ESTAB` на 10.0.0.11:8080 |
| `grep -i "proxy_balancer" /var/log/httpd/error_log` | Диагностика подсистемы | `AH01112: get_balancer_member` |

**Проверка принадлежности клиента к маршруту (sticky):**
```bash
# Запрос с cookie сессии — определить, на какой backend ушёл запрос
curl -sI -H "Cookie: JSESSIONID=abc123.node1" -H "Host: app.example.com" http://localhost/
# → ответ приходит от сервера с route=node1

# Без cookie — ротация по lbmethod
curl -s -o /dev/null -w "%{http_code}\n" -H "Host: app.example.com" http://localhost/
# → 200
```

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
|---|---|---|
| `503 Service Unavailable` для всех запросов | Все участники помечены недоступными (`E`), или `retry` не позволяет восстановить | Проверить `balancer-manager` (статусы `E`), логи бэкенда, `connectiontimeout` |
| Неравномерное распределение | `lbmethod=byrequests` не учитывает вес при `loadfactor`, sticky sessions перекрывают ротацию | Проверить `loadfactor`, включить `bytraffic`/`bybusyness`, выключить sticky для healthcheck |
| Sticky не работает | `route` не совпадает с суффиксом cookie; cookie не от имени backend | Согласовать `route` и формат cookie, проверить `Set-Cookie` через `curl -I` |
| Долгие ответы / таймауты | `timeout` меньше времени обработки бэкенда | Увеличить `timeout`/`maxattempts`; проверить `ProxyTimeout` |
| Backend не восстанавливается | `retry` завышен; запросы не попадают на health-проверку | Уменьшить `retry`; настроить `mod_proxy_hcheck` с `hcinterval` |
| Алерт cascading failure при отключении standby | «Горячий резерв» не перехватывает трафик при частичном сбое | `+H` перехватывает только при полном недоступности; использовать стоимость failonstatus или отдельный balancer |

---

## Лучшие практики

1.  Всегда задавать `stickysession` явно и согласовывать `route` с backend-приложением.
2.  Health checks выносить из «глазных» проверок (`hcuri=/healthz`), не в основной endpoint.
3.  Для долгих запросов (SSE, WebSocket) — рассматривать отдельный balancer или проксирование без балансировки.
4.  Резервирование: `status=+H` — для DR-серверов, а не для масштабирования.
5.  Мониторить состояние через `balancer-manager`/`mod_status` и алерты Prometheus на `apache_*` метрики.
6.  Директива `ProxySet` изменяется через `apachectl graceful` (без прерывания сессий).

---

## Дополнительная информация

### См. также

*   [Обзор и концепции балансировки Nginx](../Nginx/Proxy/Load_Balancing/overview_concepts.md) — алгоритмы, health checks, зоны в сравнении.
*   [Балансировка HTTP в Angie](../Angie/angie_http_load_balancing.md) — нативная балансировка Angie.
*   [AJP-интеграция Tomcat](./apache-tomcat-ajp.md) — протокол AJP13, secret, jvmRoute.
*   [Обратное проксирование: продвинутые сценарии](./apache-reverse-proxy-advanced.md) — ProxyPassMatch, cookie-rewrite, ProxyErrorOverride.
*   [Аутентификация: mod_session](./apache_authentication.md) — сессии Apache (crypto/dbd) для sticky-less балансировки.
*   [Обзор Apache](./apache_overview.md) — обратное проксирование, SSL-терминация, модули proxy.