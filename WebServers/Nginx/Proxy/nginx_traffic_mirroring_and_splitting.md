# Разделение трафика (Canary / split_clients) и теневое зеркалирование (mirror) в Nginx

**Актуально для:** Nginx 1.26+ (OSS/Plus) / Angie 1.6+

---

## 0. Декларация перекрытия (Overlap Declaration)

Настоящий документ является единым источником правды (SSoT) по механизмам управляемого разделения трафика (Canary, A/B) и зеркалирования запросов на уровне L7 Reverse Proxy в Nginx:
- [CI-CD/Deployment_Strategies/canary_deployment.md](../../../CI-CD/Deployment_Strategies/canary_deployment.md) — рассматривает Canary как общую методологию релиз-инженерии (метрики SLO/SLI, стадии раскатки в Kubernetes, Argo Rollouts), не углубляясь в конфигурирование модулей Nginx.
- [Load_Balancing/algorithms.md](./Load_Balancing/algorithms.md) — описывает базовые алгоритмы балансировки (round-robin, least_conn, hash, ip_hash), но не охватывает детерминированное процентное разделение аудитории на базе MurmurHash2.
- [nginx_reverse_proxy_core.md](./nginx_reverse_proxy_core.md) — описывает ядро HTTP-проксирования (`proxy_pass`, заголовки, таймауты).
- [WebServers/Angie/angie-traffic-mirroring.md](../../Angie/angie-traffic-mirroring.md) — рассматривает специфику веб-сервера Angie.

---

## 1. Определения

- **Canary Deployment (Канареечный релиз)** — стратегия развертывания, при которой новая версия приложения («канарейка») выкатывается на изолированный пул серверов, куда направляется строго ограниченная доля пользовательского трафика (например, 1–5%) для валидации стабильности перед полной раскаткой.
- **Модуль `ngx_http_split_clients_module`** — встроенный модуль Nginx, реализующий детерминированное процентное распределение клиентских запросов на основе 32-битного алгоритма хеширования MurmurHash2.
- **Детерминизм разделения трафика** — свойство алгоритма хеширования, гарантирующее, что при неизменном входном ключе (IP-адрес, cookie сессии или токен) пользователь всегда попадает в одну и ту же группу (версию приложения), исключая "дребезг" интерфейса.
- **Traffic Shadowing / Mirroring (Теневое зеркалирование)** — механизм дублирования реального входящего продакшен-трафика на тестовый или канареечный стенд в фоновом режиме. Ответы от теневого сервиса отбрасываются и не влияют на клиентский сеанс.
- **Модуль `ngx_http_mirror_module`** — встроенный модуль Nginx (начиная с 1.13.4), создающий внутренние неблокирующие подзапросы (subrequests) на фазе `NGX_HTTP_PRECONTENT_PHASE` для отправки копий запроса на заданные URI.
- **Dark Traffic (Темный трафик)** — запросы, отправляемые теневому бэкенду без ведома и участия пользователя для нагрузочного тестирования, профилирования и верификации совместимости новой кодовой базы.

---

## 2. Основные концепции и архитектура

### 2.1 Архитектура процентного разделения аудитории (`split_clients`)

Модуль `split_clients` работает в фазе вычисления переменных:

```text
Входящий запрос
       │
       ▼
Строка ключа: "${remote_addr}${http_user_agent}"
       │
       ▼
Алгоритм MurmurHash2 (32-bit hash)
       │
       ▼
Проекция на шкалу: [0 ... 4 294 967 295] ──► [0.0% ... 100.0%]
       │
  ┌────┴─────────────────────────────┐
  ▼                                  ▼
[0.0% — 5.0%]                 [5.0% — 100.0%]
  │                                  │
$upstream_group = "canary_pool"   $upstream_group = "stable_pool"
```

1. **Принцип работы MurmurHash2:**  
   Nginx вычисляет 32-битный хэш от переданной строки. Полученное число делится на максимальное значение $2^{32}-1$, давая процентную долю.
2. **Выбор ключа хеширования:**
   * `$remote_addr` — клиенты делятся по IP. **Подводный камень:** Пользователи за крупным корпоративным NAT имеют один IP и всей группой попадают либо на Stable, либо на Canary.
   * `"${remote_addr}${http_user_agent}"` — снижает эффект NAT за счет учета версии браузера.
   * `"$cookie_session_id"` или `"$cookie_uid"` — эталонный вариант для Web/SaaS: конкретный авторизованный пользователь всегда видит одну и ту же версию системы.
   * `"$request_id"` — случайное распределение каждого отдельного HTTP-запроса (подходит для чистых REST API без состояния, но не для UI).

---

### 2.2 Архитектура теневого зеркалирования (`mirror`)

Модуль `mirror` интегрирован в фазу ядра `NGX_HTTP_PRECONTENT_PHASE`:

```text
Клиентский запрос ──► Nginx
                        │
      ┌─────────────────┴─────────────────┐
      │ (Основной запрос)                 │ (Асинхронный подзапрос)
      ▼                                   ▼
 [Stable Upstream]                 [Shadow Upstream]
      │                                   │
      ▼                                   ▼
 HTTP 200 OK                       Ответ игнорируется
      │                            (буфер ответа отбрасывается)
      ▼                                   │
Клиент получает ответ                     X
```

1. **Неблокирующая природа подзапроса:**  
   Nginx форсирует дублирование запроса через `ngx_http_subrequest`. Воркер передает тело запроса в теневой локейшен асинхронно в цикле обработки событий `epoll`.
2. **Игнорирование ответов:**  
   Любые коды ответа от теневого бэкенда (`200`, `500`, `502`) полностью игнорируются Nginx и никогда не передаются клиенту. Клиент получает исключительно ответ от основного бэкенда.
3. **Обработка тела запроса (`mirror_request_body`):**  
   По умолчанию директива `mirror_request_body on;` активна. Тело POST/PUT запросов считывается в буфер памяти/диска и передается как на основной, так и на теневой сервер.
4. **Критическое предостережение SRE (Идемпотентность и безопасность):**  
   Зеркалирование методов `POST`, `PUT`, `DELETE` на теневой бэкенд, подключенный к продакшен-базе данных или внешним платежным шлюзам, приведет к **дублированию реальных транзакций и порче данных**. Теневой стенд обязан использовать изолированную БД (mock/sandbox).

---

## 3. Практические сценарии и конфигурация

### Сценарий 1: Детерминированный Canary-релиз (95% Stable / 5% Canary) с переопределением через Cookie/Header

Архитектура:
- 5% пользователей попадают на Canary по хэшу Cookie;
- Внутренние разработчики и QA попадают на Canary принудительно при наличии заголовка `X-Environment: canary` или cookie `canary=true`;
- При падении Canary трафик автоматически сбрасывается на Stable.

```nginx
# /etc/nginx/conf.d/canary.conf
upstream backend_stable {
    server 10.0.1.11:8080 max_fails=3 fail_timeout=10s;
    server 10.0.1.12:8080 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

upstream backend_canary {
    server 10.0.2.11:8080 max_fails=2 fail_timeout=5s;
    keepalive 16;
}

# 1. Процентное разделение аудитории (5% на canary)
split_clients "${cookie_session_id}${remote_addr}" $split_upstream {
    5.0%    backend_canary;
    *       backend_stable;
}

# 2. Переопределение для QA/разработчиков через заголовок или cookie
map $http_x_environment $env_override {
    "canary" backend_canary;
    default  "";
}

map $cookie_qa_override $qa_override {
    "true"   backend_canary;
    default  "";
}

# 3. Финальный выбор целевого апстрима
map "$env_override:$qa_override" $final_upstream {
    "backend_canary:"       backend_canary;
    ":backend_canary"       backend_canary;
    "backend_canary:backend_canary" backend_canary;
    default                 $split_upstream;
}

server {
    listen 80;
    server_name service.company.com;

    location / {
        include proxy_params;
        
        # Динамическая маршрутизация на выбранный пул
        proxy_pass http://$final_upstream;

        # Автоматический откат на Stable при падении Canary узла
        proxy_next_upstream error timeout http_502 http_503;
        proxy_next_upstream_tries 2;

        # Передача клиенту информации о версии обслуживания
        add_header X-Served-By $upstream_addr always;
    }
}
```

---

### Сценарий 2: Полнофункциональное теневое зеркалирование трафика (`mirror`)

Дублирование всех входящих запросов на стенд профилирования:

```nginx
# /etc/nginx/conf.d/shadowing.conf
upstream production_api {
    server 10.0.1.20:8000;
    keepalive 32;
}

upstream shadow_profiler {
    server 10.0.99.50:8000;
    keepalive 16;
}

server {
    listen 80;
    server_name api.company.com;

    location / {
        # Активация зеркалирования в служебный location
        mirror /mirror_traffic;
        mirror_request_body on;

        include proxy_params;
        proxy_pass http://production_api;
    }

    # Служебный внутренний блок для отправки копии запроса
    location = /mirror_traffic {
        internal;

        include proxy_params;
        proxy_pass http://shadow_profiler$request_uri;

        # Защита от деградации основного сайта:
        # Жесткие короткие таймауты, чтобы зависший теневой стенд не удерживал сокеты
        proxy_connect_timeout 500ms;
        proxy_read_timeout    1s;
        proxy_send_timeout    1s;

        # Изоляция буферов
        proxy_buffering off;
    }
}
```

---

### Сценарий 3: Сэмплированное (процентное) зеркалирование трафика

Для высоконагруженных систем отправка 100% копий трафика экономически нецелесообразна и способна перегрузить тестовую инфраструктуру.  
Решение: дублирование строго **10%** запросов с помощью связки `split_clients` и `mirror`:

```nginx
# /etc/nginx/conf.d/sampled_mirror.conf
upstream prod_backend {
    server 10.0.1.10:8080;
    keepalive 32;
}

upstream test_perf_cluster {
    server 10.0.99.10:8080;
    keepalive 16;
}

# 10% запросов получают значение URI зеркала, 90% получают пустую строку (зеркалирование отключено)
split_clients $request_id $mirror_destination {
    10.0%   /internal_sampled_mirror;
    *       "";
}

server {
    listen 80;
    server_name highload.company.com;

    location / {
        # Если переменная пустая, Nginx не выполняет подзапрос
        mirror $mirror_destination;
        mirror_request_body on;

        include proxy_params;
        proxy_pass http://prod_backend;
    }

    location = /internal_sampled_mirror {
        internal;
        include proxy_params;
        proxy_pass http://test_perf_cluster$request_uri;

        proxy_connect_timeout 300ms;
        proxy_read_timeout    500ms;
    }
}
```

---

## 4. Операции и команды

### 1. Статистическая верификация процентного разделения `split_clients`

Проверка равномерности распределения 5% канарейки с помощью цикла запросов с разными IP:

```bash
# Генерация 100 запросов с подменой X-Forwarded-For и подсчет распределения
for i in $(seq 1 100); do
    curl -sI -H "X-Forwarded-For: 198.51.100.$i" http://service.company.com/ | grep -i "x-served-by"
done | sort | uniq -c
# → 95 X-Served-By: 10.0.1.11:8080
# →  5 X-Served-By: 10.0.2.11:8080
```

### 2. Проверка работы теневого зеркалирования (`mirror`)

```bash
# 1. Отправка тестового POST-запроса на основной сервер
curl -X POST -H "Content-Type: application/json" -d '{"event":"checkout","amount":100}' \
     http://api.company.com/api/order
# → HTTP/1.1 200 OK {"status":"success"}

# 2. Проверка access-лога на стороне теневого бэкенда (10.0.99.50)
ssh admin@10.0.99.50 "tail -n 1 /var/log/app/access.log"
# → [17/Oct/2026:21:25:01] "POST /api/order HTTP/1.1" 200 124 "api.company.com"
```

---

## 5. Устранение неполадок (Troubleshooting)

| Симптом | Вероятная причина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **Canary вообще не получает трафик** | Ключ `split_clients` привязан к `$remote_addr`, но весь трафик идет через внешний шлюз/балансировщик | Просмотр `$remote_addr` в access.log (один и тот же IP) | Подключить модуль `real_ip` или сменить ключ на `$cookie_session_id` / `$request_id` |
| **Пользователя постоянно "перекидывает" между версиями** | В ключе `split_clients` используется псевдослучайная переменная (`$request_id`, `$msec`) | Проверка конфига блока `split_clients` | Использовать стабильный идентификатор: `$cookie_user_id` или `"${remote_addr}${http_user_agent}"` |
| **Рост latency и исчерпание памяти при включении `mirror`** | Теневой бэкенд завис или отвечает крайне медленно, воркеры удерживают сокеты | Метрика `$upstream_response_time` в служебном локейшене зеркала | Выставить жесткие таймауты: `proxy_connect_timeout 300ms; proxy_read_timeout 500ms;` |
| **Тело POST-запроса не доходит до теневого бэкенда** | Директива `mirror_request_body` отключена или переопределена | В логе теневого бэкенда запрос приходит с `Content-Length: 0` | Явно объявить `mirror_request_body on;` в блоке `location` |

---

## 6. Лучшие практики (Best Practices)

1. **Никогда не зеркалируйте боевой трафик на тестовый стенд с продакшен-БД:** Модуль `mirror` отправляет точные копии HTTP-запросов, включая операции модификации данных. Тестовый бэкенд обязан быть полностью изолирован.
2. **Всегда изолируйте таймауты в блоке `mirror`:** Сбой теневого сервиса ни при каких обстоятельствах не должен сказываться на пользователях. Устанавливайте таймауты подключения не более 500 мс.
3. **Используйте Fallback при Canary:** При динамической маршрутизации на канареечный узел всегда конфигурируйте `proxy_next_upstream`, чтобы отказ канарейки прозрачно перенаправлял клиента на стабильный кластер.
4. **Комбинируйте `split_clients` с `map`:** Всегда оставляйте инженерным командам возможность принудительного перехода на нужную версию через HTTP-заголовки или куки.

---

## 7. Дополнительная информация

### Внутренние ссылки
- [Архитектура и ядро HTTP Reverse Proxy](./nginx_reverse_proxy_core.md) — базовые директивы `proxy_pass`, заголовки и таймауты.
- [Алгоритмы балансировки нагрузки](./Load_Balancing/algorithms.md) — round-robin, least_conn, generic hash.
- [Стратегии канареечного развертывания](../../../CI-CD/Deployment_Strategies/canary_deployment.md) — методология Canary, метрики Prometheus, канареечные фазы.

### Внешние авторитетные источники
- [Документация ngx_http_split_clients_module](https://nginx.org/ru/docs/http/ngx_http_split_clients_module.html)
- [Документация ngx_http_mirror_module](https://nginx.org/ru/docs/http/ngx_http_mirror_module.html)
