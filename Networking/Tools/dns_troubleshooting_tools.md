# Инструменты для диагностики DNS

Для диагностики и отправки запросов к DNS-серверам используются несколько стандартных утилит.

### Сравнение `host`, `dig` и `nslookup` (из видео)

В Linux для работы с DNS, помимо утилиты `nslookup`, можно использовать команды `host` и `dig`. В то время как `nslookup` предустановлена по умолчанию в Windows и часто используется из-за своей распространенности, `host` и `dig` предлагают разные преимущества в Linux:
*   **`host`**: Проста и лаконична. Идеально подходит, если нужен только IP-адрес без лишней диагностической информации, особенно для автоматической обработки результатов.
*   **`dig`**: Мощная и гибкая утилита, предоставляющая максимально полную и детальную информацию о DNS-запросах. Она больше подходит для системных администраторов, которым необходимо глубоко понимать, что происходит в системе доменных имен, и использовать ее для диагностики. Вывод `dig` содержит информацию, аналогичную той, что можно увидеть в Wireshark (заголовки ответа, различные секции DNS-пакета).
*   **`nslookup`**: Удобна для общих запросов, но менее информативна, чем `dig`, и менее лаконична, чем `host`.

## `host`

`host` — простая и быстрая утилита для выполнения DNS-запросов. По умолчанию она запрашивает записи типа `A`, `AAAA` и `MX`.

**Примеры использования:**

*   **Базовый запрос (A, AAAA, MX записи):**
    ```bash
    $ host habr.com
    habr.com has address 178.248.237.227
    habr.com has IPv6 address 2a02:6b8:0:1781::1
    habr.com mail is handled by 10 mx.yandex.net.
    ```
    В этом выводе `host` последовательно запросил A, AAAA и MX записи для домена `habr.com`.

    ```bash
    $ host ya.ru
    ya.ru has address 93.158.134.3
    ya.ru has IPv6 address 2a02:6b8::3
    ya.ru mail is handled by 10 mx.yandex.ru.
    ```
    В этом выводе `host` последовательно запросил A, AAAA и MX записи для домена `ya.ru`.

*   **CNAME запись (псевдоним):**
    ```bash
    $ host www.sazykin.ru
    www.sazykin.ru is an alias for sazykin.ru.
    sazykin.ru has address 178.248.237.227
    sazykin.ru has IPv6 address 2a02:6b8:0:1781::1
    ```
    Здесь `host` сначала определила псевдоним `www.sazykin.ru` для `sazykin.ru`, а затем IP-адреса для канонического имени `sazykin.ru`.

*   **Запрос конкретного типа записи (NS):**
    ```bash
    $ host -t NS habr.com
    habr.com name server ns1.yandex.net.
    habr.com name server ns2.yandex.net.
    ```
    Таким образом, вывод команды `host` более лаконичный, чем команды `nslookup`.

**Более подробный вывод (`-v`):****
```bash
$ host -v ya.ru
Trying "ya.ru"
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 56193
;; flags: qr rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 0

;; QUESTION SECTION:
;ya.ru.				IN	A

;; ANSWER SECTION:
ya.ru.			133	IN	A	93.158.134.3

Received 40 bytes from 127.0.0.53#53 in 11 ms
Trying "ya.ru"
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 56193
;; flags: qr rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 0

;; QUESTION SECTION:
;ya.ru.				IN	AAAA

;; ANSWER SECTION:
ya.ru.			285	IN	AAAA	2a02:6b8::3

Received 52 bytes from 127.0.0.53#53 in 11 ms
Trying "ya.ru"
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 56193
;; flags: qr rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 0

;; QUESTION SECTION:
;ya.ru.				IN	MX

;; ANSWER SECTION:
ya.ru.			3599	IN	MX	10 mx.yandex.ru.

Received 59 bytes from 127.0.0.53#53 in 9 ms
```
Флаг `-v` (verbose) показывает детали каждого запроса и ответа, включая секции вопроса и ответа.

## `dig`

`dig` (Domain Information Groper) — более мощная и гибкая утилита, предоставляющая подробную информацию о DNS-запросах. Она популярна среди системных администраторов за полноту выводимой информации. Вывод `dig` содержит гораздо больше диагностической информации, чем `host` и `nslookup`, и поэтому больше подходит для понимания того, что происходит в системе доменных имён, и для диагностики.

**Пример использования:**
По умолчанию `dig` запрашивает только `A`-запись.
```bash
$ dig habr.com

; <<>> DiG 9.16.1-Ubuntu <<>> habr.com
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 29880
;; flags: qr rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 1

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 65494
;; QUESTION SECTION:
;habr.com.				IN	A

;; ANSWER SECTION:
habr.com.			235	IN	A	178.248.237.227

;; Query time: 10 msec
;; SERVER: 127.0.0.53#53(127.0.0.53)
;; WHEN: Fri Nov 21 12:30:00 UTC 2025
;; MSG SIZE  rcvd: 50
```
Вывод `dig` разделен на секции, что соответствует структуре DNS-пакета:
-   **HEADER:** Техническая информация о запросе и ответе (например, флаги `qr`, `rd`, `ra` и `status: NOERROR`).
-   **QUESTION SECTION:** Какой вопрос был задан (доменное имя, класс записи `IN`, тип записи `A`).
-   **ANSWER SECTION:** Полученный ответ (доменное имя, TTL, класс, тип и IP-адрес).
-   **ADDITIONAL SECTION:** Дополнительная информация, которая может быть полезна.
-   **Статистика:** Время выполнения запроса, использованный DNS-сервер и протокол транспортного уровня (например, UDP).

**Пример запроса NS-записей с дополнительной информацией:**
При запросе серверов имен для доменной зоны `dig` часто возвращает также их IP-адреса в секции `ADDITIONAL SECTION`, чтобы избежать дополнительных запросов.
```bash
$ dig yandex.ru NS

; <<>> DiG 9.16.1-Ubuntu <<>> yandex.ru NS
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 56193
;; flags: qr rd ra; QUERY: 1, ANSWER: 2, AUTHORITY: 0, ADDITIONAL: 5

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 65494
;; QUESTION SECTION:
;yandex.ru.				IN	NS

;; ANSWER SECTION:
yandex.ru.			345600	IN	NS	ns1.yandex.ru.
yandex.ru.			345600	IN	NS	ns2.yandex.ru.

;; ADDITIONAL SECTION:
ns1.yandex.ru.		345600	IN	A	213.180.193.1
ns1.yandex.ru.		345600	IN	AAAA	2a02:6b8::1
ns2.yandex.ru.		345600	IN	A	93.158.134.1
ns2.yandex.ru.		345600	IN	AAAA	2a02:6b8::2

;; Query time: 10 msec
;; SERVER: 127.0.0.53#53(127.0.0.53)
;; WHEN: Fri Nov 21 12:30:00 UTC 2025
;; MSG SIZE  rcvd: 198
```
Здесь в `ANSWER SECTION` мы видим два NS-сервера для `yandex.ru`, а в `ADDITIONAL SECTION` сразу представлены их A и AAAA записи, что избавляет от необходимости делать дополнительные запросы.

**Запрос конкретного типа записи:**
```bash
# Запросить MX-запись
dig ya.ru MX

# Запросить AAAA-запись
dig ya.ru AAAA
```

**Трассировка запроса (`+trace`):**
Флаг `+trace` позволяет увидеть весь путь рекурсивного запроса, начиная от корневых серверов. Это чрезвычайно полезно для диагностики проблем с делегированием домена.
```bash
$ dig ya.ru +trace

; <<>> DiG 9.16.1-Ubuntu <<>> ya.ru +trace
;; global options: +cmd
.			515325	IN	NS	a.root-servers.net.
.			515325	IN	NS	b.root-servers.net.
... (11 more root servers) ...
;; Received 239 bytes from 127.0.0.53#53(127.0.0.53) in 42 ms

ru.			172800	IN	NS	a.dns.ripn.net.
ru.			172800	IN	NS	b.dns.ripn.net.
... (4 more ru servers) ...
;; Received 447 bytes from 192.36.148.17#53(i.root-servers.net) in 5 ms

yandex.ru.		345600	IN	NS	ns1.yandex.ru.
yandex.ru.		345600	IN	NS	ns2.yandex.ru.
;; Received 104 bytes from 194.85.252.62#53(d.dns.ripn.net) in 10 ms

ya.ru.			3600	IN	A	93.158.134.3
;; Received 50 bytes from 213.180.193.1#53(ns1.yandex.ru) in 5 ms
```

## `nslookup`

`nslookup` — одна из старейших утилит для DNS-запросов, доступна как в Linux, так и в Windows. Считается менее предпочтительной в Linux по сравнению с `dig` и `host`, но все еще широко используется.

**Пример использования:**
```bash
$ nslookup ya.ru
Server:		127.0.0.53
Address:	127.0.0.53#53

Non-authoritative answer:
Name:	ya.ru
Address: 93.158.134.3
Name:	ya.ru
Address: 2a02:6b8::3
```

`nslookup` также имеет интерактивный режим, который можно запустить, вызвав команду без аргументов.
