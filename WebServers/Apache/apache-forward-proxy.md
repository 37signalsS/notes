# Apache: Прямое проксирование (Forward Proxy) и защита от open proxy

---

## Определения

**Forward Proxy (прямой прокси)** — прокси, устанавливаемый на стороне клиента (или в его сети) и отправляющий исходящие запросы от имени клиента к публичным серверам. Клиент явно указывает прокси в своих настройках.

**Reverse Proxy (обратный прокси)** — прокси, располагающийся перед серверами приложений и принимающий входящие запросы из интернета. Концепции обоих — в [Концепции проксирования](../../Networking/Concepts/proxy.md).

**Open Proxy (открытый прокси)** — неправильно настроенный прокси, доступный всему интернету без аутентификации. Используется злоумышленниками для рассылки спама, скрытия источника атак и обхода лимитов.

**`ProxyRequests`** — директива Apache, включающая/отключающая прямое проксирование. По умолчанию (`Off`) прямое проксирование выключено.

**CONNECT** — HTTP-метод, используемый прокси для установки HTTPS-туннеля (`ProxyRequests` в сочетании с `mod_proxy_connect`).

---

## Основные концепции

### Отличие forward от reverse proxy в Apache

| Аспект | Forward (`ProxyRequests On`) | Reverse (`ProxyPass`) |
|---|---|---|
| Сторона | Клиент/периметр | Перед бэкендами |
| Директива | `ProxyRequests` + `<Proxy *>` | `ProxyPass` / `ProxyPassMatch` / `ProxyFcgi` |
| Какие URL принимает | Абсолютные URL запросов (`GET http://example.com/`) | Относительные пути (`/`) |
| Кто указывает прокси | Клиент (настройки сети/браузера) | Серверная конфигурация |
| Поддержка CONNECT | Да (`mod_proxy_connect`) | Нет |

Forward proxy применим в Apache для: контроля исходящего доступа во внутренней сети, проброса HTTPS через CONNECT, временной фильтрации. Для массового forward-проксирования в продакшене используют выделенные решения (Squid), а не Apache.

### Как включается прямое проксирование

```apacheconf
LoadModule proxy_module modules/mod_proxy.so
LoadModule proxy_connect_module modules/mod_proxy_connect.so

ProxyRequests On
ProxyVia On
```

При `ProxyRequests On` без ограничений Apache превращается в **open proxy** — критическая уязвимость, часто эксплуатируемая для spam/reflection-атак. Поэтому ограничения обязательны.

### Ограничение зоны действия `<Proxy>`

`<Proxy>` ограничивает, кому и куда разрешено проксировать:

```apacheconf
# Разрешить только внутренним сетям
<Proxy *>
    Require ip 10.0.0.0/8 192.168.0.0/16
</Proxy>
```

Директивы внутри `<Proxy>` те же, что и в `<Directory>` (Require, Order, Limit), обрабатываются на фазе проксирования.

### CONNECT и HTTPS

Для запросов `GET https://...` через прокси клиент использует `CONNECT host:443`. После 200-ответа прокси передаёт зашифрованный поток байтов без разбора. Управление доступом к CONNECT:

```apacheconf
<Proxy CONNECT>
    Require ip 10.0.0.0/8
    # или ограничить только HTTPS-портами
    Require expr "req('host') =~ /:[0-9]{1,5}$/"
</Proxy>
```

Открытый CONNECT на произвольные порты позволяет организовать туннелирование наружу (SSH и др.) — ограничивать списком портов или запрещать.

---

## Практические сценарии

### 1. Защищённый forward proxy для внутренней сети

```apacheconf
LoadModule proxy_module modules/mod_proxy.so
LoadModule proxy_connect_module modules/mod_proxy_connect.so

ProxyRequests On

# Только для доверенных клиентов
<Proxy *>
    Require ip 10.0.0.0/8
    Require ip 127.0.0.1
</Proxy>

# Разрешить CONNECT только для стандартного HTTPS-порта
<Proxy CONNECT>
    Require ip 10.0.0.0/8
</Proxy>

# Заголовок Via для трассировки цепочки прокси
ProxyVia On
```

Debian/Ubuntu: `sudo a2enmod proxy proxy_connect; sudo systemctl reload apache2`.

### 2. Forward proxy с аутентификацией (Basic)

```apacheconf
ProxyRequests On

<Proxy *>
    AuthType Basic
    AuthName "Corporate proxy"
    AuthUserFile /etc/httpd/conf.d/proxy.htpasswd
    Require valid-user
</Proxy>
```

Аутентификация обязательна, если прокси доступен вне доверенного периметра.

### 3. Ограничение исходящих ресурсов

Разрешить проксирование только в разрешённый периметр:

```apacheconf
ProxyRequests On

<Proxy *>
    Require ip 10.0.0.0/8
</Proxy>

# Запретить доступ к внутренней IPv4-зоне через прокси (SSRF-защита)
ProxyRequests On
<Proxy "http://169.254.*">
    Require all denied
</Proxy>
```

### 4. Проверка из командной строки

```bash
# Прямой прокси-запрос (абсолютный URL обязателен)
curl -x http://127.0.0.1:3128 http://example.com/ -I
# → HTTP/1.1 200 OK

# HTTPS через CONNECT
curl -x http://127.0.0.1:3128 https://example.com/ -I
# → HTTP/1.1 200 Connection established
```

---

## Операции и команды

| Команда/проверка | Назначение | Пример вывода |
|---|---|---|
| `apache2ctl -M \| grep -i proxy` | Проверка модулей протокол | `proxy_module (shared)`, `proxy_connect_module (shared)` |
| `curl -x http://host:port URL` | Запрос через прокси | `HTTP/1.1 200 OK` |
| `curl -x http://host:port -X CONNECT` | Проверка CONNECT | `HTTP/1.1 200 Connection established` |
| `ss -tnp \| grep :3128` | Активные прокси-соединения | `ESTAB` |

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
|---|---|---|
| `403` при запросе через прокси | `<Proxy *>` с `Require ip` не включает адрес клиента | Добавить сеть/адрес клиента |
| Прокси доступен всему интернету | `ProxyRequests On` без `<Proxy *>`-ограничений и без auth | Запретить `<Proxy *>`-доступ снаружи; добавить аутентификацию |
| `407 Proxy Authentication Required` | Включена Basic-аутентификация, клиент не передаёт креды | Передать `-u user:pass` в curl/настроить клиент |
| HTTPS-запросы не проходят | Не загружен `mod_proxy_connect` | Загрузить модуль, `Require` внутри `<Proxy CONNECT>` |
| Сканер звенит «open proxy» | `ProxyRequests On` глобально, `ProxyVia` выключен, нет ограничений IP | Отключить прямые проксирование целиком или ограничить |
| CONNECT на произвольные порты | Нет ограничения по хосту/порту | `Require expr` на порт или запрет `CONNECT` кроме 443 |

---

## Лучшие практики

1. `ProxyRequests Off` по умолчанию; включать только для реального сценария forward-проксирования и с обязательными `Require ip` + аутентификацией.
2. Open proxy — критическая уязвимость: проверять после изменения через сканер или `curl` извне.
3. Для mass-forward в организации использовать выделенное ПО (Squid) — Apache для этого не оптимизирован.
4. Ограничивать `CONNECT` только стандартными HTTPS-портами, иначе через прокси можно туннелировать произвольный трафик.
5. Сочетать с `mod_remoteip` и логированием, чтобы видеть реальный IP клиентов в логах при доступе через chain прокси.
6. Логировать `Via`-заголовки (`ProxyVia On`) для трассировки.

---

## Дополнительная информация

### См. также

*   [Концепции проксирования](../../Networking/Concepts/proxy.md) — forward/reverse, Squid, open proxy (концепции).
*   [Определение реального IP клиента (mod_remoteip)](./apache_overview.md) — корректный Client IP за цепочкой прокси.
*   [Обратное проксирование: продвинутые сценарии](./apache-reverse-proxy-advanced.md) — `ProxyPassMatch`, cookie-rewrite, gRPC.