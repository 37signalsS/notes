# Apache: Интеграция с Tomcat (AJP, mod_proxy_ajp)

---

## Определения

**Tomcat** — контейнер сервлетов Java (Apache Tomcat), исполняющий JSP/Servlet-приложения. API для внешних серверов называется **Connector**.

**AJP (Apache JServ Protocol, ver. 1.3)** — бинарный протокол передачи запросов между веб-сервером (Apache) и Tomcat. Трафик меньше и «дешевле», чем HTTP, за счёт бинарной кодировки заголовков. Порт по умолчанию — `8009`.

**mod_proxy_ajp** — модуль Apache, реализующий AJP-клиент для проксирования на Tomcat (рекомендуется вместо legacy `mod_jk`).

**mod_jk** — устаревший коннектор Apache↔Tomcat с конфигурацией `workers.properties` и модулем `mod_jk`. Оставлен для legacy-инсталляций.

**jvmRoute** — параметр Tomcat, добавляемый в cookie сессии (`JSESSIONID.имя_узла`) для sticky-балансировки.

**secret / requiredSecret** — аутентификационный ключ AJP-коннектора Tomcat, обязательный в современных версиях для защиты от подделки запросов.

---

## Основные концепции

### Схема развёртывания

```
Client ──► Apache (mod_proxy_ajp) ──AJP──► Tomcat (Connector 8009, jvmRoute=node1)
                                  └──AJP──► Tomcat (Connector 8009, jvmRoute=node2)
```

Apache принимает HTTP, проксирует в Tomcat по AJP. Privilege: Apache обслуживает статику, TLS, балансировку; Tomcat — только сервлеты.

### Зачем AJP, если есть HTTP

Плюсы AJP: компактный бинарный протокол, меньше накладных расходов на заголовки, возможность передавать как атрибуты то, что плохо ложится в HTTP-заголовки (например request attributes). Минусы: закрытый протокол, обязателен secret, сложнее диагностировать. Современные стеки (Spring Boot embedded Tomcat, контейнерные развёртывания) часто используют HTTP/1.1 или HTTP/2 напрямую (`ProxyPass http://`), но большое количество legacy-связок работает именно через AJP.

### Требования к Tomcat (server.xml)

```xml
<Connector port="8009"
           protocol="AJP/1.3"
           address="127.0.0.1"
           secretRequired="true"
           secret="change-me"
           maxThreads="200" />
```

- `address` — обязателен: не слушать на всех интерфейсах (безопасность).
- `secretRequired="true"` (Tomcat 9+) — Apache должен передавать тот же `secret`.

### Sticky-сессии с jvmRoute

```xml
<Engine name="Catalina" defaultHost="localhost" jvmRoute="node1">
```

Apache в sticky-режиме добавляет `route=node1`:

```apacheconf
ProxySet stickysession=JSESSIONID
BalancerMember ajp://10.0.0.11:8009 route=node1
```

Сессия закрепляется за node, чей `jvmRoute` совпадает с суффиксом cookie `JSESSIONID.xxxx.node1`.

---

## Практические сценарии

### 1. Базовое проксирование на один Tomcat

```apacheconf
LoadModule proxy_module modules/mod_proxy.so
LoadModule proxy_ajp_module modules/mod_proxy_ajp.so

<VirtualHost *:80>
    ServerName app.example.com

    # Статику отдаёт Apache
    Alias /static/ /opt/app/static/
    <Directory "/opt/app/static">
        Require all granted
    </Directory>

    # Всё остальное — в Tomcat по AJP
    ProxyPass / ajp://127.0.0.1:8009/
    ProxyPassReverse / ajp://127.0.0.1:8009/
</VirtualHost>
```

Debian/Ubuntu: `sudo a2enmod proxy proxy_ajp`.

### 2. Секрет AJP (Tomcat 9+)

```apacheconf
ProxyPass / ajp://127.0.0.1:8009/ secret=change-me
ProxyPassReverse / ajp://127.0.0.1:8009/
```

Без совпадения `secret` Tomcat отвечает `400 Bad Request` / `503`.

### 3. Балансировка нескольких Tomcat

```apacheconf
<Proxy balancer://tomcat_cluster>
    BalancerMember ajp://10.0.0.11:8009 route=node1 loadfactor=1
    BalancerMember ajp://10.0.0.12:8009 route=node2 loadfactor=1
    BalancerMember ajp://10.0.0.13:8009 status=+H
    ProxySet stickysession=JSESSIONID
    ProxySet lbmethod=byrequests
</Proxy>

ProxyPass / balancer://tomcat_cluster/
ProxyPassReverse / balancer://tomcat_cluster/
```

### 4. AJP через TLS-интерфейс (опционально)

Нативный AJP не шифруется (Tomcat не имеет встроенного AJP-over-TLS). Для шифрования между Apache и Tomcat:
- туннель через SSH/wireguard/VPN на порт 8009 (рекомендуется);
- либо перейти на HTTP (`ProxyPass http://127.0.0.1:8080/`) — проще и безопаснее.

`mod_ssl` на AJP-стороне не используется.

### 5. Проксирование ошибок Tomcat

```apacheconf
# Чтобы на 500/503 отдавались кастомные страницы Apache
ProxyErrorOverride On
ErrorDocument 503 /errors/503.html
```

---

## Операции и команды

| Команда/проверка | Назначение | Пример вывода |
|---|---|---|
| `apache2ctl -M \| grep -i ajp` | Проверка модуля | `proxy_ajp_module (shared)` |
| `ss -tn \| grep :8009` | Соединения к AJP | `ESTAB 10.0.0.11:8009` |
| `curl -I http://localhost/` | Работоспособность | `HTTP/1.1 200 OK` |
| `ss -lnt \| grep 8009` | Открыт ли Connector | `LISTEN 127.0.0.1:8009` |
| `grep -i ajp /var/log/httpd/error_log` | Диагностика subclass | `AH00957: ajp: attempt to connect to ...` |

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
|---|---|---|
| `503 Service Unavailable` | Tomcat не слушает `8009`; `secret` не совпадает | Проверить `ss`, `server.xml`, `secret` в `ProxyPass` |
| `400 Bad Request` от AJP | Tomcat 9+ требует `secretRequired`/`secret` | Добавить `secret=` или настроить Connector |
| Sticky не работает | `jvmRoute` не задан для Engine или `route` не совпадает | Согласовать `jvmRoute` и `route`, проверить `Set-Cookie` |
| AJP отвечает с любого интерфейса | `address` в Connector не задан | `address="127.0.0.1"`, ограничить firewall |
| Периодические тайм-ауты | `timeout`/`ProxyTimeout` меньше времени отработки Tomcat | Увеличить таймауты; проверить `maxThreads` Tomcat |
| `AH01112: get_balancer_member` при балансировке | недоступный участник | См. [Балансировку нагрузки](./apache_load_balancing.md) |

---

## Лучшие практики

1. Tomcat-Connector привязывать к `127.0.0.1` и закрывать порт `8009` на firewall — AJP без secret и с открытым портом = вектором доступа к Java-приложению.
2. Обязателен `secret` (Tomcat 9+) и совпадение с `secret=` в Apache.
3. Для новых проектов рассматривать HTTP/1.1 (`ProxyPass http://127.0.0.1:8080/`) вместо AJP — проще, безопаснее, диагностируется обычными инструментами, поддерживает TLS/HTTP-экспортёр.
4. Sticky: согласовывать `jvmRoute` и `route`, тестировать запросом с cookie `JSESSIONID.xxx.node1` на конкретный узел.
5. Статику отдавать Apache, увеличивая доступность и снимая нагрузку с Tomcat.

---

## Дополнительная информация

### См. также

*   [Балансировка нагрузки (mod_proxy_balancer)](./apache_load_balancing.md) — алгоритмы, sticky, health-проверки.
*   [Обратное проксирование: продвинутые сценарии](./apache-reverse-proxy-advanced.md) — `ProxyErrorOverride`, cookie-rewrite, gRPC.
*   [Сборка Apache из исходного кода](./apache-install-from-source.md) — если требуется собрать `mod_proxy_ajp`/`mod_jk` статически.